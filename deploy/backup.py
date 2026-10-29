# -*- coding: utf-8 -*-
"""
Copia de seguridad del Collector (DISEÑO.md §7.4). La lanza ais-backup.timer cada día.

Para cada zona, en DATA_DIR/backup-staging/<ZONA>/:
  1. DIARIA (incremental): las filas de cada día UTC completo aún no copiado
     (posiciones, cambios de viaje, cobertura, huecos, sucesos y buques vistos)
     en un .db pequeño, comprimido con zstd (.db.zst).
  2. MENSUAL (completa): el día 1 de cada mes (o si no hay ninguna), una copia
     en caliente de current.db, más zone.json y el catálogo.
  3. VERIFICACIÓN: cada copia se descomprime en una carpeta temporal y se
     comprueba que se abre y que tiene las mismas filas que el original.
  4. SUBIDA: si BACKUP_PAR_URL está definida, se sube a Oracle Object Storage
     (enlace de escritura preautorizado). Lo que no se suba se reintenta mañana.
Las copias locales se conservan 30 días (diarias) y 3 meses (completas).

Uso:  python deploy/backup.py            (normal)
      python deploy/backup.py --no-upload  (solo local, para pruebas)
"""
import argparse
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from collector.config import load_settings, load_zones   # noqa: E402
from collector.storage import SCHEMA                      # noqa: E402

log = logging.getLogger("backup")
DAY = 86400
KEEP_DAILY_DAYS = 30
KEEP_FULL = 3
MAX_CATCHUP_DAYS = 14          # si faltan días sin copiar, como mucho se recuperan 14

# Qué filas de cada tabla pertenecen a un día [a, b)
DAILY_TABLES = {
    "position": "ts >= :a AND ts < :b",
    "voyage_data": "ts >= :a AND ts < :b",
    "coverage_minute": "minute >= :a AND minute < :b",
    "collector_event": "ts >= :a AND ts < :b",
    "gap": "start_ts < :b AND COALESCE(end_ts, :b) >= :a",
    "vessel": "last_seen >= :a AND first_seen < :b",
    "source": "1",
    "meta": "1",
}


def day_str(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def compress(path):
    """Comprime con zstd (si está instalado) o gzip. Devuelve la ruta comprimida."""
    if shutil.which("zstd"):
        subprocess.run(["zstd", "-q", "-f", "-10", "--rm", str(path)], check=True)
        return Path(str(path) + ".zst")
    import gzip
    out = Path(str(path) + ".gz")
    with open(path, "rb") as src, gzip.open(out, "wb", compresslevel=9) as dst:
        shutil.copyfileobj(src, dst)
    path.unlink()
    return out


def decompress_to(path, dest_dir):
    dest = Path(dest_dir) / path.name.rsplit(".", 1)[0]
    if path.suffix == ".zst":
        subprocess.run(["zstd", "-q", "-d", "-f", str(path), "-o", str(dest)], check=True)
    else:
        import gzip
        with gzip.open(path, "rb") as src, open(dest, "wb") as dst:
            shutil.copyfileobj(src, dst)
    return dest


def counts(conn, tables, where=None, params=None):
    out = {}
    for t in tables:
        sql = f"SELECT COUNT(*) FROM {t}" + (f" WHERE {where[t]}" if where else "")
        out[t] = conn.execute(sql, params or {}).fetchone()[0]
    return out


def verify(compressed, expected):
    """Descomprime en una carpeta temporal y comprueba integridad y número de filas."""
    with tempfile.TemporaryDirectory() as tmp:
        db = decompress_to(compressed, tmp)
        conn = sqlite3.connect(db)
        try:
            ok = conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            got = counts(conn, expected)
        finally:
            conn.close()
    if not ok or got != expected:
        raise RuntimeError(f"verificación fallida de {compressed.name}: esperado {expected}, obtenido {got}")
    return got


def make_daily(src_db, out_dir, zone_id, day_start):
    """Exporta las filas de un día a un .db propio y lo comprime y verifica."""
    a, b = day_start, day_start + DAY
    out = out_dir / f"{zone_id}_{day_str(a)}.db"
    out.unlink(missing_ok=True)
    conn = sqlite3.connect(out.resolve().as_uri(), uri=True)   # uri=True: permite ATTACH en solo lectura
    try:
        conn.executescript(SCHEMA)
        conn.execute("ATTACH DATABASE ? AS src", (Path(src_db).resolve().as_uri() + "?mode=ro",))
        params = {"a": a, "b": b}
        with conn:
            for table, where in DAILY_TABLES.items():
                conn.execute(f"INSERT OR REPLACE INTO main.{table} SELECT * FROM src.{table} WHERE {where}", params)
            conn.execute("INSERT OR REPLACE INTO main.meta(key, value) VALUES ('backup_day', ?)", (day_str(a),))
        expected = counts(conn, DAILY_TABLES)
        src_expected = {t: conn.execute(f"SELECT COUNT(*) FROM src.{t} WHERE {w}", params).fetchone()[0]
                        for t, w in DAILY_TABLES.items() if t != "meta"}
        conn.execute("DETACH DATABASE src")
    finally:
        conn.close()
    for t, n in src_expected.items():
        if expected[t] != n:
            raise RuntimeError(f"{out.name}: la tabla {t} tiene {expected[t]} filas y el original {n}")
    packed = compress(out)
    verify(packed, expected)
    log.info("diaria %s: %d posiciones, %.1f KB", packed.name, expected["position"], packed.stat().st_size / 1024)
    return packed


def make_full(src_db, out_dir, zone_id, now):
    """Copia completa en caliente de current.db (la API de copia de SQLite no bloquea al Collector)."""
    out = out_dir / f"{zone_id}_full_{day_str(now)}.db"
    out.unlink(missing_ok=True)
    src = sqlite3.connect(Path(src_db).resolve().as_uri() + "?mode=ro", uri=True)
    dst = sqlite3.connect(out)
    try:
        src.backup(dst)
        tables = ["position", "vessel", "voyage_data", "gap", "coverage_minute", "collector_event"]
        expected = counts(dst, tables)
    finally:
        src.close()
        dst.close()
    packed = compress(out)
    verify(packed, expected)
    log.info("completa %s: %d posiciones, %.1f MB", packed.name, expected["position"], packed.stat().st_size / 1e6)
    return packed


def upload(par_url, local_path, object_name):
    """Sube un archivo con PUT al enlace preautorizado de Object Storage."""
    url = par_url.rstrip("/") + "/" + urllib.request.quote(object_name)
    data = local_path.read_bytes()
    req = urllib.request.Request(url, data=data, method="PUT",
                                 headers={"Content-Type": "application/octet-stream"})
    with urllib.request.urlopen(req, timeout=300) as r:
        if r.status not in (200, 201):
            raise RuntimeError(f"respuesta {r.status}")


def run(settings, do_upload, now=None):
    now = now or int(time.time())
    today = now - now % DAY
    staging = Path(settings.data_dir) / "backup-staging"
    par = os.environ.get("BACKUP_PAR_URL", "") or ""
    errors = 0
    for zone in load_zones(settings.data_dir):
        zdir = staging / zone.zone_id
        (zdir / "daily").mkdir(parents=True, exist_ok=True)
        (zdir / "full").mkdir(parents=True, exist_ok=True)
        state_path = zdir / "state.json"
        state = json.loads(state_path.read_text()) if state_path.exists() else {"done_days": [], "uploaded": []}
        src_db = Path(zone.zone_dir) / zone.database["current"]
        if not src_db.exists():
            continue
        conn = sqlite3.connect(src_db.resolve().as_uri() + "?mode=ro", uri=True)
        first = conn.execute("SELECT MIN(ts) FROM position").fetchone()[0]
        conn.close()
        if first is None:
            log.info("[%s] sin posiciones todavía", zone.zone_id)
            continue
        # 1. diarias de los días completos que falten (sin hoy, que aún no ha terminado)
        start = max(first - first % DAY, today - MAX_CATCHUP_DAYS * DAY)
        for d in range(start, today, DAY):
            if day_str(d) in state["done_days"]:
                continue
            try:
                make_daily(src_db, zdir / "daily", zone.zone_id, d)
                state["done_days"].append(day_str(d))
            except Exception:
                log.exception("[%s] error en la copia del día %s", zone.zone_id, day_str(d))
                errors += 1
        # 2. completa mensual
        fulls = sorted((zdir / "full").glob("*_full_*"))
        if datetime.fromtimestamp(now, tz=timezone.utc).day == 1 or not fulls:
            try:
                make_full(src_db, zdir / "full", zone.zone_id, now)
                for extra in (zone.zone_dir / "zone.json", zone.zone_dir / zone.database["catalog"]):
                    if extra.exists():
                        shutil.copyfile(extra, zdir / "full" / f"{day_str(now)}_{extra.name}")
            except Exception:
                log.exception("[%s] error en la copia completa", zone.zone_id)
                errors += 1
        # 3. subida a Object Storage
        if do_upload and par:
            for f in sorted(zdir.glob("*/*")):
                rel = f"{settings.collector_id}/{zone.zone_id}/{f.parent.name}/{f.name}"
                if rel in state["uploaded"]:
                    continue
                try:
                    upload(par, f, rel)
                    state["uploaded"].append(rel)
                    log.info("subido %s", rel)
                except Exception as e:
                    log.error("no se pudo subir %s: %s (se reintentará)", rel, e)
                    errors += 1
        elif do_upload:
            log.warning("BACKUP_PAR_URL vacía: las copias solo están en esta máquina")
        # 4. limpieza local
        limit = now - KEEP_DAILY_DAYS * DAY
        for f in (zdir / "daily").glob("*"):
            if f.stat().st_mtime < limit:
                f.unlink()
        fulls = sorted((zdir / "full").glob("*_full_*"))
        for f in fulls[:-KEEP_FULL]:
            f.unlink()
        state["done_days"] = sorted(state["done_days"])[-400:]
        state["uploaded"] = state["uploaded"][-2000:]
        tmp = state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=1))
        os.replace(tmp, state_path)
    return errors


def main(argv=None):
    p = argparse.ArgumentParser(description="Copia de seguridad del Collector AIS")
    p.add_argument("--no-upload", action="store_true", help="no subir a Object Storage")
    p.add_argument("--env", help="ruta del .env")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = load_settings(args.env)
    errors = run(settings, not args.no_upload)
    log.info("copia terminada con %d errores", errors)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
