# -*- coding: utf-8 -*-
"""Tests del muestreo (sampler.py) y de la geometría (geo.py)."""
import unittest

from collector.config import DEFAULT_SAMPLING
from collector.geo import point_in_ring
from collector.sampler import FIRST, INTERVAL, MOTION, NAV, Sampler
from tests.helpers import T0


class TestSampler(unittest.TestCase):
    def setUp(self):
        self.s = Sampler(DEFAULT_SAMPLING)

    def d(self, dt, sog, nav=5, mmsi=1, rx_delay=2):
        return self.s.decide(mmsi, T0 + dt, T0 + dt + rx_delay, sog, nav)

    def test_stopped_vessel_every_10_min(self):
        self.assertEqual(self.d(0, 0.0), FIRST)
        self.assertIsNone(self.d(300, 0.1))
        self.assertIsNone(self.d(599, 0.0))
        self.assertEqual(self.d(600, 0.0), INTERVAL)

    def test_moving_vessel_every_minute(self):
        self.assertEqual(self.d(0, 12.0, nav=0), FIRST)
        self.assertIsNone(self.d(30, 12.0, nav=0))
        self.assertEqual(self.d(60, 12.0, nav=0), INTERVAL)

    def test_departure_saved_immediately(self):
        self.d(0, 0.0)
        self.assertEqual(self.d(20, 3.5), MOTION)

    def test_hysteresis_avoids_jitter(self):
        self.d(0, 0.0)
        for i, sog in enumerate((0.3, 0.4, 0.2, 0.45), start=1):  # parado y "temblando" < 0,5 kn
            self.assertIsNone(self.d(15 * i, sog))
        self.assertEqual(self.d(100, 0.6), MOTION)                  # ya se mueve (>= 0,5 = umbral de atraque)
        self.assertIsNone(self.d(130, 0.4))                         # sigue en movimiento (>= 0,3)
        self.assertEqual(self.d(145, 0.2), MOTION)                  # se para

    def test_pending_event_not_lost(self):
        self.d(0, 0.0)
        self.assertIsNone(self.d(5, 1.2))                           # arranca, pero < 10 s
        self.assertEqual(self.d(40, 0.4), MOTION)                   # siguiente mensaje: se guarda el evento
        self.d(100, 0.0, nav=1)
        self.assertIsNone(self.d(105, 0.0, nav=5))                  # cambio de estado aplazado...
        self.assertEqual(self.d(130, 0.0, nav=1), NAV)              # ...guardado aunque luego vuelva

    def test_nav_status_change(self):
        self.d(0, 0.0, nav=1)
        self.assertEqual(self.d(30, 0.0, nav=5), NAV)

    def test_event_min_gap(self):
        self.d(0, 0.0, nav=1)
        self.assertIsNone(self.d(5, 0.0, nav=5))                    # < 10 s: espera
        self.assertEqual(self.d(12, 0.0, nav=5), NAV)               # el cambio no se pierde

    def test_old_repeated_and_future_messages(self):
        self.assertIsNone(self.s.decide(1, T0, T0 + 901, 0.0, 5))  # > 15 min de antigüedad
        self.assertEqual(self.s.discarded_old, 1)
        self.assertEqual(self.d(0, 0.0), FIRST)
        self.assertIsNone(self.d(0, 0.0))                           # mismo instante
        self.assertIsNone(self.d(-60, 0.0))                         # más antiguo que lo guardado
        self.assertIsNone(self.s.decide(2, T0 + 600, T0, 0.0, 5))   # 10 min en el futuro
        self.assertEqual(self.s.discarded_future, 1)

    def test_unknown_speed_keeps_previous_state(self):
        self.d(0, 10.0, nav=0)
        self.assertIsNone(self.d(30, None, nav=0))
        self.assertEqual(self.d(60, None, nav=0), INTERVAL)        # sigue "en movimiento"

    def test_vessels_are_independent(self):
        self.assertEqual(self.d(0, 0.0, mmsi=1), FIRST)
        self.assertEqual(self.d(1, 0.0, mmsi=2), FIRST)

    def test_forget(self):
        self.d(0, 0.0, mmsi=1)
        self.assertEqual(self.s.forget_older_than(T0 + 1), 1)
        self.assertEqual(self.d(10, 0.0, mmsi=1), FIRST)


class TestGeo(unittest.TestCase):
    def test_point_in_polygon_lon_lat_order(self):
        tri = [[-0.4, 39.3], [0.0, 39.3], [-0.2, 39.6], [-0.4, 39.3]]   # [lon, lat]
        self.assertTrue(point_in_ring(39.4, -0.2, tri))
        self.assertFalse(point_in_ring(39.55, -0.38, tri))


if __name__ == "__main__":
    unittest.main()
