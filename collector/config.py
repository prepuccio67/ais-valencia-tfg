# -*- coding: utf-8 -*-
"""
Configuración: lee el archivo .env (claves y CollectorId) y los zone.json.

El .env tiene líneas CLAVE=valor. Nunca se sube a GitHub (está en .gitignore).
Cada zona vive en DATA_DIR/Zones/<ZONE_ID>/zone.json (formato en DISEÑO.md §5).
"""
import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

KNOWN_SOURCES = ("openseafeed", "aisstream")
REPO_ROOT = Path(__file__).resolve().parent.parent

# Valores por defecto del muestreo (DISEÑO.md §4); zone.json puede cambiarlos.
DEFAULT_SAMPLING = {
    "moving_interval_s": 60,      # en movimiento: 1 posición por minuto
    "stopped_interval_s": 600,    # parado: 1 cada 10 minutos
    "stopped_speed_kn": 0.3,      # por debajo de esto, un buque que se movía pasa a "parado"
    "moving_speed_kn": 0.5,       # desde esto, un buque parado pasa a "en movimiento" (= umbral de atracado)
    "max_age_s": 900,             # se descartan posiciones con más de 15 min de antigüedad
    "min_event_gap_s": 10,        # separación mínima entre dos guardados por evento
}


class ConfigError(Exception):
    """Error de configuración explicado en lenguaje sencillo."""


# ------------------------------------------------------------------ .env
def load_env_file(path):
    """Lee un .env sencillo (CLAVE=valor; # para comentarios). Devuelve un dict."""
    values = {}
    p = Path(path)
    if not p.exists():
        return values
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        # comentario al final de la línea solo si va precedido de un espacio
        value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


@dataclass
class Settings:
    collector_id: str
    data_dir: Path
    api_host: str
    api_port: int
    api_token: str
    aisstream_key: str = ""
    openseafeed_key: str = ""


def load_settings(env_path=None):
    """Combina el .env con las variables de entorno (estas tienen prioridad)."""
    env = load_env_file(env_path or REPO_ROOT / ".env")
    env.update({k: v for k, v in os.environ.items() if k in (
        "COLLECTOR_ID", "DATA_DIR", "API_HOST", "API_PORT", "API_TOKEN",
        "AISSTREAM_API_KEY", "OPENSEAFEED_API_KEY")})

    collector_id = env.get("COLLECTOR_ID", "").strip()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{1,40}", collector_id):
        raise ConfigError("COLLECTOR_ID debe ser algo como VALENCIA-01 (mayúsculas, números y guiones).")
    token = env.get("API_TOKEN", "")
    if len(token) < 24 or token.startswith("cambia-esto"):
        raise ConfigError("API_TOKEN debe tener al menos 24 caracteres aleatorios (ver README).")
    data_dir = env.get("DATA_DIR", "").strip()
    if not data_dir:
        raise ConfigError("Falta DATA_DIR en el .env (carpeta donde se guardan los datos).")
    try:
        port = int(env.get("API_PORT", "5080"))
    except ValueError:
        raise ConfigError("API_PORT debe ser un número (p. ej. 5080).")
    return Settings(
        collector_id=collector_id,
        data_dir=Path(data_dir).expanduser(),
        api_host=env.get("API_HOST", "127.0.0.1") or "127.0.0.1",
        api_port=port,
        api_token=token,
        aisstream_key=env.get("AISSTREAM_API_KEY", ""),
        openseafeed_key=env.get("OPENSEAFEED_API_KEY", ""),
    )


# ------------------------------------------------------------------ zonas
@dataclass
class ZoneConfig:
    zone_id: str
    name: str
    description: str
    created_utc: str
    active: bool
    geometry_type: str            # "Rectangle" o "Polygon"
    bbox: dict                    # {"north", "south", "east", "west"}
    ring: list                    # anillo exterior GeoJSON: [[lon, lat], ...] cerrado
    database: dict
    archive_policy: dict
    sources: list
    sampling: dict
    silence_alert_min: float
    zone_dir: Path
    raw: dict = field(repr=False, default_factory=dict)

    def geometry_fingerprint(self):
        """Texto que identifica la geometría: si cambia, se anota en el registro de sucesos."""
        return json.dumps({"type": self.geometry_type, "bbox": self.bbox, "ring": self.ring},
                          sort_keys=True, separators=(",", ":"))


def _bbox_from_ring(ring):
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    return {"north": max(lats), "south": min(lats), "east": max(lons), "west": min(lons)}


def parse_zone(raw, zone_dir):
    """Valida un zone.json ya leído y devuelve un ZoneConfig."""
    zone_dir = Path(zone_dir)
    zid = str(raw.get("zone_id", ""))
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{0,40}", zid):
        raise ConfigError(f"{zone_dir}: zone_id inválido ('{zid}'): usa mayúsculas, números y guiones.")
    if zid != zone_dir.name:
        raise ConfigError(f"{zone_dir}: zone_id '{zid}' no coincide con el nombre de la carpeta.")
    gtype = raw.get("geometry_type")
    if gtype not in ("Rectangle", "Polygon"):
        raise ConfigError(f"{zid}: geometry_type debe ser 'Rectangle' o 'Polygon'.")

    geom = raw.get("geometry") or {}
    ring = None
    if geom.get("type") == "Polygon" and geom.get("coordinates"):
        ring = [[float(p[0]), float(p[1])] for p in geom["coordinates"][0]]
    bbox = raw.get("bbox")
    if gtype == "Rectangle":
        if not bbox:
            raise ConfigError(f"{zid}: una zona Rectangle necesita 'bbox' (north, south, east, west).")
        bbox = {k: float(bbox[k]) for k in ("north", "south", "east", "west")}
        if ring is None:
            ring = [[bbox["west"], bbox["south"]], [bbox["east"], bbox["south"]],
                    [bbox["east"], bbox["north"]], [bbox["west"], bbox["north"]],
                    [bbox["west"], bbox["south"]]]
    else:
        if ring is None:
            raise ConfigError(f"{zid}: una zona Polygon necesita 'geometry' GeoJSON de tipo Polygon.")
    if ring[0] != ring[-1]:
        ring.append(list(ring[0]))
    if len(ring) < 4:
        raise ConfigError(f"{zid}: el polígono necesita al menos 3 vértices.")
    for lon, lat in ring:
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ConfigError(f"{zid}: coordenada fuera de rango ({lon}, {lat}). Recuerda: GeoJSON es [lon, lat].")
    if gtype == "Polygon":
        bbox = _bbox_from_ring(ring)
    if not (bbox["south"] < bbox["north"] and bbox["west"] < bbox["east"]):
        raise ConfigError(f"{zid}: el rectángulo está al revés (sur debe ser < norte y oeste < este).")

    sources = list(raw.get("sources") or KNOWN_SOURCES)
    unknown = [s for s in sources if s not in KNOWN_SOURCES]
    if unknown:
        raise ConfigError(f"{zid}: fuentes desconocidas {unknown}. Válidas: {list(KNOWN_SOURCES)}.")
    sampling = dict(DEFAULT_SAMPLING)
    sampling.update(raw.get("sampling") or {})
    if sampling["moving_speed_kn"] < sampling["stopped_speed_kn"]:
        raise ConfigError(f"{zid}: moving_speed_kn no puede ser menor que stopped_speed_kn.")
    database = {"current": "current.db", "archive_dir": "archive",
                "catalog": "archive-catalog.json", "analysis": "analysis.db"}
    database.update(raw.get("database") or {})
    return ZoneConfig(
        zone_id=zid,
        name=str(raw.get("name") or zid),
        description=str(raw.get("description") or ""),
        created_utc=str(raw.get("created_utc") or ""),
        active=bool(raw.get("active", True)),
        geometry_type=gtype,
        bbox=bbox,
        ring=ring,
        database=database,
        archive_policy=dict(raw.get("archive_policy") or {"period": "yearly"}),
        sources=sources,
        sampling=sampling,
        silence_alert_min=float(raw.get("silence_alert_min", 10)),
        zone_dir=zone_dir,
        raw=raw,
    )


def zones_root(data_dir):
    return Path(data_dir) / "Zones"


def ensure_example_zone(data_dir):
    """Si todavía no hay ninguna zona, copia la de ejemplo (VALENCIA)."""
    root = zones_root(data_dir)
    if root.exists() and any(root.glob("*/zone.json")):
        return False
    src = REPO_ROOT / "config-ejemplo" / "zones" / "VALENCIA" / "zone.json"
    dst = root / "VALENCIA" / "zone.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    return True


def load_zones(data_dir):
    """Lee todas las zonas de DATA_DIR/Zones/*/zone.json (activas e inactivas)."""
    zones = []
    for path in sorted(zones_root(data_dir).glob("*/zone.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ConfigError(f"{path}: el JSON no es válido ({e}).")
        zones.append(parse_zone(raw, path.parent))
    return zones
