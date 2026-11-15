# -*- coding: utf-8 -*-
"""
Método de escalas 'escalas-v3' (D-21 y D-22, congelado el 15/11/2026).

Sobre escalas-v2 cambia solo la espera:
  1. Área de espera: mar a menos de wait_area_nm de la bocana, fuera del recinto y sin los
     círculos de wait_area_exclude (puerto de Sagunto).
  2. Histéresis: la espera EMPIEZA en el área con < wait_start_kn (o estado «fondeado» por debajo
     de wait_continue_kn) y CONTINÚA mientras el buque esté en el área por debajo de wait_continue_kn.
  3. La espera sigue viva mientras el buque esté en el área: solo se da por ido si pasa más de
     max_gap_h fuera de ella.
  4. Una escala «sin atraque» se une con la siguiente del mismo buque si empieza antes de join_max_h
     y no hay indicios de otro puerto entre medias.
Además calcula el indicador descriptivo de «merodeo lento» (horas en el área a velocidad entre
wait_start_kn y wait_continue_kn antes de la llegada), que no se suma a la espera.
La zona de relleno (fill_zone) aporta las posiciones de fuera del rectángulo de la zona que caen en el área.
"""
import math
from collections import defaultdict
from pathlib import Path

from . import port_calls as pc
from .config import ConfigError, load_zones
from .geo import in_bbox, point_in_ring
from .queries import MAX_TS, segments_for
from .storage import connect

DEST_VALENCIA = ["ESVLC", "ES VLC", "VLC", "VALENCIA", "VALENCIA PORT"]


def nm(a, b, c, d):
    """Distancia en millas náuticas entre (a, b) y (c, d) en grados."""
    p1, p2 = math.radians(a), math.radians(c)
    dp, dl = p2 - p1, math.radians(d - b)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 3440.065 * math.asin(math.sqrt(h))


class Area:
    """Área de espera de escalas-v3."""

    def __init__(self, method, port_ring):
        self.c = method["wait_area_center"]
        self.r = method["wait_area_nm"]
        self.excl = method["wait_area_exclude"]
        self.port = port_ring

    def in_port(self, lat, lon):
        return point_in_ring(lat, lon, self.port)

    def __contains__(self, p):
        lat, lon = p
        return (nm(lat, lon, *self.c) <= self.r and not any(nm(lat, lon, a, b) <= r for a, b, r in self.excl)
                and not self.in_port(lat, lon))


def classifier(method, area, start_kn, cont_kn):
    """Devuelve classify(p, waiting): 'B' atracado, 'W' esperando o 'M' navegando."""
    berth_kn = method["berth_max_kn"]

    def classify(p, waiting):
        _, lat, lon, sog, nav = p
        if sog is not None and sog >= 102.2:          # 102,3 kn = «no disponible» en AIS
            sog = None
        if area.in_port(lat, lon):
            return "B" if (sog <= berth_kn if sog is not None else nav == 5) else "M"
        if (lat, lon) not in area:
            return "M"
        if sog is None:
            return "W" if nav == 1 else "M"
        if waiting:
            return "W" if sog < cont_kn else "M"
        return "W" if (sog < start_kn or (nav == 1 and sog < cont_kn)) else "M"
    return classify


def split(pts, method, area, classify):
    """Como port_calls.split_calls, con la histéresis y la espera viva mientras el buque esté en el área."""
    gap_s = method["max_gap_h"] * 3600
    calls, cur, prev = [], None, None
    for p in pts:
        cls = classify(p, bool(cur and cur["wait"] and not cur["berth"]))
        here = (p[1], p[2]) in area or area.in_port(p[1], p[2])
        if cur is not None and p[0] - prev[0] > gap_s:
            calls.append(cur)                          # demasiado tiempo sin ver al buque
            cur = None
        if cur is None:
            if cls in ("W", "B"):
                cur = pc._new_call(p, cls, prev)
                cur["last_area"] = p[0]
            prev = (p[0], cls)
            continue
        cur["points"].append(p)
        if here:
            cur["last_area"] = p[0]
        if cur["berth"]:
            if cls == "B":
                cur["berth"].append(p)
                cur["unberth"] = None
            elif not area.in_port(p[1], p[2]):         # sale del recinto: fin de la escala
                cur["exit"] = p[0]
                cur["unberth"] = cur["unberth"] or p[0]
                cur["exit_observed"] = p[0] - prev[0] <= pc.OBSERVED_S
                cur["points"].pop()
                calls.append(cur)
                start = classify(p, False)
                cur = pc._new_call(p, start, (prev[0], "M")) if start == "W" else None
                if cur:
                    cur["last_area"] = p[0]
            elif cur["unberth"] is None:
                cur["unberth"] = p[0]
        else:
            if cls == "W":
                cur["wait"].append(p)
                cur["anchor_out"] = None
            elif cls == "B":
                cur["berth"].append(p)
                if cur["wait"] and cur["anchor_out"] is None:
                    cur["anchor_out"] = p[0]
            else:
                if cur["wait"] and cur["anchor_out"] is None:
                    cur["anchor_out"] = p[0]           # arranca hacia el puerto (o se va)
                if cur["wait"] and p[0] - cur["last_area"] > gap_s:
                    calls.append(cur)                  # más de max_gap_h fuera del área: se fue sin atracar
                    cur = None
        prev = (p[0], cls)
    if cur is not None:
        calls.append(cur)
    return calls


def _is_other_port(dest):
    """¿El último puerto del destino declarado es otro distinto de València? (mismas reglas que eta-v1)"""
    from .eta_accuracy import destination_class
    return destination_class(dest, {"destinos_valencia": DEST_VALENCIA}) == "OTRO"


def other_port_between(fill_pts, voy, area, a, b):
    """Indicios de escala en otro puerto entre a y b: otro destino declarado, o parado (< 0,5 kn) con
    estado «fondeado» o «amarrado» fuera del área de espera."""
    if any(a < ts < b and _is_other_port(dest) for ts, dest in voy):
        return True
    return any(a < ts < b and nav in (1, 5) and (sog or 0) < 0.5 and (lat, lon) not in area and not area.in_port(lat, lon)
               for ts, lat, lon, sog, nav in fill_pts)


def _max_gap_h(pts):
    return max((b[0] - a[0] for a, b in zip(pts, pts[1:])), default=0) / 3600


def join(calls, method, fill_pts, voy, area):
    """Une cada escala «sin atraque» con la siguiente del mismo buque si empieza antes de join_max_h
    y no hay indicios de otro puerto entre medias."""
    out = []
    for c in calls:
        if out and not out[-1]["berth"] and out[-1]["wait"]:
            A = out[-1]
            a, b = A["points"][-1][0], c["points"][0][0]
            if b - a <= method["join_max_h"] * 3600 and not other_port_between(fill_pts, voy, area, a, b):
                J = dict(c)
                J["points"], J["wait"] = A["points"] + c["points"], A["wait"] + c["wait"]
                J["anchor_out"] = c["anchor_out"] or (c["points"][0][0] if not c["wait"] else None)
                J["start_observed"] = A["start_observed"]
                J["_join"] = (_max_gap_h(A["points"]), _max_gap_h(c["points"]), (b - a) / 3600)
                out[-1] = J
                continue
        out.append(c)
    return out


def slow_loiter_h(track, t_from, t_to, area, start_kn, cont_kn):
    """Horas en el área entre start_kn y cont_kn (sin bajar de start_kn) en [t_from, t_to)."""
    s = 0
    for a, b in zip(track, track[1:]):
        if t_from <= a[0] < t_to and a[3] is not None and start_kn <= a[3] < cont_kn and (a[1], a[2]) in area:
            s += min(b[0], t_to) - a[0] if b[0] - a[0] <= 3600 else min(3600, t_to - a[0])
    return s / 3600


def load_fill_v3(zone, method, mmsis):
    """Posiciones y destinos de la zona de relleno (todas: también las de fuera del área, para los indicios
    de otro puerto) y destinos de la propia zona."""
    pts, voy = defaultdict(list), defaultdict(list)
    zones = {z.zone_id: z for z in load_zones(Path(zone.zone_dir).parent.parent)}
    fill = zones.get(method["fill_zone"]) if method["fill_zone"] else None
    if method["fill_zone"] and fill is None:
        raise ConfigError(f"{zone.zone_id}: la zona de relleno '{method['fill_zone']}' no existe")
    ids = sorted(mmsis)
    for z in [zone] + ([fill] if fill else []):
        for path in segments_for(z, 0, MAX_TS)[0]:
            conn = connect(path, readonly=True)
            try:
                for i in range(0, len(ids), 500):
                    chunk = ids[i:i + 500]
                    marks = ",".join("?" * len(chunk))
                    if z is fill:
                        for mmsi, *p in conn.execute(f"SELECT mmsi, ts, lat, lon, sog, nav_status FROM position "
                                                     f"WHERE mmsi IN ({marks})", chunk):
                            pts[mmsi].append(tuple(p))
                    for mmsi, ts, dest in conn.execute(f"SELECT mmsi, ts, destination FROM voyage_data "
                                                       f"WHERE mmsi IN ({marks})", chunk):
                        voy[mmsi].append((ts, dest))
            finally:
                conn.close()
    for d in (pts, voy):
        for lst in d.values():
            lst.sort()
    return pts, voy


def compute(zone, cfg, vessels, points, draughts, zone_gaps, span, rule=None, fill=None):
    """Escalas de la zona con escalas-v3. `rule` = {"start_kn", "continue_kn"} para la sensibilidad."""
    m = cfg["method"]
    area = Area(m, pc._of_kind(cfg, "PORT_AREA")[0]["ring"])
    start_kn = rule["start_kn"] if rule else m["wait_start_kn"]
    cont_kn = rule["continue_kn"] if rule else m["wait_continue_kn"]
    classify = classifier(m, area, start_kn, cont_kn)
    fill_pts, voy = fill if fill is not None else load_fill_v3(zone, m, points.keys())
    out = []
    for mmsi, own in points.items():
        extra = [p for p in fill_pts.get(mmsi, []) if not in_bbox(p[1], p[2], zone.bbox) and (p[1], p[2]) in area]
        pts, fill_ts = pc.merge_fill(own, extra)
        prev_end = 0
        for c in join(split(pts, m, area, classify), m, fill_pts.get(mmsi, []), voy.get(mmsi, []), area):
            d = pc.describe(c, vessels[mmsi], draughts.get(mmsi, []), cfg, zone_gaps, span[1], fill_ts)
            if c.get("_join"):
                ga, gb, gj = c["_join"]
                d["joined_gap_h"] = round(gj, 1)
                # el hueco entre las dos partes no es «buque sin señal»: se sabe que estaba fuera del área
                if "buque sin señal" in d["quality"] and max(ga, gb) <= pc.MAX_TRACK_GAP_H:
                    rest = [r for r in d["quality"].split(": ", 1)[1].split(", ") if not r.startswith("buque sin señal")]
                    d["quality"] = "DUDOSA: " + ", ".join(rest) if rest else "OK"
                    d["max_track_gap_h"] = round(max(ga, gb), 2)
            arrival = d["t_anchor_in"] or d["t_berth"] or d["t_start"]
            t_from = max(prev_end, arrival - m["loiter_window_h"] * 3600)
            d["slow_loiter_h"] = round(slow_loiter_h(pts, t_from, arrival, area, start_kn, cont_kn), 3)
            prev_end = d["t_exit"] or d["t_last_seen"]
            out.append(d)
    out.sort(key=lambda c: (c["t_start"], c["mmsi"]))
    return out
