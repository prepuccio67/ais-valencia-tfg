# -*- coding: utf-8 -*-
"""
Detección de huecos por fuente dentro de una zona (DISEÑO.md §3.2).

Un hueco de una fuente es un periodo en que esa fuente no nos dio datos de la
zona. Se abre cuando:
  - la conexión se cae            -> network_failure (desde el último dato de esa conexión)
  - la fuente rechaza la clave     -> source_error
  - conectada pero sin mensajes frescos de la zona durante N minutos -> source_silence
y se cierra al llegar el siguiente mensaje fresco de esa fuente para la zona.
Los huecos de toda la zona (todas las fuentes a la vez) los calcula la API.

Al recibir un mensaje solo se anota en memoria; la base de datos se actualiza en
sync(), que se llama en cada volcado periódico. Así un problema de disco nunca
frena la recepción de mensajes, y lo que no se pudo escribir se reintenta.
"""
import logging
import sqlite3

log = logging.getLogger("collector.gaps")


class _SourceState:
    def __init__(self, start_ts):
        self.connected = False
        self.last_msg_ts = start_ts     # al arrancar se cuenta desde la hora de inicio
        self.reason = None              # motivo del hueco abierto (None = sin hueco)
        self.start = None
        self.note = None
        self.gap_id = None              # id en la base (None = aún no escrito)
        self.close_ts = None            # hora de cierre pendiente de escribir


class GapTracker:
    def __init__(self, store, source_names, silence_min, start_ts):
        self.store = store
        self.zone_id = store.zone.zone_id
        self.silence_s = int(silence_min * 60)
        self.state = {name: _SourceState(start_ts) for name in source_names}
        self._done = []    # huecos ya cerrados pendientes de escribir: (fuente, inicio, fin, motivo, nota, gap_id)

    def _open(self, source, st, start, reason, note):
        st.reason, st.start, st.note, st.gap_id, st.close_ts = reason, int(start), note, None, None
        log.warning("[%s] hueco abierto en %s: %s %s", self.zone_id, source, reason, note or "")

    def on_message(self, source, ts_rx):
        st = self.state.get(source)
        if st is None:
            return
        st.connected = True
        st.last_msg_ts = ts_rx
        if st.reason is not None and st.close_ts is None:
            st.close_ts = ts_rx
            log.info("[%s] %s vuelve a enviar datos: hueco '%s' cerrado", self.zone_id, source, st.reason)

    def on_source_up(self, source, ts):
        st = self.state.get(source)
        if st is not None:
            st.connected = True

    def on_source_down(self, source, ts, reason, note=None):
        """La fuente se ha desconectado o ha fallado (ts = último dato recibido o ahora)."""
        st = self.state.get(source)
        if st is None:
            return
        st.connected = False
        if st.close_ts is not None:
            self._retire(source, st)            # el hueco anterior ya terminó: a la cola de escritura
        if st.reason is None:
            self._open(source, st, ts, reason, note)

    def _retire(self, source, st):
        self._done.append((source, st.start, st.close_ts, st.reason, st.note, st.gap_id))
        st.reason = st.start = st.note = st.gap_id = st.close_ts = None

    def check(self, now):
        """Comprobación periódica: fuente conectada pero callada demasiado tiempo."""
        for source, st in self.state.items():
            if st.reason is None and st.connected and now - st.last_msg_ts > self.silence_s:
                self._open(source, st, st.last_msg_ts, "source_silence",
                           f"conectada pero sin mensajes de la zona durante más de {self.silence_s // 60} min")
        self.sync()

    def sync(self):
        """Escribe en la base los huecos abiertos y cerrados desde la última vez.
        Lo que no se pueda escribir se queda en memoria y se reintenta en el siguiente volcado."""
        for source, st in self.state.items():
            if st.close_ts is not None:
                self._retire(source, st)
        still = []
        for item in self._done:
            source, start, end, reason, note, gap_id = item
            try:
                if gap_id is None:
                    self.store.insert_closed_gap(self.store.source_ids[source], start, end, reason, note)
                else:
                    self.store.close_gap(gap_id, end)
                self.store.add_event("INFO", "gap_closed", f"{source}: {reason}")
            except sqlite3.Error:
                log.exception("[%s] no se pudo cerrar el hueco de %s; se reintentará", self.zone_id, source)
                still.append(item)
        self._done = still
        for source, st in self.state.items():
            if st.reason is not None and st.gap_id is None:
                try:
                    st.gap_id = self.store.open_gap(self.store.source_ids[source], st.start, st.reason, st.note)
                except sqlite3.Error:
                    log.exception("[%s] no se pudo abrir el hueco de %s; se reintentará", self.zone_id, source)

    def status(self):
        return {name: {"connected": st.connected, "last_msg_ts": st.last_msg_ts,
                       "open_gap": st.reason if st.close_ts is None else None}
                for name, st in self.state.items()}
