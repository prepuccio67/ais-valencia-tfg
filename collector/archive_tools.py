# -*- coding: utf-8 -*-
"""
Mantenimiento del archivo de segmentos (DISEÑO.md §6, Fase 6).

Compresión (.db.zst) y movimiento a otro disco, siempre en este orden:
copiar -> comprobar que la copia es idéntica -> actualizar el catálogo ->
solo entonces borrar el original. Lo lanza cada día ais-archive.timer
("mantener") y también se puede usar a mano, en el servidor, como usuario ais:

    python -m collector.archive_tools estado
    python -m collector.archive_tools mantener      (verifica, comprime lo que toca, limpia la caché)
    python -m collector.archive_tools comprimir VALENCIA_2026
    python -m collector.archive_tools mover VALENCIA_2026 /mnt/otro_disco/ais
"""
import argparse
import logging
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

import zstandard

from .archive import (CACHE_KEEP_S, ArchiveError, archive_dir, catalog_lock, catalog_path, catalog_status,
                      check_db, find_entry, read_catalog, rel_path, segment_file, sha256_file, sha256_zst)
from .storage import iso, write_json_atomic

log = logging.getLogger("collector.archive")

COMPRESS_LEVEL = 10              # el mismo nivel que las copias de seguridad


def compress_segment(zone, seg_id, now=None):
    now = now or int(time.time())
    seg = find_entry(read_catalog(zone), seg_id)
    if seg.get("status") != "ARCHIVED" or seg.get("compressed"):
        raise ArchiveError(f"{seg_id} no es un segmento cerrado sin comprimir (estado {seg.get('status')})")
    src = segment_file(zone, seg)
    if sha256_file(src) != seg["sha256"]:
        raise ArchiveError(f"{src.name} no coincide con la huella del catálogo: no se comprime")
    dst = src.with_name(src.name + ".zst")
    tmp = dst.with_name(dst.name + ".tmp")
    try:
        with open(src, "rb") as fi, open(tmp, "wb") as fo:
            zstandard.ZstdCompressor(level=COMPRESS_LEVEL, threads=-1).copy_stream(fi, fo)
        if sha256_zst(tmp) != seg["sha256"]:        # descomprimido debe ser idéntico al original
            raise ArchiveError(f"la compresión de {seg_id} no es idéntica al original")
        os.replace(tmp, dst)
    finally:
        tmp.unlink(missing_ok=True)
    _updatefind_entry(zone, seg, path=rel_path(zone, dst), status="COMPRESSED", compressed=True,
                  compressed_bytes=dst.stat().st_size, sha256_zst=sha256_file(dst), compressed_utc=iso(now))
    src.unlink()                                    # solo ahora, con la copia comprobada y anotada
    log.warning("[%s] %s comprimido: %.1f MB -> %.1f MB", zone.zone_id, seg_id,
                seg["size_bytes"] / 1e6, dst.stat().st_size / 1e6)
    return dst


def move_segment(zone, seg_id, dest_dir, now=None):
    now = now or int(time.time())
    seg = find_entry(read_catalog(zone), seg_id)
    if seg.get("status") not in ("ARCHIVED", "COMPRESSED"):
        raise ArchiveError(f"solo se mueven segmentos cerrados ({seg_id} está {seg.get('status')})")
    src = segment_file(zone, seg)
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dst = dest_dir / src.name
    if dst.resolve() == src.resolve():
        raise ArchiveError(f"{seg_id} ya está en {dest_dir}")
    if dst.exists():
        raise ArchiveError(f"{dst} ya existe: no se sobrescribe")
    expected = seg["sha256_zst"] if seg.get("compressed") else seg["sha256"]
    if sha256_file(src) != expected:
        raise ArchiveError(f"{src.name} no coincide con la huella del catálogo: no se mueve")
    tmp = dst.with_name(dst.name + ".tmp")
    try:
        shutil.copyfile(src, tmp)                       # 1. copiar
        if sha256_file(tmp) != expected:                # 2. comprobar la huella
            raise ArchiveError(f"la copia de {seg_id} en {dest_dir} no es idéntica")
        os.replace(tmp, dst)
    finally:
        tmp.unlink(missing_ok=True)
    if not seg.get("compressed"):
        check_db(dst)                                   # 3. abrir y validar
    _updatefind_entry(zone, seg, path=rel_path(zone, dst), moved_utc=iso(now))   # 4. catálogo
    src.unlink()                                        # 5. solo entonces, borrar el original
    log.warning("[%s] %s movido a %s", zone.zone_id, seg_id, dst)
    return dst


def _updatefind_entry(zone, seg, **changes):
    """Cambia una entrada del catálogo, comprobando que nadie la ha cambiado entretanto."""
    with catalog_lock(zone):
        cat = read_catalog(zone)
        current = find_entry(cat, seg["segment_id"])
        if current.get("path") != seg["path"]:
            raise ArchiveError(f"{seg['segment_id']} ha cambiado mientras se trabajaba con él")
        current.update(changes)
        write_json_atomic(catalog_path(zone), cat)


def verify_segments(zone):
    """Comprueba que cada segmento cerrado sigue idéntico (huella SHA-256). Devuelve los problemas."""
    problems = []
    for seg in read_catalog(zone)["segments"]:
        if seg.get("segment_id") == "CURRENT":
            continue
        path = segment_file(zone, seg)
        expected = seg.get("sha256_zst") if seg.get("compressed") else seg.get("sha256")
        if not path.exists():
            problems.append(f"{seg['segment_id']}: no disponible ({path}); ¿disco sin montar?")
        elif sha256_file(path) != expected:
            problems.append(f"{seg['segment_id']}: la huella no coincide: el archivo ha cambiado o está dañado")
    return problems


def maintain(zone, now=None):
    """Tarea diaria: verificar, comprimir lo que ya toca, limpiar sobrantes y la caché."""
    now = now or int(time.time())
    problems = verify_segments(zone)
    days = zone.archive_policy.get("compress_after_days")
    for seg in read_catalog(zone)["segments"]:
        closed = seg.get("to_utc")
        if (days is not None and seg.get("status") == "ARCHIVED" and closed and not any(
                p.startswith(seg["segment_id"] + ":") for p in problems)):
            age = now - datetime.fromisoformat(closed.replace("Z", "+00:00")).timestamp()
            if age >= days * 86400:
                try:
                    compress_segment(zone, seg["segment_id"], now)
                except Exception as e:
                    problems.append(f"{seg['segment_id']}: no se pudo comprimir ({e})")
    _remove_leftovers(zone)
    cache = archive_dir(zone) / "cache"
    for f in (cache.glob("*") if cache.exists() else []):
        if now - f.stat().st_mtime > CACHE_KEEP_S:
            f.unlink(missing_ok=True)
    return problems


def _remove_leftovers(zone):
    """Si se cortó una compresión o un movimiento justo antes de borrar el original, lo borra ahora,
    pero solo si es idéntico (misma huella) a lo que el catálogo ya tiene guardado en otro sitio."""
    cat = read_catalog(zone)
    in_use = {segment_file(zone, s).resolve() for s in cat["segments"]}
    for f in list(archive_dir(zone).glob("*.db")) + list(archive_dir(zone).glob("*.db.zst")):
        if f.resolve() in in_use:
            continue
        seg_id = f.name.split(".db")[0]
        seg = next((s for s in cat["segments"] if s.get("segment_id") == seg_id), None)
        if seg is None:
            continue
        digest = sha256_file(f)
        if digest in (seg.get("sha256"), seg.get("sha256_zst")):
            log.warning("[%s] se borra %s: copia sobrante idéntica a la del catálogo", zone.zone_id, f.name)
            f.unlink()
        else:
            log.error("[%s] %s no está en el catálogo y no coincide con él: revisar a mano", zone.zone_id, f.name)


# ------------------------------------------------------------ herramienta de línea de órdenes
def _print_status(zone):
    print(f"Zona {zone.zone_id}  (periodo: {zone.archive_policy.get('period', 'yearly')}, "
          f"comprimir tras {zone.archive_policy.get('compress_after_days')} días)")
    for s in catalog_status(zone)["segments"]:
        size = (s["file_bytes"] or 0) / 1e6
        print(f"  {s['segment_id']:<24} {s.get('status', ''):<10} {s.get('from_utc') or '':<21}"
              f"{s.get('to_utc') or 'ahora':<21} {size:8.1f} MB  {'' if s['available'] else 'NO DISPONIBLE'}")


def main(argv=None):
    from .config import load_settings, load_zones
    p = argparse.ArgumentParser(description="Mantenimiento del archivo de segmentos")
    p.add_argument("--env", help="ruta del .env")
    p.add_argument("--zone", help="solo esta zona")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("estado", help="lista los segmentos de cada zona")
    sub.add_parser("mantener", help="verifica, comprime lo que toca y limpia la caché")
    c = sub.add_parser("comprimir", help="comprime ya un segmento cerrado")
    c.add_argument("segmento")
    m = sub.add_parser("mover", help="mueve un segmento cerrado a otra carpeta o disco")
    m.add_argument("segmento")
    m.add_argument("destino")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = load_settings(args.env)
    zones = [z for z in load_zones(settings.data_dir) if not args.zone or z.zone_id == args.zone]
    if args.cmd in ("comprimir", "mover"):
        zones = [z for z in zones if any(s.get("segment_id") == args.segmento
                                         for s in read_catalog(z)["segments"])]
        if not zones:
            print(f"No existe el segmento {args.segmento}")
            return 2
    errors = 0
    for zone in zones:
        try:
            if args.cmd == "estado":
                _print_status(zone)
            elif args.cmd == "mantener":
                for problem in maintain(zone):
                    log.error("[%s] %s", zone.zone_id, problem)
                    errors += 1
            elif args.cmd == "comprimir":
                compress_segment(zone, args.segmento)
            elif args.cmd == "mover":
                move_segment(zone, args.segmento, args.destino)
        except ArchiveError as e:
            log.error("[%s] %s", zone.zone_id, e)
            errors += 1
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
