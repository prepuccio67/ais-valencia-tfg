# -*- coding: utf-8 -*-
"""Tests del archivo de segmentos (Fase 6): cierre de periodo, recuperación, compresión y movimiento."""
import asyncio
import importlib.util
import shutil
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from collector import archive, archive_tools
from collector import queries as q
from collector import viewer_queries as vq
from collector.config import REPO_ROOT, ConfigError
from collector.messages import parse_frame
from collector.storage import ZoneStore, iso
from collector.zone_worker import ZoneWorker
from tests.helpers import T0, make_data_dir, pos_frame, settings, static_frame, valencia, write_zone

Y2027 = 1798761600            # 01/01/2027 00:00:00 UTC
MMSI = 224000001


def load_backup():
    spec = importlib.util.spec_from_file_location("backup", REPO_ROOT / "deploy" / "backup.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = make_data_dir()
        self.zdir = self.dir / "Zones" / "VALENCIA"
        archive._failed.clear()

    def tearDown(self):
        archive._failed.clear()
        shutil.rmtree(self.dir, ignore_errors=True)

    def zone(self):
        return valencia(self.dir)

    def capture(self, start, n, period_from=None, rx_delay=1):
        """Abre current.db, guarda n posiciones (1 por minuto, en movimiento) y para de forma ordenada."""
        st = ZoneStore(self.zone(), "TEST-01").open()
        if period_from is not None:
            st.set_meta("period_from", period_from)
        st.startup(start)
        w = ZoneWorker(st.zone, st, start)
        for i in range(n):
            ts = start + 60 * i
            w.handle(parse_frame(pos_frame(mmsi=MMSI, ts=ts, sog=5.0), "aisstream", ts + rx_delay))
        w.handle(parse_frame(static_frame(mmsi=MMSI, ts=start), "aisstream", start + 1))
        w.tick(start + 60 * n)
        w.close(start + 60 * n)

    def rows(self, path, sql):
        c = sqlite3.connect(path)
        try:
            return c.execute(sql).fetchall()
        finally:
            c.close()

    def roll(self, now=Y2027 + 5):
        """Captura en 2026 y cierre del año."""
        self.capture(T0, 5, period_from=T0)
        return archive.prepare(self.zone(), "TEST-01", now)


class TestPolicy(Base):
    def test_period_keys(self):
        self.assertEqual(archive.period_key(T0, "yearly"), "2026")
        self.assertEqual(archive.period_key(T0, "quarterly"), "2026-Q4")
        self.assertEqual(archive.period_key(T0, "monthly"), "2026-10")
        z = self.zone()
        self.assertFalse(archive.rollover_due(z, T0, Y2027 - 1))
        self.assertTrue(archive.rollover_due(z, T0, Y2027))
        write_zone(self.dir, archive_policy={"period": "size", "max_segment_mb": 1})
        z = self.zone()
        self.assertFalse(archive.rollover_due(z, T0, Y2027, db_size=900_000))
        self.assertTrue(archive.rollover_due(z, T0, T0, db_size=1_100_000))

    def test_bad_policy_rejected(self):
        for bad in ({"period": "weekly"}, {"period": "size"}, {"compress_after_days": -1},
                    {"compress_after_days": "365"}):
            write_zone(self.dir, archive_policy=bad)
            with self.assertRaises(ConfigError, msg=bad):
                self.zone()

    def test_not_due_changes_nothing(self):
        self.capture(T0, 3, period_from=T0)
        self.assertIsNone(archive.prepare(self.zone(), "TEST-01", T0 + 86400))
        self.assertEqual([s["segment_id"] for s in archive.read_catalog(self.zone())["segments"]], ["CURRENT"])
        self.assertEqual(list((self.zdir / "archive").iterdir()), [])


class TestRollover(Base):
    def test_year_change(self):
        entry = self.roll()
        seg = self.zdir / "archive" / "VALENCIA_2026.db"
        self.assertTrue(seg.exists())
        self.assertFalse(Path(f"{seg}-wal").exists())            # archivo autónomo, sin diario WAL
        self.assertEqual(entry["positions"], 5)
        self.assertEqual(entry["sha256"], archive.sha256_file(seg))
        cat = archive.read_catalog(self.zone())["segments"]
        self.assertEqual([(s["segment_id"], s["status"]) for s in cat],
                         [("VALENCIA_2026", "ARCHIVED"), ("CURRENT", "ONLINE")])
        self.assertEqual(cat[0]["to_utc"], iso(Y2027 + 5))
        self.assertEqual(cat[1]["from_utc"], iso(Y2027 + 5))
        meta = dict(self.rows(seg, "SELECT key, value FROM meta"))
        self.assertEqual((meta["segment_id"], meta["period_to"]), ("VALENCIA_2026", str(Y2027 + 5)))
        cur = self.zdir / "current.db"
        new_meta = dict(self.rows(cur, "SELECT key, value FROM meta"))
        self.assertEqual(new_meta["period_from"], str(Y2027 + 5))
        self.assertEqual(new_meta["previous_segment"], "VALENCIA_2026")
        self.assertEqual(self.rows(cur, "SELECT mmsi, name FROM vessel"), [(MMSI, "RDO CONCORD")])
        self.assertEqual(self.rows(cur, "SELECT COUNT(*) FROM position"), [(0,)])

        # se sigue capturando en 2027 y las consultas cruzan los dos segmentos sin que se note
        self.capture(Y2027 + 60, 3)
        self.assertEqual(self.rows(cur, "SELECT reason FROM gap WHERE source_id IS NULL"), [("maintenance",)])
        z = self.zone()
        r = q.archive_range(z, T0 - 10, Y2027 + 3600, mmsi=MMSI)
        self.assertEqual((r["count"], r["segments_used"]), (8, 2))
        self.assertEqual(vq.vessel_info(z, MMSI)["positions"], 8)
        self.assertEqual(vq.bounds(z)["first"], T0)
        # una consulta solo de 2027 no necesita abrir el segmento de 2026
        self.assertEqual(q.archive_range(z, Y2027 + 3000, Y2027 + 3600)["segments_used"], 1)

    def test_disabled_zone_stays_disabled(self):
        write_zone(self.dir, active=False)
        st = ZoneStore(self.zone(), "TEST-01").open()
        st.set_meta("period_from", T0)
        st.startup(T0)
        st.shutdown()
        archive.prepare(self.zone(), "TEST-01", Y2027 + 5)
        old = self.rows(self.zdir / "archive" / "VALENCIA_2026.db",
                        "SELECT start_ts, end_ts FROM gap WHERE reason = 'zone_disabled'")
        self.assertEqual(old, [(T0, Y2027 + 5)])
        st = ZoneStore(self.zone(), "TEST-01").open()
        st.startup(Y2027 + 10)
        st.shutdown()
        new = self.rows(self.zdir / "current.db", "SELECT start_ts, end_ts, reason FROM gap")
        self.assertEqual(new, [(Y2027 + 5, None, "zone_disabled")])       # sigue abierto, sin duplicados

    def test_interrupted_close_is_completed_on_next_start(self):
        self.capture(T0, 5, period_from=T0)
        with mock.patch.object(archive, "register", side_effect=OSError("se va la luz")):
            self.assertIsNone(archive.prepare(self.zone(), "TEST-01", Y2027 + 5))
        self.assertTrue((self.zdir / "archive" / "VALENCIA_2026.db").exists())
        self.assertFalse((self.zdir / "current.db").exists())
        # tras un fallo no se pide otra recarga hasta pasada 1 h
        fake = mock.Mock(db_path=self.zdir / "current.db", **{"get_meta.return_value": str(T0)})
        self.assertFalse(archive.due_now(self.zone(), fake, Y2027 + 60))
        self.assertTrue(archive.due_now(self.zone(), fake, Y2027 + 5 + 3600))
        archive.prepare(self.zone(), "TEST-01", Y2027 + 100)
        cat = archive.read_catalog(self.zone())["segments"]
        self.assertEqual([s["segment_id"] for s in cat], ["VALENCIA_2026", "CURRENT"])
        self.assertEqual(cat[0]["positions"], 5)
        meta = dict(self.rows(self.zdir / "current.db", "SELECT key, value FROM meta"))
        self.assertEqual(meta["period_from"], str(Y2027 + 5))

    def test_never_overwrites_a_segment(self):
        self.roll()
        # otro cierre del mismo año (p. ej. reloj atrasado) no pisa el segmento existente
        st = ZoneStore(self.zone(), "TEST-01").open()
        st.set_meta("period_from", T0 + 86400)
        st.shutdown()
        archive.prepare(self.zone(), "TEST-01", Y2027 + 50)
        ids = [s["segment_id"] for s in archive.read_catalog(self.zone())["segments"]]
        self.assertEqual(ids, ["VALENCIA_2026", "VALENCIA_2026_2", "CURRENT"])


class TestCompressAndMove(Base):
    def test_compress_then_query(self):
        self.roll()
        z = self.zone()
        archive_tools.compress_segment(z, "VALENCIA_2026")
        self.assertFalse((self.zdir / "archive" / "VALENCIA_2026.db").exists())
        seg = archive.read_catalog(z)["segments"][0]
        self.assertEqual((seg["status"], seg["compressed"], seg["path"]),
                         ("COMPRESSED", True, "archive/VALENCIA_2026.db.zst"))
        r = q.archive_range(z, T0 - 10, Y2027, mmsi=MMSI)
        self.assertEqual((r["count"], r["segments_unavailable"]), (5, []))
        self.assertTrue((self.zdir / "archive" / "cache" / "VALENCIA_2026.db").exists())
        self.assertEqual(archive_tools.verify_segments(z), [])

    def test_damaged_compressed_segment_is_not_used(self):
        self.roll()
        z = self.zone()
        dst = archive_tools.compress_segment(z, "VALENCIA_2026")
        data = bytearray(dst.read_bytes())
        data[len(data) // 2] ^= 0xFF
        dst.write_bytes(bytes(data))
        r = q.archive_range(z, T0 - 10, Y2027, mmsi=MMSI)
        self.assertEqual(r["count"], 0)
        self.assertEqual(r["segments_unavailable"][0]["segment_id"], "VALENCIA_2026")
        self.assertEqual(len(archive_tools.verify_segments(z)), 1)

    def test_changed_segment_is_not_compressed(self):
        self.roll()
        seg = self.zdir / "archive" / "VALENCIA_2026.db"
        c = sqlite3.connect(seg)
        c.execute("DELETE FROM position WHERE ts = ?", (T0,))
        c.commit()
        c.close()
        with self.assertRaises(archive.ArchiveError):
            archive_tools.compress_segment(self.zone(), "VALENCIA_2026")
        self.assertTrue(seg.exists())                                    # el original no se toca

    def test_move_to_other_disk_and_unmount(self):
        self.roll()
        other = Path(tempfile.mkdtemp(prefix="ais_disco2_"))
        try:
            z = self.zone()
            dst = archive_tools.move_segment(z, "VALENCIA_2026", other / "ais")
            self.assertFalse((self.zdir / "archive" / "VALENCIA_2026.db").exists())
            self.assertEqual(archive.read_catalog(z)["segments"][0]["path"], dst.resolve().as_posix())
            self.assertEqual(q.archive_range(z, T0 - 10, Y2027, mmsi=MMSI)["count"], 5)
            with self.assertRaises(archive.ArchiveError):                 # no se pisa un archivo existente
                archive_tools.move_segment(z, "VALENCIA_2026", other / "ais")
            (other / "ais").rename(other / "desmontado")                  # "se desmonta el disco"
            r = q.archive_range(z, T0 - 10, Y2027, mmsi=MMSI)
            self.assertEqual(r["segments_unavailable"][0]["status"], "OFFLINE")
            self.assertIn("no disponible", archive_tools.verify_segments(z)[0])
        finally:
            shutil.rmtree(other, ignore_errors=True)

    def test_maintain_compresses_and_cleans_leftovers(self):
        write_zone(self.dir, archive_policy={"period": "yearly", "compress_after_days": 0})
        self.roll()
        z = self.zone()
        original = (self.zdir / "archive" / "VALENCIA_2026.db").read_bytes()
        self.assertEqual(archive_tools.maintain(z, Y2027 + 10), [])
        self.assertEqual(archive.read_catalog(z)["segments"][0]["status"], "COMPRESSED")
        # una compresión cortada justo antes de borrar el original: la copia idéntica sobra
        (self.zdir / "archive" / "VALENCIA_2026.db").write_bytes(original)
        archive_tools.maintain(z, Y2027 + 20)
        self.assertFalse((self.zdir / "archive" / "VALENCIA_2026.db").exists())
        # un archivo con el mismo nombre pero distinto contenido no se borra nunca
        (self.zdir / "archive" / "VALENCIA_2026.db").write_bytes(b"otro contenido")
        archive_tools.maintain(z, Y2027 + 30)
        self.assertTrue((self.zdir / "archive" / "VALENCIA_2026.db").exists())


class TestCollectorLoop(Base):
    def test_period_end_triggers_reload_and_close(self):
        from collector import main
        write_zone(self.dir, archive_policy={"period": "monthly"})
        s = settings(self.dir)
        last_month = int(time.time()) - 40 * 86400

        async def scenario():
            task = asyncio.create_task(main.run(s))
            await asyncio.sleep(0.5)                                     # Collector en marcha
            c = sqlite3.connect(self.zdir / "current.db", timeout=5)     # "pasa el mes"
            c.execute("UPDATE meta SET value = ? WHERE key = 'period_from'", (str(last_month),))
            c.commit()
            c.close()
            return await asyncio.wait_for(task, 10)

        with mock.patch.object(main, "SOURCE_CLASSES", {}), mock.patch.object(main, "TICK_S", 0.1):
            self.assertEqual(asyncio.run(scenario()), (0, True))         # pide la recarga él solo
            asyncio.run(main.run(s, minutes=0.01))                      # y al volver a arrancar cierra
        ids = [x["segment_id"] for x in archive.read_catalog(self.zone())["segments"]]
        self.assertEqual(ids, [f"VALENCIA_{archive.period_key(last_month, 'monthly')}", "CURRENT"])


class TestBackupAcrossSegments(Base):
    def test_last_day_of_year_is_complete(self):
        backup = load_backup()
        dec31 = Y2027 - 86400
        self.capture(Y2027 - 600, 5, period_from=dec31)            # 23:50 a 23:54 en el segmento de 2026
        archive.prepare(self.zone(), "TEST-01", Y2027 + 5)
        # una posición de las 23:58, recibida con retraso tras el cierre, queda en el segmento nuevo
        self.capture(Y2027 - 120, 1, rx_delay=200)
        # (la limpieza de copias de más de 30 días mira la fecha real del archivo: aquí se desactiva)
        with mock.patch.object(backup, "KEEP_DAILY_DAYS", 10 ** 5):
            backup.run(settings(self.dir), do_upload=False, now=Y2027 + 4 * 3600)
        staging = self.dir / "backup-staging" / "VALENCIA"
        daily = staging / "daily" / "VALENCIA_2026-12-31.db.zst"
        with tempfile.TemporaryDirectory() as tmp:
            db = backup.decompress_to(daily, tmp)
            self.assertEqual(self.rows(db, "SELECT COUNT(*) FROM position"), [(6,)])
        seg = staging / "archive" / "VALENCIA_2026.db.zst"           # el segmento cerrado, para subirlo
        self.assertEqual(archive.sha256_zst(seg), archive.read_catalog(self.zone())["segments"][0]["sha256"])


if __name__ == "__main__":
    unittest.main()
