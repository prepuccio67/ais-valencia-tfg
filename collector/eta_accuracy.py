# -*- coding: utf-8 -*-
"""
Precisión de la ETA declarada por AIS (módulo 7c.1, método 'eta-v1', METODO.md y D-20).

Solo lee datos: escalas ya calculadas (port_call), posiciones y voyage_data de la zona y
de su zona de relleno (APROXIMACION), que es la que ve a los buques horas antes de llegar.

Para cada escala de las terminales de contenedores, cada definición de llegada real T
(ZONA_ESPERA, RECINTO, ATRAQUE) y cada horizonte h (72 ... 0 h, más la «última ETA»):
  1. t_ref = T - h;
  2. ETA vigente = la última fila de voyage_data con hora <= t_ref;
  3. el buque debe haberse visto en [t_ref - W, t_ref];
  4. error e = ETA - T, en horas (positivo = llegó ANTES de lo declarado; Chu et al., 2024,
     usan el signo contrario en su fórmula del sesgo).
Cada caso queda con un estado (USABLE o el motivo del descarte) y se guarda en eta_obs.
"""
import bisect
import hashlib
import json
import math
import random
import shutil
from collections import defaultdict
from pathlib import Path

from . import port_calls as pc
from .config import REPO_ROOT, ConfigError, load_zones
from .geo import point_in_ring
from .queries import MAX_TS, segments_for
from .storage import connect

CONTAINER_TERMINALS = ("T-MSC", "T-CSP", "T-APM")
DEFINITIONS = ("ZONA_ESPERA", "RECINTO", "ATRAQUE")
LAST = "ULTIMA"
STATUSES = ("USABLE", "LLEGADA_NO_VISTA", "ANTES_CAPTURA", "SIN_COBERTURA", "SIN_ETA", "DESTINO_OTRO",
            "DESTINO_DUDOSO", "ETA_CADUCADA", "ETA_IMPOSIBLE", "ESCALA_EXCLUIDA")
OBS_COLS = ["rule", "mmsi", "name", "terminal_id", "call_quality", "t_start", "definition", "horizon", "t_arrival",
            "t_ref", "status", "eta_utc", "eta_raw", "eta_ts", "destination", "error_h", "lead_h", "method_version"]
MAIN, SENS = "principal", "sensibilidad"       # regla de caducidad principal y la del análisis de sensibilidad
SCHEMA = f"""
CREATE TABLE eta_obs (obs_id INTEGER PRIMARY KEY, {", ".join(OBS_COLS)});
CREATE INDEX ix_eta_def_h ON eta_obs (rule, definition, horizon);
CREATE VIEW v_eta_obs AS
  SELECT rule AS regla, name, terminal_id, definition, horizon, datetime(t_arrival, 'unixepoch') AS llegada_utc,
         datetime(eta_utc, 'unixepoch') AS eta_utc_txt, ROUND(error_h, 2) AS error_h, status, destination
  FROM eta_obs;
"""
AVISO = ("Cifras PROVISIONALES: pocas semanas de datos y método eta-v1 pendiente del visto bueno del tutor. "
         "La ETA del AIS la teclea la tripulación; los estudios de comparación usan la ETA comunicada al puerto.")
REQUIRED = ("version", "horizontes_h", "ultima_eta", "definiciones", "definicion_principal", "ventana_vista_h",
            "caducada_tolerancia_h", "caducada_referencia", "eta_max_dias", "bandas_h", "min_n",
            "destinos_valencia", "bootstrap_remuestreos", "bootstrap_min_n", "llegada_vista_h",
            "sensibilidad_caducada_referencia", "revision_umbral_h")


# ------------------------------------------------------------ parámetros
def params_path(zone):
    return Path(zone.zone_dir) / "parametros_7c.json"


def load_params(zone):
    """Lee parametros_7c.json (sección eta) de la zona; si no existe, copia el de ejemplo.
    Devuelve los valores sueltos más 'fingerprint' (cambia si cambia cualquier parámetro)."""
    path = params_path(zone)
    if not path.exists():
        example = REPO_ROOT / "config-ejemplo" / "zones" / zone.zone_id / "parametros_7c.json"
        if not example.exists():
            raise ConfigError(f"{zone.zone_id}: falta {path} (parámetros de 7c)")
        shutil.copyfile(example, path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))["eta"]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise ConfigError(f"{path.name}: no es válido o no tiene la sección 'eta' ({e})")
    missing = [k for k in REQUIRED if k not in raw]
    if missing:
        raise ConfigError(f"{path.name}: faltan parámetros en 'eta': {missing}")
    p = {k: (v["valor"] if isinstance(v, dict) and "valor" in v else v) for k, v in raw.items()}
    if any(d not in DEFINITIONS for d in p["definiciones"]) or p["definicion_principal"] not in p["definiciones"]:
        raise ConfigError(f"{path.name}: definiciones válidas: {list(DEFINITIONS)}")
    for k in ("caducada_referencia", "sensibilidad_caducada_referencia"):
        if p[k] not in ("emision", "t_ref"):
            raise ConfigError(f"{path.name}: {k} debe ser 'emision' o 't_ref'")
    for k in ("horizontes_h", "bandas_h"):
        if not p[k] or any(isinstance(x, bool) or not isinstance(x, (int, float)) or x < 0 for x in p[k]):
            raise ConfigError(f"{path.name}: {k} debe ser una lista de números positivos")
    p["destinos_valencia"] = [d.upper() for d in p["destinos_valencia"]]
    p["fingerprint"] = hashlib.sha256(json.dumps(p, sort_keys=True).encode()).hexdigest()[:16]
    return p


# ------------------------------------------------------------ reglas
_SEPARATORS = (">>", "=>", "->", ">", "-")


def _one_letter_off(a, b):
    return len(a) == len(b) and sum(x != y for x, y in zip(a, b)) == 1


def destination_class(dest, params):
    """'VALENCIA' si el último puerto del destino es València, 'OTRO' si es otro y 'DUDOSO' si
    València aparece pero no al final, o si el destino está vacío."""
    text = (dest or "").upper().strip()
    if not text:
        return "DUDOSO"
    parts = [text]
    for sep in _SEPARATORS:
        parts = [q for part in parts for q in part.split(sep)]
    parts = [" ".join(q.split()) for q in parts if q.strip()]
    if not parts:
        return "DUDOSO"
    names = params["destinos_valencia"]
    is_vlc = lambda q: q in names or _one_letter_off(q, "ESVLC")   # noqa: E731
    if is_vlc(parts[-1]):
        return "VALENCIA"
    return "DUDOSO" if any(is_vlc(q) for q in parts) else "OTRO"


def classify_eta(row, t_ref, params):
    """Estado de una fila de voyage_data (ts, eta_utc, eta_raw, destino) vista desde t_ref."""
    if row is None or row[1] is None:
        return "SIN_ETA"
    dc = destination_class(row[3], params)
    if dc != "VALENCIA":
        return "DESTINO_OTRO" if dc == "OTRO" else "DESTINO_DUDOSO"
    tol = params["caducada_tolerancia_h"] * 3600
    ref = row[0] if params["caducada_referencia"] == "emision" else t_ref
    if row[1] < ref - tol:
        return "ETA_CADUCADA"
    if row[1] > t_ref + params["eta_max_dias"] * 86400:
        return "ETA_IMPOSIBLE"
    return "USABLE"


def port_entry(points, t_berth, port_ring, observed_s):
    """Entrada en el recinto antes del atraque: la primera posición del tramo continuo dentro del
    recinto que acaba en el atraque. Devuelve (hora, vista) o (None, False)."""
    times = [p[0] for p in points]
    i = bisect.bisect_right(times, t_berth) - 1
    if i < 0 or not point_in_ring(points[i][1], points[i][2], port_ring):
        return None, False
    while i > 0 and point_in_ring(points[i - 1][1], points[i - 1][2], port_ring):
        i -= 1
    seen = i > 0 and points[i][0] - points[i - 1][0] <= observed_s
    return points[i][0], seen


def arrivals(call, points, port_ring, params):
    """Hora de llegada real y si se observó, para cada definición."""
    entry, entry_seen = (None, False)
    if call["t_berth"]:
        entry, entry_seen = port_entry(points, call["t_berth"], port_ring, params["llegada_vista_h"] * 3600)
    out = {}
    if call["t_anchor_in"]:
        out["ZONA_ESPERA"] = (call["t_anchor_in"], not call["censored_start"])
    else:
        out["ZONA_ESPERA"] = (entry, entry_seen)
    out["RECINTO"] = (entry, entry_seen)
    out["ATRAQUE"] = (call["t_berth"], entry_seen)
    return out


# ------------------------------------------------------------ datos
def _fill_zone(zone, method):
    if not method.get("fill_zone"):
        return None
    zones = {z.zone_id: z for z in load_zones(Path(zone.zone_dir).parent.parent)}
    return zones.get(method["fill_zone"])


def load_inputs(zone, method, mmsis):
    """Posiciones propias (para la entrada en el recinto), horas en que se vio al buque en
    cualquiera de las dos zonas y filas de voyage_data de las dos zonas, por buque."""
    own, seen, voy = defaultdict(list), defaultdict(set), defaultdict(dict)
    ids = sorted(mmsis)
    fill = _fill_zone(zone, method)
    for z, is_own in ((zone, True), (fill, False)):
        if z is None:
            continue
        for path in segments_for(z, 0, MAX_TS)[0]:
            conn = connect(path, readonly=True)
            try:
                for i in range(0, len(ids), 500):
                    chunk = ids[i:i + 500]
                    marks = ",".join("?" * len(chunk))
                    for mmsi, ts, lat, lon in conn.execute(
                            f"SELECT mmsi, ts, lat, lon FROM position WHERE mmsi IN ({marks})", chunk):
                        seen[mmsi].add(ts)
                        if is_own:
                            own[mmsi].append((ts, lat, lon))
                    for mmsi, ts, eta, raw, dest in conn.execute(
                            f"SELECT mmsi, ts, eta_utc, eta_raw, destination FROM voyage_data "
                            f"WHERE mmsi IN ({marks})", chunk):
                        voy[mmsi][ts] = (ts, eta, raw, dest)      # misma hora en las dos zonas: una sola
            finally:
                conn.close()
    for lst in own.values():
        lst.sort()
    return own, {m: sorted(s) for m, s in seen.items()}, {m: sorted(d.values()) for m, d in voy.items()}


def _seen_in(times, a, b):
    i = bisect.bisect_left(times, a)
    return i < len(times) and times[i] <= b


# ------------------------------------------------------------ cálculo
def compute(zone, calls, cfg, data_first, params):
    """Filas de eta_obs para las escalas (diccionarios de port_call) de las terminales de contenedores:
    una vez con la regla de caducidad principal y otra con la del análisis de sensibilidad."""
    mine = [c for c in calls if c["terminal_id"] in CONTAINER_TERMINALS]
    inputs = load_inputs(zone, cfg["method"], {c["mmsi"] for c in mine})
    rows = []
    for rule, ref in ((MAIN, params["caducada_referencia"]), (SENS, params["sensibilidad_caducada_referencia"])):
        rows += _compute_rule(mine, inputs, cfg, data_first, dict(params, caducada_referencia=ref), rule)
    return rows


def _compute_rule(mine, inputs, cfg, data_first, params, rule):
    port_ring = pc._of_kind(cfg, "PORT_AREA")[0]["ring"]
    own, seen, voy = inputs
    window = params["ventana_vista_h"] * 3600
    horizons = [str(h).rstrip("0").rstrip(".") if isinstance(h, float) else str(h) for h in params["horizontes_h"]]
    hours = dict(zip(horizons, params["horizontes_h"]))
    labels = ([LAST] if params["ultima_eta"] else []) + horizons
    rows = []
    for c in mine:
        arr = arrivals(c, own.get(c["mmsi"], []), port_ring, params)
        rows_v = voy.get(c["mmsi"], [])
        times_v = [r[0] for r in rows_v]
        times_s = seen.get(c["mmsi"], [])
        for d in params["definiciones"]:
            t_arr, observed = arr[d]
            for label in labels:
                t_ref = t_arr if label == LAST else (t_arr - hours[label] * 3600 if t_arr else None)
                row, status = None, None
                if c["quality"].startswith("EXCLUIDA"):
                    status = "ESCALA_EXCLUIDA"
                elif not t_arr or not observed:
                    status = "LLEGADA_NO_VISTA"
                elif data_first is None or t_ref < data_first:
                    status = "ANTES_CAPTURA"
                elif not _seen_in(times_s, t_ref - window, t_ref):
                    status = "SIN_COBERTURA"
                elif label == LAST:
                    # la última ETA VÁLIDA emitida antes de la llegada: se busca hacia atrás
                    k = bisect.bisect_right(times_v, t_ref)
                    for j in range(k - 1, -1, -1):
                        s = classify_eta(rows_v[j], t_ref, params)
                        if status is None:          # si ninguna vale, manda el motivo de la más reciente
                            status, row = s, rows_v[j]
                        if s == "USABLE":
                            status, row = s, rows_v[j]
                            break
                    status = status or "SIN_ETA"
                else:
                    k = bisect.bisect_right(times_v, t_ref)
                    row = rows_v[k - 1] if k else None
                    status = classify_eta(row, t_ref, params)
                usable = status == "USABLE"
                rows.append({
                    "rule": rule, "mmsi": c["mmsi"], "name": c["name"], "terminal_id": c["terminal_id"],
                    "call_quality": c["quality"].split(":")[0], "t_start": c["t_start"], "definition": d,
                    "horizon": label, "t_arrival": t_arr, "t_ref": t_ref, "status": status,
                    "eta_utc": row[1] if row else None, "eta_raw": row[2] if row else None,
                    "eta_ts": row[0] if row else None, "destination": row[3] if row else None,
                    "error_h": round((row[1] - t_arr) / 3600, 4) if usable else None,
                    "lead_h": round((t_arr - row[0]) / 3600, 4) if usable else None,
                    "method_version": params["version"]})
    return rows


# ------------------------------------------------------------ estadísticas
def _pct(values, q):
    """Percentil como PERCENTIL.INC de Excel (el mismo criterio que el resto del cuadro)."""
    if not values:
        return None
    v = sorted(values)
    k = (len(v) - 1) * q
    i = int(k)
    return v[i] if i + 1 >= len(v) else v[i] + (v[i + 1] - v[i]) * (k - i)


def indicators(errors, params, eta_raws=(), leads=(), n_with_eta=None, n_stale=None):
    """Indicadores del apartado 8 para una lista de errores (horas)."""
    n = len(errors)
    r = lambda x: None if x is None else round(x, 2)   # noqa: E731
    out = {"n": n, "pocos_datos": n < params["min_n"]}
    if n:
        out.update({
            "sesgo_h": r(sum(errors) / n), "mediana_h": r(_pct(errors, .5)),
            "mae_h": r(sum(abs(e) for e in errors) / n),
            "rmse_h": r(math.sqrt(sum(e * e for e in errors) / n)),
            "p10_h": r(_pct(errors, .1)), "p90_h": r(_pct(errors, .9))})
        for b in params["bandas_h"]:
            out[f"pct_{b:g}h".replace(".", "_")] = round(100 * sum(abs(e) <= b for e in errors) / n, 1)
        if n >= params["bootstrap_min_n"]:
            rnd = random.Random(7)                       # semilla fija: resultado repetible
            meds = sorted(_pct([rnd.choice(errors) for _ in range(n)], .5) for _ in range(params["bootstrap_remuestreos"]))
            out["ic90_mediana_h"] = [r(_pct(meds, .05)), r(_pct(meds, .95))]
        raws = [x for x in eta_raws if x]
        if raws:
            out["pct_en_punto"] = round(100 * sum(x.endswith(":00") for x in raws) / len(raws), 1)
        if leads:
            out["antelacion_mediana_h"] = r(_pct(list(leads), .5))
    if n_with_eta:
        out["pct_caducadas"] = round(100 * (n_stale or 0) / n_with_eta, 1)
    return out


def summary(rows, params, variant="base", rule=MAIN):
    """Indicadores por definición, horizonte y terminal (y total), con la regla de caducidad indicada.
    variant: 'base' (OK, dudosas y en curso con llegada vista), 'solo_ok' o 'con_caducadas'."""
    keep = {"USABLE", "ETA_CADUCADA"} if variant == "con_caducadas" else {"USABLE"}
    groups = defaultdict(list)
    counts = defaultdict(lambda: defaultdict(int))
    for o in rows:
        if o.get("rule", MAIN) != rule or (variant == "solo_ok" and o["call_quality"] != "OK"):
            continue
        counts[(o["definition"], o["horizon"])][o["status"]] += 1
        for t in (o["terminal_id"], "TOTAL"):
            groups[(o["definition"], o["horizon"], t)].append(o)
    stats = []
    for (d, h, t), obs in groups.items():
        use = [o for o in obs if o["status"] in keep]
        errors = [o["error_h"] if o["error_h"] is not None else (o["eta_utc"] - o["t_arrival"]) / 3600 for o in use]
        with_eta = [o for o in obs if o["status"] in ("USABLE", "ETA_CADUCADA", "ETA_IMPOSIBLE")]
        stats.append({"definition": d, "horizon": h, "terminal_id": t,
                      **indicators(errors, params, [o["eta_raw"] for o in use],
                                   [o["lead_h"] for o in use if o["lead_h"] is not None] if h == LAST else (),
                                   len(with_eta), sum(o["status"] == "ETA_CADUCADA" for o in with_eta))})
    order = {h: i for i, h in enumerate([LAST] + [str(x) for x in params["horizontes_h"]])}
    term = {t: i for i, t in enumerate(CONTAINER_TERMINALS + ("TOTAL",))}
    stats.sort(key=lambda s: (s["definition"], order.get(s["horizon"], 99), term.get(s["terminal_id"], 9)))
    return stats, {f"{d}|{h}": dict(v) for (d, h), v in counts.items()}


# ------------------------------------------------------------ guardar y leer
def write(conn, rows):
    conn.executescript(SCHEMA)
    conn.executemany(f"INSERT INTO eta_obs ({', '.join(OBS_COLS)}) VALUES ({', '.join('?' * len(OBS_COLS))})",
                     [[o[k] for k in OBS_COLS] for o in rows])


def read(db_path):
    conn = connect(db_path, readonly=True)
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'eta_obs'").fetchone():
            return []
        cols = {r[1] for r in conn.execute("PRAGMA table_info(eta_obs)")}
        if "rule" not in cols:                          # analysis.db anterior a la columna: se rehará
            return []
        cur = conn.execute(f"SELECT {', '.join(OBS_COLS)} FROM eta_obs ORDER BY rule, t_start, mmsi, definition, obs_id")
        return [dict(zip(OBS_COLS, r)) for r in cur]
    finally:
        conn.close()


# ------------------------------------------------------------ CSV para Excel (';', coma decimal, UTF-8 con BOM)
CASE_CSV = [("regla", "rule"), ("buque", "name"), ("mmsi", "mmsi"), ("terminal", "terminal_id"), ("calidad_escala", "call_quality"),
            ("definicion", "definition"), ("horizonte", "horizon"), ("llegada_utc", "t_arrival"),
            ("t_ref_utc", "t_ref"), ("estado", "status"), ("eta_utc", "eta_utc"), ("eta_tal_cual", "eta_raw"),
            ("eta_recibida_utc", "eta_ts"), ("destino", "destination"), ("error_h", "error_h"),
            ("antelacion_h", "lead_h"), ("metodo", "method_version")]
_TIME = {"t_arrival", "t_ref", "eta_utc", "eta_ts"}


def _cell(k, v):
    from datetime import datetime, timezone
    if v is None:
        return ""
    if k in _TIME:
        return datetime.fromtimestamp(v, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    if isinstance(v, float):
        return f"{v:.2f}".replace(".", ",")
    if isinstance(v, list):
        return " a ".join(_cell("", x) for x in v)
    if isinstance(v, bool):
        return "sí" if v else "no"
    return v


def _csv(header, rows):
    import csv
    import io
    out = io.StringIO()
    w = csv.writer(out, delimiter=";", lineterminator="\r\n")
    w.writerow(header)
    w.writerows(rows)
    return "﻿" + out.getvalue()


REVIEW_CSV = [("buque", "name"), ("mmsi", "mmsi"), ("terminal", "terminal_id"), ("calidad_escala", "call_quality"),
              ("llegada_zona_espera_utc", "t_arrival"), ("eta_declarada_utc", "eta_utc"), ("eta_tal_cual", "eta_raw"),
              ("eta_emitida_utc", "eta_ts"), ("destino", "destination"), ("error_h", "error_h"),
              ("horizontes", "horizons"), ("revisado", "check"), ("conclusion", "note")]


def review_list(rows, params):
    """Casos con |error| > revision_umbral_h (regla principal, definición principal), uno por escala y ETA,
    con los horizontes en que aparece. Para revisarlos a mano: ¿retraso real o ETA olvidada?"""
    limit = params["revision_umbral_h"]
    out = {}
    for o in rows:
        if (o["rule"] != MAIN or o["definition"] != params["definicion_principal"] or o["status"] != "USABLE"
                or abs(o["error_h"]) <= limit):
            continue
        key = (o["mmsi"], o["t_start"], o["eta_utc"])      # la misma ETA reenviada cuenta una vez
        item = out.setdefault(key, {**o, "horizons": [], "check": "", "note": ""})
        if o["eta_ts"] < item["eta_ts"]:
            item["eta_ts"] = o["eta_ts"]                       # la emisión más antigua de las que se usan
        h = "última" if o["horizon"] == LAST else o["horizon"] + " h"
        if h not in item["horizons"]:
            item["horizons"].append(h)
    items = sorted(out.values(), key=lambda x: (-abs(x["error_h"]), x["name"] or ""))
    for x in items:
        x["horizons"] = ", ".join(x["horizons"])
    return items


def to_csv_review(items):
    return _csv([h for h, _ in REVIEW_CSV], [[_cell(k, x[k]) for _, k in REVIEW_CSV] for x in items])


def to_csv_cases(rows):
    return _csv([h for h, _ in CASE_CSV], [[_cell(k, o[k]) for _, k in CASE_CSV] for o in rows])


def to_csv_stats(stats):
    keys = []
    for s in stats:
        keys += [k for k in s if k not in keys]
    return _csv(keys, [[_cell(k, s.get(k)) for k in keys] for s in stats])
