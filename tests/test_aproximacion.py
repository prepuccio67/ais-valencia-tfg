# -*- coding: utf-8 -*-
"""Tests de la zona de APROXIMACIÓN (D-18): muestreo grueso, ETA completa y VALENCIA intacta."""
import json
import shutil
import sqlite3
import time
import unittest
from pathlib import Path

from aiohttp.test_utils import AioHTTPTestCase

from collector import analysis
from collector import port_calls as pc
from collector import zones_admin as za
from collector.api import create_app
from collector.config import REPO_ROOT, ConfigError, default_zone_id, load_zones
from collector.main import State
from collector.messages import parse_frame
from collector.storage import ZoneStore
from collector.zone_worker import Router, ZoneWorker
from tests.helpers import T0, make_data_dir, pos_frame, settings, static_frame

TOKEN = "a" * 32
H = {"Authorization": f"Bearer {TOKEN}"}
APROX_JSON = REPO_ROOT / "config-ejemplo" / "zones" / "APROXIMACION" / "zone.json"


def aprox_payload():
    raw = json.loads(APROX_JSON.read_text(encoding="utf-8"))
    return {k: raw[k] for k in ("zone_id", "name", "description", "geometry_type", "bbox", "sources", "sampling")}


def static_at(lat, lon, **kw):
    f = static_frame(**kw)
    f["MetaData"].update(latitude=lat, longitude=lon)
    return f


def rows(zone, sql):
    c = sqlite3.connect(Path(zone.zone_dir) / "current.db")
    try:
        return c.execute(sql).fetchall()
    finally:
        c.close()


class TestAproxConfig(unittest.TestCase):
    def setUp(self):
        self.dir = make_data_dir()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_create_full_rectangle_with_coarse_sampling(self):
        za.create_zone(self.dir, aprox_payload())               # 32 grados²: cabe en el nuevo límite (40)
        z = {z.zone_id: z for z in load_zones(self.dir)}["APROXIMACION"]
        self.assertEqual(z.bbox, {"north": 42.0, "south": 37.0, "east": 2.9, "west": -3.5})
        self.assertEqual((z.sampling["moving_interval_s"], z.sampling["stopped_interval_s"]), (1800, 3600))
        self.assertEqual(z.sampling["moving_speed_kn"], 0.5)     # histéresis igual que VALENCIA (D-08)
        self.assertFalse(pc.has_port_analysis(z))

    def test_sampling_validation(self):
        bad = [{"moving_interval_s": 5}, {"rapido": 1}, {"stopped_interval_s": True},
               {"moving_speed_kn": "0,5"}, {"moving_speed_kn": 0.1}, "1800"]
        for i, s in enumerate(bad):
            with self.assertRaises(ConfigError, msg=str(s)):
                za.create_zone(self.dir, dict(aprox_payload(), zone_id=f"MAL{i}", sampling=s))
        self.assertEqual([z.zone_id for z in load_zones(self.dir)], ["VALENCIA"])

    def test_still_rejects_huge_zone(self):
        with self.assertRaises(ConfigError):
            za.create_zone(self.dir, dict(aprox_payload(), bbox={"north": 43, "south": 36, "east": 3, "west": -4}))

    def test_sampling_survives_other_edits(self):
        za.create_zone(self.dir, aprox_payload())
        z = {z.zone_id: z for z in load_zones(self.dir)}["APROXIMACION"]
        za.update_zone(z, {"name": "otro nombre"})
        za.set_active({z.zone_id: z for z in load_zones(self.dir)}["APROXIMACION"], False)
        z2 = {z.zone_id: z for z in load_zones(self.dir)}["APROXIMACION"]
        self.assertEqual((z2.active, z2.sampling["moving_interval_s"]), (False, 1800))

    def test_default_zone_is_explicit(self):
        self.assertEqual(default_zone_id(["APROXIMACION", "VALENCIA"]), "VALENCIA")
        self.assertEqual(default_zone_id(["APROXIMACION"]), "APROXIMACION")
        self.assertIsNone(default_zone_id([]))


class TestTwoZones(unittest.TestCase):
    """Un buque que está a la vez en VALENCIA y en APROXIMACION."""

    def setUp(self):
        self.dir = make_data_dir()
        za.create_zone(self.dir, aprox_payload())
        self.zones = {z.zone_id: z for z in load_zones(self.dir)}
        self.alone = make_data_dir()                     # VALENCIA sola, como hoy, para comparar

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)
        shutil.rmtree(self.alone, ignore_errors=True)

    def run_stream(self, zones):
        workers = []
        for z in zones:
            st = ZoneStore(z, "TEST-01").open()
            st.startup(T0)
            workers.append(ZoneWorker(z, st, T0))
        router = Router(workers)
        frames = []
        # 3 h navegando a 12 kn de Cartagena a València (fuera de VALENCIA), mensaje cada 10 s
        for i in range(0, 3 * 3600, 10):
            frames.append((pos_frame(mmsi=224000001, ts=T0 + i, lat=38.0 + i / 10800, lon=-0.5, sog=12.0, nav=0),
                           "aisstream", T0 + i + 2))
        # AIS 5 cada 6 min con la ETA cambiando 3 veces lejos de València
        for k, i in enumerate(range(0, 3 * 3600, 360)):
            eta = (11, 2, 6 + (k // 10), 30)
            frames.append((static_at(38.0 + i / 10800, -0.5, ts=T0 + i + 1, eta=eta), "aisstream", T0 + i + 3))
        # luego 1 h dentro de VALENCIA: maniobra, para y atraca; cada mensaje llega dos veces (repetido)
        t1 = T0 + 3 * 3600
        for i in range(0, 3600, 10):
            sog = 8.0 if i < 1200 else (2.0 if i < 2400 else 0.0)
            f = pos_frame(mmsi=224000001, ts=t1 + i, lat=39.45, lon=-0.32, sog=sog, nav=0 if sog else 5)
            frames.append((f, "aisstream", t1 + i + 2))
            frames.append((f, "aisstream", t1 + i + 3))
        frames.append((static_frame(ts=t1 + 1800, eta=(11, 2, 9, 0), draught=11.0), "aisstream", t1 + 1801))
        frames.sort(key=lambda x: x[2])
        for f, src, rx in frames:
            router.route(parse_frame(f, src, rx))
        for w in workers:
            w.tick(t1 + 4000)
            w.close(t1 + 4000)
        return {w.zone_id: w.zone for w in workers}

    def test_valencia_identical_and_aprox_coarse_with_every_eta(self):
        both = self.run_stream([self.zones["VALENCIA"], self.zones["APROXIMACION"]])
        alone = self.run_stream(load_zones(self.alone))
        q_pos = "SELECT mmsi, ts, lat, lon, sog, nav_status, reason FROM position ORDER BY ts"
        q_voy = "SELECT mmsi, ts, draught_m, destination, eta_raw FROM voyage_data ORDER BY ts"
        q_cov = "SELECT minute, source_id, msgs, vessels FROM coverage_minute ORDER BY minute"
        # VALENCIA: exactamente lo mismo que sin la zona nueva (posiciones, ETA y cobertura)
        for q in (q_pos, q_voy, q_cov):
            self.assertEqual(rows(both["VALENCIA"], q), rows(alone["VALENCIA"], q))
        # APROXIMACION: posiciones gruesas (1 cada 30 min en marcha + eventos), sin duplicados
        pos = rows(both["APROXIMACION"], q_pos)
        far = [p for p in pos if p[1] < T0 + 3 * 3600]
        self.assertEqual(len(far), 6)                       # 3 h a 1 cada 30 min
        self.assertEqual(len(pos), len({(p[0], p[1]) for p in pos}))
        # el paso a «parado» (y a «amarrado») se guarda al momento, como evento (2 o 3), no por intervalo
        self.assertTrue(any(p[6] in (2, 3) and p[4] == 0.0 for p in pos))
        # y TODOS los cambios de ETA, incluidos los recibidos lejos de VALENCIA
        etas = [r[4] for r in rows(both["APROXIMACION"], q_voy)]
        self.assertEqual(etas, ["11-02 06:30", "11-02 07:30", "11-02 08:30", "11-02 09:00"])


class TestApiWithAprox(AioHTTPTestCase):
    async def get_application(self):
        self.dir = make_data_dir()
        za.create_zone(self.dir, aprox_payload())
        zones = load_zones(self.dir)
        self.assertEqual([z.zone_id for z in zones], ["APROXIMACION", "VALENCIA"])   # A va antes por orden
        return create_app(State(settings(self.dir, TOKEN), zones))

    async def asyncTearDown(self):
        await super().asyncTearDown()
        shutil.rmtree(self.dir, ignore_errors=True)

    async def test_default_zone_and_no_port_calls_error(self):
        data = await (await self.client.get("/api/zones", headers=H)).json()
        self.assertEqual(data["default_zone"], "VALENCIA")
        flags = {z["zone_id"]: z["port_calls"] for z in data["zones"]}
        self.assertEqual(flags, {"APROXIMACION": False, "VALENCIA": True})
        for path in ("/api/port_calls", "/api/subzones"):
            r = await self.client.get(f"{path}?zone=APROXIMACION", headers=H)
            self.assertEqual(r.status, 400)
            self.assertIn("no tiene terminales", (await r.json())["error"])
        r = await self.client.get("/api/port_calls?zone=VALENCIA", headers=H)
        self.assertEqual(r.status, 200)


class TestAnalysisCli(unittest.TestCase):
    def test_skips_zone_without_terminals_and_does_valencia(self):
        d = make_data_dir()
        try:
            za.create_zone(d, aprox_payload())
            env = d / "test.env"
            env.write_text(f"COLLECTOR_ID=TEST-01\nAPI_TOKEN={TOKEN}\nDATA_DIR={d.as_posix()}\n", encoding="utf-8")
            self.assertEqual(analysis.main(["--env", str(env)]), 0)
            self.assertTrue((d / "Zones" / "VALENCIA" / "analysis.db").exists())
            self.assertFalse((d / "Zones" / "APROXIMACION" / "analysis.db").exists())
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
