# -*- coding: utf-8 -*-
"""
API HTTP del Collector (DISEÑO.md §8).

Escucha solo en 127.0.0.1 (dentro de la máquina): desde fuera se llega con un
túnel SSH. Además, todas las rutas /api/ exigen el token:
    cabecera  Authorization: Bearer <token>
    o bien    ?token=<token>   (cómodo en el navegador)
"""
import asyncio
import hmac
import shutil
import time

from aiohttp import web

from . import VERSION
from . import queries as q
from . import viewer_queries as vq
from . import zones_admin
from .config import REPO_ROOT, ConfigError
from .storage import iso

DAY = 86400
VIEWER_DIR = REPO_ROOT / "viewer"


@web.middleware
async def auth_middleware(request, handler):
    if request.path.startswith("/api/"):
        token = request.app[TOKEN]
        header = request.headers.get("Authorization", "")
        given = header[7:].strip() if header.startswith("Bearer ") else ""
        # Las consultas (GET) también aceptan ?token= por comodidad; los cambios (POST/PUT) solo
        # con la cabecera, para que otra página web abierta en el navegador no pueda hacerlos.
        if not given and request.method == "GET":
            given = request.query.get("token", "")
        if not given or not hmac.compare_digest(given.encode(), token.encode()):
            return web.json_response({"error": "token ausente o incorrecto"}, status=401)
    try:
        return await handler(request)
    except (ValueError, OverflowError, ConfigError) as e:   # datos mal escritos -> 400 con explicación
        return web.json_response({"error": str(e)}, status=400)


def _zone(request):
    zid = request.query.get("zone")
    zones = request.app[STATE].zones
    if not zid:
        if len(zones) == 1:
            return next(iter(zones.values()))
        raise ValueError("indique ?zone=ZONE_ID")
    if zid not in zones:
        raise web.HTTPNotFound(text=f'{{"error": "zona {zid} no existe"}}', content_type="application/json")
    return zones[zid]


def _range(request, default_days=1):
    now = int(time.time())
    t_to = q.parse_when(request.query.get("to"), "to")
    if t_to is None:
        t_to = now + 60
    t_from = q.parse_when(request.query.get("from"), "from")
    if t_from is None:
        t_from = t_to - default_days * DAY
    return t_from, t_to


def _int_param(request, name, default, lo, hi):
    raw = request.query.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"'{name}' debe ser un número entero")
    if not lo <= value <= hi:
        raise ValueError(f"'{name}' debe estar entre {lo} y {hi}")
    return value


async def health(request):
    st = request.app[STATE]
    now = int(time.time())
    sources = {}
    for name, src in st.sources.items():
        s = src.status
        sources[name] = {"connected": s["connected"],
                         "last_msg_age_s": now - s["last_msg_ts"] if s["last_msg_ts"] else None,
                         "connects": s["connects"], "disconnects": s["disconnects"],
                         "frames": s["frames"], "dropped_queue_full": s["dropped_queue_full"],
                         "last_error": s["last_error"]}
    for name, why in st.disabled_sources.items():
        sources[name] = {"connected": False, "disabled": why}
    zones = {}
    for zid, w in st.workers.items():
        zones[zid] = {"active": True, "counters": w.counters, "sources": w.gaps.status()}
    for zid, z in st.zones.items():
        zones.setdefault(zid, {"active": z.active})
    healthy = any(s.get("connected") and (s.get("last_msg_age_s") or 0) < 120 for s in sources.values())
    disk = shutil.disk_usage(st.settings.data_dir)
    return web.json_response({
        "status": "ok" if healthy else "degraded",
        "collector_id": st.settings.collector_id, "version": VERSION,
        "now": iso(now), "uptime_s": now - st.started_ts,
        "disk_free_gb": round(disk.free / 1e9, 1),
        "queue_size": st.queue.qsize() if st.queue else 0,
        "sources": sources, "zones": zones})


def _zone_summary(z):
    return {"zone_id": z.zone_id, "name": z.name, "description": z.description, "active": z.active,
            "geometry_type": z.geometry_type, "bbox": z.bbox,
            "geometry": {"type": "Polygon", "coordinates": [z.ring]}, "sources": z.sources,
            "created_utc": z.created_utc}


async def zones(request):
    return web.json_response({"zones": [_zone_summary(z) for z in request.app[STATE].zones.values()]})


async def zone(request):
    z = _zone(request)
    stats = await asyncio.to_thread(q.zone_stats, z)
    return web.json_response({**_zone_summary(z), "archive_policy": z.archive_policy,
                              "sampling": z.sampling, "stats": stats,
                              "collector_id": request.app[STATE].settings.collector_id})


async def archive_range(request):
    z = _zone(request)
    t_from, t_to = _range(request)
    mmsi = _int_param(request, "mmsi", None, 1, 999999999)
    bbox = request.query.get("bbox")
    if bbox:
        try:
            bbox = [float(x) for x in bbox.split(",")]
        except ValueError:
            raise ValueError("bbox debe ser sur,oeste,norte,este")
        if len(bbox) != 4:
            raise ValueError("bbox debe ser sur,oeste,norte,este")
    after = request.query.get("after")
    if after:
        try:
            ts, m = after.split(":")
            after = (int(ts), int(m))
            if not (0 <= after[0] <= q.MAX_TS and 0 <= after[1] <= 999999999):
                raise ValueError
        except ValueError:
            raise ValueError("after debe tener la forma <ts>:<mmsi> (el valor next_after de la respuesta anterior)")
    limit = _int_param(request, "limit", 10000, 1, q.MAX_LIMIT)
    data = await asyncio.to_thread(q.archive_range, z, t_from, t_to, mmsi, bbox or None, limit, after or None)
    return web.json_response(data)


async def gaps(request):
    z = _zone(request)
    t_from, t_to = _range(request, default_days=30)
    data = await asyncio.to_thread(q.gaps, z, t_from, t_to, request.query.get("status"))
    return web.json_response(data)


async def coverage(request):
    z = _zone(request)
    t_from, t_to = _range(request)
    data = await asyncio.to_thread(q.coverage, z, t_from, t_to, request.query.get("bucket", "hour"))
    return web.json_response(data)


def _mmsi(request):
    try:
        mmsi = int(request.match_info["mmsi"])
    except ValueError:
        raise ValueError("el MMSI debe ser un número")
    if not 1 <= mmsi <= 999999999:
        raise ValueError("el MMSI debe tener como máximo 9 dígitos")
    return mmsi


async def vessels(request):
    """Foto del puerto: última posición de cada buque en el instante 'at' (por defecto, ahora)."""
    z = _zone(request)
    at = q.parse_when(request.query.get("at"), "at")
    if at is None:
        at = int(time.time())
    window = _int_param(request, "window", 1200, 60, 7200)
    return web.json_response(await asyncio.to_thread(vq.snapshot, z, at, window))


async def vessel(request):
    z = _zone(request)
    info = await asyncio.to_thread(vq.vessel_info, z, _mmsi(request))
    if info is None:
        return web.json_response({"error": "buque no encontrado en esta zona"}, status=404)
    return web.json_response(info)


async def track(request):
    z = _zone(request)
    t_from, t_to = _range(request)
    return web.json_response(await asyncio.to_thread(vq.track, z, _mmsi(request), t_from, t_to))


async def bounds(request):
    return web.json_response(await asyncio.to_thread(vq.bounds, _zone(request)))


# ------------------------------------------------------------ edición de zonas (Fase 5)
RELOAD_DELAY_S = 1.0


async def _payload(request):
    try:
        data = await request.json()
    except Exception:
        raise ValueError("el cuerpo de la petición debe ser JSON")
    if not isinstance(data, dict):
        raise ValueError("el cuerpo de la petición debe ser un objeto JSON")
    return data


def _schedule_reload(request, why):
    """Responde primero y recarga el Collector un momento después (guardando todo antes)."""
    state = request.app[STATE]
    asyncio.get_running_loop().call_later(RELOAD_DELAY_S, state.request_reload, why)
    return {"ok": True, "reload_in_s": RELOAD_DELAY_S,
            "note": "El Collector se recarga para aplicar el cambio (1-2 s, queda registrado)."}


def _existing_zone(request):
    zid = request.match_info["zone_id"].upper()
    zones = request.app[STATE].zones
    if zid not in zones:
        raise web.HTTPNotFound(text=f'{{"error": "zona {zid} no existe"}}', content_type="application/json")
    return zones[zid]


async def zone_create(request):
    raw = zones_admin.create_zone(request.app[STATE].settings.data_dir, await _payload(request))
    return web.json_response({**_schedule_reload(request, f"zona {raw['zone_id']} creada"),
                              "zone": raw}, status=201)


async def zone_update(request):
    raw = zones_admin.update_zone(_existing_zone(request), await _payload(request))
    return web.json_response({**_schedule_reload(request, f"zona {raw['zone_id']} editada"), "zone": raw})


async def zone_activate(request):
    z = _existing_zone(request)
    zones_admin.set_active(z, True)
    return web.json_response(_schedule_reload(request, f"zona {z.zone_id} activada"))


async def zone_deactivate(request):
    z = _existing_zone(request)
    zones_admin.set_active(z, False)
    return web.json_response(_schedule_reload(request, f"zona {z.zone_id} desactivada"))


async def index(request):
    """Página del visor. No lleva datos: los pide a /api/ con el token."""
    return web.FileResponse(VIEWER_DIR / "index.html", headers={"Cache-Control": "no-cache"})


STATE = web.AppKey("state", object)
TOKEN = web.AppKey("token", str)


def create_app(state):
    app = web.Application(middlewares=[auth_middleware])
    app[STATE] = state
    app[TOKEN] = state.settings.api_token
    app.router.add_get("/", index)
    app.router.add_get("/api/health", health)
    app.router.add_get("/api/zones", zones)
    app.router.add_get("/api/zone", zone)
    app.router.add_get("/api/archive/range", archive_range)
    app.router.add_get("/api/gaps", gaps)
    app.router.add_get("/api/coverage", coverage)
    app.router.add_get("/api/vessels", vessels)
    app.router.add_get("/api/vessel/{mmsi}", vessel)
    app.router.add_get("/api/track/{mmsi}", track)
    app.router.add_get("/api/bounds", bounds)
    app.router.add_post("/api/zones", zone_create)
    app.router.add_put("/api/zones/{zone_id}", zone_update)
    app.router.add_post("/api/zones/{zone_id}/activate", zone_activate)
    app.router.add_post("/api/zones/{zone_id}/deactivate", zone_deactivate)
    app.router.add_static("/static/", VIEWER_DIR, show_index=False)
    return app
