# -*- coding: utf-8 -*-
"""Tests del traductor de mensajes (messages.py)."""
import unittest

from collector.messages import clean_eta, parse_frame, parse_time
from tests.helpers import T0, pos_frame, static_frame


class TestTime(unittest.TestCase):
    def test_formats_of_both_sources(self):
        self.assertEqual(parse_time("2026-10-28T18:34:37.040+00:00"), parse_time("2026-10-28 18:34:37.794168 +0000 UTC"))
        self.assertEqual(parse_time("2026-10-28T18:34:37Z"), parse_time("2026-10-28T18:34:37.040+00:00"))

    def test_offset_is_applied(self):
        self.assertEqual(parse_time("2026-10-28T20:34:37+02:00"), parse_time("2026-10-28T18:34:37Z"))

    def test_garbage(self):
        self.assertIsNone(parse_time("ayer"))
        self.assertIsNone(parse_time(None))


class TestPositions(unittest.TestCase):
    def test_osf_and_aisstream_give_same_result(self):
        a = parse_frame(pos_frame(time_fmt="osf"), "openseafeed", T0 + 3)
        b = parse_frame(pos_frame(time_fmt="ais"), "aisstream", T0 + 3)
        for f in ("mmsi", "ts", "lat", "lon", "sog", "cog", "heading", "nav_status"):
            self.assertEqual(getattr(a, f), getattr(b, f), f)
        self.assertEqual(a.ts, T0)
        self.assertEqual(b.hint_name, "PRUEBA")      # '@' de relleno eliminados

    def test_unavailable_values_become_none(self):
        m = parse_frame(pos_frame(Sog=102.3, Cog=360, TrueHeading=511), "aisstream", T0)
        self.assertIsNone(m.sog)
        self.assertIsNone(m.cog)
        self.assertIsNone(m.heading)

    def test_invalid_position_is_dropped(self):
        self.assertIsNone(parse_frame(pos_frame(lat=91, lon=181), "aisstream", T0))
        self.assertIsNone(parse_frame(pos_frame(lat=0, lon=0), "aisstream", T0))

    def test_invalid_flag_and_bad_mmsi(self):
        self.assertIsNone(parse_frame(pos_frame(Valid=False), "aisstream", T0))
        f = pos_frame(mmsi=12345)
        f["Message"]["PositionReport"]["UserID"] = 12345
        self.assertIsNone(parse_frame(f, "aisstream", T0))

    def test_class_b_has_no_nav_status(self):
        m = parse_frame(pos_frame(mtype="StandardClassBPositionReport"), "aisstream", T0)
        self.assertEqual(m.ais_class, "B")
        self.assertIsNone(m.nav_status)

    def test_position_without_time_is_dropped(self):
        f = pos_frame()
        del f["MetaData"]["time_utc"]
        self.assertIsNone(parse_frame(f, "aisstream", T0 + 7))
        s = static_frame()
        del s["MetaData"]["time_utc"]
        self.assertEqual(parse_frame(s, "aisstream", T0 + 7).ts, T0 + 7)   # estático: hora de recepción

    def test_absurd_message_id_ignored(self):
        self.assertIsNone(parse_frame(pos_frame(MessageID=10**30), "aisstream", T0).msg_id)

    def test_other_types_ignored(self):
        self.assertIsNone(parse_frame({"MessageType": "BaseStationReport", "Message": {}}, "x", T0))
        self.assertIsNone(parse_frame("texto", "x", T0))


class TestStatic(unittest.TestCase):
    def test_ship_static_data(self):
        m = parse_frame(static_frame(), "openseafeed", T0)
        self.assertEqual((m.imo, m.name, m.callsign, m.ship_type), (9401283, "RDO CONCORD", "A8TG2", 72))
        self.assertEqual((m.length_m, m.beam_m, m.draught_m, m.destination), (304.0, 40.0, 11.2, "ESVLC"))
        self.assertEqual(m.eta_raw, "11-02 06:30")
        self.assertIsNotNone(m.eta_utc)
        self.assertFalse(m.has_position)
        self.assertEqual((m.meta_lat, m.meta_lon), (39.45, -0.32))

    def test_eta_year_rolls_over(self):
        dec = parse_time("2026-12-30T00:00:00Z")
        raw, ts = clean_eta({"Month": 1, "Day": 3, "Hour": 8, "Minute": 0}, dec)
        self.assertEqual(ts, parse_time("2027-01-03T08:00:00Z"))

    def test_eta_unavailable(self):
        self.assertEqual(clean_eta({"Month": 0, "Day": 0, "Hour": 24, "Minute": 60}, T0), (None, None))
        raw, ts = clean_eta({"Month": 11, "Day": 2, "Hour": 24, "Minute": 60}, T0)
        self.assertEqual(raw, "11-02 24:60")
        self.assertIsNone(ts)

    def test_static_report_type_24(self):
        f = {"MessageType": "StaticDataReport", "MetaData": {"MMSI": 224000002},
             "Message": {"StaticDataReport": {"UserID": 224000002, "Valid": True,
                         "ReportA": {"Valid": True, "Name": "VELERO@@"},
                         "ReportB": {"Valid": False, "ShipType": 37}}}}
        m = parse_frame(f, "aisstream", T0)
        self.assertEqual(m.name, "VELERO")
        self.assertIsNone(m.ship_type)          # la mitad B no era válida
        self.assertEqual(m.ais_class, "B")


if __name__ == "__main__":
    unittest.main()
