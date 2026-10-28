# DISEÑO del sistema AIS – Puerto de València

> Versión 1 · 28/10/2026 · Estado: **propuesta, pendiente de visto bueno**
> Todas las horas del sistema están en **UTC**.

Este documento fija las decisiones que serían caras de cambiar con meses de
datos guardados: arquitectura, esquema de la base de datos, carpetas, formato de
las zonas, catálogo de segmentos y API. La compresión, el movimiento de
segmentos entre discos y la reparación de huecos se programan más tarde
(fases 6 y 8), pero el esquema ya los tiene en cuenta.

---

## 1. Arquitectura

```
 OpenSeaFeed (WebSocket) ─┐                       ┌─ Zona VALENCIA ─ current.db (+ archive/)
                          ├─► Adaptadores ─► Router ┤
 aisstream.io (WebSocket) ┘    de fuente     por    └─ Zona X ─ current.db (+ archive/)
                                             zona        (un "trabajador" por zona)
                                                              │
                          Navegador (Viewer) ◄── API HTTP ◄───┘   (lee en modo WAL)
```

**Collector**: programa sin pantalla, siempre encendido, en el servidor de Oracle.
Un único proceso hace cuatro cosas:

1. **Adaptadores de fuente.** Hay uno por proveedor (OpenSeaFeed, aisstream).
   - Cada uno abre **una sola conexión** que cubre el rectángulo envolvente de
     todas las zonas activas.
   - Si la conexión se cae, el adaptador reintenta con esperas crecientes
     (5 s, 10 s, 20 s… hasta 5 min) y deja anotada la caída.
   - Los dos adaptadores producen el mismo «mensaje normalizado», así que
     añadir o quitar una fuente no toca el resto del programa.
2. **Router.** Decide a qué zona o zonas pertenece cada mensaje, comprobando si
   el punto cae dentro del rectángulo o polígono de la zona.
3. **Trabajador por zona.** Aplica el muestreo (§4), elimina duplicados entre
   fuentes y escribe en la base de datos de su zona. Si una zona falla, las
   demás siguen.
4. **API HTTP.** Responde a las consultas del visor y de los scripts de análisis.

**Viewer**: página web (HTML + JavaScript + Leaflet) que sirve la propia API.
No hay que instalar nada: se abre en el navegador del PC.

**Por qué un solo proceso.** Con 1 GB de RAM (máquina E2.1.Micro) es lo más
ligero y sencillo de vigilar. La lectura no bloquea la escritura gracias al
modo WAL (§3.1).

### 1.1 Tecnología

| Pieza | Elección | Motivo |
|---|---|---|
| Lenguaje | Python 3.12 (el de Ubuntu 24.04) | Ya hay código en Python; es legible |
| Conexiones y API | `aiohttp` (una sola librería) | Sirve como cliente WebSocket con compresión (la exige aisstream) y como servidor HTTP |
| Base de datos | SQLite (incluida en Python) | Un archivo por zona, sin servidor aparte; se puede abrir con *DB Browser for SQLite* |
| Compresión (fase 6) | `zstandard` (.zst) | La misma que usa el tutor |
| Mapa | Leaflet + OpenStreetMap | Gratis, sin instalación |
| Arranque y reinicio | systemd | Viene con Ubuntu (§7) |

### 1.2 Identidad de los datos

- Cada máquina tiene un **CollectorId** (`VALENCIA-01`), definido en `.env`.
- Cada conjunto de datos se identifica por **CollectorId + ZoneId**. Los dos se
  guardan dentro de cada base de datos (tabla `meta`), así que un archivo
  suelto sigue diciendo de dónde viene.
- La reparación de huecos (fase 8) solo acepta datos de **otro Collector de la
  misma zona**.

---

## 2. Estructura de carpetas

### 2.1 Repositorio (código, en GitHub)

```
ais-valencia-tfg/
├── collector/            Código del Collector (paquete Python)
│   ├── main.py           Punto de arranque
│   ├── config.py         Lee .env y zones/*/zone.json
│   ├── sources/          base.py · openseafeed.py · aisstream.py
│   ├── router.py         Asigna mensajes a zonas
│   ├── geo.py            Punto en polígono, distancias
│   ├── zone_worker.py    Muestreo + escritura por zona
│   ├── storage.py        Esquema SQLite, segmentos, catálogo
│   ├── gaps.py           Detección y registro de huecos
│   └── api.py            API HTTP + sirve el Viewer
├── viewer/               index.html · app.js · style.css
├── analysis/             Cálculo de escalas (fase 7, sucesor de procesar.py)
├── deploy/               ais-collector.service · ais-backup.service/.timer · scripts
├── config-ejemplo/       zones/VALENCIA/zone.json de ejemplo
├── reference/            operators.csv (MMSI/IMO → naviera, rellenado a mano)
├── tests/
├── legacy/               captura_ais.py, procesar.py… (la versión de GitHub Actions)
├── .env.example          Plantilla SIN claves; el .env real nunca se sube
└── README.md · DISEÑO.md · ROADMAP.md · DECISIONES.md · LIMITACIONES.md
```

### 2.2 Servidor (datos, fuera del repositorio)

```
/opt/ais/                       Copia del repositorio (código)
/opt/ais/.env                   Claves y CollectorId (permisos 600: solo el usuario ais)
/srv/ais/                       ← disco de datos separado (block volume, §7.2)
├── Zones/
│   └── VALENCIA/
│       ├── zone.json           Definición de la zona (§5)
│       ├── current.db          Segmento activo (se escribe aquí)
│       ├── archive/            Segmentos cerrados: VALENCIA_2026.db, VALENCIA_2027.db.zst…
│       ├── archive-catalog.json  Catálogo de segmentos (§6)
│       └── analysis.db         Subzonas, escalas y navieras (datos derivados, recalculables)
├── logs/collector.log          Registro de texto (rotación diaria, 30 días)
└── backup-staging/             Ficheros temporales de la copia de seguridad
```

---

## 3. Esquema SQLite

### 3.1 Reglas generales

- **Modo WAL** (*write-ahead log*). El Collector escribe primero en un «diario»
  aparte y lo pasa a la base de datos poco a poco. Así el visor puede leer
  mientras se escribe, igual que puedes consultar el libro de registro de un
  puerto mientras alguien anota una nueva entrada en una hoja aparte.
- Ajustes: `synchronous=NORMAL` y `busy_timeout=5000`.
- **Escrituras por lotes** cada 5 s, para cuidar el disco. Si la máquina se
  cae, se pierden como mucho 5 s.
- **Horas en segundos UTC desde 1970** (*epoch*): números enteros que ocupan
  poco y se ordenan rápido. Para leerlas como fecha se usan las vistas `v_*`,
  que las convierten a texto `AAAA-MM-DD HH:MM:SS`.
- **Valores «no disponible» de AIS → NULL** (vacío): velocidad 102,3; rumbo 360;
  proa 511; latitud 91; longitud 181.
- Cada segmento (`current.db` o un archivo de `archive/`) es **autónomo**: lleva
  su `meta`, sus buques y sus huecos. Se puede leer sin los demás.

### 3.2 Tablas de cada segmento (`current.db` / `archive/*.db`)

| Tabla | Qué guarda (en una línea) |
|---|---|
| `meta` | Clave/valor: zone_id, collector_id, schema_version, periodo del segmento, geometría de la zona vigente |
| `source` | Lista de fuentes: 1 = openseafeed, 2 = aisstream; más adelante, `repair:VALENCIA-02`… |
| `vessel` | Ficha de cada buque visto en el periodo: MMSI, IMO, nombre, indicativo, tipo, eslora, manga, primera y última vez visto |
| `voyage_data` | Cada **cambio** de calado, destino o ETA, con su hora |
| `position` | Posiciones muestreadas (§4) |
| `coverage_minute` | Por minuto y fuente: mensajes recibidos y buques distintos (demuestra la continuidad) |
| `gap` | Huecos de datos con su motivo y estado |
| `collector_event` | Diario de sucesos: arranques, conexiones, caídas y cambios de configuración |

```sql
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE source (
  source_id INTEGER PRIMARY KEY,
  name      TEXT NOT NULL UNIQUE          -- 'openseafeed', 'aisstream', 'repair:VALENCIA-02'
);

CREATE TABLE vessel (
  mmsi        INTEGER PRIMARY KEY,
  imo         INTEGER,
  name        TEXT,
  callsign    TEXT,
  ship_type   INTEGER,                   -- código ITU (70–79 = carga)
  length_m    REAL,                      -- dimensiones A+B del AIS
  beam_m      REAL,                      -- dimensiones C+D del AIS
  ais_class   TEXT,                      -- 'A' o 'B'
  first_seen  INTEGER NOT NULL,          -- epoch UTC
  last_seen   INTEGER NOT NULL,
  last_static INTEGER                    -- última vez que llegó su mensaje estático
);

CREATE TABLE voyage_data (
  mmsi        INTEGER NOT NULL,
  ts          INTEGER NOT NULL,          -- hora en que se observó el cambio
  draught_m   REAL,
  destination TEXT,
  eta_raw     TEXT,                      -- tal cual llega: 'MM-DD HH:MM' (el AIS no da el año)
  eta_utc     INTEGER,                   -- ETA con el año deducido (la siguiente fecha futura)
  source_id   INTEGER NOT NULL,
  PRIMARY KEY (mmsi, ts)
);

CREATE TABLE position (
  mmsi       INTEGER NOT NULL,
  ts         INTEGER NOT NULL,           -- hora AIS (la que da la fuente), epoch UTC
  ts_rx      INTEGER NOT NULL,           -- hora en que la recibió nuestro Collector
  lat        REAL NOT NULL,
  lon        REAL NOT NULL,
  sog        REAL,                       -- velocidad sobre el fondo (nudos)
  cog        REAL,                       -- rumbo sobre el fondo (grados)
  heading    INTEGER,                    -- proa verdadera (grados)
  nav_status INTEGER,                    -- 0 navegando, 1 fondeado, 5 amarrado…
  msg_type   INTEGER,                    -- tipo de mensaje AIS (1, 2, 3, 18, 19, 27)
  source_id  INTEGER NOT NULL,
  reason     INTEGER NOT NULL,           -- por qué se guardó: 0 primera, 1 intervalo,
                                         -- 2 cambio de estado AIS, 3 arranca/para
  PRIMARY KEY (mmsi, ts)
) WITHOUT ROWID;
CREATE INDEX ix_position_ts ON position (ts);

CREATE TABLE coverage_minute (
  minute    INTEGER NOT NULL,            -- epoch del inicio del minuto
  source_id INTEGER NOT NULL,
  msgs      INTEGER NOT NULL,            -- mensajes recibidos (antes del muestreo)
  vessels   INTEGER NOT NULL,            -- buques distintos
  PRIMARY KEY (minute, source_id)
) WITHOUT ROWID;

CREATE TABLE gap (
  gap_id      INTEGER PRIMARY KEY,
  source_id   INTEGER,                   -- NULL = afecta a toda la zona
  start_ts    INTEGER NOT NULL,
  end_ts      INTEGER,                   -- NULL = hueco todavía abierto
  reason      TEXT NOT NULL,             -- ver lista abajo
  status      TEXT NOT NULL DEFAULT 'PENDING',  -- PENDING, REPAIRED, UNREPAIRABLE
  detected_ts INTEGER NOT NULL,
  notes       TEXT
);
CREATE INDEX ix_gap_start ON gap (start_ts);

CREATE TABLE collector_event (
  ts     INTEGER NOT NULL,
  level  TEXT NOT NULL,                  -- INFO, WARN, ERROR
  event  TEXT NOT NULL,                  -- 'start', 'source_connected', 'source_lost', 'zone_config_changed'…
  detail TEXT
);
CREATE INDEX ix_event_ts ON collector_event (ts);
```

**Por qué la clave de `position` es `(mmsi, ts)` y la tabla es `WITHOUT ROWID`.**
- Los datos quedan ordenados por buque y hora, así que reproducir la ruta de un
  buque es muy rápido.
- Ahorra un índice entero, cerca de un 25 % de espacio.
- Si llega dos veces la misma posición (por las dos fuentes o en una
  reparación), la segunda se ignora sola: `INSERT OR IGNORE`.

**Motivos de hueco (`gap.reason`):**

| Motivo | Cuándo se registra |
|---|---|
| `zone_disabled` | Alguien desactivó la zona |
| `collector_failure` | El programa o la máquina estuvieron parados. Se detecta al arrancar comparando con el último «latido» guardado cada 60 s en `meta` |
| `network_failure` | La conexión con una fuente se cayó |
| `source_silence` | La conexión sigue abierta pero no llega nada de la zona en 10 min (configurable) |
| `source_error` | La fuente rechazó la clave o la suscripción |
| `maintenance` | Parada manual anotada a propósito |
| `unknown` | Cualquier otro caso |

Un hueco de **una** fuente no es un hueco de la zona si la otra seguía
recibiendo. La API calcula los huecos de zona cruzando los de todas las fuentes.

**Inicio y cierre de un hueco:**
- Un hueco por caída de conexión empieza **cuando se detecta la caída**. Hasta
  entonces la conexión estaba viva; si estaba viva pero muda, lo cubre
  `source_silence`, que empieza en el último mensaje recibido.
- El hueco se cierra con el siguiente mensaje **fresco** de esa fuente para la
  zona. Las posiciones antiguas que OpenSeaFeed reenvía al conectar no cierran
  huecos ni cuentan en `coverage_minute`.

### 3.3 Base derivada (`analysis.db`, una por zona)

Guarda cálculos que se pueden **rehacer** a partir de las posiciones; por eso
no va dentro de los segmentos.

| Tabla | Qué guarda |
|---|---|
| `subzone` | Fondeadero, terminales y recinto como polígonos GeoJSON, con `valid_from`/`valid_to` (si se redibuja una terminal, se conserva la versión anterior) |
| `port_call` | Escalas calculadas: llegada al fondeo, fin de fondeo, atraque, desatraque, salida, espera (h), estancia (h), terminal, calado de entrada y salida, banderas de calidad y versión del método |
| `operator` | MMSI/IMO → naviera, con la fuente pública y la fecha de comprobación (se carga desde `reference/operators.csv`) |

```sql
CREATE TABLE subzone (
  subzone_id TEXT PRIMARY KEY,            -- 'FONDEO-NORTE', 'T-CSP', 'T-MSC'…
  kind       TEXT NOT NULL,               -- ANCHORAGE, TERMINAL, PORT_AREA, CHANNEL
  name       TEXT NOT NULL,
  geometry   TEXT NOT NULL,               -- GeoJSON Polygon
  valid_from INTEGER NOT NULL,
  valid_to   INTEGER,
  notes      TEXT
);
CREATE TABLE port_call (
  call_id         INTEGER PRIMARY KEY,
  mmsi            INTEGER NOT NULL,
  imo             INTEGER,
  terminal_id     TEXT,
  t_anchor_in     INTEGER,  t_anchor_out INTEGER,
  t_berth         INTEGER,  t_unberth    INTEGER,  t_exit INTEGER,
  wait_h          REAL,     stay_h       REAL,
  draught_in_m    REAL,     draught_out_m REAL,
  censored_start  INTEGER NOT NULL,       -- 1 = empezó antes de tener datos o tras un hueco
  censored_end    INTEGER NOT NULL,       -- 1 = sin final observado
  overlaps_gap    INTEGER NOT NULL,       -- 1 = algún hueco de zona dentro de la escala
  quality         TEXT,                   -- 'OK', 'DUDOSA', 'EXCLUIDA' + motivo
  method_version  TEXT NOT NULL,          -- p. ej. 'escalas-v1'
  computed_ts     INTEGER NOT NULL
);
CREATE TABLE operator (
  imo INTEGER, mmsi INTEGER, operator TEXT NOT NULL,
  source_url TEXT, checked_on TEXT,
  PRIMARY KEY (imo, mmsi)
);
```

Los parámetros del método de escalas (atracado ≤ 0,5 kn, fondeo ≤ 1,0 kn, tipos
70–79, eslora ≥ 100 m, hueco máximo 12 h, fondeo máximo sin atraque 10 días) se
heredan de `zonas.json` y se aplican **al analizar**, no al capturar. Se guarda
todo; se filtra después.

---

## 4. Muestreo (qué posiciones se guardan)

Las fuentes envían todos los mensajes AIS. Por cada buque se guarda una
posición nueva si se cumple **alguna** de estas condiciones:

| Regla | Valor por defecto | Para qué |
|---|---|---|
| Primera posición del buque (o tras reiniciar) | — | Saber que está |
| Se mueve y han pasado ≥ 60 s desde la última guardada | 60 s | Trayectorias para el visor |
| Está parado y han pasado ≥ 600 s | 10 min | Saber que sigue ahí |
| Cambia el estado de navegación AIS (p. ej. 1 fondeado → 0 navegando) | siempre (≥ 10 s desde la anterior) | Precisión en llegadas y salidas |
| Pasa de parado a en marcha o al revés | siempre (≥ 10 s desde la anterior) | Hora exacta de atraque y desatraque |

**«Parado» y «en movimiento» con histéresis** (como un termostato):
- un buque parado pasa a «en movimiento» cuando su SOG llega a **≥ 0,5 kn**, el mismo
  umbral con el que el análisis de escalas considera «atracado»;
- un buque en movimiento pasa a «parado» cuando baja de **0,3 kn**.

Así, un buque atracado cuya velocidad «tiembla» entre 0,1 y 0,45 kn no dispara
un guardado en cada mensaje. Si un evento llega menos de 10 s después del
último guardado, no se pierde: se guarda con el siguiente mensaje.

Además:
- **Se descarta** cualquier posición con hora igual o anterior a la última
  guardada de ese buque, o con más de 15 min de antigüedad. Así se evitan las
  «repeticiones» que OpenSeaFeed envía al reconectar.
- **Duplicados entre fuentes:** se guarda el primer mensaje que llega, venga de
  la fuente que venga. Su origen queda anotado en `source_id`.
- Los **mensajes estáticos** (nombre, tipo, dimensiones, calado, destino, ETA)
  actualizan `vessel`. Solo se añade una fila a `voyage_data` cuando cambia
  calado, destino o ETA.
- Se guardan **todos** los buques de la zona, clase A y B. El filtro de
  portacontenedores se aplica en el análisis.
- Todos los valores son configurables en `zone.json → sampling`.

---

## 5. Formato de `zone.json`

```json
{
  "schema_version": 1,
  "zone_id": "VALENCIA",
  "name": "Puerto de València",
  "description": "Puerto y zona de fondeo. Rectángulo heredado de la versión de GitHub Actions.",
  "created_utc": "2026-10-28T00:00:00Z",
  "active": true,
  "geometry_type": "Rectangle",
  "bbox": { "north": 39.60, "south": 39.25, "east": 0.00, "west": -0.36 },
  "geometry": {
    "type": "Polygon",
    "coordinates": [[[-0.36, 39.25], [0.00, 39.25], [0.00, 39.60], [-0.36, 39.60], [-0.36, 39.25]]]
  },
  "database": {
    "current": "current.db",
    "archive_dir": "archive",
    "catalog": "archive-catalog.json",
    "analysis": "analysis.db"
  },
  "archive_policy": {
    "period": "yearly",
    "max_segment_mb": null,
    "compress_after_days": 365,
    "compression": "zstd"
  },
  "sources": ["openseafeed", "aisstream"],
  "sampling": {
    "moving_interval_s": 60,
    "stopped_interval_s": 600,
    "stopped_speed_kn": 0.3,
    "moving_speed_kn": 0.5,
    "max_age_s": 900,
    "min_event_gap_s": 10
  },
  "silence_alert_min": 10
}
```

- **Ojo con el orden de las coordenadas.** GeoJSON usa `[longitud, latitud]`; el
  antiguo `zonas.json` usaba `[latitud, longitud]`. Para no confundirse, el
  rectángulo se guarda **también** como `bbox` con nombres (norte, sur, este,
  oeste).
- `geometry_type` puede ser `"Rectangle"` o `"Polygon"`. En los dos casos
  `geometry` es un `Polygon` GeoJSON. A las fuentes se les pide el rectángulo
  envolvente y el polígono exacto se filtra en el Collector.
- `archive_policy.period` puede valer `yearly` (por defecto), `quarterly`,
  `monthly` o `size` (usa `max_segment_mb`).
- **Desactivar** (`"active": false`) detiene la captura de esa zona. El
  histórico se conserva y se puede consultar, y se abre un hueco
  `zone_disabled` que se cierra al reactivarla.
- **Cambiar la geometría** se anota en `collector_event` como
  `zone_config_changed`, con la geometría anterior y la nueva, y se actualiza
  `meta`. Así siempre se sabe qué área se vigilaba en cada momento.
- Las subzonas (terminales y fondeaderos) **no** van aquí: están en
  `analysis.db` porque sirven para el análisis, no para la captura.

---

## 6. Segmentos y catálogo

**Segmentación:**
- Se escribe siempre en `current.db`.
- Al cambiar de periodo (por defecto, el 1 de enero a las 00:00 UTC), el
  Collector:
  1. vacía el diario WAL en la base de datos;
  2. renombra el archivo a `archive/VALENCIA_2026.db`;
  3. calcula su huella SHA-256 y cuenta sus posiciones;
  4. lo anota en el catálogo;
  5. crea un `current.db` nuevo y copia en él la tabla `vessel`.
- Una escala que cruza la frontera de periodo no es un problema: las escalas se
  calculan en `analysis.db` leyendo varios segmentos.

**Catálogo** (`archive-catalog.json`). Se escribe en un archivo temporal y luego
se renombra, para que nunca quede a medias:

```json
{
  "zone_id": "VALENCIA",
  "segments": [
    {
      "segment_id": "VALENCIA_2026",
      "collector_id": "VALENCIA-01",
      "from_utc": "2026-10-28T00:00:00Z",
      "to_utc":   "2027-01-01T00:00:00Z",
      "path": "archive/VALENCIA_2026.db",
      "status": "ONLINE",
      "compressed": false,
      "size_bytes": 1830000000,
      "positions": 18500000,
      "sha256": "9f2c…",
      "schema_version": 1,
      "created_utc": "2027-01-01T00:00:05Z"
    },
    {
      "segment_id": "CURRENT",
      "from_utc": "2027-01-01T00:00:00Z",
      "to_utc": null,
      "path": "current.db",
      "status": "ONLINE",
      "compressed": false
    }
  ]
}
```

**Estados** (`status`):

| Estado | Significado |
|---|---|
| `ONLINE` | `.db` listo para consultar |
| `ARCHIVED` | Cerrado y verificado, sin comprimir |
| `COMPRESSED` | Guardado como `.zst`; se descomprime temporalmente si una consulta lo necesita |
| `OFFLINE` | Movido a otro disco que no está montado; la API avisa de que esas fechas no están disponibles |

**Consultas que cruzan segmentos.** La API mira en el catálogo qué segmentos
cubren el intervalo pedido, los abre en **solo lectura**, consulta cada uno y
une los resultados ordenados por hora. El visor no se entera de que hay varios
archivos.

**Mover un segmento a otro disco (fase 6):**
1. Copiar.
2. Comprobar la huella SHA-256.
3. Abrir y validar.
4. Actualizar el catálogo.
5. **Solo entonces** borrar el original.

**Archivo ≠ copia de seguridad.** Archivar es ordenar los datos dentro del
servidor. La copia de seguridad (§7.4) es tener los datos **fuera** de él.

---

## 7. Servidor, servicio y seguridad

### 7.1 Máquina
- **Cuenta:** Oracle Cloud con pago por uso (decidido el 28/10/2026), región
  Madrid si está disponible.
- **Máquina:** VM.Standard.E2.1.Micro (1 GB de RAM) con Ubuntu 24.04. Si se
  consigue una Ampere A1, se usa esa.
- **Memoria de reserva:** archivo *swap* de 2 GB. Es disco que hace de memoria
  extra si alguna vez falta RAM.

### 7.2 Discos
- **Disco de arranque:** 50 GB (sistema y código).
- **Disco de datos aparte:** *block volume* de 100 GB montado en `/srv/ais`.
  Si hubiera que recrear la máquina, el disco de datos se desconecta y se
  conecta a la nueva sin copiar nada.
- **Total:** 150 de los 200 GB gratuitos.

### 7.3 Servicio (systemd)
**systemd** es el «encargado de turno» de Linux: arranca los programas al
encender la máquina y los vuelve a lanzar si se caen.

```ini
# deploy/ais-collector.service (borrador)
[Unit]
Description=Collector AIS (VALENCIA-01)
After=network-online.target
Wants=network-online.target

[Service]
User=ais
WorkingDirectory=/opt/ais
EnvironmentFile=/opt/ais/.env
ExecStart=/opt/ais/venv/bin/python -m collector.main
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Cada caída o reconexión queda anotada en tres sitios: `collector_event`,
`logs/collector.log` y el diario del sistema (`journalctl -u ais-collector`).

### 7.4 Copias de seguridad (fuera de la máquina)

Un temporizador de systemd (`ais-backup.timer`) se ejecuta cada noche a las
03:30 UTC y hace esto:
1. **Copia diaria incremental:** exporta las filas del día anterior (posiciones,
   buques, huecos y sucesos) a un pequeño `.db` comprimido con zstd, de unos
   1–2 MB.
2. **Copia completa semanal** (domingos): `current.db`, copiado con la función
   de copia en caliente de SQLite y comprimido, más `zone.json`, el catálogo y
   `analysis.db`.
3. Sube los archivos a **Oracle Object Storage**. En cuenta de pago son gratis
   10 GB estándar + 10 GB de acceso infrecuente + 10 GB de archivo, y 50.000
   operaciones al mes. Usamos menos de 100 operaciones al mes.
4. Conserva todas las copias diarias y las 4 últimas completas. Cálculo:
   unos 0,7 GB al año de diarias y unos 2 GB de completas, dentro de los 10 GB.
5. Script `deploy/descargar_copias.ps1` para traer de vez en cuando las copias
   a tu PC con un solo comando: es una segunda copia en otro sitio.

Una copia de seguridad solo vale si se puede restaurar. En la fase 3 haremos
una prueba de restauración real.

### 7.5 Acceso desde tu PC: túnel SSH (recomendado) frente a HTTPS con token

- **SSH** es la forma segura de manejar el servidor a distancia. Tu PC guarda
  una **llave privada** (como la llave de casa) y el servidor solo abre a quien
  la tenga. No se usan contraseñas.
- Un **puerto** es la «puerta numerada» de un servicio en la máquina: 22 es SSH
  y 443 es HTTPS.

| | Túnel SSH | HTTPS con token |
|---|---|---|
| Qué es | La API solo escucha **dentro** del servidor (127.0.0.1:5080). Con la llave SSH creas un «pasadizo» privado desde tu PC | La API se publica en Internet en el puerto 443 con certificado, y pide un token en cada petición |
| Puertos abiertos | **Solo el 22** | 22 y 443 |
| Requisitos extra | Ninguno | Un dominio, un certificado y un servidor web delante (Caddy o nginx) |
| Exposición | Nula: nadie de fuera ve la API | Visible para todo Internet; un fallo de la API sería explotable |
| Comodidad | Ejecutar un comando antes de abrir el visor | Abrir una URL desde cualquier sitio, incluido el móvil |
| Compartir con el tutor | Necesita tu llave (no recomendable) | Basta darle un token |

**Recomendación: túnel SSH.** Es lo más sencillo y seguro. El comando sería:

```
ssh -L 5080:127.0.0.1:5080 ubuntu@IP_DEL_SERVIDOR
```

y luego se abre `http://localhost:5080` en el navegador. Si más adelante el
tutor necesita acceso directo, se añade HTTPS con token sin cambiar la API.

**El token se exige igualmente** en todas las llamadas a la API, aunque se use
el túnel. Un **token** es una contraseña larga para programas: se envía en la
cabecera `Authorization: Bearer <token>`. Es una segunda cerradura por si algún
día se abre el puerto.

### 7.6 Medidas de seguridad
- **SSH:** solo con llave. El acceso con contraseña ya viene desactivado en
  Oracle y lo comprobamos.
- **Cortafuegos en dos capas, solo con el puerto 22 de entrada:**
  - la *security list* de Oracle;
  - `iptables` en Ubuntu. Ojo: las imágenes de Oracle traen reglas propias y
    no conviene usar `ufw` encima.
- **Programa sin privilegios:** el Collector se ejecuta con un usuario `ais`
  sin permisos de administrador.
- **Claves:** `.env` con permisos 600 (solo el usuario `ais` puede leerlo) y
  `.gitignore` con `.env` y `clave_api.txt`. En GitHub solo hay `.env.example`
  sin claves.
- **Actualizaciones:** se instalan solas (`unattended-upgrades`).
- **Gasto:** alerta de presupuesto en 1 €, cuotas por compartimento y solo
  recursos con la etiqueta «Always Free-eligible».

**Contenido de `.env.example`:**

```
COLLECTOR_ID=VALENCIA-01
DATA_DIR=/srv/ais
API_HOST=127.0.0.1
API_PORT=5080
API_TOKEN=cambia-esto-por-un-token-largo
AISSTREAM_API_KEY=
OPENSEAFEED_API_KEY=          # opcional: sin clave se usa el nivel libre
```

---

## 8. API HTTP

- **Base:** `http://127.0.0.1:5080`.
- **Token obligatorio** en todas las rutas (cabecera `Authorization: Bearer …`).
- **Horas:** en las peticiones se aceptan ISO 8601 en UTC
  (`2026-10-28T12:00:00Z`) o epoch; en las respuestas, ISO con `Z`.

| Método y ruta | Devuelve | Fase |
|---|---|---|
| `GET /api/health` | Estado: CollectorId, versión, tiempo encendido, estado de cada fuente (conectada y antigüedad del último mensaje), espacio libre en disco | 2 |
| `GET /api/zone?zone=VALENCIA` | Definición de la zona + estadísticas (buques ahora, posiciones hoy, tamaño, huecos pendientes) | 2 |
| `GET /api/archive/range?zone=&from=&to=[&mmsi=][&bbox=][&limit=]` | Posiciones del intervalo, cruzando segmentos | 2 |
| `GET /api/zones` | Lista de zonas (activas e inactivas) | 2 |
| `GET /api/gaps?zone=&from=&to=[&status=]` | Huecos por fuente y huecos de zona calculados | 2 |
| `GET /api/coverage?zone=&from=&to=&bucket=hour` | Mensajes y buques por intervalo y fuente | 2 |
| `GET /api/vessels?zone=&at=` | Última posición conocida de cada buque en el instante `at` (la «foto» del mapa) | 4 |
| `GET /api/vessel/{mmsi}?zone=` | Ficha del buque + historial de calado, destino y ETA | 4 |
| `GET /api/track/{mmsi}?zone=&from=&to=` | Trayectoria para reproducir la ruta | 4 |
| `POST /api/zones` · `PUT /api/zones/{id}` · `POST /api/zones/{id}/activate` · `…/deactivate` | Crear, editar, activar y desactivar zonas | 5 |
| `GET /api/catalog?zone=` | Catálogo de segmentos | 6 |
| `GET /api/port_calls?zone=&from=&to=[&format=csv]` | Escalas calculadas (también en CSV para Excel) | 7 |
| `GET /api/export?zone=&from=&to=` · `POST /api/import` | Intercambio de datos entre Collectors de la misma zona | 8 |

Ejemplo de `GET /api/health`:

```json
{ "status": "ok", "collector_id": "VALENCIA-01", "version": "0.1.0",
  "uptime_s": 86400, "disk_free_gb": 92.4,
  "sources": { "openseafeed": { "connected": true, "last_msg_age_s": 2 },
               "aisstream":   { "connected": true, "last_msg_age_s": 1 } },
  "zones": { "VALENCIA": { "active": true, "open_gaps": 0 } } }
```

Límites de protección:
- `archive/range` devuelve como máximo 50.000 filas por petición y se pagina
  con `&after=`.
- Rangos de más de 31 días solo para un MMSI concreto.

---

## 9. Estimación de volumen

**Datos medidos (28/10/2026):**
- OpenSeaFeed envió unas 30 posiciones por minuto en tiempo real dentro del
  rectángulo (prueba de 3 min).
- Su mapa de cobertura muestra 520 buques distintos en 7 días en la celda del
  puerto.

**Supuestos (a confirmar en la Fase 2 con las dos fuentes y 24 h de datos):**
unos 150 buques presentes a la vez; el 80 % parados (atracados, fondeados o
amarrados en la marina) y el 20 % en movimiento.

| Concepto | Cálculo | Filas/día |
|---|---|---|
| Parados | 120 buques × 144 (1 cada 10 min) | 17.300 |
| En movimiento | 30 buques × 1.440 (1 por minuto, como mucho) | 43.200 |
| Cambios de estado y arranques/paradas | estimación | ~2.000 |
| **Total posiciones** | | **~62.000** |

| Tabla | Bytes por fila (con índices) | MB/día |
|---|---|---|
| `position` | ~95 | ~5,9 |
| `coverage_minute` | 1.440 min × 2 fuentes × ~30 B | ~0,1 |
| `vessel` + `voyage_data` + resto | | < 0,1 |
| **Total** | | **≈ 6 MB/día** |

**≈ 6 MB/día ≈ 2,2 GB/año**, con un margen razonable de 3–8 MB/día
(1–3 GB/año).
- Hasta abril de 2027 (unos 6 meses) serían unos 1,1 GB.
- Un segmento anual comprimido con zstd ocuparía unos 0,4–0,6 GB (compresión
  de 4–5 veces, a confirmar).
- Sin muestreo, guardando todos los mensajes, serían unos 10 veces más.

---

## 10. Riesgos de diseño y cómo se cubren

| Riesgo | Medida |
|---|---|
| OpenSeaFeed desaparece o pierde la cobertura de València | Fuente doble desde el primer día; `coverage_minute` lo hace visible |
| Oracle recupera la máquina por inactividad | Cuenta de pago; datos en un disco separado; copias diarias fuera |
| Se llena el disco | `health` informa del espacio libre; segmentación anual; compresión (fase 6) |
| Cambio de esquema con datos ya guardados | `meta.schema_version` + scripts de migración numerados |
| Reloj del servidor desajustado | Ubuntu sincroniza la hora con NTP; además se guarda `ts_rx` para comparar con la hora de la fuente |
| Repeticiones de posiciones antiguas al reconectar | Regla de antigüedad máxima (15 min) y de «más nueva que la última» |
