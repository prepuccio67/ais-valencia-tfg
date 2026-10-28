# -*- coding: utf-8 -*-
"""
Mensaje normalizado: convierte los mensajes JSON de las fuentes en un objeto
común. OpenSeaFeed y aisstream.io usan el mismo formato ("aisstream-compatible"),
con pequeñas diferencias que se resuelven aquí:
  - MetaData: aisstream usa "Latitude"/"latitude" según la versión; OpenSeaFeed
    usa "latitude" y añade "ShipType" e "IMO".
  - time_utc: aisstream "2026-08-20 15:21:32.794168 +0000 UTC";
              OpenSeaFeed "2026-10-28T18:34:37.040+00:00".
Valores AIS que significan "no disponible" se convierten en None.
"""
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

POSITION_TYPES = {
    "PositionReport",                 # clase A, mensajes 1, 2 y 3
    "StandardClassBPositionReport",   # clase B, mensaje 18
    "ExtendedClassBPositionReport",   # clase B, mensaje 19 (lleva también nombre y tipo)
    "LongRangeAisBroadcastMessage",   # mensaje 27 (largo alcance)
}
STATIC_TYPES = {"ShipStaticData", "StaticDataReport"}   # mensajes 5 y 24
SUBSCRIBED_TYPES = sorted(POSITION_TYPES | STATIC_TYPES)

CLASS_B_TYPES = {"StandardClassBPositionReport", "ExtendedClassBPositionReport", "StaticDataReport"}

_TIME_RE = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:\.\d+)?\s*(?:(Z)|([+-])(\d{2}):?(\d{2}))?")


@dataclass
class Message:
    source: str
    msg_type_name: str
    mmsi: int
    ts: int                   # hora del mensaje según la fuente (epoch UTC, segundos)
    ts_rx: int                # hora en que lo recibimos (epoch UTC, segundos)
    lat: float = None         # posición del mensaje (solo mensajes de posición)
    lon: float = None
    meta_lat: float = None    # última posición conocida que añade la fuente (sirve para enrutar)
    meta_lon: float = None
    sog: float = None
    cog: float = None
    heading: int = None
    nav_status: int = None
    msg_id: int = None        # número de mensaje AIS (1, 2, 3, 5, 18, 19, 24, 27)
    ais_class: str = None     # "A" o "B"
    # ficha (mensajes estáticos y el 19)
    imo: int = None
    name: str = None
    callsign: str = None
    ship_type: int = None
    length_m: float = None
    beam_m: float = None
    draught_m: float = None
    destination: str = None
    eta_raw: str = None
    eta_utc: int = None
    # pistas débiles de MetaData: solo rellenan huecos de la ficha
    hint_name: str = None
    hint_imo: int = None
    hint_ship_type: int = None

    @property
    def has_position(self):
        return self.lat is not None and self.lon is not None

    @property
    def has_static(self):
        return any(v is not None for v in (self.imo, self.name, self.callsign, self.ship_type,
                                           self.length_m, self.beam_m, self.draught_m,
                                           self.destination, self.eta_raw))

    @property
    def route_lat(self):
        return self.lat if self.lat is not None else self.meta_lat

    @property
    def route_lon(self):
        return self.lon if self.lon is not None else self.meta_lon


# ------------------------------------------------------------------ limpieza
def parse_time(value):
    """Texto de hora de cualquiera de las dos fuentes -> epoch UTC (int) o None."""
    if not isinstance(value, str):
        return None
    m = _TIME_RE.search(value)
    if not m:
        return None
    y, mo, d, h, mi, s = (int(x) for x in m.groups()[:6])
    try:
        t = datetime(y, mo, d, h, mi, s, tzinfo=timezone.utc)
    except ValueError:
        return None
    if m.group(8):   # desfase horario explícito distinto de Z
        offset = timedelta(hours=int(m.group(9)), minutes=int(m.group(10)))
        t = t - offset if m.group(8) == "+" else t + offset
    return int(t.timestamp())


def _num(v):
    if isinstance(v, bool) or v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _int(v):
    f = _num(v)
    return int(f) if f is not None else None


def clean_lat(v):
    f = _num(v)
    return f if f is not None and -90 <= f <= 90 and f != 91 else None


def clean_lon(v):
    f = _num(v)
    return f if f is not None and -180 <= f <= 180 and f != 181 else None


def clean_sog(v):
    f = _num(v)
    return f if f is not None and 0 <= f < 102.2 else None       # 102,3 = no disponible


def clean_cog(v):
    f = _num(v)
    return f if f is not None and 0 <= f < 360 else None         # 360 = no disponible


def clean_heading(v):
    i = _int(v)
    return i if i is not None and 0 <= i <= 359 else None        # 511 = no disponible


def clean_nav(v):
    i = _int(v)
    return i if i is not None and 0 <= i <= 15 else None


def clean_text(v):
    """Nombres AIS: quitan los '@' de relleno y los espacios sobrantes."""
    if not isinstance(v, str):
        return None
    t = " ".join(v.replace("@", " ").split())
    return t or None


def clean_imo(v):
    i = _int(v)
    return i if i is not None and 1000000 <= i <= 9999999 else None


def clean_ship_type(v):
    i = _int(v)
    return i if i is not None and 1 <= i <= 99 else None


def clean_dims(dim):
    """Dimensiones AIS A+B (eslora) y C+D (manga). 0 = desconocido."""
    if not isinstance(dim, dict):
        return None, None
    a, b, c, d = (_int(dim.get(k)) or 0 for k in ("A", "B", "C", "D"))
    length = float(a + b) if a + b > 0 else None
    beam = float(c + d) if c + d > 0 else None
    return length, beam


def clean_eta(eta, ref_ts):
    """ETA AIS (mes, día, hora, minuto, sin año) -> (texto tal cual, epoch UTC o None).
    El año se deduce: la primera fecha que no quede más de 30 días en el pasado."""
    if not isinstance(eta, dict):
        return None, None
    mo, d, h, mi = (_int(eta.get(k)) for k in ("Month", "Day", "Hour", "Minute"))
    if not mo or not d or mo > 12 or d > 31:
        return None, None
    raw = f"{mo:02d}-{d:02d} {h if h is not None else 24:02d}:{mi if mi is not None else 60:02d}"
    if h is None or mi is None or h > 23 or mi > 59:
        return raw, None
    ref = datetime.fromtimestamp(ref_ts, tz=timezone.utc)
    for year in (ref.year - 1, ref.year, ref.year + 1):
        try:
            cand = datetime(year, mo, d, h, mi, tzinfo=timezone.utc)
        except ValueError:
            continue
        if cand >= ref - timedelta(days=30):
            return raw, int(cand.timestamp())
    return raw, None


def _first(d, *keys):
    for k in keys:
        if isinstance(d, dict) and d.get(k) is not None:
            return d[k]
    return None


# ------------------------------------------------------------------ análisis
def parse_frame(obj, source, ts_rx):
    """Convierte un mensaje JSON de la fuente en Message, o None si no sirve."""
    if not isinstance(obj, dict):
        return None
    mtype = obj.get("MessageType")
    if mtype not in POSITION_TYPES and mtype not in STATIC_TYPES:
        return None
    body = (obj.get("Message") or {}).get(mtype)
    if not isinstance(body, dict):
        return None
    if body.get("Valid") is False:
        return None
    meta = obj.get("MetaData") or {}

    mmsi = _int(_first(meta, "MMSI") or body.get("UserID"))
    if mmsi is None or not 100000000 <= mmsi <= 999999999:
        return None
    ts = parse_time(_first(meta, "time_utc", "TimeUtc"))
    if ts is None:
        # Sin hora de la fuente no sabemos si es una posición actual o una repetición antigua:
        # las posiciones se descartan; los datos estáticos usan la hora de recepción.
        if mtype in POSITION_TYPES:
            return None
        ts = ts_rx
    msg_id = _int(body.get("MessageID"))

    msg = Message(source=source, msg_type_name=mtype, mmsi=mmsi, ts=ts, ts_rx=ts_rx,
                  msg_id=msg_id if msg_id is not None and 1 <= msg_id <= 27 else None,
                  ais_class="B" if mtype in CLASS_B_TYPES else "A")
    msg.meta_lat = clean_lat(_first(meta, "latitude", "Latitude"))
    msg.meta_lon = clean_lon(_first(meta, "longitude", "Longitude"))
    msg.hint_name = clean_text(_first(meta, "ShipName"))
    msg.hint_imo = clean_imo(_first(meta, "IMO"))
    msg.hint_ship_type = clean_ship_type(_first(meta, "ShipType"))

    if mtype in POSITION_TYPES:
        lat, lon = clean_lat(body.get("Latitude")), clean_lon(body.get("Longitude"))
        if lat is None or lon is None or (lat == 0 and lon == 0):
            return None   # sin posición válida no hay nada que guardar
        msg.lat, msg.lon = lat, lon
        msg.sog = clean_sog(body.get("Sog"))
        msg.cog = clean_cog(body.get("Cog"))
        msg.heading = clean_heading(body.get("TrueHeading"))
        if mtype in ("PositionReport", "LongRangeAisBroadcastMessage"):
            msg.nav_status = clean_nav(body.get("NavigationalStatus"))
        if mtype == "ExtendedClassBPositionReport":
            msg.name = clean_text(body.get("Name"))
            msg.ship_type = clean_ship_type(body.get("Type"))
            msg.length_m, msg.beam_m = clean_dims(body.get("Dimension"))
    elif mtype == "ShipStaticData":
        msg.imo = clean_imo(body.get("ImoNumber"))
        msg.name = clean_text(body.get("Name"))
        msg.callsign = clean_text(body.get("CallSign"))
        msg.ship_type = clean_ship_type(body.get("Type"))
        msg.length_m, msg.beam_m = clean_dims(body.get("Dimension"))
        draught = _num(body.get("MaximumStaticDraught"))
        msg.draught_m = draught if draught and 0 < draught < 25.5 else None
        msg.destination = clean_text(body.get("Destination"))
        msg.eta_raw, msg.eta_utc = clean_eta(body.get("Eta"), ts)
    else:  # StaticDataReport (24): dos mitades, cada una con su indicador Valid
        rep_a = body.get("ReportA") or {}
        rep_b = body.get("ReportB") or {}
        if rep_a.get("Valid"):
            msg.name = clean_text(rep_a.get("Name"))
        if rep_b.get("Valid"):
            msg.ship_type = clean_ship_type(rep_b.get("ShipType"))
            msg.callsign = clean_text(rep_b.get("CallSign"))
            msg.length_m, msg.beam_m = clean_dims(rep_b.get("Dimension"))
        if not msg.has_static:
            return None
    return msg
