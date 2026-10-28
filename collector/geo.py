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
