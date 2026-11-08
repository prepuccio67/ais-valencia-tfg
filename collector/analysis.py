# -*- coding: utf-8 -*-
"""
Base de análisis de una zona (analysis.db, DISEÑO.md §3.3) y estadísticas del cuadro de mando.

analysis.db solo guarda datos derivados: se puede borrar cuando se quiera y se
vuelve a calcular a partir de las posiciones. Se rehace entera (tarda menos de
1 s) si tiene más de 10 minutos o si han cambiado las subzonas o los parámetros.

Uso a mano:  python -m collector.analysis [--zone VALENCIA] [--csv escalas.csv]
"""
import argparse
import csv
import io
import json
import logging
import os
import sqlite3
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from . import port_calls as pc
from .storage import connect, iso

log = logging.getLogger("collector.analysis")

MAX_AGE_S = 600                  # el cálculo se rehace si tiene más de 10 minutos
CALL_COLS = ["mmsi", "imo", "name", "ship_type", "length_m", "terminal_id", "wait_location",
             "t_start", "t_anchor_in", "t_anchor_out", "t_berth", "t_unberth", "t_exit", "t_last_seen",
             "wait_h", "stay_h", "draught_in_m", "draught_out_m", "berth_lat", "berth_lon",
             "censored_start", "censored_end", "overlaps_gap", "gap_overlap_min", "max_track_gap_h",
             "quality", "method_version"]
TIME_COLS = [c for c in CALL_COLS if c.startswith("t_")]
SCHEMA = f"""
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE subzone (
  subzone_id TEXT NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL, geometry TEXT NOT NULL,
  valid_from INTEGER NOT NULL, valid_to INTEGER, notes TEXT,
  PRIMARY KEY (subzone_id, valid_from)
);
CREATE TABLE port_call (call_id INTEGER PRIMARY KEY, {", ".join(CALL_COLS)}, computed_ts INTEGER NOT NULL);
CREATE INDEX ix_call_start ON port_call (t_start);
CREATE TABLE operator (
  imo INTEGER, mmsi INTEGER, operator TEXT NOT NULL, source_url TEXT, checked_on TEXT,
  PRIMARY KEY (imo, mmsi)
);
CREATE VIEW v_port_call AS
  SELECT call_id, name, mmsi, terminal_id, wait_location,
         datetime(t_anchor_in, 'unixepoch') AS llegada_fondeo_utc, datetime(t_berth, 'unixepoch') AS atraque_utc,
         datetime(t_unberth, 'unixepoch') AS desatraque_utc, ROUND(wait_h, 2) AS espera_h,
         ROUND(stay_h, 2) AS estancia_h, quality
  FROM port_call;
"""
_locks = defaultdict(threading.Lock)


def db_path(zone):
    return Path(zone.zone_dir) / zone.database["analysis"]


# ------------------------------------------------------------ cálculo y guardado
def _old_subzones(path):
    if not path.exists():
        return [], {}
    conn = connect(path, readonly=True)
    try:
        rows = conn.execute("SELECT subzone_id, kind, name, geometry, valid_from, valid_to, notes FROM subzone").fetchall()
        meta = dict(conn.execute("SELECT key, value FROM meta"))
    except sqlite3.DatabaseError:
        return [], {}
    finally:
        conn.close()
    return rows, meta


def recompute(zone, now=None):
    """Recalcula todas las escalas y escribe analysis.db de golpe (archivo temporal + cambio de nombre)."""
    now = now or int(time.time())
    with _locks[zone.zone_id]:
        cfg = pc.load_config(zone)
        t0 = time.time()
        calls, (first, last) = pc.compute(zone, cfg, now)
        path = db_path(zone)
        # historial de subzonas: si se redibujan, la versión anterior se conserva con su fecha de fin
        old_rows, old_meta = _old_subzones(path)
        same = old_meta.get("fingerprint") == cfg["fingerprint"]
        history = [r for r in old_rows if r[5] is not None]
        current = [r for r in old_rows if r[5] is None]
        if same and current:
            subzone_rows = history + current
        else:
            subzone_rows = history + [r[:5] + (now, r[6]) for r in current]
            subzone_rows += [(s["subzone_id"], s["kind"], s["name"],
                              json.dumps({"type": "Polygon", "coordinates": [s["ring"]]}), now, None, s["notes"])
                             for s in cfg["subzones"]]
        tmp = path.with_name(path.name + ".tmp")
        tmp.unlink(missing_ok=True)
        conn = sqlite3.connect(tmp)
        try:
            conn.executescript(SCHEMA)
            with conn:
                conn.executemany("INSERT INTO subzone VALUES (?,?,?,?,?,?,?)", subzone_rows)
                conn.executemany(f"INSERT INTO port_call ({', '.join(CALL_COLS)}, computed_ts) "
                                 f"VALUES ({', '.join('?' * (len(CALL_COLS) + 1))})",
                                 [[c[k] for k in CALL_COLS] + [now] for c in calls])
                meta = {"zone_id": zone.zone_id, "computed_ts": now, "fingerprint": cfg["fingerprint"],
                        "method": json.dumps(cfg["method"]), "data_first_ts": first or "", "data_last_ts": last or ""}
                conn.executemany("INSERT INTO meta VALUES (?, ?)", [(k, str(v)) for k, v in meta.items()])
        finally:
            conn.close()
        os.replace(tmp, path)
        log.info("[%s] %d escalas calculadas en %.2f s", zone.zone_id, len(calls), time.time() - t0)
        return len(calls)


def ensure_fresh(zone, now=None, max_age=MAX_AGE_S):
    """Recalcula si analysis.db no existe, es antigua o no corresponde a las subzonas actuales."""
    now = now or int(time.time())
    cfg = pc.load_config(zone)
    _, meta = _old_subzones(db_path(zone))
    if (meta.get("fingerprint") != cfg["fingerprint"] or now - int(meta.get("computed_ts") or 0) > max_age):
        recompute(zone, now)
    return cfg


def read_calls(zone, t_from, t_to):
    """Escalas que se solapan con [t_from, t_to), como diccionarios."""
    conn = connect(db_path(zone), readonly=True)
    try:
        cur = conn.execute(f"SELECT call_id, {', '.join(CALL_COLS)} FROM port_call "
                           "WHERE t_start < ? AND COALESCE(t_exit, t_last_seen) >= ? ORDER BY t_start, mmsi",
                           (t_to, t_from))
        calls = [dict(zip(["call_id"] + CALL_COLS, row)) for row in cur]
        meta = dict(conn.execute("SELECT key, value FROM meta"))
    finally:
        conn.close()
    return calls, meta


# ------------------------------------------------------------ estadísticas
def percentile(values, q):
    """Percentil con interpolación lineal (el mismo criterio que Excel PERCENTIL.INC)."""
    if not values:
        return None
    v = sorted(values)
    k = (len(v) - 1) * q
    i = int(k)
    return v[i] if i + 1 >= len(v) else v[i] + (v[i + 1] - v[i]) * (k - i)


def _stats(calls):
    waits = [c["wait_h"] for c in calls]
    stays = [c["stay_h"] for c in calls if c["stay_h"] is not None]
    r = lambda x: None if x is None else round(x, 2)     # noqa: E731
    return {"calls": len(calls), "with_wait": sum(1 for w in waits if w > 0),
            "wait_mean_h": r(sum(waits) / len(waits)) if waits else None,
            "wait_median_h": r(percentile(waits, .5)), "wait_p75_h": r(percentile(waits, .75)),
            "wait_p90_h": r(percentile(waits, .9)), "wait_max_h": r(max(waits)) if waits else None,
            "stay_median_h": r(percentile(stays, .5)), "stay_p90_h": r(percentile(stays, .9))}


def summary(calls, cfg, t_from, t_to, now):
    """Cifras del cuadro de mando. Las estadísticas de tiempos usan solo las escalas OK."""
    ok = [c for c in calls if c["quality"] == "OK"]
    terminals = [(s["subzone_id"], s["name"]) for s in cfg["subzones"] if s["kind"] == "TERMINAL"]
    terminals.append((pc.OTHER_BERTH, "Otros muelles"))
    by_terminal = [{"terminal_id": tid, "name": name, **_stats([c for c in ok if c["terminal_id"] == tid])}
                   for tid, name in terminals]
    containers = [c for c in ok if c["terminal_id"] not in (None, pc.OTHER_BERTH)]
    quality = defaultdict(int)
    for c in calls:
        quality[c["quality"].split(":")[0]] += 1
    # cola: buques esperando y atracados al principio de cada hora (todas las escalas: es lo observado)
    start = t_from - t_from % 3600
    hours = list(range(start, min(t_to, now) + 1, 3600))
    waiting, berthed = [0] * len(hours), defaultdict(lambda: [0] * len(hours))
    for c in calls:
        if c["t_anchor_in"]:
            end = c["t_anchor_out"] if c["t_berth"] or c["quality"] != "EN CURSO" else c["t_last_seen"]
            _count(waiting, hours, c["t_anchor_in"], end)
        if c["t_berth"]:
            _count(berthed[c["terminal_id"]], hours, c["t_berth"], c["t_unberth"] or c["t_last_seen"])
    # atraques por día y terminal (sin las excluidas)
    daily = defaultdict(lambda: defaultdict(int))
    for c in calls:
        if c["t_berth"] and not c["quality"].startswith("EXCLUIDA") and t_from <= c["t_berth"] < t_to:
            daily[iso(c["t_berth"])[:10]][c["terminal_id"]] += 1
    ongoing = [c for c in calls if c["quality"] == "EN CURSO"]
    return {"terminals": by_terminal, "containers": _stats(containers), "all_ok": _stats(ok),
            "quality": dict(quality),
            "queue": {"hours": [iso(h) for h in hours], "waiting": waiting,
                      "berthed": {k: v for k, v in berthed.items()}},
            "daily_berths": {d: dict(v) for d, v in sorted(daily.items())},
            "waiting_now": [_short(c) for c in ongoing if not c["t_berth"]],
            "berthed_now": [_short(c) for c in ongoing if c["t_berth"]]}


def _count(series, hours, a, b):
    for i, h in enumerate(hours):
        if a <= h < (b or a):
            series[i] += 1


def _short(c):
    return {"name": c["name"], "mmsi": c["mmsi"], "terminal_id": c["terminal_id"],
            "wait_location": c["wait_location"], "since": iso(c["t_berth"] or c["t_anchor_in"]),
            "wait_h": c["wait_h"], "length_m": c["length_m"]}


def to_json(c):
    return {**c, **{k: iso(c[k]) for k in TIME_COLS}}


# ------------------------------------------------------------ CSV para Excel
CSV_COLUMNS = [("buque", "name"), ("mmsi", "mmsi"), ("imo", "imo"), ("tipo_ais", "ship_type"),
               ("eslora_m", "length_m"), ("terminal", "terminal_id"), ("lugar_espera", "wait_location"),
               ("llegada_fondeo_utc", "t_anchor_in"), ("fin_fondeo_utc", "t_anchor_out"),
               ("atraque_utc", "t_berth"), ("desatraque_utc", "t_unberth"), ("salida_puerto_utc", "t_exit"),
               ("espera_h", "wait_h"), ("estancia_h", "stay_h"), ("calado_entrada_m", "draught_in_m"),
               ("calado_salida_m", "draught_out_m"), ("calidad", "quality"),
               ("llegada_no_vista", "censored_start"), ("salida_no_vista", "censored_end"),
               ("hueco_zona_min", "gap_overlap_min"), ("max_sin_senal_h", "max_track_gap_h"),
               ("metodo", "method_version")]


def to_csv(calls):
    """CSV que Excel en español abre bien: separador ';', coma decimal y UTF-8 con BOM."""
    out = io.StringIO()
    w = csv.writer(out, delimiter=";", lineterminator="\r\n")
    w.writerow([h for h, _ in CSV_COLUMNS])
    for c in calls:
        row = []
        for _, k in CSV_COLUMNS:
            v = c[k]
            if k in TIME_COLS and v is not None:
                v = datetime.fromtimestamp(v, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
            elif isinstance(v, float):
                v = f"{v:.2f}".replace(".", ",")
            row.append("" if v is None else v)
        w.writerow(row)
    return "﻿" + out.getvalue()


# ------------------------------------------------------------ línea de órdenes
def main(argv=None):
    from .config import default_zone_id, load_settings, load_zones
    p = argparse.ArgumentParser(description="Recalcula las escalas y muestra el resumen")
    p.add_argument("--env", help="ruta del .env")
    p.add_argument("--zone", help="solo esta zona")
    p.add_argument("--csv", help="guardar también todas las escalas en este CSV")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = load_settings(args.env)
    now = int(time.time())
    zones = {z.zone_id: z for z in load_zones(settings.data_dir)}
    if args.zone and args.zone not in zones:
        print(f"No existe la zona {args.zone}")
        return 2
    # VALENCIA primero (explícito, no por orden alfabético); las zonas sin terminales se saltan
    first = default_zone_id(zones)
    for zone in sorted(zones.values(), key=lambda z: z.zone_id != first):
        if args.zone and zone.zone_id != args.zone:
            continue
        if not pc.has_port_analysis(zone):
            print(f"\nZona {zone.zone_id}: sin terminales ni fondeadero, no tiene escalas (se salta)")
            continue
        recompute(zone, now)
        cfg = pc.load_config(zone)
        calls, _ = read_calls(zone, 0, now + 1)
        s = summary(calls, cfg, now - 30 * 86400, now, now)
        print(f"\nZona {zone.zone_id}: {len(calls)} escalas {s['quality']}")
        for t in s["terminals"]:
            print(f"  {t['name']:<32} escalas OK={t['calls']:3d}  espera mediana={t['wait_median_h']} h  "
                  f"p90={t['wait_p90_h']} h  estancia mediana={t['stay_median_h']} h")
        if args.csv:
            Path(args.csv).write_text(to_csv(calls), encoding="utf-8")
            print(f"  CSV guardado en {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
