# -*- coding: utf-8 -*-
"""
Almacenamiento SQLite de una zona (DISEÑO.md §3 y §6).

Un ZoneStore escribe en Zones/<ZONA>/current.db. Las escrituras se acumulan en
memoria y se guardan juntas cada pocos segundos (flush), en una sola
transacción: menos trabajo para el disco y nunca quedan datos a medias.
Los huecos (gap) y sucesos importantes se escriben al momento.
"""
import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from . import SCHEMA_VERSION, VERSION

log = logging.getLogger("collector.storage")

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS source (
  source_id INTEGER PRIMARY KEY,
  name      TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS vessel (
  mmsi        INTEGER PRIMARY KEY,
  imo         INTEGER,
  name        TEXT,
  callsign    TEXT,
  ship_type   INTEGER,
  length_m    REAL,
  beam_m      REAL,
  ais_class   TEXT,
  first_seen  INTEGER NOT NULL,
  last_seen   INTEGER NOT NULL,
  last_static INTEGER
);

CREATE TABLE IF NOT EXISTS voyage_data (
  mmsi        INTEGER NOT NULL,
  ts          INTEGER NOT NULL,
  draught_m   REAL,
  destination TEXT,
  eta_raw     TEXT,
  eta_utc     INTEGER,
  source_id   INTEGER NOT NULL,
  PRIMARY KEY (mmsi, ts)
);

CREATE TABLE IF NOT EXISTS position (
  mmsi       INTEGER NOT NULL,
  ts         INTEGER NOT NULL,
  ts_rx      INTEGER NOT NULL,
  lat        REAL NOT NULL,
  lon        REAL NOT NULL,
  sog        REAL,
  cog        REAL,
  heading    INTEGER,
  nav_status INTEGER,
  msg_type   INTEGER,
  source_id  INTEGER NOT NULL,
  reason     INTEGER NOT NULL,
  PRIMARY KEY (mmsi, ts)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_position_ts ON position (ts);

CREATE TABLE IF NOT EXISTS coverage_minute (
  minute    INTEGER NOT NULL,
  source_id INTEGER NOT NULL,
  msgs      INTEGER NOT NULL,
  vessels   INTEGER NOT NULL,
  PRIMARY KEY (minute, source_id)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS gap (
  gap_id      INTEGER PRIMARY KEY,
  source_id   INTEGER,
  start_ts    INTEGER NOT NULL,
  end_ts      INTEGER,
  reason      TEXT NOT NULL,
  status      TEXT NOT NULL DEFAULT 'PENDING',
  detected_ts INTEGER NOT NULL,
  notes       TEXT
);
CREATE INDEX IF NOT EXISTS ix_gap_start ON gap (start_ts);

CREATE TABLE IF NOT EXISTS collector_event (
  ts     INTEGER NOT NULL,
  level  TEXT NOT NULL,
  event  TEXT NOT NULL,
  detail TEXT
);
CREATE INDEX IF NOT EXISTS ix_event_ts ON collector_event (ts);

-- Vistas con las horas en texto legible (UTC), para abrir la base con DB Browser.
CREATE VIEW IF NOT EXISTS v_position AS
  SELECT p.mmsi, v.name, datetime(p.ts, 'unixepoch') AS hora_utc, p.lat, p.lon, p.sog, p.cog,
         p.heading, p.nav_status, s.name AS fuente, p.reason, p.ts_rx - p.ts AS retraso_s
  FROM position p LEFT JOIN vessel v USING (mmsi) LEFT JOIN source s USING (source_id);
CREATE VIEW IF NOT EXISTS v_gap AS
  SELECT g.gap_id, COALESCE(s.name, '(toda la zona)') AS fuente,
         datetime(g.start_ts, 'unixepoch') AS inicio_utc, datetime(g.end_ts, 'unixepoch') AS fin_utc,
         ROUND((COALESCE(g.end_ts, strftime('%s', 'now')) - g.start_ts) / 60.0, 1) AS minutos,
         g.reason, g.status, g.notes
  FROM gap g LEFT JOIN source s USING (source_id);
CREATE VIEW IF NOT EXISTS v_event AS
  SELECT datetime(ts, 'unixepoch') AS hora_utc, level, event, detail FROM collector_event;
"""

# Fuentes con número fijo, para que el mismo número signifique lo mismo en todas las bases.
FIXED_SOURCES = {"openseafeed": 1, "aisstream": 2}

# El latido (heartbeat_ts) se guarda en cada volcado, cada 5 s. Tras una caída, si el último
# latido tiene más de 15 s (3 volcados), se registra el hueco; tras una parada ordenada, siempre.
HEARTBEAT_GAP_S = 15
MAX_PENDING_ROWS = 2_000_000   # si no se puede escribir y se acumula esto en memoria, se para el proceso

# Campos de la ficha del buque: un dato más reciente sustituye al anterior; uno más antiguo
# (mensaje retrasado) solo rellena lo que esté vacío.
STATIC_FIELDS = ("imo", "name", "callsign", "ship_type", "length_m", "beam_m")
_STATIC_SET = ",\n".join(
    f"  {f} = CASE WHEN excluded.last_static >= COALESCE(vessel.last_static, 0) "
    f"THEN COALESCE(excluded.{f}, vessel.{f}) ELSE COALESCE(vessel.{f}, excluded.{f}) END"
    for f in STATIC_FIELDS)
SQL_VESSEL_STATIC = f"""
INSERT INTO vessel(mmsi, imo, name, callsign, ship_type, length_m, beam_m,
                   ais_class, first_seen, last_seen, last_static)
VALUES (?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(mmsi) DO UPDATE SET
{_STATIC_SET},
  ais_class = COALESCE(vessel.ais_class, excluded.ais_class),
  first_seen = MIN(vessel.first_seen, excluded.first_seen),
  last_seen = MAX(vessel.last_seen, excluded.last_seen),
  last_static = MAX(COALESCE(vessel.last_static, 0), excluded.last_static)"""
# Las pistas de MetaData (nombre, IMO, tipo) solo rellenan campos vacíos.
SQL_VESSEL_SEEN = """
INSERT INTO vessel(mmsi, imo, name, ship_type, ais_class, first_seen, last_seen)
VALUES (?,?,?,?,?,?,?)
ON CONFLICT(mmsi) DO UPDATE SET
  imo = COALESCE(vessel.imo, excluded.imo),
  name = COALESCE(vessel.name, excluded.name),
  ship_type = COALESCE(vessel.ship_type, excluded.ship_type),
  ais_class = COALESCE(vessel.ais_class, excluded.ais_class),
  first_seen = MIN(vessel.first_seen, excluded.first_seen),
  last_seen = MAX(vessel.last_seen, excluded.last_seen)"""
SQL_POSITION = ("INSERT OR IGNORE INTO position(mmsi, ts, ts_rx, lat, lon, sog, cog, heading, "
                "nav_status, msg_type, source_id, reason) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)")
SQL_VOYAGE = ("INSERT OR IGNORE INTO voyage_data(mmsi, ts, draught_m, destination, eta_raw, eta_utc, "
              "source_id) VALUES (?,?,?,?,?,?,?)")
SQL_COVERAGE = """
INSERT INTO coverage_minute(minute, source_id, msgs, vessels) VALUES (?,?,?,?)
ON CONFLICT(minute, source_id) DO UPDATE SET
  msgs = msgs + excluded.msgs, vessels = MAX(vessels, excluded.vessels)"""
SQL_EVENT = "INSERT INTO collector_event(ts, level, event, detail) VALUES (?,?,?,?)"


def now_ts():
    return int(time.time())


def iso(ts):
    if ts is None:
        return None
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(path, readonly=False):
    """Abre una base SQLite con los ajustes del proyecto.

    La conexión de escritura del Collector espera como mucho 0,5 s si la base está bloqueada
    (por ejemplo, abierta con cambios sin guardar en DB Browser): así no frena la recepción de
    mensajes, y lo que no se pudo escribir se reintenta en el siguiente volcado.
    """
    if readonly:
        conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
        conn.execute("PRAGMA busy_timeout=5000")
    else:
        conn = sqlite3.connect(str(path), timeout=0.5)
        conn.execute("PRAGMA busy_timeout=500")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    return conn


# Errores que significan "esta fila concreta no se puede guardar". Cualquier otro error
# (base bloqueada, disco lleno, base dañada...) es un problema del almacenamiento y el lote
# entero se reintenta más tarde, sin perder nada.
POISON_ERRORS = (sqlite3.IntegrityError, sqlite3.DataError, sqlite3.ProgrammingError,
                 sqlite3.InterfaceError, OverflowError, ValueError, TypeError)


def write_json_atomic(path, data):
    """Escribe en un archivo temporal y lo renombra: nunca queda un JSON a medias."""
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


class ZoneStore:
    def __init__(self, zone, collector_id):
        self.zone = zone
        self.collector_id = collector_id
        self.dir = Path(zone.zone_dir)
        self.db_path = self.dir / zone.database["current"]
        self.catalog_path = self.dir / zone.database["catalog"]
        self.conn = None
        self.source_ids = {}
        # buffers que se vuelcan en flush()
        self._positions = []
        self._seen = {}       # mmsi -> [first_ts, last_ts, ais_class, hint_name, hint_imo, hint_type]
        self._static = []     # una fila por mensaje estático (se aplican en orden de hora)
        self._voyages = []
        self._events = []
        self._coverage = []   # (minute, source_id, msgs, vessels)
        self._retry = []      # lotes que no se pudieron escribir: [(sql, filas), ...]
        self.voyage_cache = {}   # mmsi -> (calado, destino, eta_raw, ts del último cambio)
        self.flush_failures = 0  # volcados fallidos seguidos

    # ------------------------------------------------------------ apertura
    def open(self):
        (self.dir / self.zone.database["archive_dir"]).mkdir(parents=True, exist_ok=True)
        new_db = not self.db_path.exists()
        self.conn = connect(self.db_path)
        self.conn.executescript(SCHEMA)
        with self.conn:
            for name, sid in FIXED_SOURCES.items():
                self.conn.execute("INSERT OR IGNORE INTO source(source_id, name) VALUES (?, ?)", (sid, name))
            self.source_ids = dict(self.conn.execute("SELECT name, source_id FROM source"))
            self._check_identity(new_db)
        self._ensure_catalog()
        self._load_voyage_cache()
        return self

    def _check_identity(self, new_db):
        """La base debe pertenecer a esta zona y a este Collector (identidad CollectorId + ZoneId)."""
        meta = self.get_all_meta()
        if new_db or "zone_id" not in meta:
            created = now_ts()
            for k, v in {"zone_id": self.zone.zone_id, "collector_id": self.collector_id,
                         "schema_version": str(SCHEMA_VERSION), "segment_id": "CURRENT",
                         "period_from": str(created), "created_ts": str(created),
                         "created_by_version": VERSION}.items():
                self.set_meta(k, v, commit=False)
            return
        if meta["zone_id"] != self.zone.zone_id:
            raise RuntimeError(f"{self.db_path} pertenece a la zona {meta['zone_id']}, no a {self.zone.zone_id}.")
        if meta.get("collector_id") != self.collector_id:
            raise RuntimeError(f"{self.db_path} es del Collector {meta.get('collector_id')}, "
                               f"pero este es {self.collector_id}. No se mezclan datos de Collectors.")
        if int(meta.get("schema_version", 0)) != SCHEMA_VERSION:
            raise RuntimeError(f"{self.db_path}: versión de esquema {meta.get('schema_version')} "
                               f"distinta de la del programa ({SCHEMA_VERSION}); hace falta migrar.")

    def _ensure_catalog(self):
        """Crea el catálogo de segmentos con el segmento activo si aún no existe."""
        if self.catalog_path.exists():
            return
        write_json_atomic(self.catalog_path, {
            "zone_id": self.zone.zone_id,
            "segments": [{
                "segment_id": "CURRENT", "collector_id": self.collector_id,
                "from_utc": iso(int(self.get_meta("period_from") or now_ts())), "to_utc": None,
                "path": self.zone.database["current"], "status": "ONLINE", "compressed": False,
                "schema_version": SCHEMA_VERSION,
            }]})

    def _load_voyage_cache(self):
        """Último calado/destino/ETA de cada buque, para guardar solo los cambios."""
        rows = self.conn.execute("""
            SELECT v.mmsi, v.draught_m, v.destination, v.eta_raw, v.ts FROM voyage_data v
            JOIN (SELECT mmsi, MAX(ts) AS ts FROM voyage_data GROUP BY mmsi) u USING (mmsi, ts)""")
        self.voyage_cache = {r[0]: (r[1], r[2], r[3], r[4]) for r in rows}

    # ------------------------------------------------------------ meta
    def get_meta(self, key):
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def get_all_meta(self):
        return dict(self.conn.execute("SELECT key, value FROM meta"))

    def set_meta(self, key, value, commit=True):
        self.conn.execute("INSERT INTO meta(key, value) VALUES (?, ?) "
                          "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))
        if commit:
            self.conn.commit()

    # ------------------------------------------------------------ arranque y parada
    def startup(self, now=None):
        """Al arrancar: cierra huecos que quedaron abiertos y registra el tiempo parado."""
        now = now or now_ts()
        meta = self.get_all_meta()
        hb = int(meta["heartbeat_ts"]) if meta.get("heartbeat_ts") else None
        clean = meta.get("clean_shutdown") == "1"
        disabled_was_open = False
        with self.conn:
            for gap_id, reason in self.conn.execute(
                    "SELECT gap_id, reason FROM gap WHERE end_ts IS NULL").fetchall():
                if reason == "zone_disabled":
                    if self.zone.active:      # la zona se ha reactivado: el hueco termina ahora
                        self.conn.execute("UPDATE gap SET end_ts = ? WHERE gap_id = ?", (now, gap_id))
                    disabled_was_open = True
                else:   # el Collector se paró con el hueco abierto (el fin nunca antes del inicio)
                    self.conn.execute("UPDATE gap SET end_ts = MAX(start_ts, ?) WHERE gap_id = ?",
                                      (hb or now, gap_id))
            threshold = 0 if clean else HEARTBEAT_GAP_S
            if hb is not None and now - hb > threshold and not disabled_was_open:
                reason = "maintenance" if clean else "collector_failure"
                note = ("parada ordenada del Collector" if clean
                        else "el Collector o la máquina estuvieron parados sin cierre ordenado")
                self.conn.execute(
                    "INSERT INTO gap(source_id, start_ts, end_ts, reason, detected_ts, notes) "
                    "VALUES (NULL, ?, ?, ?, ?, ?)", (hb, now, reason, now, note))
                log.warning("[%s] hueco %s de %.1f min detectado al arrancar",
                            self.zone.zone_id, reason, (now - hb) / 60)
            if not self.zone.active and not disabled_was_open:
                # empieza ahora: el tiempo parado anterior ya lo cubre el hueco de arriba
                self.conn.execute(
                    "INSERT INTO gap(source_id, start_ts, end_ts, reason, detected_ts, notes) "
                    "VALUES (NULL, ?, NULL, 'zone_disabled', ?, 'zona desactivada en zone.json')",
                    (now, now))
            self.set_meta("clean_shutdown", "0", commit=False)
            self.set_meta("heartbeat_ts", now, commit=False)
            fp = self.zone.geometry_fingerprint()
            old_fp = meta.get("zone_geometry")
            if old_fp != fp:
                if old_fp is not None:
                    self._insert_event(now, "WARN", "zone_config_changed",
                                       json.dumps({"antes": json.loads(old_fp), "ahora": json.loads(fp)}))
                self.set_meta("zone_geometry", fp, commit=False)
            self._insert_event(now, "INFO", "start",
                               f"version={VERSION} collector={self.collector_id} activa={self.zone.active}")

    def shutdown(self):
        """Parada ordenada: vuelca lo pendiente y marca el cierre como limpio."""
        if self.conn is None:
            return
        try:
            self.add_event("INFO", "stop", "parada ordenada")
            for attempt in range(5):           # la base puede estar bloqueada un momento
                try:
                    self.flush()
                    break
                except Exception:
                    if attempt == 4:
                        log.critical("[%s] no se pudo guardar al parar: se pierden %d filas",
                                     self.zone.zone_id, self.pending())
                        raise
                    time.sleep(1)
            self.set_meta("clean_shutdown", "1", commit=False)
            self.set_meta("heartbeat_ts", now_ts(), commit=False)
            self.conn.commit()
        finally:
            self.conn.close()
            self.conn = None

    # ------------------------------------------------------------ huecos (se escriben al momento)
    def open_gap(self, source_id, start_ts, reason, notes=None):
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO gap(source_id, start_ts, end_ts, reason, detected_ts, notes) "
                "VALUES (?, ?, NULL, ?, ?, ?)", (source_id, int(start_ts), reason, now_ts(), notes))
        return cur.lastrowid

    def close_gap(self, gap_id, end_ts):
        with self.conn:
            self.conn.execute("UPDATE gap SET end_ts = MAX(start_ts, ?) WHERE gap_id = ? AND end_ts IS NULL",
                              (int(end_ts), gap_id))

    def insert_closed_gap(self, source_id, start_ts, end_ts, reason, notes=None):
        """Hueco que se abrió y se cerró entre dos comprobaciones."""
        with self.conn:
            self.conn.execute(
                "INSERT INTO gap(source_id, start_ts, end_ts, reason, detected_ts, notes) "
                "VALUES (?, ?, MAX(?, ?), ?, ?, ?)",
                (source_id, int(start_ts), int(start_ts), int(end_ts), reason, now_ts(), notes))

    # ------------------------------------------------------------ buffers
    def add_position(self, msg, source_id, reason):
        self._positions.append((msg.mmsi, msg.ts, msg.ts_rx, msg.lat, msg.lon, msg.sog, msg.cog,
                                msg.heading, msg.nav_status, msg.msg_id, source_id, reason))
        self.mark_seen(msg)

    def mark_seen(self, msg):
        s = self._seen.get(msg.mmsi)
        if s is None:
            self._seen[msg.mmsi] = [msg.ts, msg.ts, msg.ais_class, msg.hint_name, msg.hint_imo, msg.hint_ship_type]
        else:
            s[0] = min(s[0], msg.ts)
            s[1] = max(s[1], msg.ts)
            s[3] = s[3] or msg.hint_name
            s[4] = s[4] or msg.hint_imo
            s[5] = s[5] or msg.hint_ship_type

    def add_static(self, msg):
        """Una fila por mensaje: al volcar se aplican por orden de hora y el SQL decide qué
        campos sustituir (más nuevo) o solo rellenar (más antiguo)."""
        self._static.append((msg.mmsi,) + tuple(getattr(msg, f) for f in STATIC_FIELDS) +
                            (msg.ais_class, msg.ts, msg.ts, msg.ts))

    def add_voyage(self, msg, source_id):
        """Guarda calado/destino/ETA cuando cambian, tal como llegan (None = 'no disponible').

        No se mezclan valores de mensajes distintos: cada fila es lo que el buque declaraba en
        ese momento. Un mensaje más antiguo que el último cambio guardado se ignora.
        """
        if msg.draught_m is None and msg.destination is None and msg.eta_raw is None:
            return False
        new = (msg.draught_m, msg.destination, msg.eta_raw)
        old = self.voyage_cache.get(msg.mmsi)
        if old is not None and (old[:3] == new or msg.ts <= old[3]):
            return False
        self.voyage_cache[msg.mmsi] = new + (msg.ts,)
        self._voyages.append((msg.mmsi, msg.ts, new[0], new[1], new[2], msg.eta_utc, source_id))
        return True

    def add_coverage(self, minute, source_id, msgs, vessels):
        self._coverage.append((minute, source_id, msgs, vessels))

    def add_event(self, level, event, detail=None):
        self._events.append((now_ts(), level, event, detail))

    def _insert_event(self, ts, level, event, detail):
        self.conn.execute("INSERT INTO collector_event(ts, level, event, detail) VALUES (?, ?, ?, ?)",
                          (ts, level, event, detail))

    def pending(self):
        retry = sum(len(rows) for _, rows in self._retry)
        return retry + len(self._positions) + len(self._voyages) + len(self._events) + len(self._seen)

    # ------------------------------------------------------------ volcado
    def flush(self, now=None):
        """Escribe todo lo acumulado en una única transacción y actualiza el latido."""
        now = now or now_ts()
        positions, self._positions = self._positions, []
        seen, self._seen = self._seen, {}
        static, self._static = self._static, []
        voyages, self._voyages = self._voyages, []
        events, self._events = self._events, []
        coverage, self._coverage = self._coverage, []
        batch = self._retry + [
            (SQL_POSITION, positions),
            (SQL_VESSEL_STATIC, sorted(static, key=lambda r: r[-1])),
            (SQL_VESSEL_SEEN, [(m, himo, hname, htype, cls, first, last)
                               for m, (first, last, cls, hname, himo, htype) in seen.items()]),
            (SQL_VOYAGE, voyages),
            (SQL_COVERAGE, coverage),
            (SQL_EVENT, events),
        ]
        self._retry = []
        batch = [(sql, rows) for sql, rows in batch if rows]
        try:
            try:
                with self.conn:
                    for sql, rows in batch:
                        self.conn.executemany(sql, rows)
                    self.set_meta("heartbeat_ts", now, commit=False)
            except POISON_ERRORS:
                # Algún valor imposible de guardar: se escriben las filas una a una y solo se
                # descartan las que fallan, para que una fila "envenenada" no bloquee las demás.
                log.exception("[%s] lote con datos no válidos: se guarda fila a fila", self.zone.zone_id)
                bad = self._write_row_by_row(batch, now)
                log.error("[%s] %d filas descartadas por datos no válidos", self.zone.zone_id, bad)
        except Exception:
            # Fallo del almacenamiento (base bloqueada, disco lleno, base dañada...): el lote
            # entero se reintenta en el próximo volcado. Como todo va en una transacción que se
            # deshace al fallar, el reintento no duplica nada.
            self._retry = batch
            self.flush_failures += 1
            raise
        self.flush_failures = 0
        return len(positions)

    def _write_row_by_row(self, batch, now):
        bad = 0
        with self.conn:
            for sql, rows in batch:
                for row in rows:
                    try:
                        self.conn.execute(sql, row)
                    except POISON_ERRORS:
                        bad += 1          # cualquier otro error sale y el lote entero se reintenta
            self._insert_event(now, "ERROR", "bad_rows", f"{bad} filas descartadas por datos no válidos")
            self.set_meta("heartbeat_ts", now, commit=False)
        return bad
