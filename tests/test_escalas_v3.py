# -*- coding: utf-8 -*-
"""Tests de escalas-v3 (D-22, método congelado) y de las reglas nuevas de eta-v1 (D-21)."""
import shutil

from aiohttp.test_utils import AioHTTPTestCase

from collector import analysis
from collector import eta_accuracy as eta
from collector import port_calls as pc
from collector.api import create_app
from collector.config import ConfigError, load_zones
from collector.main import State
from tests.helpers import T0, settings
from tests.test_escalas_v2 import BaseV2
from tests.test_port_calls import ANCHOR, ENTRY, MIN, MSC, SEA

H = 3600
DRIFT = (39.40, 0.08)        # al este del rectángulo VALENCIA, dentro del área de espera (≈ 18 NM)
FAR = (39.10, 0.20)          # fuera del área de espera (≈ 31 NM)
V3 = dict(version="escalas-v3", fill_zone="APROXIMACION", fill_box_east=0.25, wait_area_nm=25,
          wait_area_center=[39.44, -0.31], wait_area_exclude=[[39.635, -0.205, 3]], wait_start_kn=1.0,
          wait_continue_kn=3.9, join_max_h=72, min_wait_h=1, loiter_window_h=72,
          sensitivity_rules=[{"name": "1,0 kn", "start_kn": 1.0, "continue_kn": 1.0},
                             {"name": "3,9 kn", "start_kn": 3.9, "continue_kn": 3.9}])


class BaseV3(BaseV2):
    def v3(self, **more):
        self.method(**dict(V3, **more))

    def berth_from(self, mmsi, start_min):
        """Entra al recinto y atraca 20 h desde start_min, y sale."""
        self.leg(mmsi, start_min, start_min + 40, 10, SEA, 9.0)
        self.leg(mmsi, start_min + 50, start_min + 55, 5, ENTRY, 4.0)
        self.leg(mmsi, start_min + 60, start_min + 1260, 10, MSC, 0.0, nav=5)
        self.leg(mmsi, start_min + 1270, start_min + 1275, 5, ENTRY, 5.0)
        self.leg(mmsi, start_min + 1280, start_min + 1330, 10, SEA, 12.0)

    def one(self, mmsi, **rule):
        cfg = pc.load_config(self.zone)
        if rule:
            cfg = dict(cfg, method=dict(cfg["method"], **rule))
        out, _ = pc.compute(self.zone, cfg, T0 + 30 * 86400)
        return [c for c in out if c["mmsi"] == mmsi]


class TestHysteresis(BaseV3):
    def test_slow_approach_is_not_a_wait_but_counts_as_slow_loiter(self):
        m = self.vessel()
        self.leg(m, 0, 58, 2, SEA, 12.0)
        self.leg(m, 60, 180, 10, SEA, 2.5)               # 2 h a 2,5 kn sin bajar de 1 kn (frenada / merodeo lento)
        self.berth_from(m, 190)
        self.v3()
        (c,) = self.one(m)
        self.assertEqual((c["wait_h"], c["t_anchor_in"]), (0.0, None))       # histéresis: no empieza la espera
        self.assertAlmostEqual(c["slow_loiter_h"], 130 / 60, places=2)        # descriptivo, no se suma
        (c39,) = self.one(m, wait_start_kn=3.9, wait_continue_kn=3.9)        # sensibilidad 3,9 kn: sí cuenta
        self.assertAlmostEqual(c39["wait_h"], 130 / 60, places=2)

    def test_wait_continues_while_drifting_below_3_9_kn(self):
        m = self.vessel()
        self.leg(m, 0, 58, 2, SEA, 12.0)
        self.leg(m, 60, 120, 10, ANCHOR, 0.2, nav=1)     # se para en el fondeadero oficial sur
        self.leg(m, 130, 300, 10, SEA, 2.5)              # luego deriva a 2,5 kn
        self.berth_from(m, 310)
        self.v3()
        (c,) = self.one(m)
        self.assertEqual((c["t_anchor_in"], c["t_anchor_out"]), (T0 + 60 * MIN, T0 + 310 * MIN))
        self.assertAlmostEqual(c["anchor_official_h"], 70 / 60, places=2)    # solo el rato en el fondeadero oficial
        self.assertEqual(c["quality"], "OK")
        (c1,) = self.one(m, wait_start_kn=1.0, wait_continue_kn=1.0)         # sensibilidad 1,0 kn
        self.assertAlmostEqual(c1["wait_h"], 70 / 60, places=2)

    def test_wait_stays_alive_while_loitering_in_the_area(self):
        m = self.vessel()
        self.leg(m, 0, 58, 2, SEA, 12.0)
        self.leg(m, 60, 120, 10, ANCHOR, 0.2, nav=1)
        self.leg(m, 130, 970, 10, SEA, 5.0)              # 14 h merodeando a 5 kn dentro del área
        self.berth_from(m, 980)
        self.method(version="escalas-v2")
        self.assertEqual(len(self.one(m)), 2)            # v2: la espera se da por perdida y se parte
        self.v3()
        calls = self.one(m)
        self.assertEqual(len(calls), 1)                  # v3: una sola escala, con atraque
        self.assertIsNotNone(calls[0]["t_berth"])


class TestJoin(BaseV3):
    def setup_split(self, mmsi, dest=None):
        self.leg(mmsi, 0, 58, 2, SEA, 12.0)
        self.leg(mmsi, 60, 300, 10, ANCHOR, 0.2, nav=1)          # espera 4 h
        self.aleg(mmsi, 330, 1500, 60, FAR, 2.0)                 # se va a esperar fuera del área ≈ 20 h
        if dest:
            self.adb.execute("INSERT INTO voyage_data(mmsi, ts, destination, eta_raw, eta_utc, source_id) "
                             "VALUES (?,?,?,?,?,1)", (mmsi, T0 + 900 * MIN, dest, "11-05 10:00", T0 + 2000 * MIN))
            self.adb.commit()
        self.leg(mmsi, 1560, 1680, 10, ANCHOR, 0.2, nav=1)       # vuelve y espera 2 h más
        self.berth_from(mmsi, 1690)

    def test_split_wait_is_joined(self):
        m = self.vessel()
        self.setup_split(m)
        self.v3()
        (c,) = self.one(m)
        self.assertEqual((c["t_anchor_in"], c["t_anchor_out"]), (T0 + 60 * MIN, T0 + 1690 * MIN))
        self.assertAlmostEqual(c["joined_gap_h"], 21.0, places=0)
        self.assertEqual(c["quality"], "OK")             # el hueco de la unión no cuenta como «sin señal»

    def test_no_join_if_another_port_in_between(self):
        m = self.vessel()
        self.setup_split(m, dest="MAPTM")
        self.v3()
        calls = self.one(m)
        # sin unir: la primera queda «sin atraque» y la segunda, sin llegada vista (dudosa)
        self.assertEqual([c["quality"].split(":")[0] for c in calls], ["EXCLUIDA", "DUDOSA"])


class TestStatsAndConfig(BaseV3):
    def test_min_wait_anchor_and_sensitivity_in_summary(self):
        a, b = self.vessel(1), self.vessel(2)
        self.leg(a, 0, 58, 2, SEA, 12.0)
        self.leg(a, 60, 90, 10, SEA, 0.5)                # espera de 0,5 h: con el mínimo de 1 h, «sin espera»
        self.berth_from(a, 100)
        self.leg(b, 0, 58, 2, SEA, 12.0)
        self.leg(b, 60, 360, 10, ANCHOR, 0.2, nav=1)     # 5 h en el fondeadero oficial
        self.berth_from(b, 370)
        self.v3()
        now = T0 + 5 * 86400
        analysis.recompute(self.zone, now)
        calls, _ = analysis.read_calls(self.zone, T0, now)
        cfg = pc.load_config(self.zone)
        s = analysis.summary(calls, cfg, T0, now, now)["containers"]
        self.assertEqual((s["wait_calls"], s["with_wait"], s["pct_wait"], s["pct_wait_3h"]), (2, 1, 50.0, 50.0))
        self.assertEqual((s["anchor_n"], s["pct_anchor"]), (1, 50.0))
        sens = analysis.sensitivity_summary(analysis.read_sensitivity(self.zone, T0, now), cfg)
        self.assertEqual([x["rule"] for x in sens], ["1,0 kn", "3,9 kn"])
        self.assertTrue(all(x["wait_calls"] == 2 for x in sens))

    def test_config_errors(self):
        for bad in ({"wait_area_nm": None}, {"wait_area_center": [39.44]}, {"wait_start_kn": 5.0},
                    {"sensitivity_rules": [{"name": "x"}]}):
            self.v3(**bad)
            with self.assertRaises(ConfigError, msg=str(bad)):
                pc.load_config(self.zone)


class TestEtaNewRules(BaseV3):
    def eta_row(self, mmsi, ts, eta_utc):
        self.db.execute("INSERT INTO voyage_data(mmsi, ts, draught_m, destination, eta_raw, eta_utc, source_id) "
                        "VALUES (?,?,?,?,?,?,1)", (mmsi, ts, 11.0, "ESVLC", "11-02 06:30", eta_utc))
        self.db.commit()

    def rows(self):
        cfg = pc.load_config(self.zone)
        calls, (first, _) = pc.compute(self.zone, cfg, T0 + 30 * 86400)
        return eta.compute(self.zone, calls, cfg, first, eta.load_params(self.zone))

    def test_escala_anterior(self):
        m = self.vessel()
        self.leg(m, 0, 58, 2, SEA, 12.0)
        self.berth_from(m, 60)                            # primera escala: sale a los ≈ 22 h
        self.eta_row(m, T0 + 30 * MIN, T0 + 70 * MIN)     # su ETA, emitida durante esa escala
        self.leg(m, 1500, 1558, 2, SEA, 12.0)             # vuelve
        self.leg(m, 1560, 1700, 10, ANCHOR, 0.2, nav=1)
        self.berth_from(m, 1710)
        self.v3()
        second = [o for o in self.rows() if o["rule"] == eta.MAIN and o["definition"] == "ZONA_ESPERA"
                  and o["t_arrival"] == T0 + 1560 * MIN]
        self.assertTrue(second)
        self.assertEqual({o["status"] for o in second if o["horizon"] in ("ULTIMA", "0", "1")}, {"ESCALA_ANTERIOR"})

    def test_eta_de_atraque_is_counted_not_discarded(self):
        m = self.vessel()
        self.leg(m, -120, 58, 2, SEA, 12.0)
        self.leg(m, 60, 360, 10, ANCHOR, 0.2, nav=1)      # espera 5 h
        self.berth_from(m, 370)                           # atraque a los 430 min
        self.eta_row(m, T0 - 60 * MIN, T0 + 440 * MIN)    # ETA = hora del atraque, no de la llegada
        self.v3()
        rows = self.rows()
        last = next(o for o in rows if o["rule"] == eta.MAIN and o["definition"] == "ZONA_ESPERA" and o["horizon"] == "ULTIMA")
        self.assertEqual((last["status"], last["category"]), ("USABLE", eta.ETA_BERTH))
        stats, _ = eta.summary(rows, dict(eta.load_params(self.zone), min_n=1))
        tot = next(s for s in stats if s["definition"] == "ZONA_ESPERA" and s["horizon"] == "ULTIMA" and s["terminal_id"] == "TOTAL")
        self.assertEqual((tot["n"], tot["n_eta_atraque"], tot["pct_eta_atraque"]), (1, 1, 100.0))


class TestApiV3(AioHTTPTestCase):
    async def get_application(self):
        self.b = BaseV3()
        self.b.setUp()
        m = self.b.vessel()
        self.b.leg(m, 0, 58, 2, SEA, 12.0)
        self.b.leg(m, 60, 360, 10, ANCHOR, 0.2, nav=1)
        self.b.berth_from(m, 370)
        self.b.v3()
        self.zone = self.b.zone
        analysis.recompute(self.zone)
        return create_app(State(settings(self.b.dir, "v" * 32), load_zones(self.b.dir)))

    async def asyncTearDown(self):
        await super().asyncTearDown()
        self.b.adb.close()
        self.b.db.close()
        shutil.rmtree(self.b.dir, ignore_errors=True)

    async def test_port_calls_has_double_wait_sensitivity_and_apv(self):
        H_ = {"Authorization": "Bearer " + "v" * 32}
        d = await (await self.client.get(f"/api/port_calls?zone=VALENCIA&from={T0 - 86400}", headers=H_)).json()
        self.assertEqual(d["method"]["version"], "escalas-v3")
        c = d["summary"]["containers"]
        self.assertEqual((c["anchor_n"], c["pct_anchor"]), (1, 100.0))
        self.assertEqual([x["rule"] for x in d["sensitivity"]], ["1,0 kn", "3,9 kn"])
        self.assertEqual(d["apv"]["pct_fondeo"], 37.8)
        self.assertEqual(len(d["summary"]["sizes"]), 4)
        self.assertGreater(d["calls"][0]["anchor_official_h"], 4.9)
