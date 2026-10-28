# -*- coding: utf-8 -*-
"""Tests de robustez: fallos de disco o de base de datos en mitad de la captura."""
import shutil
import sqlite3
import unittest
from unittest import mock

from collector.messages import parse_frame
from collector.storage import ZoneStore
from collector.zone_worker import ZoneWorker
from tests.helpers import T0, make_data_dir, pos_frame, static_frame, valencia


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = make_data_dir()
        self.st = ZoneStore(valencia(self.dir), "TEST-01").open()
        self.st.startup(T0)
        self.w = ZoneWorker(self.st.zone, self.st, T0)

    def tearDown(self):
        try:
            self.st.conn.close()
        except Exception:
            pass
        shutil.rmtree(self.dir, ignore_errors=True)

    def q(self, sql):
        c = sqlite3.connect(self.dir / "Zones" / "VALENCIA" / "current.db")
        try:
            return c.execute(sql).fetchall()
        finally:
            c.close()


class TestGapsUnderDbFailure(Base):
    def test_new_outage_not_lost_when_db_fails(self):
        g = self.w.gaps
        g.on_source_down("aisstream", T0 + 10, "network_failure")
        self.w.tick(T0 + 12)                                     # hueco 1 escrito (abierto)
        self.w.handle(parse_frame(pos_frame(ts=T0 + 20), "aisstream", T0 + 20))   # se cierra en memoria
        with mock.patch.object(self.st, "close_gap", side_effect=sqlite3.OperationalError("locked")), \
             mock.patch.object(self.st, "open_gap", side_effect=sqlite3.OperationalError("locked")):
            g.on_source_down("aisstream", T0 + 30, "network_failure")          # vuelve a caer
            self.w.gaps.sync()                                                 # la base falla
        self.w.tick(T0 + 40)                                     # la base se recupera
        self.assertEqual(self.q("SELECT start_ts, end_ts FROM gap ORDER BY start_ts"),
                         [(T0 + 10, T0 + 20), (T0 + 30, None)])


class TestFlushUnderDbFailure(Base):
    def test_lock_during_row_by_row_keeps_batch(self):
        self.st._positions.append((224000009, T0, T0, 39.4, -0.3, 0, 0, 0, 0, 10**30, 2, 0))   # envenenada
        self.st._positions.append((224000008, T0, T0, 39.4, -0.3, 0, 0, 0, 0, 1, 2, 0))
        real = self.st._write_row_by_row
        calls = {"n": 0}

        def flaky(batch, now):
            calls["n"] += 1
            if calls["n"] == 1:
                raise sqlite3.OperationalError("database is locked")
            return real(batch, now)

        with mock.patch.object(self.st, "_write_row_by_row", side_effect=flaky):
            with self.assertRaises(sqlite3.OperationalError):
                self.st.flush(T0 + 5)
            self.assertEqual(self.st.flush_failures, 1)
            self.st.flush(T0 + 10)                          # reintento: se guarda la buena
        self.assertEqual(self.q("SELECT mmsi FROM position"), [(224000008,)])

    def test_corrupt_database_error_is_retried_not_discarded(self):
        self.w.handle(parse_frame(pos_frame(ts=T0 + 1), "aisstream", T0 + 2))
        orig = self.st.conn
        bad = mock.MagicMock(wraps=orig)
        bad.executemany.side_effect = sqlite3.DatabaseError("database disk image is malformed")
        bad.__enter__.return_value = bad
        bad.__exit__.side_effect = lambda *a: orig.__exit__(*a)
        self.st.conn = bad
        with self.assertRaises(sqlite3.DatabaseError):
            self.st.flush(T0 + 5)
        self.st.conn = orig
        self.st.flush(T0 + 10)
        self.assertEqual(self.q("SELECT COUNT(*) FROM position"), [(1,)])


class TestFreshness(Base):
    def test_future_message_is_not_coverage(self):
        g = self.w.gaps
        g.on_source_down("aisstream", T0 + 10, "network_failure")
        self.w.handle(parse_frame(pos_frame(ts=T0 + 4000), "aisstream", T0 + 20))   # hora +1 h
        self.w.tick(T0 + 120)
        self.assertEqual(self.q("SELECT end_ts FROM gap"), [(None,)])          # el hueco sigue abierto
        self.assertEqual(self.q("SELECT COUNT(*) FROM coverage_minute"), [(0,)])
        self.assertEqual(self.w.sampler.discarded_future, 1)                  # contado una sola vez


class TestStaticOrder(Base):
    def test_old_field_does_not_overwrite_newer_in_same_flush(self):
        first = static_frame(ts=T0 + 80)
        first["Message"]["ShipStaticData"]["CallSign"] = "CS80"
        self.w.handle(parse_frame(first, "aisstream", T0 + 81))
        self.w.tick(T0 + 85)
        newer = static_frame(ts=T0 + 100)
        newer["Message"]["ShipStaticData"]["CallSign"] = ""            # sin indicativo
        older = static_frame(ts=T0 + 50)
        older["Message"]["ShipStaticData"]["CallSign"] = "CS50"
        self.w.handle(parse_frame(newer, "aisstream", T0 + 101))
        self.w.handle(parse_frame(older, "openseafeed", T0 + 102))
        self.w.tick(T0 + 110)
        self.assertEqual(self.q("SELECT callsign, last_static FROM vessel"), [("CS80", T0 + 100)])


if __name__ == "__main__":
    unittest.main()
