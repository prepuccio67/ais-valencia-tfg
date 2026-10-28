# -*- coding: utf-8 -*-
"""
Consultas de solo lectura para la API (DISEÑO.md §6 y §8).

La API no sabe cuántos archivos hay: lee el catálogo, elige los segmentos que
cubren el intervalo pedido, consulta cada uno en solo lectura y une los
resultados por orden de hora. Estas funciones son síncronas; la API las lanza
en un hilo aparte para no frenar la captura.
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from .storage import connect, iso

MAX_LIMIT = 50000
MAX_RANGE_ALL_S = 31 * 86400
MAX_TS = 4102444800          # 01/01/2100


def parse_when(value, name):
    """Acepta ISO 8601 (2026-10-28T12:00:00Z), fecha (2026-10-28) o epoch en segundos."""
    if value is None or value == "":
        return None
    v = str(value).strip()
    if v.isdigit() and len(v) <= 12:
        ts = int(v)
    else:
        try:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError(f"'{name}' no es una fecha válida: use 2026-10-28T12:00:00Z")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        ts = int(dt.timestamp())
    if not 0 <= ts <= MAX_TS:
        raise ValueError(f"'{name}' fuera de rango (1970-2100)")
    return ts


def read_catalog(zone):
    path = Path(zone.zone_dir) / zone.database["catalog"]
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"zone_id": zone.zone_id, "segments": []}


def _seg_bounds(seg):
    a = parse_when(seg.get("from_utc"), "from_utc") or 0
    b = parse_when(seg.get("to_utc"), "to_utc") if seg.get("to_utc") else None
    return a, b


def segments_for(zone, t_from, t_to):
    """Segmentos del catálogo que se solapan con [t_from, t_to). Devuelve (consultables, no disponibles)."""
    usable, unavailable = [], []
    # Un segmento puede contener posiciones algo anteriores a su inicio (se aceptan mensajes
    # con hasta max_age_s de antigüedad), así que se amplía su comienzo por ese margen.
    margin = int(zone.sampling.get("max_age_s", 900))
    segs = sorted(read_catalog(zone)["segments"], key=lambda s: _seg_bounds(s)[0])
    for seg in segs:
        a, b = _seg_bounds(seg)
        a -= margin
        if (b is not None and b <= t_from) or a >= t_to:
            continue
        path = Path(zone.zone_dir) / seg["path"]
        if seg.get("status") == "ONLINE" and path.exists():
            usable.append(path)
        else:
            unavailable.append({"segment_id": seg.get("segment_id"), "status": seg.get("status"),
                                "from_utc": seg.get("from_utc"), "to_utc": seg.get("to_utc")})
    return usable, unavailable


def current_db(zone):
    return Path(zone.zone_dir) / zone.database["current"]


# ------------------------------------------------------------ posiciones
def archive_range(zone, t_from, t_to, mmsi=None, bbox=None, limit=10000, after=None):
    if t_to <= t_from:
        raise ValueError("'to' debe ser posterior a 'from'")
    if mmsi is None and t_to - t_from > MAX_RANGE_ALL_S:
        raise ValueError("para intervalos de más de 31 días indique un 'mmsi'")
    limit = max(1, min(int(limit), MAX_LIMIT))
    where, args = ["p.ts >= ?", "p.ts < ?"], [t_from, t_to]
    if mmsi is not None:
        where.append("p.mmsi = ?")
        args.append(mmsi)
    if bbox is not None:
        s, w, n, e = bbox
        where.append("p.lat BETWEEN ? AND ? AND p.lon BETWEEN ? AND ?")
        args += [s, n, w, e]
    if after is not None:
        where.append("(p.ts, p.mmsi) > (?, ?)")
        args += list(after)
    sql = ("SELECT p.mmsi, p.ts, p.lat, p.lon, p.sog, p.cog, p.heading, p.nav_status, s.name, p.reason, "
           "p.ts_rx FROM position p JOIN source s USING (source_id) WHERE " + " AND ".join(where) +
           " ORDER BY p.ts, p.mmsi LIMIT ?")
    segments, unavailable = segments_for(zone, t_from, t_to)
    rows = []
    for path in segments:
        conn = connect(path, readonly=True)
        try:
            rows += conn.execute(sql, args + [limit - len(rows)]).fetchall()
        finally:
            conn.close()
        if len(rows) >= limit:
            break
    positions = [{"mmsi": r[0], "ts": iso(r[1]), "lat": r[2], "lon": r[3], "sog": r[4], "cog": r[5],
                  "heading": r[6], "nav_status": r[7], "source": r[8], "reason": r[9],
                  "delay_s": r[10] - r[1]} for r in rows]
    nxt = f"{rows[-1][1]}:{rows[-1][0]}" if len(rows) >= limit else None
    return {"zone": zone.zone_id, "from": iso(t_from), "to": iso(t_to), "count": len(positions),
            "next_after": nxt, "segments_used": len(segments), "segments_unavailable": unavailable,
            "positions": positions}


# ------------------------------------------------------------ huecos
def _merge(intervals):
    out = []
    for a, b in sorted(intervals):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _intersect(xs, ys):
    out, i, j = [], 0, 0
    while i < len(xs) and j < len(ys):
        a, b = max(xs[i][0], ys[j][0]), min(xs[i][1], ys[j][1])
        if a < b:
            out.append([a, b])
        if xs[i][1] < ys[j][1]:
            i += 1
        else:
            j += 1
    return out


def gaps(zone, t_from, t_to, status=None, now=None):
    now = now or int(time.time())
    segments, _ = segments_for(zone, t_from, t_to)
    rows = []
    for path in segments:
        conn = connect(path, readonly=True)
        try:
            rows += conn.execute(
                "SELECT g.gap_id, s.name, g.start_ts, g.end_ts, g.reason, g.status, g.notes "
                "FROM gap g LEFT JOIN source s USING (source_id) "
                "WHERE g.start_ts < ? AND COALESCE(g.end_ts, ?) > ? ORDER BY g.start_ts",
                (t_to, now, t_from)).fetchall()
        finally:
            conn.close()
    # el filtro de estado solo afecta a la lista mostrada; los huecos de zona usan todos
    shown = [r for r in rows if not status or r[5] == status]
    source_gaps = [{"gap_id": r[0], "source": r[1] or "(toda la zona)", "start": iso(r[2]),
                    "end": iso(r[3]), "open": r[3] is None,
                    "minutes": round(((r[3] or now) - r[2]) / 60, 1),
                    "reason": r[4], "status": r[5], "notes": r[6]} for r in shown]
    # Hueco de zona = hueco "de toda la zona" o periodo en que TODAS las fuentes tenían hueco.
    whole = [[r[2], r[3] or now] for r in rows if r[1] is None]
    per_source = None
    for src in zone.sources:
        iv = _merge([[r[2], r[3] or now] for r in rows if r[1] == src])
        per_source = iv if per_source is None else _intersect(per_source, iv)
    zone_gaps = _merge(whole + (per_source or []))
    return {"zone": zone.zone_id, "from": iso(t_from), "to": iso(t_to),
            "pending": sum(1 for r in rows if r[5] == "PENDING"),
            "zone_gaps": [{"start": iso(a), "end": iso(b) if b < now else None,
                           "minutes": round((b - a) / 60, 1)} for a, b in zone_gaps],
            "source_gaps": source_gaps}


# ------------------------------------------------------------ cobertura y estadísticas
BUCKETS = {"minute": 60, "hour": 3600, "day": 86400}


def coverage(zone, t_from, t_to, bucket="hour"):
    if bucket not in BUCKETS:
        raise ValueError("bucket debe ser minute, hour o day")
    step = BUCKETS[bucket]
    if bucket == "minute" and t_to - t_from > 2 * 86400:
        raise ValueError("con bucket=minute el intervalo máximo es de 2 días")
    segments, _ = segments_for(zone, t_from, t_to)
    out = {}
    for path in segments:
        conn = connect(path, readonly=True)
        try:
            for b, src, msgs, vessels in conn.execute(
                    "SELECT (c.minute / ?) * ?, s.name, SUM(c.msgs), MAX(c.vessels) FROM coverage_minute c "
                    "JOIN source s USING (source_id) WHERE c.minute >= ? AND c.minute < ? "
                    "GROUP BY 1, 2 ORDER BY 1", (step, step, t_from, t_to)):
                out.setdefault(b, {})[src] = {"msgs": msgs, "max_vessels_per_min": vessels}
        finally:
            conn.close()
    return {"zone": zone.zone_id, "bucket": bucket,
            "rows": [{"t": iso(b), "sources": out[b]} for b in sorted(out)]}


def zone_stats(zone, now=None):
    now = now or int(time.time())
    path = current_db(zone)
    if not path.exists():
        return {"available": False}
    conn = connect(path, readonly=True)
    try:
        midnight = now - now % 86400
        size = sum(p.stat().st_size for p in path.parent.glob(path.name + "*") if p.is_file())
        first, last = conn.execute("SELECT MIN(ts), MAX(ts) FROM position").fetchone()
        return {
            "available": True,
            "vessels_last_hour": conn.execute(
                "SELECT COUNT(DISTINCT mmsi) FROM position WHERE ts >= ?", (now - 3600,)).fetchone()[0],
            "positions_today": conn.execute(
                "SELECT COUNT(*) FROM position WHERE ts >= ?", (midnight,)).fetchone()[0],
            "vessels_known": conn.execute("SELECT COUNT(*) FROM vessel").fetchone()[0],
            "open_gaps": conn.execute("SELECT COUNT(*) FROM gap WHERE end_ts IS NULL").fetchone()[0],
            "pending_gaps": conn.execute("SELECT COUNT(*) FROM gap WHERE status = 'PENDING'").fetchone()[0],
            "first_position": iso(first), "last_position": iso(last),
            "current_db_bytes": size,
        }
    finally:
        conn.close()
