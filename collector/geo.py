# -*- coding: utf-8 -*-
"""Utilidades geográficas sencillas (sin librerías externas)."""


def in_bbox(lat, lon, bbox):
    """¿Está el punto dentro del rectángulo {north, south, east, west}?"""
    return bbox["south"] <= lat <= bbox["north"] and bbox["west"] <= lon <= bbox["east"]


def point_in_ring(lat, lon, ring):
    """Punto en polígono por el método del rayo.

    ring es un anillo GeoJSON: lista de [lon, lat] (¡longitud primero!).
    Un punto exactamente sobre el borde puede quedar dentro o fuera; para AIS
    (precisión de metros) no importa.
    """
    inside = False
    n = len(ring)
    for i in range(n - 1):
        x1, y1 = ring[i]
        x2, y2 = ring[i + 1]
        if (y1 > lat) != (y2 > lat):
            x_cross = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
            if lon < x_cross:
                inside = not inside
    return inside


def in_zone(lat, lon, zone):
    """¿Pertenece el punto a la zona? Primero el rectángulo (rápido), luego el polígono."""
    if lat is None or lon is None or not in_bbox(lat, lon, zone.bbox):
        return False
    if zone.geometry_type == "Rectangle":
        return True
    return point_in_ring(lat, lon, zone.ring)


def _segments_cross(p1, p2, p3, p4):
    """¿Se cruzan los segmentos p1-p2 y p3-p4? (sin contar extremos compartidos)."""
    def orient(a, b, c):
        v = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        return (v > 1e-12) - (v < -1e-12)
    o1, o2 = orient(p1, p2, p3), orient(p1, p2, p4)
    o3, o4 = orient(p3, p4, p1), orient(p3, p4, p2)
    return o1 * o2 < 0 and o3 * o4 < 0


def ring_self_intersects(ring):
    """¿Se cruza el polígono consigo mismo? (un "lazo" o "pajarita" daría zonas absurdas)."""
    n = len(ring) - 1                     # el último punto repite el primero
    edges = [(ring[i], ring[i + 1]) for i in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            if j == i + 1 or (i == 0 and j == n - 1):
                continue                  # lados contiguos: comparten un vértice
            if _segments_cross(*edges[i], *edges[j]):
                return True
    return False
