# -*- coding: utf-8 -*-
"""Tests del editor de zonas (Fase 5): validación, escritura de zone.json y API."""
import asyncio
import json
import shutil
import unittest

from aiohttp.test_utils import AioHTTPTestCase

from collector import api as api_mod
from collector import zones_admin as za
from collector.api import create_app
from collector.config import ConfigError, load_zones
from collector.main import State
from tests.helpers import make_data_dir, settings, valencia

TOKEN = "z" * 32
H = {"Authorization": f"Bearer {TOKEN}"}
RECT = {"zone_id": "SAGUNTO", "name": "Puerto de Sagunto", "geometry_type": "Rectangle",
        "bbox": {"north": 39.66, "south": 39.62, "east": -0.20, "west": -0.25}}
POLY = {"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [[
    [-0.33, 39.40], [-0.28, 39.40], [-0.28, 39.46], [-0.33, 39.46], [-0.33, 39.40]]]}}


class TestZonesAdmin(unittest.TestCase):
    def setUp(self):
        self.dir = make_data_dir()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def zones(self):
        return {z.zone_id: z for z in load_zones(self.dir)}

    def test_create_rectangle(self):
        za.create_zone(self.dir, RECT)
        z = self.zones()["SAGUNTO"]
        self.assertEqual((z.geometry_type, z.bbox["north"], z.active), ("Rectangle", 39.66, True))
        self.assertEqual(z.ring[0], z.ring[-1])
        self.assertEqual(z.sampling["moving_speed_kn"], 0.5)       # valores por defecto incluidos

    def test_create_polygon_from_feature(self):
        za.create_zone(self.dir, {"zone_id": "dique", "geometry_type": "Polygon", "geometry": POLY})
        z = self.zones()["DIQUE"]                                   # el identificador pasa a mayúsculas
        self.assertEqual(z.geometry_type, "Polygon")
        self.assertEqual(z.bbox, {"north": 39.46, "south": 39.40, "east": -0.28, "west": -0.33})

    def test_rejections(self):
        bad = [
            dict(RECT, zone_id="VALENCIA"),                                         # ya existe
            dict(RECT, zone_id="mal id!"),                                          # identificador inválido
            dict(RECT, bbox={"north": 39.0, "south": 39.5, "east": 0, "west": -1}),  # al revés
            dict(RECT, bbox={"north": 45, "south": 35, "east": 5, "west": -5}),      # demasiado grande
            {"zone_id": "LAZO", "geometry_type": "Polygon", "geometry": {"type": "Polygon", "coordinates": [[
                [0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]]}},                         # se cruza consigo mismo
            {"zone_id": "MULTI", "geometry_type": "Polygon", "geometry": {"type": "MultiPolygon", "coordinates": []}},
            {"zone_id": "SIN", "geometry_type": "Rectangle"},                         # falta la geometría
            dict(RECT, zone_id="NOFUENTE", sources=[]),
        ]
        for payload in bad:
            with self.assertRaises(ConfigError, msg=payload.get("zone_id")):
                za.create_zone(self.dir, payload)
        self.assertEqual(set(self.zones()), {"VALENCIA"})           # nada se ha escrito

    def test_update_keeps_what_is_not_sent(self):
        z = valencia(self.dir)
        za.update_zone(z, {"name": "València (nuevo nombre)"})
        z2 = self.zones()["VALENCIA"]
        self.assertEqual(z2.name, "València (nuevo nombre)")
        self.assertEqual(z2.bbox, z.bbox)
        self.assertEqual(z2.created_utc, z.created_utc)
        za.update_zone(z2, {"geometry_type": "Polygon", "geometry": POLY["geometry"]})
        self.assertEqual(self.zones()["VALENCIA"].geometry_type, "Polygon")
        with self.assertRaises(ConfigError):
            za.update_zone(z2, {"zone_id": "OTRA"})                  # el id no se cambia

    def test_set_active(self):
        za.set_active(valencia(self.dir), False)
        self.assertFalse(self.zones()["VALENCIA"].active)
        raw = json.loads((self.dir / "Zones" / "VALENCIA" / "zone.json").read_text(encoding="utf-8"))
        self.assertIn("sampling", raw)                               # el resto del archivo intacto


class TestZonesApi(AioHTTPTestCase):
    async def get_application(self):
        self.dir = make_data_dir()
        api_mod.RELOAD_DELAY_S = 0.01
        self.reloads = []
        state = State(settings(self.dir, TOKEN), [valencia(self.dir)])
        state.request_reload = lambda why="": self.reloads.append(why)
        return create_app(state)

    async def asyncTearDown(self):
        await super().asyncTearDown()
        shutil.rmtree(self.dir, ignore_errors=True)

    async def test_create_requires_header_token(self):
        r = await self.client.post(f"/api/zones?token={TOKEN}", json=RECT)     # token en la URL: no vale
        self.assertEqual(r.status, 401)
        r = await self.client.post("/api/zones", json=RECT, headers=H)
        self.assertEqual(r.status, 201)
        await asyncio.sleep(0.05)
        self.assertEqual(self.reloads, ["zona SAGUNTO creada"])
        self.assertTrue((self.dir / "Zones" / "SAGUNTO" / "zone.json").exists())

    async def test_bad_payload_is_400_and_no_reload(self):
        r = await self.client.post("/api/zones", data="no es json", headers=H)
        self.assertEqual(r.status, 400)
        r = await self.client.post("/api/zones", json=dict(RECT, bbox={"north": 1}), headers=H)
        self.assertEqual(r.status, 400)
        self.assertIn("north", (await r.json())["error"])
        await asyncio.sleep(0.05)
        self.assertEqual(self.reloads, [])

    async def test_update_and_deactivate(self):
        r = await self.client.put("/api/zones/VALENCIA", json={"description": "prueba"}, headers=H)
        self.assertEqual(r.status, 200)
        r = await self.client.post("/api/zones/VALENCIA/deactivate", headers=H)
        self.assertEqual(r.status, 200)
        r = await self.client.post("/api/zones/NOEXISTE/activate", headers=H)
        self.assertEqual(r.status, 404)
        await asyncio.sleep(0.05)
        self.assertEqual(len(self.reloads), 2)
        self.assertFalse(load_zones(self.dir)[0].active)


if __name__ == "__main__":
    unittest.main()
