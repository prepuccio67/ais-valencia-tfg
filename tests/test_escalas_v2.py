# -*- coding: utf-8 -*-
"""Tests de escalas-v2 (D-19): completar la trayectoria con la zona de aproximación."""
import json
import sqlite3

from collector import analysis
from collector import port_calls as pc
from collector import zones_admin as za
from collector.config import ConfigError, load_zones
from collector.storage import ZoneStore, iso
from tests.helpers import T0
from tests.test_aproximacion import aprox_payload
from tests.test_port_calls import ANCHOR, ENTRY, MIN, MSC, SEA, Base

DRIFT = (39.40, 0.08)         # a la deriva al este del borde de VALENCIA, dentro del área ampliada
FAR_EAST = (39.40, 0.40)      # fuera del área ampliada (más allá de 0,25 E)
CASTELLON = (39.97, 0.02)     # parado frente a Castellón: otra latitud, no es espera en València


def without_version(calls):
    return [{k: v for k, v in c.items() if k != "method_version"} for c in calls]


class BaseV2(Base):
    def setUp(self):
        super().setUp()
        za.create_zone(self.dir, aprox_payload())
        self.aprox = {z.zone_id: z for z in load_zones(self.dir)}["APROXIMACION"]
        ZoneStore(self.aprox, "TEST-01").open().conn.close()
        self.adb = sqlite3.connect(self.dir / "Zones" / "APROXIMACION" / "current.db")
        self.addCleanup(self.adb.close)

    def method(self, **changes):
        path = pc.subzones_path(self.zone)
        if not path.exists():
            pc.load_config(self.zone)                       # copia el de ejemplo
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["method"].update(changes)
        path.write_text(json.dumps(raw), encoding="utf-8")

    def v2(self, **more):
        self.method(version="escalas-v2", fill_zone="APROXIMACION", fill_box_east=0.25, **more)

    def aleg(self, mmsi, start_min, end_min, step_min, place, sog):
        """Como leg(), pero en la base de la zona de aproximación."""
        rows = [(mmsi, T0 + m * MIN, T0 + m * MIN + 2, place[0], place[1], sog)
                for m in range(start_min, end_min + 1, step_min)]
        self.adb.executemany("INSERT INTO position(mmsi, ts, ts_rx, lat, lon, sog, cog, heading, nav_status, "
                             "msg_type, source_id, reason) VALUES (?,?,?,?,?,?,0,0,0,1,1,0)", rows)
        self.adb.commit()

    def drifter(self, mmsi, where=DRIFT):
        """Llega, espera 6 h a la deriva FUERA de VALENCIA (solo lo ve la aproximación), entra y atraca."""
        self.leg(mmsi, 0, 28, 2, SEA, 12.0)                 # visto llegando en VALENCIA
        self.aleg(mmsi, 30, 30, 1, where, 0.4)              # se para (evento guardado al momento)
        self.aleg(mmsi, 90, 390, 60, where, 0.3)            # parado: 1 posición cada 60 min
        self.aleg(mmsi, 395, 395, 1, where, 9.0)            # arranca hacia el puerto
        self.leg(mmsi, 400, 440, 10, SEA, 10.0)
        self.leg(mmsi, 450, 455, 5, ENTRY, 4.0)
        self.leg(mmsi, 460, 1660, 10, MSC, 0.0, nav=5)
        self.leg(mmsi, 1670, 1675, 5, ENTRY, 5.0)
        self.leg(mmsi, 1680, 1730, 10, SEA, 12.0)


class TestFill(BaseV2):
    def test_without_fill_zone_is_identical_to_v1(self):
        a, b = self.vessel(1), self.vessel(2)
        self.full_call(a)
        self.drifter(b)
        v1 = self.calls()
        self.method(version="escalas-v2")                   # sin fill_zone: nada cambia salvo la etiqueta
        self.assertEqual(without_version(v1), without_version(self.calls()))
        self.assertEqual({c["fill_points"] for c in v1}, {0})

    def test_drift_east_of_the_box_is_seen_with_v2(self):
        m = self.vessel()
        self.drifter(m)
        (c1,) = self.calls(m)       # v1 no ve la espera: sale como atraque directo y, además, OK (el sesgo)
        self.assertEqual((c1["wait_h"], c1["quality"]), (0.0, "OK"))
        self.v2()
        (c2,) = self.calls(m)
        self.assertEqual((round(c2["wait_h"], 2), c2["wait_location"], c2["quality"]), (6.08, "DERIVA", "OK"))
        self.assertEqual((c2["t_anchor_in"], c2["t_anchor_out"]), (T0 + 30 * MIN, T0 + 395 * MIN))
        self.assertEqual((c2["fill_points"], c2["method_version"]), (8, "escalas-v2"))
        self.assertEqual(c2["t_berth"], c1["t_berth"])      # el atraque no cambia

    def test_normal_call_does_not_change_with_v2(self):
        m = self.vessel()
        self.full_call(m)
        self.aleg(m, 0, 1700, 30, ANCHOR, 5.0)              # la aproximación también lo ve DENTRO de VALENCIA
        (c1,) = self.calls(m)
        self.v2()
        (c2,) = self.calls(m)
        self.assertEqual(c2["fill_points"], 0)              # dentro del rectángulo manda VALENCIA
        self.assertEqual(without_version([c1]), without_version([c2]))

    def test_stopped_elsewhere_does_not_count(self):
        for mmsi, place in ((1, CASTELLON), (2, FAR_EAST)):
            self.vessel(mmsi)
            self.drifter(mmsi, where=place)
        self.v2()
        for c in self.calls():
            self.assertEqual((c["wait_h"], c["fill_points"]), (0.0, 0))

    def test_config_errors(self):
        for bad in ({"fill_zone": "APROXIMACION"},                           # falta fill_box_east
                    {"fill_zone": "APROXIMACION", "fill_box_east": -0.1},    # al oeste del borde
                    {"fill_zone": "VALENCIA", "fill_box_east": 0.25},        # la propia zona
                    {"wait_stats_from": "ayer"}):
            self.method(fill_zone=None, fill_box_east=None, wait_stats_from=None)
            self.method(**bad)
            with self.assertRaises(ConfigError, msg=str(bad)):
                pc.load_config(self.zone)
        self.method(fill_zone="NOEXISTE", fill_box_east=0.25, wait_stats_from=None)
        self.full_call(self.vessel())
        with self.assertRaises(ConfigError):
            self.calls()


class TestWaitPeriod(BaseV2):
    def test_wait_stats_only_from_cutoff_and_csv_column(self):
        old, new = self.vessel(1, name="ANTERIOR"), self.vessel(2, name="POSTERIOR")
        self.full_call(old)                                 # espera 5 h, fondeado dentro de VALENCIA
        self.drifter(new)                                   # espera 6,08 h a la deriva fuera
        for db in (self.db, self.adb):                      # POSTERIOR ocurre dos días más tarde
            db.execute("UPDATE position SET ts = ts + 172800, ts_rx = ts_rx + 172800 WHERE mmsi = 2")
            db.commit()
        cut = T0 + 86400                                    # el corte queda entre las dos escalas
        self.v2(wait_stats_from=iso(cut))
        now = T0 + 5 * 86400
        analysis.recompute(self.zone, now)
        calls, _ = analysis.read_calls(self.zone, T0, now)
        self.assertEqual([(c["name"], c["quality"], c["fill_points"]) for c in calls],
                         [("ANTERIOR", "OK", 0), ("POSTERIOR", "OK", 8)])
        s = analysis.summary(calls, pc.load_config(self.zone), T0, now, now)
        c = s["containers"]
        self.assertEqual(s["wait_stats_from"], iso(cut))
        self.assertEqual((c["calls"], c["wait_calls"], c["with_wait"]), (2, 1, 1))     # 2 escalas, 1 para esperas
        self.assertEqual((c["wait_median_h"], c["wait_mean_waiting_h"]), (6.08, 6.08))
        self.assertIsNotNone(c["stay_median_h"])                                       # la estancia usa las dos
        text = analysis.to_csv(calls)
        self.assertIn(";puntos_aprox;metodo", text.splitlines()[0])
        self.assertIn(";8;escalas-v2", text)
