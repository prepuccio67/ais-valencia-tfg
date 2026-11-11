# Hoja de ruta

Última actualización: 11/11/2026

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

- **Fase 7. Escalas y tiempos de espera** (01/11/2026, primera versión):
  - subzonas dibujadas con los datos reales: recinto portuario, terminales MSC,
    CSP y APM, y fondeadero;
  - método `escalas-v1`: escalas con fondeo, atraque directo, cambio de muelle
    y calidad de cada escala;
  - `analysis.db` recalculable, `/api/port_calls` (JSON o CSV para Excel) y
    `/api/subzones`;
  - cuadro de mando `/escalas`, enlazado desde el visor;
  - 115 tests; desplegado: 53 escalas calculadas con los datos del 29/10 al
    01/11/2026.

- **Zona de APROXIMACIÓN** (08/11/2026, D-18):
  - prueba de 1 h que solo contaba mensajes: 16.065 mensajes/h, 967 buques,
    alcance de hasta 189 NM con cobertura «a islas»;
  - rectángulo 37,0–42,0 N; 3,5 W–2,9 E con 1 posición cada 30 min en marcha y
    cada 60 min parado, y todos los cambios de destino/calado/ETA;
  - VALENCIA, zona por defecto explícita; el editor acepta el muestreo; límite de
    zona de 40 grados²;
  - 123 tests; desplegada a las 17:04 UTC y vigilada 30 min: VALENCIA igual
    (324 posiciones frente a 327), sin huecos ni errores.

## 🔄 En curso
- **Fase 7c. Núcleo del TFG** (método en METODO.md; cada módulo se aprueba antes
  de programarlo):
  - 7c.1, precisión de la ETA declarada (`eta-v1`): método propuesto el
    04/11/2026, pendiente de aprobación;
  - 7c.2, combustible, CO₂ y coste EU ETS de la espera (`emisiones-v1`): pendiente;
  - 7c.3, escenarios de llegada *just in time* (`jit-v1`): pendiente;
  - `escalas-v2` (D-19), completar los huecos de VALENCIA con la zona de aproximación:
    aprobado, programado (129 tests) y **desplegado el 11/11/2026 a las 19:09 UTC**.
    Las esperas se miden solo con escalas desde el 08/11 a las 17:05 UTC. Pendiente de
    decidir: umbral mínimo de 1 h para contar una espera.
- **Revisiones pendientes:**
  - ~~gasto de Oracle 0 € y retención de 93 € liberada~~: comprobado por Marcos el 08/11/2026;
  - el enlace de las copias caduca el 31/12/2027: renovarlo si el proyecto sigue;
  - ~~comprobar que la copia diaria incluye la zona `APROXIMACION`~~: comprobado el
    11/11/2026 (copias del 08, 09 y 10/11 hechas y subidas, 0 errores; unas 21.000
    posiciones al día, ≈0,55 GB/año, dentro de lo estimado);
  - systemd avisa de que el archivo `ais-collector.service` cambió en disco (aviso
    anterior a D-18): revisar la diferencia y ejecutar `systemctl daemon-reload`.

## ⏳ Pendiente
| Fase | Contenido |
|---|---|
| 7b | **Pendientes del análisis:** revisar los recintos de las terminales (sobre todo APM) con el plano de la Autoridad Portuaria; tabla de navieras (`operator`); con varias semanas de datos, tratar las esperas sin terminar con un análisis de supervivencia (Kaplan-Meier); «permanencias» y «fundido temporal» del visor |
| 8 | (Opcional) Reparación de huecos entre dos Collectors de la misma zona |


