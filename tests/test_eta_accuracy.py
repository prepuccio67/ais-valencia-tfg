# -*- coding: utf-8 -*-
"""Tests de la precisión de la ETA (7c.1, eta-v1, D-20) con trayectorias y ETA inventadas."""
import json
import math
import shutil

from aiohttp.test_utils import AioHTTPTestCase

from collector import analysis
from collector import eta_accuracy as eta
from collector import port_calls as pc
from collector.api import create_app
from collector.main import State
from tests.helpers import T0, make_data_dir, settings, valencia
from tests.test_port_calls import ANCHOR, ENTRY, MIN, MSC, SEA, Base

H = 3600


def obs(rows, d="ZONA_ESPERA", h="0"):
    return next(o for o in rows if o["definition"] == d and o["horizon"] == h)


class EtaBase(Base):
    def setUp(self):
        super().setUp()
        self.params = eta.load_params(self.zone)

    def eta(self, mmsi, ts, eta_utc, dest="ESVLC", raw=None):
        self.db.execute("INSERT INTO voyage_data(mmsi, ts, draught_m, destination, eta_raw, eta_utc, source_id) "
                        "VALUES (?,?,?,?,?,?,1)", (mmsi, ts, 11.0, dest, raw or "11-02 06:30", eta_utc))
        self.db.commit()

    def rows(self, **params):
        p = dict(self.params, **params)
        cfg = pc.load_config(self.zone)
        calls, (first, _) = pc.compute(self.zone, cfg, T0 + 30 * 86400)
        return eta.compute(self.zone, calls, cfg, first, p)

    def long_call(self, mmsi):
        """Visto desde 10 h antes de fondear: llega navegando, fondea 5 h, entra y atraca."""
        self.leg(mmsi, -600, 58, 10, SEA, 12.0)
        self.leg(mmsi, 60, 360, 10, ANCHOR, 0.1, nav=1)
        self.leg(mmsi, 370, 410, 10, SEA, 8.0)
        self.leg(mmsi, 420, 425, 5, ENTRY, 4.0)
        self.leg(mmsi, 430, 1630, 10, MSC, 0.0, nav=5)
        self.leg(mmsi, 1640, 1645, 5, ENTRY, 5.0)
        self.leg(mmsi, 1650, 1700, 10, SEA, 12.0)


class TestRules(EtaBase):
    def test_sign_and_arrival_definitions(self):
        m = self.vessel()
        self.long_call(m)
        arrival = T0 + 60 * MIN                              # entra en el fondeadero (ZONA_ESPERA)
        self.eta(m, T0 - 5 * H, arrival + 2 * H)             # declaraba 2 h más tarde de lo que llegó
        rows = self.rows(caducada_referencia="emision")      # «emision»: el atraque, 4 h tarde, no cuenta como caducada
        o = obs(rows)
        self.assertEqual((o["status"], o["error_h"]), ("USABLE", 2.0))     # + = llegó ANTES de lo declarado
        self.assertEqual(obs(rows, "RECINTO")["t_arrival"], T0 + 420 * MIN)
        self.assertEqual(obs(rows, "ATRAQUE")["t_arrival"], T0 + 430 * MIN)
        self.assertEqual(obs(rows, "ATRAQUE")["error_h"], round(2 - 370 / 60, 4))   # negativo: atracó más tarde
        # con la regla aprobada («t_ref»), llegar más de 1 h tarde deja la ETA «caducada» a 0 h vista
        self.assertEqual(obs(self.rows(caducada_referencia="t_ref"), "ATRAQUE")["status"], "ETA_CADUCADA")

    def test_horizons_coverage_and_before_capture(self):
        m = self.vessel()
        self.long_call(m)                                    # primer dato: T0 - 10 h
        self.eta(m, T0 - 10 * H, T0 + 60 * MIN)
        rows = self.rows()
        self.assertEqual(obs(rows, h="6")["status"], "USABLE")
        self.assertEqual(obs(rows, h="12")["status"], "ANTES_CAPTURA")
        self.db.execute("DELETE FROM position WHERE mmsi = ? AND ts BETWEEN ? AND ?", (m, T0 - 8 * H, T0 - 2 * H))
        self.db.commit()
        rows = self.rows()
        self.assertEqual(obs(rows, h="2")["status"], "USABLE")             # visto en las 2 h anteriores
        self.assertEqual(obs(rows, h="6")["status"], "SIN_COBERTURA")

    def test_destination_rules(self):
        p = self.params
        cases = {"ESVLC": "VALENCIA", "ESBCN>ESVLC": "VALENCIA", "ESVLS": "VALENCIA", "valencia": "VALENCIA",
                 "SGSGP>>ESVLC": "VALENCIA", "ESVLC>ESBCN": "DUDOSO", "MAPTM": "OTRO", "ESVLC-MACAS": "DUDOSO",
                 "": "DUDOSO", None: "DUDOSO"}
        for dest, want in cases.items():
            self.assertEqual(eta.destination_class(dest, p), want, dest)

    def test_last_eta_skips_invalid_and_reports_lead_time(self):
        m = self.vessel()
        self.long_call(m)
        arrival = T0 + 60 * MIN
        self.eta(m, T0 - 8 * H, arrival + 30 * MIN)          # válida, emitida 9 h antes de llegar
        self.eta(m, T0 - 1 * H, arrival + 1 * H, dest="ESVLC>MAPTM")   # la más reciente: destino siguiente
        rows = self.rows()
        last = obs(rows, h=eta.LAST)
        self.assertEqual((last["status"], last["error_h"], last["lead_h"]), ("USABLE", 0.5, 9.0))
        self.assertEqual(obs(rows, h="0")["status"], "DESTINO_DUDOSO")     # el horizonte 0 no busca atrás

    def test_stale_eta_reference(self):
        m = self.vessel()
        self.long_call(m)
        arrival = T0 + 60 * MIN
        self.eta(m, T0 - 8 * H, arrival - 3 * H)             # válida al emitirla; el buque llega 3 h tarde
        o = obs(self.rows(caducada_referencia="emision"))
        self.assertEqual((o["status"], o["error_h"]), ("USABLE", -3.0))
        self.assertEqual(obs(self.rows(caducada_referencia="t_ref"))["status"], "ETA_CADUCADA")
        self.eta(m, T0 - 7 * H, T0 - 9 * H)                  # ya había pasado al emitirla: caducada siempre
        self.assertEqual(obs(self.rows())["status"], "ETA_CADUCADA")

    def test_impossible_missing_and_unseen_arrival(self):
        m = self.vessel()
        self.long_call(m)
        self.eta(m, T0 - 8 * H, T0 + 40 * 86400)
        self.assertEqual(obs(self.rows())["status"], "ETA_IMPOSIBLE")
        self.eta(m, T0 - 7 * H, None, raw="11-02 24:60")
        self.assertEqual(obs(self.rows())["status"], "SIN_ETA")
        n = self.vessel(2)
        self.leg(n, 0, 300, 10, ANCHOR, 0.1, nav=1)          # aparece ya fondeado: llegada no vista
        self.leg(n, 310, 330, 10, SEA, 8.0)
        self.leg(n, 340, 345, 5, ENTRY, 4.0)
        self.leg(n, 350, 900, 10, MSC, 0.0, nav=5)
        rows = [o for o in self.rows() if o["mmsi"] == n]
        self.assertEqual(obs(rows)["status"], "LLEGADA_NO_VISTA")
        self.assertEqual(obs(rows, "ATRAQUE")["status"], "SIN_ETA")          # la entrada sí se vio


class TestIndicators(EtaBase):
    def test_rmse_mae_bias_and_bands(self):
        p = dict(self.params, min_n=1)
        s = eta.indicators([1.0, -3.0], p)
        self.assertEqual((s["sesgo_h"], s["mae_h"], s["rmse_h"]), (-1.0, 2.0, round(math.sqrt(5), 2)))
        s = eta.indicators([0.25, -0.5, 0.75, 1.5, -7.0], p)
        self.assertEqual((s["pct_0_5h"], s["pct_1h"], s["pct_2h"], s["pct_6h"]), (40.0, 60.0, 80.0, 80.0))
        self.assertTrue(eta.indicators([1.0] * 4, self.params)["pocos_datos"])          # min_n = 5
        s = eta.indicators([float(i) for i in range(12)], p)
        self.assertEqual(len(s["ic90_mediana_h"]), 2)                                   # bootstrap con n >= 10
        self.assertEqual(s["ic90_mediana_h"], eta.indicators([float(i) for i in range(12)], p)["ic90_mediana_h"])

    def test_summary_variants(self):
        for mmsi, err in ((1, 1.0), (2, -2.0)):
            self.vessel(mmsi)
            self.long_call(mmsi)
            self.eta(mmsi, T0 - 8 * H, T0 + 60 * MIN + int(err * H))
        stats, counts = eta.summary(self.rows(caducada_referencia="emision"), dict(self.params, min_n=1))
        tot = next(s for s in stats if s["definition"] == "ZONA_ESPERA" and s["horizon"] == "0"
                   and s["terminal_id"] == "TOTAL")
        self.assertEqual((tot["n"], tot["mae_h"], tot["pct_1h"]), (2, 1.5, 50.0))
        self.assertEqual(counts["ZONA_ESPERA|0"], {"USABLE": 2})


class TestStorageAndApi(AioHTTPTestCase):
    async def get_application(self):
        self.dir = make_data_dir()
        self.zone = valencia(self.dir)
        b = EtaBase()
        b.dir, b.zone = self.dir, self.zone
        from collector.storage import ZoneStore
        import sqlite3
        ZoneStore(self.zone, "TEST-01").open().conn.close()
        b.db = sqlite3.connect(self.dir / "Zones" / "VALENCIA" / "current.db")
        b.vessel()
        b.long_call(224000001)
        b.eta(224000001, T0 - 8 * H, T0 + 90 * MIN)
        b.db.close()
        self.now = T0 + 3 * 86400
        analysis.recompute(self.zone, self.now)
        return create_app(State(settings(self.dir, "e" * 32), [self.zone]))

    async def asyncTearDown(self):
        await super().asyncTearDown()
        shutil.rmtree(self.dir, ignore_errors=True)

    async def test_eta_obs_table_json_and_csv(self):
        rows = eta.read(analysis.db_path(self.zone))
        self.assertEqual(obs(rows)["error_h"], 0.5)
        H_ = {"Authorization": "Bearer " + "e" * 32}
        analysis.recompute(self.zone)                        # que la API no tenga que recalcular por la hora
        data = await (await self.client.get("/api/eta_accuracy?zone=VALENCIA", headers=H_)).json()
        self.assertEqual(data["params"]["bandas_h"], [0.5, 1, 2, 6])
        self.assertIn("PROVISIONALES", data["aviso"])
        tot = next(s for s in data["stats"] if s["definition"] == "ZONA_ESPERA" and s["horizon"] == "0"
                   and s["terminal_id"] == "TOTAL")
        self.assertEqual((tot["n"], tot["pocos_datos"], tot["mediana_h"]), (1, True, 0.5))
        r = await self.client.get("/api/eta_accuracy?zone=VALENCIA&format=csv", headers=H_)
        text = await r.text()
        self.assertTrue(text.startswith("﻿buque;mmsi;"))
        self.assertIn(";0,50;", text)
        r = await self.client.get("/api/eta_accuracy?zone=VALENCIA&format=csv&tabla=indicadores", headers=H_)
        self.assertIn("rmse_h", (await r.text()).splitlines()[0])
        bad = await self.client.get("/api/eta_accuracy?zone=VALENCIA&variante=otra", headers=H_)
        self.assertEqual(bad.status, 400)

    async def test_params_change_triggers_recompute(self):
        path = eta.params_path(self.zone)
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["eta"]["bandas_h"]["valor"] = [0.5, 1]
        path.write_text(json.dumps(raw), encoding="utf-8")
        before = analysis._old_subzones(analysis.db_path(self.zone))[1]["eta_fingerprint"]
        analysis.ensure_fresh(self.zone, self.now + 1)
        after = analysis._old_subzones(analysis.db_path(self.zone))[1]["eta_fingerprint"]
        self.assertNotEqual(before, after)
