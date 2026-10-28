# -*- coding: utf-8 -*-
"""
Adaptador genérico para fuentes con WebSocket "compatible con aisstream.io".

Una conexión WebSocket es como una llamada telefónica que no se cuelga: la
fuente nos va enviando los mensajes según llegan. Este adaptador:
  1. conecta y envía la suscripción (rectángulos de las zonas) en < 3 s;
  2. lee mensajes, los normaliza y los pone en la cola común;
  3. si la conexión se cae o se queda muda, avisa (para registrar el hueco) y
     reintenta con esperas crecientes: 5 s, 10 s, 20 s... hasta 5 min.
Cada subclase solo define la URL y los detalles propios de su proveedor.
"""
import asyncio
import json
import logging
import random
import time

import aiohttp

from ..messages import SUBSCRIBED_TYPES, parse_frame

log = logging.getLogger("collector.sources")

BACKOFF_START_S = 5
BACKOFF_MAX_S = 300
CONNECT_TIMEOUT_S = 30    # conexión + saludo WebSocket: si tarda más, se aborta y se reintenta
IDLE_TIMEOUT_S = 300      # sin ningún mensaje en 5 min -> reconectar
STABLE_AFTER_S = 60       # conexión que dura más de esto: se reinicia la espera


class SourceError(Exception):
    """La fuente rechazó la conexión (clave inválida, suscripción incorrecta...)."""


class WsSource:
    name = "base"
    url = None
    compress = 15              # permessage-deflate (aisstream lo exige desde 09/2026)

    def __init__(self, api_key, boxes):
        self.api_key = api_key
        self.boxes = boxes      # lista de [[lat_sur, lon_oeste], [lat_norte, lon_este]]
        self.listeners = []     # objetos con on_source_up / on_source_down (GapTracker)
        self.status = {"connected": False, "last_msg_ts": None, "connected_since": None,
                       "connects": 0, "disconnects": 0, "frames": 0, "parsed": 0,
                       "dropped_queue_full": 0, "last_error": None}

    # -------- personalizable por cada proveedor
    def subscription(self):
        sub = {"BoundingBoxes": self.boxes, "FilterMessageTypes": SUBSCRIBED_TYPES}
        if self.api_key:
            sub["APIKey"] = self.api_key
        return sub

    # -------- avisos a los trabajadores de zona
    def _notify_up(self, ts):
        for l in self.listeners:
            l.on_source_up(self.name, ts)

    def _notify_down(self, ts, reason, note):
        for l in self.listeners:
            try:
                l.on_source_down(self.name, ts, reason, note)
            except Exception:   # un fallo al registrar un hueco no debe tumbar la conexión
                log.exception("[%s] error registrando hueco", self.name)

    # -------- bucle principal
    async def run(self, queue, stop_event):
        backoff = BACKOFF_START_S
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            while not stop_event.is_set():
                started = int(time.time())   # entero, como last_msg_ts, para poder compararlos
                reason, note = "network_failure", None
                try:
                    await self._session_once(session, queue, stop_event)
                    if stop_event.is_set():
                        break
                    note = "la fuente cerró la conexión"
                except SourceError as e:
                    reason, note = "source_error", str(e)[:300]
                except asyncio.TimeoutError:
                    note = f"sin mensajes durante {IDLE_TIMEOUT_S} s o tiempo de conexión agotado"
                except (aiohttp.ClientError, OSError) as e:
                    note = f"{type(e).__name__}: {e}"[:300]
                except asyncio.CancelledError:
                    raise
                except Exception as e:   # error inesperado: se registra y se reintenta
                    log.exception("[%s] error inesperado", self.name)
                    reason, note = "unknown", f"{type(e).__name__}: {e}"[:300]
                finally:
                    if self.status["connected"]:
                        self.status["disconnects"] += 1
                    self.status["connected"] = False
                    self.status["connected_since"] = None

                now = int(time.time())
                self.status["last_error"] = f"{reason}: {note}"
                log.warning("[%s] conexión perdida (%s): %s", self.name, reason, note)
                # El hueco empieza en el último dato que llegó por ESTA conexión (si llegó alguno):
                # una conexión muda hasta el corte por inactividad también es tiempo sin datos.
                last = self.status["last_msg_ts"]
                start = last if last and started <= last <= now else now
                self._notify_down(start, reason, note)
                if time.time() - started > STABLE_AFTER_S:
                    backoff = BACKOFF_START_S
                wait = backoff * random.uniform(0.8, 1.2)
                log.info("[%s] reintento en %.0f s", self.name, wait)
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=wait)
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, BACKOFF_MAX_S)

    async def _session_once(self, session, queue, stop_event):
        # Tiempo límite para conectar: sin él, un servidor que acepta la conexión pero nunca
        # responde al saludo dejaría el Collector esperando para siempre sin capturar.
        ws = await asyncio.wait_for(
            session.ws_connect(self.url, heartbeat=30, compress=self.compress,
                               max_msg_size=8 * 1024 * 1024),
            timeout=CONNECT_TIMEOUT_S)
        async with ws:
            await ws.send_str(json.dumps(self.subscription()))
            log.info("[%s] conectado a %s; suscripción enviada (%d rectángulos)",
                     self.name, self.url, len(self.boxes))
            self.status["connects"] += 1
            self.status["connected"] = True
            self.status["connected_since"] = int(time.time())
            self._notify_up(int(time.time()))
            stop_wait = asyncio.ensure_future(stop_event.wait())
            try:
                while True:
                    recv = asyncio.ensure_future(ws.receive())
                    done, _ = await asyncio.wait({recv, stop_wait}, timeout=IDLE_TIMEOUT_S,
                                                 return_when=asyncio.FIRST_COMPLETED)
                    if stop_wait in done:
                        recv.cancel()
                        return
                    if not done:
                        recv.cancel()
                        raise asyncio.TimeoutError()
                    msg = recv.result()
                    if msg.type in (aiohttp.WSMsgType.TEXT, aiohttp.WSMsgType.BINARY):
                        self._handle_payload(msg.data, queue)
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        raise aiohttp.ClientError(f"error de WebSocket: {ws.exception()}")
                    elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSING,
                                      aiohttp.WSMsgType.CLOSED):
                        detail = f"cierre del servidor (código {ws.close_code}) {msg.extra or ''}".strip()
                        if ws.close_code in (1008, 4000, 4001, 4003):
                            raise SourceError(detail)
                        raise aiohttp.ClientError(detail)
            finally:
                stop_wait.cancel()

    def _handle_payload(self, data, queue):
        ts_rx = int(time.time())
        self.status["frames"] += 1
        try:
            obj = json.loads(data)
        except (ValueError, UnicodeDecodeError):
            return
        if isinstance(obj, dict) and ("error" in obj or "Error" in obj):
            raise SourceError(str(obj.get("error") or obj.get("Error")))
        if isinstance(obj, dict) and obj.get("MessageType") == "SubscriptionConfirmation":
            log.info("[%s] suscripción confirmada %s", self.name, obj.get("Message"))
            return
        self.status["last_msg_ts"] = ts_rx
        msg = parse_frame(obj, self.name, ts_rx)
        if msg is None:
            return
        self.status["parsed"] += 1
        try:
            queue.put_nowait(msg)
        except asyncio.QueueFull:
            self.status["dropped_queue_full"] += 1
