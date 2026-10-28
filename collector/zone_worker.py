# -*- coding: utf-8 -*-
"""
Trabajador de una zona: recibe los mensajes que el router le asigna, aplica el
muestreo, cuenta la cobertura por minuto y vuelca a SQLite periódicamente.
"""
import logging

from .gaps import GapTracker
from .geo import in_zone
from .sampler import Sampler

log = logging.getLogger("collector.worker")

FORGET_AFTER_S = 2 * 86400     # olvidar buques que no se ven en 2 días (solo memoria)


class ZoneWorker:
    def __init__(self, zone, store, start_ts):
        self.zone = zone
        self.store = store
        self.sampler = Sampler(zone.sampling)
        self.sampler.count_in_decide = False     # los descartes se cuentan una vez, en handle()
        self.gaps = GapTracker(store, zone.sources, zone.silence_alert_min, start_ts)
        self.known_mmsi = set()            # buques con alguna posición en esta zona
        self._cov = {}                     # (minute, source) -> [msgs, set(mmsi)]
        self.counters = {"msgs": 0, "saved": 0, "static": 0, "voyage": 0}
        self._last_forget = start_ts

    @property
    def zone_id(self):
        return self.zone.zone_id

    def wants(self, msg):
        """¿Le interesa este mensaje a la zona? (fuente y posición)"""
        if msg.source not in self.zone.sources:
            return False
        if msg.has_position:
            return in_zone(msg.lat, msg.lon, self.zone)
        # mensaje estático: por la posición que añade la fuente o porque ya conocemos el buque
        if msg.meta_lat is not None and in_zone(msg.meta_lat, msg.meta_lon, self.zone):
            return True
        return msg.mmsi in self.known_mmsi

    def handle(self, msg):
        sid = self.store.source_ids[msg.source]
        self.counters["msgs"] += 1
        # Solo los mensajes con hora razonable demuestran que la fuente funciona: las
        # repeticiones de posiciones antiguas que OpenSeaFeed envía al conectar, o un mensaje
        # con la hora en el futuro, no cuentan como cobertura, no cierran huecos y no se guardan.
        if not self.sampler.is_fresh(msg.ts, msg.ts_rx):
            return
        self.gaps.on_message(msg.source, msg.ts_rx)
        key = (msg.ts_rx - msg.ts_rx % 60, msg.source)
        cov = self._cov.get(key)
        if cov is None:
            cov = self._cov[key] = [0, set()]
        cov[0] += 1
        cov[1].add(msg.mmsi)

        if msg.has_position:
            reason = self.sampler.decide(msg.mmsi, msg.ts, msg.ts_rx, msg.sog, msg.nav_status)
            if reason is not None:
                self.store.add_position(msg, sid, reason)
                self.known_mmsi.add(msg.mmsi)
                self.counters["saved"] += 1
        if msg.has_static:
            self.store.add_static(msg)
            self.counters["static"] += 1
            if self.store.add_voyage(msg, sid):
                self.counters["voyage"] += 1

    def _move_coverage(self, now, everything=False):
        current_minute = now - now % 60
        for key in [k for k in self._cov if everything or k[0] < current_minute]:
            msgs, mmsis = self._cov.pop(key)
            self.store.add_coverage(key[0], self.store.source_ids[key[1]], msgs, len(mmsis))

    def tick(self, now):
        """Cada pocos segundos: huecos por silencio, cobertura cerrada y volcado a disco."""
        self.gaps.check(now)
        self._move_coverage(now)
        if now - self._last_forget > 3600:
            self.sampler.forget_older_than(now - FORGET_AFTER_S)
            self._last_forget = now
        return self.store.flush(now)

    def close(self, now):
        self._move_coverage(now, everything=True)
        self.gaps.sync()
        if self.sampler.discarded_old or self.sampler.discarded_future:
            self.store.add_event("INFO", "discarded",
                                 f"antiguas={self.sampler.discarded_old} futuras={self.sampler.discarded_future}")
        self.store.shutdown()


class Router:
    """Reparte cada mensaje entre las zonas a las que pertenece."""

    def __init__(self, workers):
        self.workers = workers

    def route(self, msg):
        n = 0
        for w in self.workers:
            try:                       # un fallo en una zona no debe cortar las demás
                if w.wants(msg):
                    w.handle(msg)
                    n += 1
            except Exception:
                log.exception("[%s] error procesando mensaje de %s (MMSI %s)", w.zone_id, msg.source, msg.mmsi)
        return n
