# -*- coding: utf-8 -*-
"""Tests del almacenamiento, los huecos y el trabajador de zona."""
import shutil
import sqlite3
import unittest

from collector.config import ConfigError, parse_zone
from collector.messages import parse_frame
from collector.storage import ZoneStore
from collector.zone_worker import ZoneWorker
from tests.helpers import T0, make_data_dir, pos_frame, static_frame, valencia, write_zone


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = make_data_dir()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def store(self, collector="TEST-01"):
        return ZoneStore(valencia(self.dir), collector).open()

    def q(self, sql):
        c = sqlite3.connect(self.dir / "Zones" / "VALENCIA" / "current.db")
        try:
            return c.execute(sql).fetchall()
        finally:
            c.close()


class TestWorker(Base):
    def test_full_flow_and_dedup_between_sources(self):
        st = self.store()
        st.startup(T0)
        w = ZoneWorker(st.zone, st, T0)
        w.handle(parse_frame(pos_frame(ts=T0), "openseafeed", T0 + 2))
        w.handle(parse_frame(pos_frame(ts=T0, time_fmt="ais"), "aisstream", T0 + 3))   # mismo dato
        w.handle(parse_frame(pos_frame(ts=T0 + 30, sog=4.0), "aisstream", T0 + 31))    # arranca
        w.handle(parse_frame(static_frame(ts=T0 + 40), "openseafeed", T0 + 41))
        w.handle(parse_frame(static_frame(ts=T0 + 50), "openseafeed", T0 + 51))        # sin cambios
        w.handle(parse_frame(static_frame(ts=T0 + 60, draught=12.0), "aisstream", T0 + 61))
        w.tick(T0 + 200)
        self.assertEqual(self.q("SELECT ts, source_id, reason FROM position ORDER BY ts"),
                         [(T0, 1, 0), (T0 + 30, 2, 3)])
        self.assertEqual(self.q("SELECT name, imo, length_m, first_seen, last_seen FROM vessel"),
                         [("RDO CONCORD", 9401283, 304.0, T0, T0 + 60)])
        self.assertEqual(self.q("SELECT draught_m FROM voyage_data ORDER BY ts"), [(11.2,), (12.0,)])
        cov = self.q("SELECT source_id, SUM(msgs) FROM coverage_minute GROUP BY 1")
        self.assertEqual(dict(cov), {1: 3, 2: 3})

    def test_message_outside_zone_is_ignored(self):
        st = self.store()
        st.startup(T0)
        w = ZoneWorker(st.zone, st, T0)
        self.assertFalse(w.wants(parse_frame(pos_frame(lat=40.5), "aisstream", T0)))

    def test_stale_replay_does_not_count_as_coverage(self):
        st = self.store()
        st.startup(T0)
        w = ZoneWorker(st.zone, st, T0)
        w.handle(parse_frame(pos_frame(ts=T0 - 3600), "openseafeed", T0))
        w.tick(T0 + 120)
        self.assertEqual(self.q("SELECT COUNT(*) FROM coverage_minute"), [(0,)])
        self.assertEqual(self.q("SELECT COUNT(*) FROM position"), [(0,)])


class TestGaps(Base):
    def test_disconnect_then_data_closes_gap(self):
        st = self.store()
        st.startup(T0)
        w = ZoneWorker(st.zone, st, T0)
        w.handle(parse_frame(pos_frame(ts=T0 + 10), "aisstream", T0 + 10))
        w.gaps.on_source_down("aisstream", T0 + 100, "network_failure", "prueba")
        w.gaps.on_source_down("aisstream", T0 + 105, "network_failure", "otra vez")   # no duplica
        w.handle(parse_frame(pos_frame(ts=T0 + 400), "aisstream", T0 + 401))
        w.tick(T0 + 405)
        self.assertEqual(self.q("SELECT source_id, start_ts, end_ts, reason FROM gap"),
                         [(2, T0 + 100, T0 + 401, "network_failure")])

    def test_silence(self):
        st = self.store()
        st.startup(T0)
        w = ZoneWorker(st.zone, st, T0)
        w.gaps.on_source_up("openseafeed", T0)
        w.tick(T0 + 599)
        self.assertEqual(self.q("SELECT COUNT(*) FROM gap"), [(0,)])
        w.tick(T0 + 601)
        self.assertEqual(self.q("SELECT source_id, start_ts, reason FROM gap"), [(1, T0, "source_silence")])

    def test_crash_and_clean_restart(self):
        st = self.store()
        st.startup(T0)
        st.flush(T0 + 60)                       # último latido
        st.open_gap(1, T0 + 30, "network_failure")
        st.conn.close()                         # "se va la luz": sin cierre ordenado
        st2 = self.store()
        st2.startup(T0 + 3600)
        rows = self.q("SELECT source_id, start_ts, end_ts, reason FROM gap ORDER BY gap_id")
        self.assertEqual(rows, [(1, T0 + 30, T0 + 60, "network_failure"),
                                (None, T0 + 60, T0 + 3600, "collector_failure")])
        st2.shutdown()
        st3 = self.store()
        hb = int(self.q("SELECT value FROM meta WHERE key='heartbeat_ts'")[0][0])
        st3.startup(hb + 1000)                  # tras una parada ordenada -> mantenimiento
        self.assertEqual(self.q("SELECT reason FROM gap ORDER BY gap_id DESC LIMIT 1"), [("maintenance",)])
        st3.shutdown()

    def test_gap_written_while_open_then_closed(self):
        st = self.store()
        st.startup(T0)
        w = ZoneWorker(st.zone, st, T0)
        w.gaps.on_source_down("openseafeed", T0 + 50, "network_failure")
        w.tick(T0 + 55)
        self.assertEqual(self.q("SELECT start_ts, end_ts FROM gap"), [(T0 + 50, None)])
        w.handle(parse_frame(pos_frame(ts=T0 + 90), "openseafeed", T0 + 91))
        w.tick(T0 + 95)
        self.assertEqual(self.q("SELECT start_ts, end_ts FROM gap"), [(T0 + 50, T0 + 91)])

    def test_short_crash_is_recorded(self):
        st = self.store()
        st.startup(T0)
        st.flush(T0 + 60)
        st.conn.close()
        st2 = self.store()
        st2.startup(T0 + 160)                   # caída de solo 100 s
        self.assertEqual(self.q("SELECT start_ts, end_ts, reason FROM gap"),
                         [(T0 + 60, T0 + 160, "collector_failure")])
        st2.shutdown()

    def test_crash_then_disable_does_not_overlap(self):
        st = self.store()
        st.startup(T0)
        st.flush(T0 + 60)
        st.conn.close()
        write_zone(self.dir, active=False)
        st2 = self.store()
        st2.startup(T0 + 3600)
        self.assertEqual(self.q("SELECT start_ts, end_ts, reason FROM gap ORDER BY gap_id"),
                         [(T0 + 60, T0 + 3600, "collector_failure"), (T0 + 3600, None, "zone_disabled")])
        st2.shutdown()

    def test_disabled_zone(self):
        write_zone(self.dir, active=False)
        st = self.store()
        st.startup(T0)
        st.shutdown()
        self.assertEqual(self.q("SELECT reason, end_ts FROM gap"), [("zone_disabled", None)])
        write_zone(self.dir, active=True)
        st = self.store()
        st.startup(T0 + 5000)
        self.assertEqual(self.q("SELECT reason, end_ts FROM gap"), [("zone_disabled", T0 + 5000)])
        st.shutdown()


class TestVoyageAndStatic(Base):
    def test_voyage_stored_as_received(self):
        st = self.store()
        st.startup(T0)
        w = ZoneWorker(st.zone, st, T0)
        w.handle(parse_frame(static_frame(ts=T0), "openseafeed", T0 + 1))
        w.handle(parse_frame(static_frame(ts=T0 + 60, dest="ESBCN", eta=(0, 0, 24, 60)), "openseafeed", T0 + 61))
        w.handle(parse_frame(static_frame(ts=T0 + 30, draught=9.0), "aisstream", T0 + 62))  # retrasado
        w.tick(T0 + 120)
        rows = self.q("SELECT ts, draught_m, destination, eta_raw, eta_utc IS NOT NULL FROM voyage_data ORDER BY ts")
        self.assertEqual(rows, [(T0, 11.2, "ESVLC", "11-02 06:30", 1),
                                (T0 + 60, 11.2, "ESBCN", None, 0)])      # ETA no disponible, no heredada

    def test_old_static_does_not_overwrite_newer(self):
        st = self.store()
        st.startup(T0)
        w = ZoneWorker(st.zone, st, T0)
        new = static_frame(ts=T0 + 100)
        new["Message"]["ShipStaticData"]["Name"] = "NOMBRE NUEVO"
        w.handle(parse_frame(new, "openseafeed", T0 + 101))
        w.tick(T0 + 105)
        w.handle(parse_frame(static_frame(ts=T0 + 50), "aisstream", T0 + 106))   # mensaje retrasado
        w.tick(T0 + 110)
        self.assertEqual(self.q("SELECT name, last_static FROM vessel"), [("NOMBRE NUEVO", T0 + 100)])


class TestFlushFailures(Base):
    def test_locked_database_retries_without_loss(self):
        st = self.store()
        st.startup(T0)
        w = ZoneWorker(st.zone, st, T0)
        w.handle(parse_frame(pos_frame(ts=T0 + 1), "aisstream", T0 + 2))
        blocker = sqlite3.connect(self.dir / "Zones" / "VALENCIA" / "current.db", timeout=0)
        blocker.execute("BEGIN IMMEDIATE")            # otro proceso bloquea la escritura
        st.conn.execute("PRAGMA busy_timeout=50")
        with self.assertRaises(sqlite3.OperationalError):
            st.flush(T0 + 5)
        self.assertEqual(st.flush_failures, 1)
        blocker.rollback()
        blocker.close()
        st.flush(T0 + 10)
        self.assertEqual(self.q("SELECT COUNT(*) FROM position"), [(1,)])
        self.assertEqual(st.flush_failures, 0)

    def test_poison_row_only_loses_itself(self):
        st = self.store()
        st.startup(T0)
        st._positions.append((224000009, T0, T0, 39.4, -0.3, 0, 0, 0, 0, 10**30, 2, 0))   # msg_type imposible
        st._positions.append((224000008, T0, T0, 39.4, -0.3, 0, 0, 0, 0, 1, 2, 0))
        st.flush(T0 + 5)
        self.assertEqual(self.q("SELECT mmsi FROM position"), [(224000008,)])
        self.assertEqual(self.q("SELECT event FROM collector_event WHERE event='bad_rows'"), [("bad_rows",)])


class TestIdentity(Base):
    def test_other_collector_cannot_write(self):
        self.store().shutdown()
        with self.assertRaises(RuntimeError):
            self.store("OTRO-02")

    def test_geometry_change_is_logged(self):
        st = self.store()
        st.startup(T0)
        st.shutdown()
        write_zone(self.dir, bbox={"north": 39.7, "south": 39.25, "east": 0.0, "west": -0.36},
                   geometry=None)
        st = self.store()
        st.startup(T0 + 100)
        st.shutdown()
        self.assertEqual(self.q("SELECT COUNT(*) FROM collector_event WHERE event='zone_config_changed'"), [(1,)])


class TestZoneConfig(unittest.TestCase):
    def test_reversed_rectangle_rejected(self):
        from pathlib import Path
        raw = {"zone_id": "X", "geometry_type": "Rectangle",
               "bbox": {"north": 39.0, "south": 39.5, "east": 0.0, "west": -0.3}}
        with self.assertRaises(ConfigError):
            parse_zone(raw, Path("X"))

    def test_polygon_bbox_is_computed(self):
        from pathlib import Path
        raw = {"zone_id": "P", "geometry_type": "Polygon",
               "geometry": {"type": "Polygon", "coordinates": [[[-0.4, 39.3], [0.0, 39.3], [-0.2, 39.6]]]}}
        z = parse_zone(raw, Path("P"))
        self.assertEqual(z.bbox, {"north": 39.6, "south": 39.3, "east": 0.0, "west": -0.4})
        self.assertEqual(z.ring[0], z.ring[-1])          # se cierra solo


if __name__ == "__main__":
    unittest.main()
