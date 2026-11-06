# -*- coding: utf-8 -*-
"""Tests del cálculo de escalas y tiempos de espera (Fase 7) con trayectorias inventadas."""
import json
import shutil
import sqlite3
import unittest

from collector import analysis
from collector import port_calls as pc
from collector.config import ConfigError
from collector.storage import ZoneStore
from tests.helpers import T0, make_data_dir, valencia

MIN = 60
SEA = (39.40, -0.10)          # mar abierto, dentro de la zona
ANCHOR = (39.40, -0.22)       # fondeadero
ENTRY = (39.428, -0.305)      # dentro del recinto, cerca de la bocana
MSC = (39.439, -0.325)
CSP = (39.432, -0.320)
OTHER = (39.4451, -0.3117)    # muelle sin terminal dibujada (terminal de coches, dársena este)


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = make_data_dir()
        self.zone = valencia(self.dir)
        ZoneStore(self.zone, "TEST-01").open().conn.close()
        self.db = sqlite3.connect(self.dir / "Zones" / "VALENCIA" / "current.db")

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def vessel(self, mmsi=224000001, ship_type=71, length=300, name="PRUEBA"):
        self.db.execute("INSERT INTO vessel(mmsi, name, ship_type, length_m, first_seen, last_seen) "
                        "VALUES (?,?,?,?,?,?)", (mmsi, name, ship_type, length, T0, T0))
        self.db.commit()
        return mmsi

    def leg(self, mmsi, start_min, end_min, step_min, place, sog, nav=0):
        """Posiciones cada step_min minutos entre start_min y end_min (incluidos) en un sitio."""
        rows = [(mmsi, T0 + m * MIN, T0 + m * MIN + 2, place[0], place[1], sog, nav)
                for m in range(start_min, end_min + 1, step_min)]
        self.db.executemany("INSERT INTO position(mmsi, ts, ts_rx, lat, lon, sog, cog, heading, nav_status, "
                            "msg_type, source_id, reason) VALUES (?,?,?,?,?,?,0,0,?,1,1,0)", rows)
        self.db.commit()

    def calls(self, mmsi=None):
        cfg = pc.load_config(self.zone)
        out, _ = pc.compute(self.zone, cfg, T0 + 30 * 86400)
        return [c for c in out if mmsi is None or c["mmsi"] == mmsi]

    def full_call(self, mmsi, berth=MSC):
        """Llega navegando, fondea 5 h, entra, atraca 20 h y sale."""
        self.leg(mmsi, 0, 58, 2, SEA, 12.0)
        self.leg(mmsi, 60, 360, 10, ANCHOR, 0.1, nav=1)
        self.leg(mmsi, 370, 410, 10, SEA, 8.0)
        self.leg(mmsi, 420, 425, 5, ENTRY, 4.0)
        self.leg(mmsi, 430, 1630, 10, berth, 0.0, nav=5)
        self.leg(mmsi, 1640, 1645, 5, ENTRY, 5.0)
        self.leg(mmsi, 1650, 1700, 10, SEA, 12.0)


class TestMethod(Base):
    def test_full_call_with_anchorage(self):
        m = self.vessel()
        self.full_call(m)
        [c] = self.calls(m)
        self.assertEqual((c["terminal_id"], c["wait_location"], c["quality"]), ("T-MSC", "FONDEO", "OK"))
        self.assertEqual((c["t_anchor_in"], c["t_anchor_out"]), (T0 + 60 * MIN, T0 + 370 * MIN))
        self.assertEqual((c["t_berth"], c["t_unberth"], c["t_exit"]), (T0 + 430 * MIN, T0 + 1640 * MIN, T0 + 1650 * MIN))
        self.assertAlmostEqual(c["wait_h"], 310 / 60, places=3)
        self.assertAlmostEqual(c["stay_h"], 1210 / 60, places=3)
        self.assertEqual((c["censored_start"], c["censored_end"], c["overlaps_gap"]), (0, 0, 0))

    def test_direct_berth_has_no_wait(self):
        m = self.vessel()
        self.leg(m, 0, 30, 5, SEA, 12.0)
        self.leg(m, 35, 40, 5, ENTRY, 4.0)
        self.leg(m, 45, 800, 10, CSP, 0.0)
        self.leg(m, 810, 820, 10, SEA, 10.0)
        [c] = self.calls(m)
        self.assertEqual((c["terminal_id"], c["wait_h"], c["wait_location"], c["quality"]), ("T-CSP", 0.0, None, "OK"))

    def test_first_seen_at_anchor_is_doubtful(self):
        m = self.vessel()
        self.leg(m, 0, 200, 10, ANCHOR, 0.2)                     # ya estaba fondeado al empezar los datos
        self.leg(m, 210, 230, 10, ENTRY, 4.0)
        self.leg(m, 240, 900, 10, MSC, 0.0)
        self.leg(m, 910, 920, 10, SEA, 10.0)
        [c] = self.calls(m)
        self.assertEqual((c["censored_start"], c["quality"]), (1, "DUDOSA: llegada no observada"))

    def test_shift_between_berths_is_one_call(self):
        m = self.vessel()
        self.leg(m, 0, 30, 5, SEA, 12.0)
        self.leg(m, 35, 35, 5, ENTRY, 4.0)
        self.leg(m, 40, 200, 10, MSC, 0.0)                       # 2,7 h en MSC
        self.leg(m, 205, 215, 5, ENTRY, 3.0)                     # cambio de muelle
        self.leg(m, 220, 1000, 10, CSP, 0.0)                     # 13 h en CSP
        self.leg(m, 1010, 1020, 10, SEA, 10.0)
        [c] = self.calls(m)
        self.assertEqual((c["terminal_id"], c["t_berth"], c["t_unberth"]), ("T-CSP", T0 + 40 * MIN, T0 + 1010 * MIN))

    def test_wait_then_leave_without_berth_is_excluded(self):
        m = self.vessel()
        self.leg(m, 0, 30, 5, SEA, 12.0)
        self.leg(m, 40, 300, 10, ANCHOR, 0.1)
        self.leg(m, 310, 310 + 14 * 60, 30, SEA, 11.0)           # se va (sigue en la zona más de 12 h)
        self.leg(m, 2000, 2400, 60, SEA, 11.0)                   # los datos siguen después
        [c] = self.calls(m)
        self.assertEqual((c["t_berth"], c["quality"]), (None, "EXCLUIDA: sin atraque"))

    def test_ongoing_wait_and_berth(self):
        a, b = self.vessel(1), self.vessel(2)
        self.leg(a, 0, 30, 5, SEA, 12.0)
        self.leg(a, 40, 600, 10, ANCHOR, 0.1)                    # aún esperando al final de los datos
        self.leg(b, 0, 30, 5, SEA, 12.0)
        self.leg(b, 35, 35, 5, ENTRY, 4.0)
        self.leg(b, 40, 600, 10, OTHER, 0.0)                     # aún atracado
        ca, cb = self.calls(1)[0], self.calls(2)[0]
        self.assertEqual((ca["quality"], ca["t_berth"]), ("EN CURSO", None))
        self.assertEqual((cb["quality"], cb["terminal_id"], cb["stay_h"]), ("EN CURSO", pc.OTHER_BERTH, None))

    def test_long_silence_splits_the_call(self):
        m = self.vessel()
        self.leg(m, 0, 30, 5, SEA, 12.0)
        self.leg(m, 35, 35, 5, ENTRY, 4.0)
        self.leg(m, 40, 300, 10, MSC, 0.0)
        self.leg(m, 300 + 13 * 60, 300 + 20 * 60, 10, MSC, 0.0)  # 13 h sin señal, sigue atracado
        self.leg(m, 300 + 20 * 60 + 10, 300 + 20 * 60 + 30, 10, SEA, 10.0)
        first, second = self.calls(m)
        self.assertEqual(first["quality"], "DUDOSA: salida no observada")
        self.assertEqual(second["quality"], "DUDOSA: llegada no observada")

    def test_only_cargo_100m(self):
        for mmsi, t, length in ((1, 60, 300), (2, 71, 90), (3, 80, 250)):   # pasaje, carga pequeña, petrolero
            self.vessel(mmsi, t, length)
            self.full_call(mmsi)
        self.assertEqual(self.calls(), [])

    def test_zone_gap_only_counts_if_long(self):
        a = self.vessel()
        self.full_call(a)
        self.db.execute("INSERT INTO gap(source_id, start_ts, end_ts, reason, detected_ts) VALUES "
                        "(NULL, ?, ?, 'maintenance', ?)", (T0 + 500 * MIN, T0 + 500 * MIN + 30, T0))
        self.db.commit()
        self.assertEqual(self.calls()[0]["quality"], "OK")                  # 30 s: no afecta
        self.db.execute("INSERT INTO gap(source_id, start_ts, end_ts, reason, detected_ts) VALUES "
                        "(NULL, ?, ?, 'collector_failure', ?)", (T0 + 800 * MIN, T0 + 840 * MIN, T0))
        self.db.commit()
        c = self.calls()[0]
        self.assertEqual((c["quality"], c["overlaps_gap"]), ("DUDOSA: hueco de datos de la zona", 1))


class TestConfigAndOutputs(Base):
    def test_subzones_validation(self):
        path = pc.subzones_path(self.zone)
        pc.load_config(self.zone)                                # copia el de ejemplo
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["features"] = [f for f in raw["features"] if f["properties"]["kind"] != "PORT_AREA"]
        path.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaises(ConfigError):
            pc.load_config(self.zone)

    def test_analysis_db_summary_and_csv(self):
        a, b = self.vessel(1, name="UNO"), self.vessel(2, name="DOS")
        self.full_call(a, MSC)
        self.full_call(b, CSP)
        analysis.recompute(self.zone, T0 + 3 * 86400)
        calls, meta = analysis.read_calls(self.zone, T0, T0 + 3 * 86400)
        self.assertEqual(len(calls), 2)
        cfg = pc.load_config(self.zone)
        s = analysis.summary(calls, cfg, T0, T0 + 2 * 86400, T0 + 3 * 86400)
        msc = next(t for t in s["terminals"] if t["terminal_id"] == "T-MSC")
        self.assertEqual((msc["calls"], msc["wait_median_h"], msc["stay_median_h"]), (1, 5.17, 20.17))
        self.assertEqual(s["containers"]["calls"], 2)
        self.assertEqual(max(s["queue"]["waiting"]), 2)                    # los dos fondeados a la vez
        text = analysis.to_csv(calls)
        self.assertTrue(text.startswith("﻿buque;mmsi;"))
        self.assertIn(";5,17;20,17;", text)                                  # coma decimal para Excel
        # las subzonas quedan guardadas con su fecha; si se redibujan, la versión anterior se conserva
        path = pc.subzones_path(self.zone)
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["features"][1]["properties"]["name"] = "MSC (redibujada)"
        path.write_text(json.dumps(raw), encoding="utf-8")
        analysis.ensure_fresh(self.zone, T0 + 3 * 86400 + 1)
        c = sqlite3.connect(analysis.db_path(self.zone))
        rows = c.execute("SELECT name, valid_to FROM subzone WHERE subzone_id = 'T-MSC' ORDER BY valid_from").fetchall()
        c.close()
        self.assertEqual(rows, [("MSC Terminal Valencia", T0 + 3 * 86400 + 1), ("MSC (redibujada)", None)])

    def test_percentile_like_excel(self):
        self.assertEqual(analysis.percentile([1, 2, 3, 4], 0.5), 2.5)
        self.assertAlmostEqual(analysis.percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.9), 9.1)
        self.assertIsNone(analysis.percentile([], 0.5))


if __name__ == "__main__":
    unittest.main()
