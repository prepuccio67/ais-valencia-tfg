# -*- coding: utf-8 -*-
"""Tests de la API HTTP (token, rangos, huecos de zona, cobertura)."""
import shutil
import time

from aiohttp.test_utils import AioHTTPTestCase

from collector.api import create_app
from collector.main import State
from collector.messages import parse_frame
from collector.storage import ZoneStore
from collector.zone_worker import ZoneWorker
from collector.storage import iso
from tests.helpers import make_data_dir, pos_frame, settings, valencia

TOKEN = "x" * 32
H = {"Authorization": f"Bearer {TOKEN}"}


class TestApi(AioHTTPTestCase):
    async def get_application(self):
        self.dir = make_data_dir()
        zone = valencia(self.dir)
        st = ZoneStore(zone, "TEST-01").open()
        now = int(time.time())
        self.t = now - 3600
        st.startup(self.t)
        w = ZoneWorker(zone, st, self.t)
        for i in range(5):     # un buque en movimiento, 1 posición por minuto
            ts = self.t + 60 * i
            w.handle(parse_frame(pos_frame(mmsi=224000001, ts=ts, sog=8.0, nav=0), "aisstream", ts + 1))
        w.handle(parse_frame(pos_frame(mmsi=224000002, ts=self.t + 30), "openseafeed", self.t + 31))
        # las dos fuentes caen a la vez entre t+1000 y t+1500 -> hueco de zona
        w.gaps.on_source_down("aisstream", self.t + 1000, "network_failure")
        w.gaps.on_source_down("openseafeed", self.t + 1200, "network_failure")
        w.handle(parse_frame(pos_frame(mmsi=224000003, ts=self.t + 1500), "aisstream", self.t + 1500))
        w.handle(parse_frame(pos_frame(mmsi=224000003, ts=self.t + 1500), "openseafeed", self.t + 1500))
        w.tick(self.t + 1600)
        self.worker = w
        state = State(settings(self.dir, TOKEN), [zone])
        state.workers = {"VALENCIA": w}
        return create_app(state)

    async def asyncTearDown(self):
        await super().asyncTearDown()
        self.worker.store.shutdown()
        shutil.rmtree(self.dir, ignore_errors=True)

    async def test_token_required(self):
        r = await self.client.get("/api/health")
        self.assertEqual(r.status, 401)
        r = await self.client.get("/api/health", headers={"Authorization": "Bearer malo"})
        self.assertEqual(r.status, 401)
        r = await self.client.get(f"/api/health?token={TOKEN}")
        self.assertEqual(r.status, 200)
        self.assertEqual((await r.json())["collector_id"], "TEST-01")

    async def test_zone(self):
        r = await self.client.get("/api/zone?zone=VALENCIA", headers=H)
        data = await r.json()
        self.assertEqual(data["zone_id"], "VALENCIA")
        self.assertEqual(data["stats"]["vessels_known"], 3)
        r = await self.client.get("/api/zone?zone=NOEXISTE", headers=H)
        self.assertEqual(r.status, 404)

    async def test_archive_range_and_pagination(self):
        url = f"/api/archive/range?zone=VALENCIA&from={self.t - 10}&to={self.t + 4000}"
        data = await (await self.client.get(url, headers=H)).json()
        self.assertEqual(data["count"], 7)
        data = await (await self.client.get(url + "&limit=4", headers=H)).json()
        self.assertEqual(data["count"], 4)
        rest = await (await self.client.get(url + f"&limit=4&after={data['next_after']}", headers=H)).json()
        self.assertEqual(rest["count"], 3)
        one = await (await self.client.get(url + "&mmsi=224000002", headers=H)).json()
        self.assertEqual([p["source"] for p in one["positions"]], ["openseafeed"])

    async def test_bad_params(self):
        r = await self.client.get("/api/archive/range?zone=VALENCIA&from=ayer", headers=H)
        self.assertEqual(r.status, 400)
        r = await self.client.get("/api/archive/range?zone=VALENCIA&from=2026-01-01&to=2026-06-01", headers=H)
        self.assertEqual(r.status, 400)          # > 31 días sin mmsi
        for bad in ("from=99999999999999999999", "mmsi=99999999999999999999", "limit=0", "limit=abc",
                    "after=1:2:3", "bbox=1,2,3"):
            r = await self.client.get(f"/api/archive/range?zone=VALENCIA&{bad}", headers=H)
            self.assertEqual(r.status, 400, bad)
        r = await self.client.get(f"/api/archive/range?zone=VALENCIA&from=0&to={self.t + 4000}&mmsi=224000002",
                                  headers=H)
        self.assertEqual((await r.json())["from"], "1970-01-01T00:00:00Z")   # from=0 es una fecha válida

    async def test_zone_gap_is_intersection_of_sources(self):
        data = await (await self.client.get(f"/api/gaps?zone=VALENCIA&from={self.t}", headers=H)).json()
        self.assertEqual(len(data["source_gaps"]), 2)
        filtered = await (await self.client.get(
            f"/api/gaps?zone=VALENCIA&from={self.t}&status=REPAIRED", headers=H)).json()
        self.assertEqual(filtered["source_gaps"], [])
        self.assertEqual(filtered["zone_gaps"], data["zone_gaps"])     # el filtro no altera el cálculo
        self.assertEqual(len(data["zone_gaps"]), 1)
        self.assertEqual(data["zone_gaps"][0]["minutes"], round(300 / 60, 1))   # t+1200 .. t+1500

    async def test_coverage(self):
        data = await (await self.client.get(
            f"/api/coverage?zone=VALENCIA&from={self.t - 60}&bucket=hour", headers=H)).json()
        total = sum(s["msgs"] for row in data["rows"] for s in row["sources"].values())
        self.assertEqual(total, 8)


class TestViewerApi(TestApi):
    """Endpoints del visor (Fase 4). Reutiliza los mismos datos de prueba."""

    async def test_snapshot_latest_position_per_vessel(self):
        at = self.t + 250
        data = await (await self.client.get(f"/api/vessels?zone=VALENCIA&at={at}&window=1200", headers=H)).json()
        by = {v["mmsi"]: v for v in data["vessels"]}
        self.assertEqual(set(by), {224000001, 224000002})          # el 3 aún no había aparecido
        self.assertEqual(by[224000001]["ts"], iso(self.t + 240))   # la última antes de 'at'
        self.assertEqual(by[224000001]["age_s"], 10)
        self.assertEqual(by[224000001]["name"], "PRUEBA")          # nombre de la pista de MetaData
        later = await (await self.client.get(f"/api/vessels?zone=VALENCIA&at={self.t + 1600}&window=600",
                                             headers=H)).json()
        self.assertEqual([v["mmsi"] for v in later["vessels"]], [224000003])   # ventana: solo recientes

    async def test_snapshot_bad_window(self):
        r = await self.client.get("/api/vessels?zone=VALENCIA&window=5", headers=H)
        self.assertEqual(r.status, 400)

    async def test_track_and_vessel(self):
        tr = await (await self.client.get(
            f"/api/track/224000001?zone=VALENCIA&from={self.t - 10}&to={self.t + 4000}", headers=H)).json()
        self.assertEqual(tr["count"], 5)
        self.assertEqual([p[0] for p in tr["points"]], [self.t + 60 * i for i in range(5)])
        self.assertEqual(tr["fields"][:3], ["ts", "lat", "lon"])
        info = await (await self.client.get("/api/vessel/224000001?zone=VALENCIA", headers=H)).json()
        self.assertEqual((info["mmsi"], info["positions"]), (224000001, 5))
        r = await self.client.get("/api/vessel/999999999?zone=VALENCIA", headers=H)
        self.assertEqual(r.status, 404)
        r = await self.client.get("/api/track/abc?zone=VALENCIA", headers=H)
        self.assertEqual(r.status, 400)
        r = await self.client.get(f"/api/track/224000001?zone=VALENCIA&from=0&to={self.t}", headers=H)
        self.assertEqual(r.status, 400)                              # más de 31 días

    async def test_bounds(self):
        b = await (await self.client.get("/api/bounds?zone=VALENCIA", headers=H)).json()
        self.assertEqual((b["first"], b["last"]), (self.t, self.t + 1500))

    async def test_viewer_page_needs_no_token_but_api_does(self):
        r = await self.client.get("/")
        self.assertEqual(r.status, 200)
        self.assertIn("Visor AIS", await r.text())
        r = await self.client.get("/static/app.js")
        self.assertEqual(r.status, 200)
        r = await self.client.get("/static/../.env")              # no se puede salir de la carpeta del visor
        self.assertIn(r.status, (403, 404))
        r = await self.client.get("/api/vessels")
        self.assertEqual(r.status, 401)
