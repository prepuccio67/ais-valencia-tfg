# -*- coding: utf-8 -*-
"""Utilidades comunes de los tests: zona de prueba y mensajes de ejemplo."""
import json
import shutil
import tempfile
from pathlib import Path

from collector.config import REPO_ROOT, Settings, load_zones

T0 = 1793200000          # una hora fija (28/10/2026) para que los tests sean repetibles


def make_data_dir():
    """Carpeta temporal con la zona VALENCIA de ejemplo."""
    d = Path(tempfile.mkdtemp(prefix="ais_test_"))
    dst = d / "Zones" / "VALENCIA"
    dst.mkdir(parents=True)
    shutil.copyfile(REPO_ROOT / "config-ejemplo" / "zones" / "VALENCIA" / "zone.json", dst / "zone.json")
    return d


def valencia(data_dir):
    return load_zones(data_dir)[0]


def settings(data_dir, token="t" * 32):
    return Settings(collector_id="TEST-01", data_dir=Path(data_dir), api_host="127.0.0.1",
                    api_port=0, api_token=token)


def iso(ts):
    from collector.storage import iso as _iso
    return _iso(ts)


def pos_frame(mmsi=224000001, ts=T0, lat=39.45, lon=-0.32, sog=0.0, nav=5, mtype="PositionReport",
              time_fmt="osf", **extra):
    """Mensaje de posición con el formato de OpenSeaFeed ('osf') o de aisstream ('ais')."""
    if time_fmt == "osf":
        t = iso(ts).replace("Z", ".040+00:00")
        meta = {"MMSI": mmsi, "latitude": lat, "longitude": lon, "time_utc": t, "ShipName": "PRUEBA"}
    else:
        t = iso(ts).replace("T", " ").replace("Z", ".794168 +0000 UTC")
        meta = {"MMSI": mmsi, "Latitude": lat, "Longitude": lon, "time_utc": t, "ShipName": "PRUEBA@@@"}
    body = {"MessageID": 1 if mtype == "PositionReport" else 18, "UserID": mmsi, "Valid": True,
            "Latitude": lat, "Longitude": lon, "Sog": sog, "Cog": 90.0, "TrueHeading": 91,
            "NavigationalStatus": nav}
    body.update(extra)
    return {"MessageType": mtype, "MetaData": meta, "Message": {mtype: body}}


def static_frame(mmsi=224000001, ts=T0, draught=11.2, dest="ESVLC", eta=(11, 2, 6, 30)):
    return {"MessageType": "ShipStaticData",
            "MetaData": {"MMSI": mmsi, "latitude": 39.45, "longitude": -0.32,
                         "time_utc": iso(ts).replace("Z", "+00:00")},
            "Message": {"ShipStaticData": {
                "MessageID": 5, "UserID": mmsi, "Valid": True, "ImoNumber": 9401283,
                "CallSign": "A8TG2@@", "Name": "RDO CONCORD@@@@", "Type": 72,
                "Dimension": {"A": 250, "B": 54, "C": 20, "D": 20},
                "Eta": {"Month": eta[0], "Day": eta[1], "Hour": eta[2], "Minute": eta[3]},
                "MaximumStaticDraught": draught, "Destination": dest}}}


def write_zone(data_dir, **changes):
    path = Path(data_dir) / "Zones" / "VALENCIA" / "zone.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw.update(changes)
    path.write_text(json.dumps(raw), encoding="utf-8")
