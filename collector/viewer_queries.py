# -*- coding: utf-8 -*-
"""
Consultas del visor (Fase 4): la "foto" del puerto en un instante, la ficha de
un buque, su trayectoria y el intervalo de fechas con datos.

Igual que queries.py, todas abren los segmentos necesarios en solo lectura y
unen los resultados, así que siguen funcionando cuando haya varios años.
"""
from .queries import MAX_LIMIT, segments_for
from .storage import connect, iso

MAX_TRACK_S = 31 * 86400

_SNAPSHOT_SQL = """
SELECT p.mmsi, p.ts, p.lat, p.lon, p.sog, p.cog, p.heading, p.nav_status, s.name,
       v.name, v.imo, v.callsign, v.ship_type, v.length_m, v.beam_m, v.ais_class,
       (SELECT destination FROM voyage_data d WHERE d.mmsi = p.mmsi AND d.ts <= :at
        ORDER BY d.ts DESC LIMIT 1),
       (SELECT draught_m FROM voyage_data d WHERE d.mmsi = p.mmsi AND d.ts <= :at
        ORDER BY d.ts DESC LIMIT 1)
FROM position p
JOIN (SELECT mmsi, MAX(ts) AS ts FROM position WHERE ts > :a AND ts <= :at GROUP BY mmsi) m
     USING (mmsi, ts)
JOIN source s USING (source_id)
LEFT JOIN vessel v USING (mmsi)
"""

_FIELDS = ("mmsi", "ts", "lat", "lon", "sog", "cog", "heading", "nav_status", "source",
           "name", "imo", "callsign", "ship_type", "length_m", "beam_m", "ais_class",
           "destination", "draught_m")


def snapshot(zone, at, window_s=1200):
    """Última posición de cada buque visto en (at - window_s, at].

    Con 20 minutos de ventana aparecen también los buques parados, que solo
    guardan una posición cada 10 minutos.
    """
    segments, unavailable = segments_for(zone, at - window_s, at + 1)
    latest = {}
    for path in segments:
        conn = connect(path, readonly=True)
        try:
            for row in conn.execute(_SNAPSHOT_SQL, {"a": at - window_s, "at": at}):
                old = latest.get(row[0])
                if old is None or row[1] > old[1]:
                    latest[row[0]] = row
        finally:
            conn.close()
    vessels = []
    for row in latest.values():
        v = dict(zip(_FIELDS, row))
        v["age_s"] = at - v["ts"]
        v["ts"] = iso(v["ts"])
        vessels.append(v)
    vessels.sort(key=lambda v: (v["name"] or "~", v["mmsi"]))
    return {"zone": zone.zone_id, "at": iso(at), "window_s": window_s, "count": len(vessels),
            "segments_unavailable": unavailable, "vessels": vessels}


def vessel_info(zone, mmsi):
    """Ficha de un buque: datos estáticos y cambios de calado, destino y ETA."""
    segments, _ = segments_for(zone, 0, 4102444800)
    info, voyages, n_positions = None, [], 0
    for path in segments:
        conn = connect(path, readonly=True)
        try:
            row = conn.execute("SELECT mmsi, imo, name, callsign, ship_type, length_m, beam_m, ais_class, "
                               "first_seen, last_seen FROM vessel WHERE mmsi = ?", (mmsi,)).fetchone()
            if row:
                keys = ("mmsi", "imo", "name", "callsign", "ship_type", "length_m", "beam_m",
                        "ais_class", "first_seen", "last_seen")
                cur = dict(zip(keys, row))
                if info is None:
                    info = cur
                else:   # se combinan segmentos: lo más reciente manda, lo antiguo rellena huecos
                    info["first_seen"] = min(info["first_seen"], cur["first_seen"])
                    if cur["last_seen"] >= info["last_seen"]:
                        info.update({k: v for k, v in cur.items() if v is not None and k != "first_seen"})
            voyages += conn.execute("SELECT ts, draught_m, destination, eta_raw, eta_utc FROM voyage_data "
                                    "WHERE mmsi = ? ORDER BY ts", (mmsi,)).fetchall()
            n_positions += conn.execute("SELECT COUNT(*) FROM position WHERE mmsi = ?", (mmsi,)).fetchone()[0]
        finally:
            conn.close()
    if info is None:
        return None
    info["first_seen"], info["last_seen"] = iso(info["first_seen"]), iso(info["last_seen"])
    info["positions"] = n_positions
    info["voyage"] = [{"ts": iso(t), "draught_m": d, "destination": dest, "eta_raw": er, "eta_utc": iso(eu)}
                      for t, d, dest, er, eu in sorted(voyages)[-100:]]
    return info


def track(zone, mmsi, t_from, t_to):
    """Trayectoria de un buque en formato compacto: [ts, lat, lon, sog, cog, nav_status]."""
    if t_to <= t_from:
        raise ValueError("'to' debe ser posterior a 'from'")
    if t_to - t_from > MAX_TRACK_S:
        raise ValueError("la trayectoria puede pedirse como máximo para 31 días")
    segments, _ = segments_for(zone, t_from, t_to)
    points = []
    for path in segments:
        conn = connect(path, readonly=True)
        try:
            points += conn.execute(
                "SELECT ts, lat, lon, sog, cog, nav_status FROM position "
                "WHERE mmsi = ? AND ts >= ? AND ts < ? ORDER BY ts LIMIT ?",
                (mmsi, t_from, t_to, MAX_LIMIT - len(points))).fetchall()
        finally:
            conn.close()
    points.sort()
    return {"zone": zone.zone_id, "mmsi": mmsi, "from": iso(t_from), "to": iso(t_to),
            "count": len(points), "fields": ["ts", "lat", "lon", "sog", "cog", "nav_status"],
            "points": [list(p) for p in points]}


def bounds(zone):
    """Primera y última posición guardadas (para los extremos de la línea temporal)."""
    segments, _ = segments_for(zone, 0, 4102444800)
    first = last = None
    for path in segments:
        conn = connect(path, readonly=True)
        try:
            a, b = conn.execute("SELECT MIN(ts), MAX(ts) FROM position").fetchone()
        finally:
            conn.close()
        if a is not None:
            first = a if first is None else min(first, a)
            last = b if last is None else max(last, b)
    return {"zone": zone.zone_id, "first": first, "last": last,
            "first_utc": iso(first), "last_utc": iso(last)}
