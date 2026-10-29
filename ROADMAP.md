# Hoja de ruta

Última actualización: 29/10/2026

## ✅ Hecho
- **Versión 0 (GitHub Actions):**
  - captura en CSV cada 30 min;
  - cálculo provisional de escalas;
  - cuadro de mando en GitHub Pages.
  - Sigue en marcha hasta que funcione el servidor.
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

## 🔄 En curso
- **Solapamiento con GitHub Actions** hasta el 30/10/2026; después se retira y
  el código antiguo pasa a `legacy/`.
- **Revisiones pendientes:**
  - comprobar en *Cost Analysis* que el gasto de Oracle es 0 €;
  - comprobar el 08/11/2026 que el banco ha liberado la retención de 93 €;
  - el enlace de las copias caduca el 31/12/2027: renovarlo si el proyecto sigue.

## ⏳ Pendiente
| Fase | Contenido |
|---|---|
| 4 | Viewer web: mapa, lista de buques, línea temporal, aviso de huecos, selector de zona y reproducción de rutas |
| 5 | Zonas configurables: varias zonas, editor (coordenadas, polígono o GeoJSON, ratón), activar y desactivar |
| 6 | Archivo: cierre de segmentos, catálogo, consultas entre segmentos, compresión .zst y movimiento verificado |
| 7 | Análisis TFG: subzonas, escalas y tiempos de espera, exportación CSV/Excel, gráficos. Usar «atracado» con SOG < 0,5 kn para coincidir con el muestreo |
| 8 | (Opcional) Reparación de huecos entre dos Collectors de la misma zona |


