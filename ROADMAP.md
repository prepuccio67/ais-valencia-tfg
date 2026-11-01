# Hoja de ruta

Última actualización: 01/11/2026

## ✅ Hecho
- **Versión 0 (GitHub Actions):**
  - captura en CSV cada 30 min;
  - cálculo provisional de escalas;
  - cuadro de mando en GitHub Pages.
  - **Retirada el 01/11/2026**: workflow desactivado en GitHub y código y
    CSV movidos a `legacy/`. La web de GitHub Pages se mantiene congelada.
- **Fase 0. Verificación** (28/10/2026):
  - OpenSeaFeed: gratis, WebSocket compatible con aisstream, datos con licencia
    CC BY 4.0 y cobertura en València comprobada en directo.
  - Oracle Always Free: límites y riesgo de recuperación por inactividad
    revisados. Decisión: cuenta de pago por uso.

- **Fase 1. Diseño** (aprobado el 28/10/2026): DISEÑO.md.
- **Fase 2. Collector mínimo** (28/10/2026):
  - fuente doble (OpenSeaFeed + aisstream), muestreo, SQLite en modo WAL,
    registro de huecos con motivo y API con token;
  - 56 tests automáticos;
  - revisión adversarial en dos rondas;
  - prueba local de 30 min sin errores: 445 posiciones de 184 buques.

- **Fase 3. Despliegue en Oracle** (29/10/2026):
  - Collector `VALENCIA-01` **capturando 24/7 desde las 19:33 UTC**, en una
    máquina Ampere A1 en Madrid;
  - datos en un disco de 100 GB aparte; servicio systemd; SSH solo con llave;
    cortafuegos con solo el puerto 22;
  - copias de seguridad diarias verificadas, subidas a Oracle Object Storage
    (bucket privado `ais-backups`, con un enlace de solo escritura) y
    descargables al PC;
  - pruebas superadas: reinicio de la máquina, corte de red y restauración de
    una copia.

- **Fase 4. Visor web** (29/10/2026):
  - mapa OpenStreetMap con iconos orientados y coloreados por velocidad;
  - lista con buscador y filtro de carga ≥ 100 m, ficha del buque y contadores;
  - línea temporal con cobertura y huecos, aviso de huecos y estado de las
    fuentes;
  - rutas de 24 h, 3 días o 7 días con reproducción;
  - desplegado en el servidor y probado por el túnel SSH con datos reales.
  - Pendiente de la hoja de ruta del tutor: «permanencias» y «fundido
    temporal» (estelas). Se harán junto con la Fase 7, cuando existan las
    subzonas.

- **Fase 5. Zonas configurables** (29/10/2026):
  - varias zonas en el mismo Collector;
  - editor en el visor (rectángulo, lista de puntos, GeoJSON y dibujo con
    ratón, con vértices arrastrables);
  - activar y desactivar conservando el histórico;
  - recarga ordenada en caliente y cambios registrados;
  - 75 tests; desplegado en el servidor.

- **Fase 6. Archivo de segmentos** (01/11/2026):
  - cierre automático del segmento al cambiar de periodo (por defecto, el
    1 de enero), verificado con SHA-256 y recuperable si se corta a mitad;
  - catálogo, consultas que cruzan segmentos y `/api/catalog`;
  - compresión `.zst` (×3,2 con datos reales) y movimiento a otro disco, con
    el original borrado solo después de comprobar la copia;
  - mantenimiento diario (`ais-archive.timer`) y copia de seguridad adaptada
    a los segmentos;
  - 96 tests; ensayo del cierre de 2026 con una copia de los datos reales;
    desplegado en el servidor.
  - El primer cierre real será el **01/01/2027 a las 00:00 UTC**: revisarlo
    ese día con `archive_tools estado`.

## 🔄 En curso
- **Revisiones pendientes:**
  - comprobar en *Cost Analysis* que el gasto de Oracle es 0 €;
  - comprobar el 08/11/2026 que el banco ha liberado la retención de 93 €;
  - el enlace de las copias caduca el 31/12/2027: renovarlo si el proyecto sigue.

## ⏳ Pendiente
| Fase | Contenido |
|---|---|
| 7 | Análisis TFG: subzonas, escalas y tiempos de espera, exportación CSV/Excel, gráficos. Usar «atracado» con SOG < 0,5 kn para coincidir con el muestreo |
| 8 | (Opcional) Reparación de huecos entre dos Collectors de la misma zona |


