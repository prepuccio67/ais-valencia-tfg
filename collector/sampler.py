# -*- coding: utf-8 -*-
"""
Muestreo: decide qué posiciones se guardan (DISEÑO.md §4).

Por cada buque se recuerda la última posición guardada. Se guarda una nueva si:
  0 FIRST   es la primera del buque desde que arrancó el Collector;
  2 NAV     cambia el estado de navegación AIS (p. ej. 1 fondeado -> 0 navegando);
  3 MOTION  pasa de parado a en movimiento o al revés;
  1 INTERVAL ha pasado el intervalo: 60 s si se mueve, 600 s si está parado.

Para que un buque que "tiembla" alrededor del umbral no dispare guardados sin
parar, hay histéresis (como un termostato): un buque parado pasa a "en
movimiento" con >= 0,5 kn (el mismo umbral que usa el análisis de escalas para
"atracado") y uno en movimiento pasa a "parado" con < 0,3 kn.

Si un evento llega menos de min_event_gap_s después del último guardado, queda
"pendiente" y se guarda con el siguiente mensaje del buque, aunque ese mensaje
ya no muestre el cambio.
"""
from dataclasses import dataclass

FIRST, INTERVAL, NAV, MOTION = 0, 1, 2, 3
REASON_NAMES = {FIRST: "primera", INTERVAL: "intervalo", NAV: "cambio_estado_ais", MOTION: "arranca_para"}

MAX_FUTURE_S = 120   # una hora del mensaje más de 2 min en el futuro se considera errónea


@dataclass
class _VesselState:
    last_ts: int
    moving: bool
    nav: int
    pending: int = None       # motivo de un evento aplazado por min_event_gap


class Sampler:
    def __init__(self, sampling):
        self.moving_interval = int(sampling["moving_interval_s"])
        self.stopped_interval = int(sampling["stopped_interval_s"])
        self.stopped_speed = float(sampling["stopped_speed_kn"])
        self.moving_speed = float(sampling["moving_speed_kn"])
        self.max_age = int(sampling["max_age_s"])
        self.min_event_gap = int(sampling["min_event_gap_s"])
        self._state = {}
        self.discarded_old = 0     # contadores para el registro de sucesos
        self.discarded_future = 0
        self.count_in_decide = True   # el ZoneWorker ya cuenta los descartes antes de llamar a decide()

    def _is_moving(self, sog, prev):
        if sog is None:
            return prev if prev is not None else False
        if prev:                                   # se movía: sigue hasta bajar de stopped_speed (0,3)
            return sog >= self.stopped_speed
        return sog >= self.moving_speed            # estaba parado: necesita llegar a moving_speed (0,5)

    def staleness(self, ts, ts_rx):
        """Comprobación pura de la hora: None si es razonable, 'old' o 'future' si no."""
        if ts_rx - ts > self.max_age:
            return "old"
        if ts - ts_rx > MAX_FUTURE_S:
            return "future"
        return None

    def is_fresh(self, ts, ts_rx):
        """Como staleness(), pero contando los descartes (para el registro de sucesos)."""
        problem = self.staleness(ts, ts_rx)
        if problem == "old":
            self.discarded_old += 1
        elif problem == "future":
            self.discarded_future += 1
        return problem is None

    def decide(self, mmsi, ts, ts_rx, sog, nav):
        """Devuelve el motivo (FIRST, INTERVAL, NAV, MOTION) si hay que guardar, o None."""
        if self.staleness(ts, ts_rx) is not None:
            if self.count_in_decide:
                self.is_fresh(ts, ts_rx)
            return None
        st = self._state.get(mmsi)
        if st is None:
            moving = self._is_moving(sog, None)
            self._state[mmsi] = _VesselState(ts, moving, nav)
            return FIRST
        if ts <= st.last_ts:                       # repetido o más antiguo que lo ya guardado
            return None
        moving = self._is_moving(sog, st.moving)
        elapsed = ts - st.last_ts
        event = None
        if nav is not None and st.nav is not None and nav != st.nav:
            event = NAV
        elif moving != st.moving:
            event = MOTION
        event = event if event is not None else st.pending
        reason = None
        if event is not None:
            if elapsed >= self.min_event_gap:
                reason = event
            else:
                st.pending = event         # demasiado pronto: se guarda con el siguiente mensaje
        if reason is None and elapsed >= (self.moving_interval if moving else self.stopped_interval):
            reason = INTERVAL
        if reason is not None:
            st.last_ts = ts
            st.moving = moving
            st.pending = None
            if nav is not None:
                st.nav = nav
        return reason

    def forget_older_than(self, ts_limit):
        """Libera memoria de buques que no se ven desde hace tiempo."""
        old = [m for m, st in self._state.items() if st.last_ts < ts_limit]
        for m in old:
            del self._state[m]
        return len(old)
