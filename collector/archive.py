# -*- coding: utf-8 -*-
"""
Archivo de segmentos (DISEÑO.md §6, Fase 6).

- CIERRE DE PERIODO: al cambiar de año (o de trimestre o mes, según
  archive_policy) el Collector se recarga y, antes de abrir las bases,
  current.db pasa a archive/<ZONA>_<periodo>.db, se comprueba, se calcula su
  huella SHA-256 y se anota en el catálogo. Después se crea un current.db
  nuevo con las fichas de los buques.
- COMPRESIÓN (.db.zst) y MOVIMIENTO a otro disco, siempre en este orden:
  copiar -> comprobar que la copia es idéntica -> actualizar el catálogo ->
  solo entonces borrar el original.
- Las consultas abren un segmento comprimido descomprimiéndolo en archive/cache/.

Cada paso deja los archivos en un estado del que se puede seguir: si el proceso
se corta a mitad, reconcile() termina el trabajo en el siguiente arranque.

La compresión, el movimiento y la verificación están en archive_tools.py.
"""
import hashlib
import json
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import zstandard

from . import SCHEMA_VERSION, VERSION
from .storage import SCHEMA, connect, iso, write_json_atomic

try:
    import fcntl          # Linux
except ImportError:       # Windows
    fcntl = None
    import msvcrt

log = logging.getLogger("collector.archive")

QUERYABLE = ("ONLINE", "ARCHIVED", "COMPRESSED")
CACHE_KEEP_S = 7 * 86400         # un segmento descomprimido sin usar 7 días se borra de la caché
RETRY_AFTER_FAIL_S = 3600        # si un cierre falla, no se reintenta hasta pasada 1 h
_failed = {}                     # zone_id -> hora del último cierre fallido


class ArchiveError(Exception):
    pass


# ------------------------------------------------------------ rutas y catálogo
def current_path(zone):
    return Path(zone.zone_dir) / zone.database["current"]


def archive_dir(zone):
    return Path(zone.zone_dir) / zone.database["archive_dir"]


def catalog_path(zone):
    return Path(zone.zone_dir) / zone.database["catalog"]


def read_catalog(zone):
    try:
        return json.loads(catalog_path(zone).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"zone_id": zone.zone_id, "segments": []}


def segment_file(zone, seg):
    """Ruta del archivo de un segmento (el catálogo la guarda relativa a la zona, o absoluta si está en otro disco)."""
    return Path(zone.zone_dir) / seg["path"]


def rel_path(zone, path):
    try:
        return Path(path).resolve().relative_to(Path(zone.zone_dir).resolve()).as_posix()
    except ValueError:
        return Path(path).resolve().as_posix()


def find_entry(cat, seg_id):
    for seg in cat["segments"]:
        if seg.get("segment_id") == seg_id:
            return seg
    raise ArchiveError(f"el segmento {seg_id} no está en el catálogo")


def _sorted(segments):
    """Segmentos cerrados por fecha de inicio y el activo (CURRENT) al final."""
    return sorted(segments, key=lambda s: (s.get("segment_id") == "CURRENT", s.get("from_utc") or ""))


@contextmanager
def catalog_lock(zone):
    """Solo un proceso cambia el catálogo a la vez (el Collector o la herramienta de mantenimiento)."""
    f = open(Path(zone.zone_dir) / ".catalog.lock", "a+b")
    try:
        if fcntl:
            fcntl.flock(f, fcntl.LOCK_EX)
        else:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
        yield
    finally:
        if fcntl:
            fcntl.flock(f, fcntl.LOCK_UN)
        else:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        f.close()


# ------------------------------------------------------------ comprobaciones
def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def sha256_zst(path, out=None):
    """Huella del contenido descomprimido de un .zst (y, si se da `out`, lo escribe ahí)."""
    h = hashlib.sha256()
    with open(path, "rb") as f, zstandard.ZstdDecompressor().stream_reader(f) as reader:
        for block in iter(lambda: reader.read(1 << 20), b""):
            h.update(block)
            if out is not None:
                out.write(block)
    return h.hexdigest()


def check_db(path):
    """Abre en solo lectura y comprueba la integridad. Devuelve (posiciones, meta)."""
    conn = connect(path, readonly=True)
    try:
        result = conn.execute("PRAGMA quick_check").fetchone()[0]
        if result != "ok":
            raise ArchiveError(f"{Path(path).name} está dañado: {result}")
        positions = conn.execute("SELECT COUNT(*) FROM position").fetchone()[0]
        meta = dict(conn.execute("SELECT key, value FROM meta"))
    finally:
        conn.close()
    return positions, meta


# ------------------------------------------------------------ cierre de periodo
def period_key(ts, period):
    d = datetime.fromtimestamp(ts, tz=timezone.utc)
    if period == "monthly":
        return f"{d.year}-{d.month:02d}"
    if period == "quarterly":
        return f"{d.year}-Q{(d.month - 1) // 3 + 1}"
    return str(d.year)


def _db_size(path):
    return sum(p.stat().st_size for p in (path, Path(f"{path}-wal")) if p.exists())


def rollover_due(zone, period_from, now, db_size=0):
    """¿Hay que cerrar el segmento activo? (ha cambiado el periodo o se ha superado el tamaño)."""
    policy = zone.archive_policy
    period = policy.get("period", "yearly")
    if period == "size":
        return db_size > float(policy["max_segment_mb"]) * 1e6
    return period_key(period_from, period) != period_key(now, period)


def due_now(zone, store, now):
    """Lo consulta el Collector cada pocos segundos para pedir la recarga que cierra el segmento."""
    if now - _failed.get(zone.zone_id, -RETRY_AFTER_FAIL_S) < RETRY_AFTER_FAIL_S:
        return False
    period_from = store.get_meta("period_from")
    return period_from is not None and rollover_due(zone, int(period_from), now, _db_size(store.db_path))


def segment_name(zone, period_from, now):
    period = zone.archive_policy.get("period", "yearly")
    if period == "size":
        day = lambda t: datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y%m%d")   # noqa: E731
        return f"{zone.zone_id}_{day(period_from)}-{day(now)}"
    return f"{zone.zone_id}_{period_key(period_from, period)}"


def _free_name(zone, name):
    """Nunca se sobrescribe un segmento: si el nombre ya existe se añade _2, _3..."""
    ids = {s.get("segment_id") for s in read_catalog(zone)["segments"]}
    candidate, n = name, 1
    while candidate in ids or any(archive_dir(zone).glob(candidate + ".db*")):
        n += 1
        candidate = f"{name}_{n}"
    return candidate


def prepare(zone, collector_id, now):
    """Al arrancar, antes de abrir current.db: termina un cierre a medias y cierra el periodo si toca.

    Nunca impide la captura: si algo falla se registra y se sigue escribiendo en current.db.
    """
    try:
        with catalog_lock(zone):
            reconcile(zone, collector_id, now)
            cur = current_path(zone)
            if not cur.exists():
                return None
            conn = connect(cur, readonly=True)
            try:
                row = conn.execute("SELECT value FROM meta WHERE key = 'period_from'").fetchone()
            finally:
                conn.close()
            if row and rollover_due(zone, int(row[0]), now, _db_size(cur)):
                return close_segment(zone, collector_id, now)
    except Exception:
        _failed[zone.zone_id] = now
        log.exception("[%s] no se pudo cerrar el segmento: se sigue escribiendo en current.db "
                      "y se reintentará dentro de 1 h", zone.zone_id)
    return None


def close_segment(zone, collector_id, now):
    """Pasa current.db al archivo. Se llama con el Collector parado y el catálogo bloqueado."""
    cur = current_path(zone)
    archive_dir(zone).mkdir(parents=True, exist_ok=True)
    # 1. Dejar la base cerrada y autónoma: huecos cerrados, fin del periodo anotado y sin diario WAL
    conn = sqlite3.connect(str(cur))
    try:
        meta = dict(conn.execute("SELECT key, value FROM meta"))
        name = _free_name(zone, segment_name(zone, int(meta["period_from"]), now))
        heartbeat = int(meta.get("heartbeat_ts") or now)
        with conn:
            for gap_id, reason in conn.execute("SELECT gap_id, reason FROM gap WHERE end_ts IS NULL").fetchall():
                # una zona desactivada sigue desactivada: el hueco continúa en el segmento nuevo
                end = now if reason == "zone_disabled" else heartbeat
                conn.execute("UPDATE gap SET end_ts = MAX(start_ts, ?) WHERE gap_id = ?", (end, gap_id))
            for k, v in {"segment_id": name, "period_to": now, "closed_ts": now}.items():
                conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (k, str(v)))
            conn.execute("INSERT INTO collector_event(ts, level, event, detail) VALUES (?, 'INFO', ?, ?)",
                         (now, "segment_closed", f"{name}: periodo cerrado y archivado"))
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("PRAGMA journal_mode=DELETE")       # un solo archivo, sin -wal ni -shm
    finally:
        conn.close()
    if Path(f"{cur}-wal").exists():
        raise ArchiveError(f"{cur.name}-wal sigue existiendo: no se archiva para no perder datos")
    Path(f"{cur}-shm").unlink(missing_ok=True)
    # 2. Moverla al archivo (mismo disco: el cambio de nombre es instantáneo y atómico)
    target = archive_dir(zone) / f"{name}.db"
    os.replace(cur, target)
    # 3. Comprobarla y anotarla en el catálogo; 4. base nueva
    entry = register(zone, collector_id, target, now)
    new_current(zone, target, now)
    log.warning("[%s] segmento %s cerrado: %d posiciones, %.1f MB, sha256 %s…", zone.zone_id, name,
                entry["positions"], entry["size_bytes"] / 1e6, entry["sha256"][:12])
    return entry


def register(zone, collector_id, path, now):
    """Comprueba un segmento cerrado y lo anota en el catálogo (escritura atómica)."""
    positions, meta = check_db(path)
    entry = {"segment_id": path.stem, "collector_id": meta.get("collector_id", collector_id),
             "from_utc": iso(int(meta.get("period_from") or 0)),
             "to_utc": iso(int(meta.get("period_to") or path.stat().st_mtime)),
             "path": rel_path(zone, path), "status": "ARCHIVED", "compressed": False,
             "size_bytes": path.stat().st_size, "positions": positions, "sha256": sha256_file(path),
             "schema_version": int(meta.get("schema_version", SCHEMA_VERSION)), "created_utc": iso(now)}
    cat = read_catalog(zone)
    segs = [s for s in cat["segments"] if s.get("segment_id") != entry["segment_id"]]
    for s in segs:
        if s.get("segment_id") == "CURRENT":
            s["from_utc"] = entry["to_utc"]
    cat["segments"] = _sorted(segs + [entry])
    write_json_atomic(catalog_path(zone), cat)
    return entry


def new_current(zone, prev, now):
    """current.db nuevo: misma identidad, fichas de los buques y el latido del segmento anterior."""
    cur = current_path(zone)
    tmp = cur.with_name(cur.name + ".new")
    tmp.unlink(missing_ok=True)
    conn = sqlite3.connect(tmp.resolve().as_uri(), uri=True)
    try:
        conn.executescript(SCHEMA)
        conn.execute("ATTACH DATABASE ? AS prev", (Path(prev).resolve().as_uri() + "?mode=ro",))
        old = dict(conn.execute("SELECT key, value FROM prev.meta"))
        start = int(old.get("period_to") or now)
        meta = {"zone_id": old["zone_id"], "collector_id": old["collector_id"],
                "schema_version": str(SCHEMA_VERSION), "segment_id": "CURRENT", "period_from": str(start),
                "created_ts": str(now), "created_by_version": VERSION, "previous_segment": Path(prev).stem}
        # el latido permite registrar al arrancar el hueco de la parada; la geometría, detectar cambios
        meta.update({k: old[k] for k in ("heartbeat_ts", "clean_shutdown", "zone_geometry") if k in old})
        with conn:
            conn.execute("INSERT INTO main.source SELECT * FROM prev.source")
            conn.execute("INSERT INTO main.vessel SELECT * FROM prev.vessel")
            conn.execute("INSERT INTO main.gap(source_id, start_ts, end_ts, reason, detected_ts, notes) "
                         "SELECT source_id, end_ts, NULL, reason, ?, notes FROM prev.gap "
                         "WHERE reason = 'zone_disabled' AND end_ts = ?", (start, start))
            conn.executemany("INSERT INTO main.meta(key, value) VALUES (?, ?)", meta.items())
        conn.execute("DETACH DATABASE prev")
    finally:
        conn.close()
    os.replace(tmp, cur)


def reconcile(zone, collector_id, now):
    """Termina un cierre que se cortó a medias, para que todo quede como si hubiera ido bien."""
    adir = archive_dir(zone)
    if not adir.exists():
        return
    known = {s.get("segment_id") for s in read_catalog(zone)["segments"]}
    for f in sorted(adir.glob("*.db")):
        if f.stem not in known:
            log.warning("[%s] %s no estaba en el catálogo (cierre interrumpido): se anota", zone.zone_id, f.name)
            register(zone, collector_id, f, now)
    if not current_path(zone).exists():
        closed = [s for s in read_catalog(zone)["segments"]
                  if s.get("status") == "ARCHIVED" and segment_file(zone, s).exists()]
        if closed:
            last = _sorted(closed)[-1]
            log.warning("[%s] falta current.db tras el cierre de %s: se crea", zone.zone_id, last["segment_id"])
            new_current(zone, segment_file(zone, last), now)


# ------------------------------------------------------------ consultas sobre segmentos
def query_path(zone, seg):
    """Archivo .db que se puede abrir para consultar este segmento, o None si no está disponible."""
    path = segment_file(zone, seg)
    if not path.exists():
        return None
    if not seg.get("compressed"):
        return path
    cache = archive_dir(zone) / "cache" / f"{seg['segment_id']}.db"
    if cache.exists():
        try:
            os.utime(cache)          # marca de último uso, para la limpieza de la caché
        except OSError:
            pass
        return cache
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_name(f"{cache.name}.{os.getpid()}-{threading.get_ident()}.tmp")
    try:
        with open(tmp, "wb") as out:
            digest = sha256_zst(path, out)
        if digest != seg.get("sha256"):
            log.error("[%s] %s no coincide con su huella: no se usa", zone.zone_id, path.name)
            return None
        os.replace(tmp, cache)
    except (OSError, zstandard.ZstdError) as e:
        log.error("[%s] no se pudo descomprimir %s: %s", zone.zone_id, path.name, e)
        return None
    finally:
        tmp.unlink(missing_ok=True)
    log.info("[%s] %s descomprimido en la caché para una consulta", zone.zone_id, seg["segment_id"])
    return cache


def catalog_status(zone):
    """Catálogo con la disponibilidad real de cada archivo (para /api/catalog)."""
    cat = read_catalog(zone)
    for seg in cat["segments"]:
        path = segment_file(zone, seg)
        seg["available"] = path.exists()
        seg["file_bytes"] = path.stat().st_size if path.exists() else None
    return cat
