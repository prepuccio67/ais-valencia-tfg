# -*- coding: utf-8 -*-
"""
Cálculo de escalas y tiempos de espera (DISEÑO.md §3.3, Fase 7). Método 'escalas-v1'.

1. Cada posición de un buque de carga (tipos 70-79, eslora >= 100 m) se clasifica:
     B  ATRACADO    dentro del recinto portuario y SOG <= 0,5 kn
     W  ESPERANDO   fuera del recinto y SOG <= 1,0 kn (fondeado o a la deriva)
     M  NAVEGANDO   el resto
   Si falta la velocidad se usa el estado AIS (5 amarrado, 1 fondeado).
2. Una escala empieza en la primera espera (o en el atraque, si el buque entra
   directo) y termina cuando el buque, ya atracado, sale del recinto. Cambiar de
   muelle dentro del puerto no corta la escala.
3. Espera = de la primera posición de espera hasta que el buque arranca hacia el
   puerto. Estancia = del atraque al desatraque (inicio de la maniobra de salida).
   Terminal = la del recinto donde pasó más tiempo atracado.
4. Calidad: OK, DUDOSA (con el motivo), EXCLUIDA (con el motivo) o EN CURSO.
   Las estadísticas usan solo las OK.

Método 'escalas-v2' (D-19): igual que el anterior, pero la trayectoria de cada buque se
completa con las posiciones de otra zona (`fill_zone`, la de aproximación) que caen fuera
del rectángulo de esta zona y dentro de un «área de espera ampliada» (el mismo rectángulo
con el borde este movido a `fill_box_east`). Así se ve a los buques que esperan a la
deriva justo al este del borde. Con `fill_zone: null` el resultado es el de escalas-v1.

Los parámetros y las subzonas están en Zones/<ZONA>/subzones.geojson.
"""
import bisect
import hashlib
import json
import shutil
from collections import Counter, defaultdict
from pathlib import Path

from .config import REPO_ROOT, ConfigError, load_zones
from .geo import in_bbox, point_in_ring
from .queries import MAX_TS, gaps, parse_when, segments_for
from .storage import connect

DEFAULT_METHOD = {"version": "escalas-v1", "ship_types": [70, 79], "min_length_m": 100,
                  "berth_max_kn": 0.5, "anchor_max_kn": 1.0, "max_gap_h": 12,
                  "max_wait_days": 10, "min_stay_h": 2,
                  # escalas-v2 (D-19); con estos tres valores vacíos el método es escalas-v1
                  "fill_zone": None,           # zona con la que se completan los huecos (APROXIMACION)
                  "fill_box_east": None,       # borde este del área de espera ampliada (grados)
                  "wait_stats_from": None}     # las estadísticas de espera solo usan escalas desde esta hora
KINDS = ("PORT_AREA", "TERMINAL", "ANCHORAGE")
OBSERVED_S = 3600        # una llegada o salida cuenta como vista si hay un punto en movimiento a menos de 1 h
MAX_TRACK_GAP_H = 2      # parado se guarda 1 posición cada 10 min: más de 2 h sin datos es pérdida de señal
OTHER_BERTH = "OTRO"     # atracado dentro del puerto pero fuera de las terminales dibujadas
GAP_TOLERANCE_MIN = 15   # huecos de zona más cortos (p. ej. un reinicio de segundos) no restan calidad


# ------------------------------------------------------------ configuración
def subzones_path(zone):
    return Path(zone.zone_dir) / "subzones.geojson"


def has_port_analysis(zone):
    """¿Tiene la zona terminales y fondeadero (subzones.geojson propio o de ejemplo)?
    Las zonas sin ellos (p. ej. la de aproximación) no tienen escalas, pero tampoco dan error."""
    example = REPO_ROOT / "config-ejemplo" / "zones" / zone.zone_id / "subzones.geojson"
    return subzones_path(zone).exists() or example.exists()


def load_config(zone):
    """Lee subzones.geojson (si no existe, copia el de ejemplo de la zona) y lo valida."""
    path = subzones_path(zone)
    if not path.exists():
        example = REPO_ROOT / "config-ejemplo" / "zones" / zone.zone_id / "subzones.geojson"
        if not example.exists():
            raise ConfigError(f"{zone.zone_id}: falta {path} (las subzonas del análisis)")
        shutil.copyfile(example, path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigError(f"{path.name} no es un JSON válido: {e}")
    method = dict(DEFAULT_METHOD)
    method.update(raw.get("method") or {})
    if method["fill_zone"] is not None:
        east = method["fill_box_east"]
        if isinstance(east, bool) or not isinstance(east, (int, float)) or not zone.bbox["east"] < east <= 180:
            raise ConfigError(f"{path.name}: con fill_zone hay que indicar fill_box_east, un número mayor que "
                              f"el borde este de la zona ({zone.bbox['east']})")
        if method["fill_zone"] == zone.zone_id:
            raise ConfigError(f"{path.name}: fill_zone no puede ser la propia zona")
    if method["wait_stats_from"] is not None:
        try:
            parse_when(method["wait_stats_from"], "wait_stats_from")
        except ValueError as e:
            raise ConfigError(f"{path.name}: wait_stats_from no es una fecha válida ({e})")
    subzones = []
    for f in raw.get("features") or []:
        props, geom = f.get("properties") or {}, f.get("geometry") or {}
        sid, kind = props.get("subzone_id"), props.get("kind")
        if not sid or kind not in KINDS or geom.get("type") != "Polygon":
            raise ConfigError(f"{path.name}: cada subzona necesita subzone_id, kind {list(KINDS)} y un Polygon")
        ring = [[float(x), float(y)] for x, y in geom["coordinates"][0]]
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        subzones.append({"subzone_id": str(sid), "kind": kind, "name": props.get("name") or str(sid),
                         "notes": props.get("notes") or "", "ring": ring})
    if sum(s["kind"] == "PORT_AREA" for s in subzones) != 1:
        raise ConfigError(f"{path.name}: tiene que haber exactamente una subzona PORT_AREA (el recinto portuario)")
    fingerprint = hashlib.sha256(json.dumps({"m": method, "s": subzones}, sort_keys=True).encode()).hexdigest()[:16]
    return {"method": method, "subzones": subzones, "fingerprint": fingerprint}


def _of_kind(cfg, kind):
    return [s for s in cfg["subzones"] if s["kind"] == kind]


def _where(lat, lon, subzones):
    for s in subzones:
        if point_in_ring(lat, lon, s["ring"]):
            return s["subzone_id"]
    return None


# ------------------------------------------------------------ lectura de datos
def load_data(zone, method):
    """Buques que cumplen el filtro, con sus posiciones y calados, leyendo todos los segmentos."""
    segments, _ = segments_for(zone, 0, MAX_TS)
    vessels = {}
    for path in segments:                      # de antiguo a reciente: el más reciente manda
        conn = connect(path, readonly=True)
        try:
            for row in conn.execute("SELECT mmsi, imo, name, ship_type, length_m FROM vessel"):
                v = vessels.setdefault(row[0], {"mmsi": row[0]})
                for k, val in zip(("imo", "name", "ship_type", "length_m"), row[1:]):
                    if val is not None:
                        v[k] = val
        finally:
            conn.close()
    lo, hi = method["ship_types"]
    wanted = {m: v for m, v in vessels.items()
              if lo <= (v.get("ship_type") or -1) <= hi and (v.get("length_m") or 0) >= method["min_length_m"]}
    points, draughts, first, last = defaultdict(list), defaultdict(list), None, None
    ids = sorted(wanted)
    for path in segments:
        conn = connect(path, readonly=True)
        try:
            a, b = conn.execute("SELECT MIN(ts), MAX(ts) FROM position").fetchone()
            if a is not None:
                first, last = min(first or a, a), max(last or b, b)
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                marks = ",".join("?" * len(chunk))
                for mmsi, *p in conn.execute(f"SELECT mmsi, ts, lat, lon, sog, nav_status FROM position "
                                             f"WHERE mmsi IN ({marks})", chunk):
                    points[mmsi].append(tuple(p))
                for mmsi, ts, d in conn.execute(f"SELECT mmsi, ts, draught_m FROM voyage_data WHERE mmsi IN ({marks}) "
                                                f"AND draught_m IS NOT NULL", chunk):
                    draughts[mmsi].append((ts, d))
        finally:
            conn.close()
    for lst in list(points.values()) + list(draughts.values()):
        lst.sort()
    return wanted, points, draughts, (first, last)


def load_fill(zone, method, mmsis):
    """Posiciones de la zona de relleno (escalas-v2) para completar las trayectorias.

    Solo las que están FUERA del rectángulo de `zone` (dentro ya manda `zone`, que tiene más
    detalle) y DENTRO del área de espera ampliada: mismas latitudes y borde oeste, y borde
    este en fill_box_east. Así un buque parado en otro puerto no cuenta como espera aquí.
    """
    if method["fill_zone"] is None or not mmsis:
        return {}
    others = {z.zone_id: z for z in load_zones(Path(zone.zone_dir).parent.parent)}
    fill = others.get(method["fill_zone"])
    if fill is None:
        raise ConfigError(f"{zone.zone_id}: la zona de relleno '{method['fill_zone']}' no existe")
    b = zone.bbox
    out = defaultdict(list)
    ids = sorted(mmsis)
    for path in segments_for(fill, 0, MAX_TS)[0]:
        conn = connect(path, readonly=True)
        try:
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                marks = ",".join("?" * len(chunk))
                for mmsi, *p in conn.execute(
                        f"SELECT mmsi, ts, lat, lon, sog, nav_status FROM position WHERE mmsi IN ({marks}) "
                        "AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
                        chunk + [b["south"], b["north"], b["west"], method["fill_box_east"]]):
                    if not in_bbox(p[1], p[2], b):
                        out[mmsi].append(tuple(p))
        finally:
            conn.close()
    return out


def merge_fill(pts, extra):
    """Mezcla por hora las posiciones propias con las de relleno. Devuelve (puntos, horas de relleno).
    Si las dos zonas tienen una posición con la misma hora, se queda la propia."""
    if not extra:
        return pts, frozenset()
    own = {p[0] for p in pts}
    added = {p[0]: p for p in extra if p[0] not in own}
    return sorted(pts + list(added.values())), frozenset(added)


def zone_gap_intervals(zone, t_from, t_to, now):
    """Huecos de toda la zona como [(inicio, fin)] en segundos."""
    out = []
    for g in gaps(zone, t_from, t_to, now=now)["zone_gaps"]:
        out.append((parse_when(g["start"], "start"), parse_when(g["end"], "end") if g["end"] else now))
    return out


# ------------------------------------------------------------ el método
def classify(point, port_ring, m):
    _, lat, lon, sog, nav = point
    if sog is not None and sog >= 102.2:       # 102,3 kn = «velocidad no disponible» en AIS
        sog = None
    if point_in_ring(lat, lon, port_ring):
        return "B" if (sog <= m["berth_max_kn"] if sog is not None else nav == 5) else "M"
    return "W" if (sog <= m["anchor_max_kn"] if sog is not None else nav == 1) else "M"


def _new_call(p, cls, prev):
    observed = prev is not None and prev[1] == "M" and p[0] - prev[0] <= OBSERVED_S
    return {"points": [p], "wait": [p] if cls == "W" else [], "berth": [p] if cls == "B" else [],
            "anchor_out": None, "unberth": None, "exit": None, "start_observed": observed}


def split_calls(pts, cfg):
    """Recorre las posiciones de un buque (ordenadas por hora) y las agrupa en escalas."""
    m = cfg["method"]
    port = _of_kind(cfg, "PORT_AREA")[0]["ring"]
    gap_s = m["max_gap_h"] * 3600
    calls, cur, prev = [], None, None          # prev = (hora, clase) del punto anterior
    for p in pts:
        cls = classify(p, port, m)
        if cur is not None and p[0] - prev[0] > gap_s:
            calls.append(cur)                  # demasiado tiempo sin ver al buque: escala sin final visto
            cur = None
        if cur is None:
            if cls in ("W", "B"):
                cur = _new_call(p, cls, prev)
            prev = (p[0], cls)
            continue
        cur["points"].append(p)
        inside = point_in_ring(p[1], p[2], port)
        if cur["berth"]:                       # ya ha atracado
            if cls == "B":
                cur["berth"].append(p)
                cur["unberth"] = None          # cambio de muelle: sigue la misma escala
            elif not inside:                   # ha salido del recinto: fin de la escala
                cur["exit"] = p[0]
                cur["unberth"] = cur["unberth"] or p[0]
                cur["exit_observed"] = p[0] - prev[0] <= OBSERVED_S
                cur["points"].pop()
                calls.append(cur)
                cur = _new_call(p, cls, (prev[0], "M")) if cls == "W" else None
            elif cur["unberth"] is None:
                cur["unberth"] = p[0]          # empieza a moverse: desatraque (o cambio de muelle)
        else:                                  # aún esperando o acercándose
            if cls == "W":
                cur["wait"].append(p)
                cur["anchor_out"] = None
            elif cls == "B":
                cur["berth"].append(p)
                if cur["wait"] and cur["anchor_out"] is None:
                    cur["anchor_out"] = p[0]
            else:
                if cur["wait"] and cur["anchor_out"] is None:
                    cur["anchor_out"] = p[0]   # arranca hacia el puerto (o se va)
                if cur["wait"] and p[0] - cur["wait"][-1][0] > gap_s:
                    calls.append(cur)          # se fue sin atracar
                    cur = None
        prev = (p[0], cls)
    if cur is not None:
        calls.append(cur)
    return calls


def _latest(series, t):
    """Último valor de una serie [(hora, valor)] anterior o igual a t."""
    i = bisect.bisect_right(series, (t, float("inf")))
    return series[i - 1][1] if i else None


def describe(call, vessel, draughts, cfg, zone_gaps, data_end, fill_ts=frozenset()):
    """Convierte una escala en bruto en una fila de port_call, con sus tiempos y su calidad."""
    m = cfg["method"]
    pts, wait, berth = call["points"], call["wait"], call["berth"]
    t_anchor_in = wait[0][0] if wait else None
    t_anchor_out = (call["anchor_out"] or wait[-1][0]) if wait else None
    t_berth = berth[0][0] if berth else None
    t_unberth = call["unberth"] or (berth[-1][0] if berth else None)
    t_start, t_end = pts[0][0], call["exit"] or pts[-1][0]
    wait_h = (t_anchor_out - t_anchor_in) / 3600 if wait else 0.0
    stay_h = (t_unberth - t_berth) / 3600 if berth and call["exit"] else None
    terms = Counter(_where(p[1], p[2], _of_kind(cfg, "TERMINAL")) or OTHER_BERTH for p in berth)
    places = Counter(_where(p[1], p[2], _of_kind(cfg, "ANCHORAGE")) or "DERIVA" for p in wait)
    track_gap = max((b[0] - a[0] for a, b in zip(pts, pts[1:])), default=0) / 3600
    gap_min = sum(max(0, min(b, t_end) - max(a, t_start)) for a, b in zone_gaps) / 60
    overlaps = gap_min >= GAP_TOLERANCE_MIN
    censored_start = not call["start_observed"]
    censored_end = not (call["exit"] and call.get("exit_observed"))
    ongoing = call["exit"] is None and data_end - pts[-1][0] <= m["max_gap_h"] * 3600
    reasons = []
    if ongoing:
        quality = "EN CURSO"
    elif not berth:
        quality = "EXCLUIDA: sin atraque"
    elif wait_h > m["max_wait_days"] * 24:
        quality = f"EXCLUIDA: espera de más de {m['max_wait_days']} días"
    else:
        if censored_start:
            reasons.append("llegada no observada")
        if censored_end:
            reasons.append("salida no observada")
        if overlaps:
            reasons.append("hueco de datos de la zona")
        if track_gap > MAX_TRACK_GAP_H:
            reasons.append(f"buque sin señal {track_gap:.0f} h")
        if stay_h is not None and stay_h < m["min_stay_h"]:
            reasons.append(f"estancia < {m['min_stay_h']} h")
        quality = "DUDOSA: " + ", ".join(reasons) if reasons else "OK"
    lat = sorted(p[1] for p in berth)[len(berth) // 2] if berth else None
    lon = sorted(p[2] for p in berth)[len(berth) // 2] if berth else None
    return {"mmsi": vessel["mmsi"], "imo": vessel.get("imo"), "name": vessel.get("name"),
            "ship_type": vessel.get("ship_type"), "length_m": vessel.get("length_m"),
            "terminal_id": terms.most_common(1)[0][0] if berth else None,
            "wait_location": places.most_common(1)[0][0] if wait else None,
            "t_start": t_start, "t_anchor_in": t_anchor_in, "t_anchor_out": t_anchor_out, "t_berth": t_berth,
            "t_unberth": t_unberth if call["exit"] else None, "t_exit": call["exit"], "t_last_seen": pts[-1][0],
            "wait_h": round(wait_h, 3), "stay_h": None if stay_h is None else round(stay_h, 3),
            "draught_in_m": _latest(draughts, t_berth or t_start),
            "draught_out_m": _latest(draughts, t_end) if call["exit"] else None,
            "berth_lat": lat, "berth_lon": lon,
            "censored_start": int(censored_start), "censored_end": int(censored_end),
            "overlaps_gap": int(overlaps), "gap_overlap_min": round(gap_min, 1),
            "max_track_gap_h": round(track_gap, 2),
            "fill_points": sum(1 for p in pts if p[0] in fill_ts),
            "quality": quality, "method_version": m["version"]}


def compute(zone, cfg, now):
    """Todas las escalas de la zona, ordenadas por hora de inicio."""
    vessels, points, draughts, (first, last) = load_data(zone, cfg["method"])
    if first is None:
        return [], (None, None)
    zone_gaps = zone_gap_intervals(zone, first, now + 1, now)
    fill = load_fill(zone, cfg["method"], points.keys())
    out = []
    for mmsi, own in points.items():
        pts, fill_ts = merge_fill(own, fill.get(mmsi))
        for call in split_calls(pts, cfg):
            out.append(describe(call, vessels[mmsi], draughts.get(mmsi, []), cfg, zone_gaps, last, fill_ts))
    out.sort(key=lambda c: (c["t_start"], c["mmsi"]))
    return out, (first, last)
