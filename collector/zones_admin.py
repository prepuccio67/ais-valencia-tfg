# -*- coding: utf-8 -*-
"""
Gestión de zonas desde la API (Fase 5): crear, editar, activar y desactivar.

Cada cambio se valida con las mismas reglas que al arrancar (config.parse_zone),
se escribe en Zones/<ZONA>/zone.json sin dejar nunca el archivo a medias y,
después, el Collector se recarga de forma ordenada para aplicarlo. El histórico
nunca se borra: una zona desactivada sigue consultable (DISEÑO.md §5).
"""
import copy
import json
from datetime import datetime, timezone
from pathlib import Path

from .config import DEFAULT_SAMPLING, KNOWN_SOURCES, ConfigError, parse_zone, zones_root
from .geo import ring_self_intersects
from .storage import write_json_atomic

MAX_ZONE_DEG2 = 25.0        # tamaño máximo del rectángulo envolvente (grados²); València mide 0,13
MAX_VERTICES = 200

DEFAULT_RAW = {
    "schema_version": 1,
    "database": {"current": "current.db", "archive_dir": "archive",
                 "catalog": "archive-catalog.json", "analysis": "analysis.db"},
    "archive_policy": {"period": "yearly", "max_segment_mb": None,
                       "compress_after_days": 365, "compression": "zstd"},
    "sources": list(KNOWN_SOURCES),
    "sampling": dict(DEFAULT_SAMPLING),
    "silence_alert_min": 10,
}


def _polygon_from_geojson(g):
    """Acepta un Polygon, un Feature con Polygon o una FeatureCollection con un Polygon."""
    if isinstance(g, str):
        try:
            g = json.loads(g)
        except json.JSONDecodeError as e:
            raise ConfigError(f"el GeoJSON no es válido: {e}")
    if not isinstance(g, dict):
        raise ConfigError("el GeoJSON debe ser un objeto")
    if g.get("type") == "FeatureCollection":
        polys = [f.get("geometry") for f in g.get("features", []) if (f.get("geometry") or {}).get("type") == "Polygon"]
        if len(polys) != 1:
            raise ConfigError("la FeatureCollection debe contener exactamente un polígono")
        g = polys[0]
    elif g.get("type") == "Feature":
        g = g.get("geometry") or {}
    if g.get("type") != "Polygon" or not g.get("coordinates"):
        raise ConfigError("la geometría debe ser un Polygon (no se admiten MultiPolygon ni líneas)")
    if len(g["coordinates"]) > 1:
        raise ConfigError("el polígono no puede tener agujeros interiores")
    try:
        ring = [[float(p[0]), float(p[1])] for p in g["coordinates"][0]]
    except (TypeError, ValueError, IndexError):
        raise ConfigError("las coordenadas del polígono deben ser pares [longitud, latitud]")
    return {"type": "Polygon", "coordinates": [ring]}


def build_raw(payload, base=None, zone_id=None):
    """Mezcla lo recibido con la configuración anterior (o la de por defecto)."""
    if not isinstance(payload, dict):
        raise ConfigError("se esperaba un objeto JSON")
    raw = copy.deepcopy(base or DEFAULT_RAW)
    raw["zone_id"] = zone_id
    for key in ("name", "description"):
        if key in payload:
            raw[key] = str(payload[key])[:200]
    if "sources" in payload:
        if not isinstance(payload["sources"], list) or not payload["sources"]:
            raise ConfigError("marca al menos una fuente de datos (openseafeed y/o aisstream)")
        raw["sources"] = list(payload["sources"])
    if "active" in payload:
        raw["active"] = bool(payload["active"])
    gtype = payload.get("geometry_type", raw.get("geometry_type"))
    if gtype == "Rectangle" and "bbox" in payload:
        try:
            raw["bbox"] = {k: float(payload["bbox"][k]) for k in ("north", "south", "east", "west")}
        except (KeyError, TypeError, ValueError):
            raise ConfigError("el rectángulo necesita north, south, east y west numéricos")
        raw["geometry_type"] = "Rectangle"
        raw.pop("geometry", None)            # parse_zone la reconstruye a partir de bbox
    elif gtype == "Polygon" and "geometry" in payload:
        raw["geometry_type"] = "Polygon"
        raw["geometry"] = _polygon_from_geojson(payload["geometry"])
        raw.pop("bbox", None)                # parse_zone la calcula a partir del polígono
    elif "geometry_type" in payload and payload["geometry_type"] != raw.get("geometry_type"):
        raise ConfigError("al cambiar el tipo de geometría hay que enviar la geometría nueva")
    return raw


def _validate(raw, zone_dir):
    zone = parse_zone(raw, zone_dir)
    b = zone.bbox
    area = (b["north"] - b["south"]) * (b["east"] - b["west"])
    if area > MAX_ZONE_DEG2:
        raise ConfigError(f"la zona es demasiado grande ({area:.1f} grados²; máximo {MAX_ZONE_DEG2:.0f}): "
                          "recibiría más mensajes de los que la máquina puede procesar")
    if len(zone.ring) - 1 > MAX_VERTICES:
        raise ConfigError(f"el polígono tiene más de {MAX_VERTICES} vértices")
    if len({tuple(p) for p in zone.ring}) < 3:
        raise ConfigError("el polígono necesita al menos 3 vértices distintos")
    if zone.geometry_type == "Polygon" and ring_self_intersects(zone.ring):
        raise ConfigError("el polígono se cruza consigo mismo: revisa el orden de los vértices")
    if not zone.sources:
        raise ConfigError("la zona necesita al menos una fuente de datos")
    # para el archivo se guarda la geometría ya normalizada (anillo cerrado y bbox)
    raw["bbox"] = zone.bbox
    raw["geometry"] = {"type": "Polygon", "coordinates": [zone.ring]}
    return zone


def create_zone(data_dir, payload):
    zid = str(payload.get("zone_id", "")).strip().upper()
    zone_dir = zones_root(data_dir) / zid
    if (zone_dir / "zone.json").exists():
        raise ConfigError(f"ya existe una zona {zid}")
    raw = build_raw(payload, zone_id=zid)
    raw.setdefault("name", zid)
    raw.setdefault("description", "")
    raw.setdefault("active", True)
    raw["created_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if "geometry_type" not in raw:
        raise ConfigError("indica geometry_type ('Rectangle' o 'Polygon') y su geometría")
    _validate(raw, zone_dir)
    zone_dir.mkdir(parents=True, exist_ok=False)
    write_json_atomic(zone_dir / "zone.json", raw)
    return raw


def update_zone(zone, payload):
    if "zone_id" in payload and str(payload["zone_id"]).upper() != zone.zone_id:
        raise ConfigError("el identificador de una zona no se puede cambiar (sus datos dependen de él)")
    raw = build_raw(payload, base=zone.raw, zone_id=zone.zone_id)
    _validate(raw, zone.zone_dir)
    write_json_atomic(Path(zone.zone_dir) / "zone.json", raw)
    return raw


def set_active(zone, active):
    raw = copy.deepcopy(zone.raw)
    raw["active"] = bool(active)
    write_json_atomic(Path(zone.zone_dir) / "zone.json", raw)
    return raw
