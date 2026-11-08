# -*- coding: utf-8 -*-
"""
Prueba de 1 h (Paso 1): CUENTA los mensajes del rectángulo de aproximación (opción A)
sin guardarlos en el sistema. Usa las mismas clases de fuente y el mismo muestreo que el
Collector, con la suscripción que tendría el servidor (VALENCIA + APROXIMACION).
Al final crea una base SQLite TEMPORAL con el esquema real solo para medir el tamaño.

Se usó el 08/11/2026 (15:28-16:28 UTC) para decidir la zona de aproximación (D-18);
resultado en informes/prueba_aproximacion_2026-11-08.json.

Uso (desde la carpeta del repositorio):
    .venv/Scripts/python.exe scripts/prueba_aproximacion.py . 3600 resultado.json
"""
import asyncio
import json
import math
import os
import sqlite3
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

REPO = Path(sys.argv[1]).resolve()
DURATION = int(sys.argv[2])
OUT = Path(sys.argv[3])
sys.path.insert(0, str(REPO))

from collector.config import load_env_file, DEFAULT_SAMPLING      # noqa: E402
from collector.geo import in_bbox                                  # noqa: E402
from collector.sampler import Sampler                              # noqa: E402
from collector.sources.aisstream import AisStreamSource            # noqa: E402
from collector.sources.openseafeed import OpenSeaFeedSource        # noqa: E402
from collector.storage import SCHEMA, SQL_POSITION, SQL_VOYAGE     # noqa: E402

VAL = {"north": 39.60, "south": 39.25, "east": 0.00, "west": -0.36}
APR = {"north": 42.0, "south": 37.0, "east": 2.9, "west": -3.5}
PORT = (39.44, -0.31)          # bocana aproximada del puerto de València
SAMPLING_APR = dict(DEFAULT_SAMPLING, moving_interval_s=1800, stopped_interval_s=3600)
BINS = [0, 15, 30, 50, 75, 100, 125, 150, 400]


def nm(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 3440.065 * math.asin(math.sqrt(a))


def bin_of(d):
    for lo, hi in zip(BINS, BINS[1:]):
        if lo <= d < hi:
            return f"{lo}-{hi}"
    return "400+"


class Stats:
    def __init__(self):
        self.t0 = int(time.time())
        self.frames = defaultdict(int)                 # fuente -> mensajes recibidos (todos)
        self.in_apr = defaultdict(int)                 # fuente -> mensajes en APROX (hora válida)
        self.in_val = defaultdict(int)
        self.stale = defaultdict(int)
        self.static5 = defaultdict(int)                # fuente -> mensajes tipo 5 (ShipStaticData)
        self.static5_apr = defaultdict(int)
        self.mmsi = defaultdict(set)
        self.mmsi_all = set()
        self.dups = defaultdict(int)                   # mensaje idéntico repetido (misma fuente)
        self.dups_val = defaultdict(int)
        self.seen = set()
        self.per_min = defaultdict(int)                # minuto -> mensajes (todas las fuentes)
        self.dist_msgs = defaultdict(int)
        self.dist_mmsi = defaultdict(set)
        self.grid = defaultdict(int)                   # celda 0,5° -> mensajes
        self.max_dist = (0, None)
        self.sampler = Sampler(SAMPLING_APR)
        self.known = set()
        self.voy_cache = {}
        self.pos_rows, self.voy_rows = [], []
        self.vlc_first = {}                            # mmsi -> (dist, sog) primera vez visto declarando VLC
        self.dest = {}
        self.last_pos = {}

    def on(self, m):
        src = m.source
        self.frames[src] += 1
        if m.ts_rx - m.ts > 900 or m.ts - m.ts_rx > 120:
            self.stale[src] += 1
            return
        lat, lon = (m.lat, m.lon) if m.has_position else (m.meta_lat, m.meta_lon)
        key = (src, m.msg_type_name, m.mmsi, m.ts, m.lat, m.lon, m.eta_raw)
        dup = key in self.seen
        self.seen.add(key)
        if lat is not None and in_bbox(lat, lon, VAL) and dup:
            self.dups_val[src] += 1
        if dup:
            self.dups[src] += 1
        # ¿lo querría la zona APROXIMACION? (misma regla que ZoneWorker.wants)
        if m.has_position:
            wanted = in_bbox(m.lat, m.lon, APR)
        else:
            wanted = (m.meta_lat is not None and in_bbox(m.meta_lat, m.meta_lon, APR)) or m.mmsi in self.known
        if m.msg_type_name == "ShipStaticData":
            self.static5[src] += 1
            if wanted:
                self.static5_apr[src] += 1
        if lat is not None and in_bbox(lat, lon, VAL):
            self.in_val[src] += 1
        if not wanted:
            return
        self.in_apr[src] += 1
        self.mmsi[src].add(m.mmsi)
        self.mmsi_all.add(m.mmsi)
        self.per_min[m.ts_rx // 60] += 1
        if lat is not None:
            d = nm(lat, lon, *PORT)
            b = bin_of(d)
            self.dist_msgs[b] += 1
            self.dist_mmsi[b].add(m.mmsi)
            self.grid[(math.floor(lat * 2) / 2, math.floor(lon * 2) / 2)] += 1
            if d > self.max_dist[0]:
                self.max_dist = (round(d, 1), [round(lat, 3), round(lon, 3)])
        if m.has_position:
            self.last_pos[m.mmsi] = (m.lat, m.lon, m.sog)
            r = self.sampler.decide(m.mmsi, m.ts, m.ts_rx, m.sog, m.nav_status)
            if r is not None:
                self.known.add(m.mmsi)
                self.pos_rows.append((m.mmsi, m.ts, m.ts_rx, m.lat, m.lon, m.sog, m.cog, m.heading,
                                      m.nav_status, m.msg_id, 1 if src == "openseafeed" else 2, r))
            dst = (self.dest.get(m.mmsi) or "").upper()
            if ("VLC" in dst or "VALENC" in dst) and m.mmsi not in self.vlc_first:
                self.vlc_first[m.mmsi] = (round(nm(m.lat, m.lon, *PORT), 1), m.sog)
        if m.has_static:
            if m.destination:
                self.dest[m.mmsi] = m.destination
            if m.draught_m is None and m.destination is None and m.eta_raw is None:
                return
            new = (m.draught_m, m.destination, m.eta_raw)
            old = self.voy_cache.get(m.mmsi)
            if old is None or (old[:3] != new and m.ts > old[3]):
                self.voy_cache[m.mmsi] = new + (m.ts,)
                self.voy_rows.append((m.mmsi, m.ts, new[0], new[1], new[2], m.eta_utc,
                                      1 if src == "openseafeed" else 2))

    def report(self, sources):
        hours = (int(time.time()) - self.t0) / 3600
        tmp = Path(tempfile.mkdtemp()) / "medida.db"
        c = sqlite3.connect(tmp)
        c.executescript(SCHEMA)
        c.executemany(SQL_POSITION, self.pos_rows)
        c.executemany(SQL_VOYAGE, self.voy_rows)
        c.commit()
        c.execute("VACUUM")
        c.close()
        empty = Path(tempfile.mkdtemp()) / "vacia.db"
        e = sqlite3.connect(empty)
        e.executescript(SCHEMA)
        e.commit()
        e.execute("VACUUM")
        e.close()
        size = tmp.stat().st_size - empty.stat().st_size
        rate = sorted(self.per_min.values())
        per10 = defaultdict(int)
        for r in self.pos_rows:
            per10[(r[2] - self.t0) // 600 * 10] += 1
        nrows = len(self.pos_rows) + len(self.voy_rows)
        bpr = size / nrows if nrows else 0
        steady = [per10[k] for k in per10 if k >= 30 and k < (hours * 60 - 10)]
        steady_h = sum(steady) * 6 / len(steady) if steady else None
        voy_h = len(self.voy_rows) / hours
        return {
            "posiciones_guardadas_por_bloque_10min": dict(sorted(per10.items())),
            "bytes_por_fila": round(bpr, 1),
            "posiciones_hora_regimen_estable": round(steady_h) if steady_h else None,
            "GB_ano_regimen_estable": round((steady_h + voy_h) * bpr * 8760 / 1e9, 3) if steady_h else None,
            "horas": round(hours, 3),
            "mensajes_recibidos_total_por_fuente": dict(self.frames),
            "descartados_hora_antigua_o_futura": dict(self.stale),
            "mensajes_en_APROX_por_hora": {k: round(v / hours) for k, v in self.in_apr.items()},
            "mensajes_en_VALENCIA_por_hora": {k: round(v / hours) for k, v in self.in_val.items()},
            "buques_distintos_APROX": {**{k: len(v) for k, v in self.mmsi.items()}, "total": len(self.mmsi_all)},
            "ais5_por_hora_todos": {k: round(v / hours) for k, v in self.static5.items()},
            "ais5_por_hora_APROX": {k: round(v / hours) for k, v in self.static5_apr.items()},
            "duplicados_identicos": dict(self.dups),
            "duplicados_identicos_dentro_VALENCIA": dict(self.dups_val),
            "pico_mensajes_por_minuto": rate[-1] if rate else 0,
            "mediana_mensajes_por_minuto": rate[len(rate) // 2] if rate else 0,
            "distancia_al_puerto_NM_mensajes": dict(self.dist_msgs),
            "distancia_al_puerto_NM_buques": {k: len(v) for k, v in self.dist_mmsi.items()},
            "max_distancia_NM": self.max_dist,
            "posiciones_que_se_guardarian": len(self.pos_rows),
            "cambios_voyage_que_se_guardarian": len(self.voy_rows),
            "bytes_medidos_sqlite": size,
            "GB_ano_extrapolado": round(size / hours * 8760 / 1e9, 3),
            "buques_declarando_VLC_primera_distancia": sorted(self.vlc_first.values(), reverse=True),
            "rejilla_05grados": {f"{k[0]},{k[1]}": v for k, v in sorted(self.grid.items())},
            "estado_fuentes": {n: {k: s.status[k] for k in ("connects", "disconnects", "frames", "parsed",
                                                              "dropped_queue_full", "last_error")}
                               for n, s in sources.items()},
        }


async def main():
    env = load_env_file(REPO / ".env")
    boxes = [[[b["south"], b["west"]], [b["north"], b["east"]]] for b in (VAL, APR)]
    sources = {"aisstream": AisStreamSource(env.get("AISSTREAM_API_KEY", ""), boxes),
               "openseafeed": OpenSeaFeedSource(env.get("OPENSEAFEED_API_KEY", ""), boxes)}
    if not sources["aisstream"].api_key:
        del sources["aisstream"]
    q = asyncio.Queue(maxsize=200000)
    stop = asyncio.Event()
    st = Stats()
    tasks = [asyncio.create_task(s.run(q, stop)) for s in sources.values()]

    async def consume():
        while True:
            st.on(await q.get())
    ct = asyncio.create_task(consume())

    async def progress():
        while True:
            await asyncio.sleep(300)
            OUT.write_text(json.dumps(st.report(sources), ensure_ascii=False, indent=1), encoding="utf-8")
    pt = asyncio.create_task(progress())
    await asyncio.sleep(DURATION)
    stop.set()
    await asyncio.gather(*tasks, return_exceptions=True)
    while not q.empty():
        st.on(q.get_nowait())
    ct.cancel()
    pt.cancel()
    OUT.write_text(json.dumps(st.report(sources), ensure_ascii=False, indent=1), encoding="utf-8")
    print("FIN", OUT)


if __name__ == "__main__":
    asyncio.run(main())
