# -*- coding: utf-8 -*-
"""
Punto de arranque del Collector.

    python -m collector.main                  # funciona hasta que se pare (Ctrl+C o systemd)
    python -m collector.main --minutes 30     # prueba: se para solo a los 30 minutos

Pasos: lee .env y zonas -> abre una base por zona -> conecta las fuentes ->
reparte mensajes a las zonas -> vuelca a disco cada 5 s -> sirve la API.
"""
import argparse
import asyncio
import logging
import logging.handlers
import signal
import sys
import time
from pathlib import Path

from aiohttp import web

from . import VERSION
from .api import create_app
from .config import ConfigError, ensure_example_zone, load_settings, load_zones
from .sources import SOURCE_CLASSES
from .storage import MAX_PENDING_ROWS, ZoneStore
from .zone_worker import Router, ZoneWorker

log = logging.getLogger("collector")

TICK_S = 5           # cada cuánto se vuelca a disco y se comprueban silencios
QUEUE_MAX = 20000    # mensajes en espera como máximo (si se llena, se descartan y se cuenta)


class State:
    """Lo que la API necesita consultar del Collector en marcha."""

    def __init__(self, settings, zones):
        self.settings = settings
        self.zones = {z.zone_id: z for z in zones}
        self.workers = {}
        self.sources = {}
        self.disabled_sources = {}
        self.queue = None
        self.started_ts = int(time.time())
        self.exit_code = 0
        self.stop_event = None
        self.reload = False

    def request_reload(self, why=""):
        """Parada ordenada seguida de un nuevo arranque con la configuración de zonas actual."""
        log.info("Recarga solicitada: %s", why)
        self.reload = True
        if self.stop_event:
            self.stop_event.set()


def setup_logging(data_dir):
    logs = Path(data_dir) / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    fmt.converter = time.gmtime                 # registro en UTC, como los datos
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # acentos bien en cualquier consola
    except (AttributeError, ValueError):
        pass
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    files = logging.handlers.TimedRotatingFileHandler(
        logs / "collector.log", when="midnight", utc=True, backupCount=30, encoding="utf-8")
    files.setFormatter(fmt)
    root.handlers[:] = [console, files]
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)


def build_sources(settings, workers):
    """Una conexión por fuente, con un rectángulo por cada zona activa que la usa."""
    sources, disabled = {}, {}
    keys = {"aisstream": settings.aisstream_key, "openseafeed": settings.openseafeed_key}
    for name, cls in SOURCE_CLASSES.items():
        users = [w for w in workers if name in w.zone.sources]
        if not users:
            continue
        if cls.requires_key and not keys[name]:
            disabled[name] = "falta la clave en .env"
            log.warning("Fuente %s desactivada: falta la clave en .env", name)
            now = int(time.time())
            for w in users:
                w.gaps.on_source_down(name, now, "source_error", "falta la clave en .env")
            continue
        boxes = [[[w.zone.bbox["south"], w.zone.bbox["west"]], [w.zone.bbox["north"], w.zone.bbox["east"]]]
                 for w in users]
        src = cls(keys[name], boxes)
        src.listeners = [w.gaps for w in users]
        sources[name] = src
    return sources, disabled


async def consume(queue, router):
    while True:
        msg = await queue.get()
        try:
            router.route(msg)
        except Exception:
            log.exception("Error procesando un mensaje de %s (MMSI %s)", msg.source, msg.mmsi)


async def ticker(workers, stop_event, state):
    last_report = time.time()
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=TICK_S)
        except asyncio.TimeoutError:
            pass
        now = int(time.time())
        for w in workers:
            try:
                w.tick(now)
            except Exception as e:
                fails, pending = w.store.flush_failures, w.store.pending()
                if fails <= 1 or fails % 60 == 0:     # no llenar el registro: al principio y cada 5 min
                    log.error("[%s] no se puede escribir en disco (%s); fallos seguidos=%d, filas en memoria=%d",
                              w.zone_id, e, fails, pending)
                if pending > MAX_PENDING_ROWS:
                    # Mejor parar con error (systemd lo reinicia y queda registrado) que seguir
                    # "vivo" acumulando datos en memoria hasta agotarla.
                    log.critical("[%s] demasiadas filas sin poder guardar: se detiene el Collector", w.zone_id)
                    state.exit_code = 1
                    stop_event.set()
        if time.time() - last_report >= 300:         # resumen cada 5 minutos en el registro
            last_report = time.time()
            for w in workers:
                log.info("[%s] mensajes=%d guardadas=%d fichas=%d cambios_viaje=%d",
                         w.zone_id, *w.counters.values())


async def run(settings, minutes=None):
    created = ensure_example_zone(settings.data_dir)
    if created:
        log.info("Creada la zona de ejemplo VALENCIA en %s", settings.data_dir / "Zones")
    zones = load_zones(settings.data_dir)
    state = State(settings, zones)
    stores = []
    start = int(time.time())
    for z in zones:
        store = ZoneStore(z, settings.collector_id).open()
        store.startup(start)
        stores.append(store)
        if z.active:
            state.workers[z.zone_id] = ZoneWorker(z, store, start)
        else:
            store.shutdown()      # zona inactiva: su histórico sigue consultable, no captura
            log.info("Zona %s inactiva: no se captura (histórico consultable)", z.zone_id)
    workers = list(state.workers.values())
    if not workers:
        log.error("No hay ninguna zona activa: solo se sirve la API")

    stop_event = asyncio.Event()
    state.stop_event = stop_event
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except (NotImplementedError, AttributeError, RuntimeError):
            pass                                      # Windows: se usa Ctrl+C (KeyboardInterrupt)

    state.queue = asyncio.Queue(maxsize=QUEUE_MAX)
    state.sources, state.disabled_sources = build_sources(settings, workers)
    runner = web.AppRunner(create_app(state), access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, settings.api_host, settings.api_port)
    for attempt in range(10):     # tras una recarga, el sistema puede tardar un instante en liberar el puerto
        try:
            await site.start()
            break
        except OSError as e:
            if attempt == 9:
                log.critical("No se puede abrir la API en %s:%d (%s). ¿Hay otro Collector en marcha?",
                             settings.api_host, settings.api_port, e)
                await runner.cleanup()
                for w in workers:
                    w.close(int(time.time()))     # cierre ordenado: el hueco queda bien registrado
                raise
            log.warning("Puerto %d ocupado; reintento en 1 s (%s)", settings.api_port, e)
            await asyncio.sleep(1)
    log.info("Collector %s v%s en marcha. API en http://%s:%d  Zonas activas: %s  Fuentes: %s",
             settings.collector_id, VERSION, settings.api_host, settings.api_port,
             [w.zone_id for w in workers], list(state.sources))

    tasks = [asyncio.create_task(src.run(state.queue, stop_event), name=f"fuente-{n}")
             for n, src in state.sources.items()]
    tasks.append(asyncio.create_task(consume(state.queue, Router(workers)), name="router"))
    tasks.append(asyncio.create_task(ticker(workers, stop_event, state), name="volcado"))
    try:
        if minutes:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=minutes * 60)
            except asyncio.TimeoutError:
                log.info("Han pasado %s minutos: parada programada", minutes)
        else:
            await stop_event.wait()
    finally:
        stop_event.set()
        log.info("Parando: cerrando conexiones y guardando lo pendiente...")
        await asyncio.sleep(0.5)
        # procesar lo que quede en la cola antes de cerrar
        router = Router(workers)
        while not state.queue.empty():
            router.route(state.queue.get_nowait())
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await runner.cleanup()
        now = int(time.time())
        for w in workers:
            try:
                w.close(now)
            except Exception:
                log.exception("[%s] error en el cierre", w.zone_id)
        log.info("Collector parado (código de salida %d)%s", state.exit_code,
                 " - se vuelve a arrancar con la configuración nueva" if state.reload else "")
    return state.exit_code, state.reload


def main(argv=None):
    parser = argparse.ArgumentParser(description="Collector AIS (TFG Puerto de València)")
    parser.add_argument("--env", help="ruta del archivo .env (por defecto, el de la carpeta del proyecto)")
    parser.add_argument("--minutes", type=float, help="parar automáticamente tras N minutos (pruebas)")
    args = parser.parse_args(argv)
    try:
        settings = load_settings(args.env)
    except ConfigError as e:
        print(f"ERROR de configuración: {e}", file=sys.stderr)
        return 2
    setup_logging(settings.data_dir)
    try:
        while True:      # una recarga de zonas vuelve a arrancar dentro del mismo proceso
            code, reload = asyncio.run(run(settings, args.minutes))
            if not reload or code:
                return code
    except KeyboardInterrupt:
        pass
    except ConfigError as e:
        log.error("Configuración: %s", e)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
