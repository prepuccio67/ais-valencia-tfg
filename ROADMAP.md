# Hoja de ruta

Última actualización: 28/10/2026

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

## 🔄 En curso
- **Alta de la cuenta de Oracle** con pago por uso (la hace Marcos).

## ⏳ Pendiente
| Fase | Contenido |
|---|---|
| 3 | Despliegue en Oracle: máquina, disco de datos, servicio systemd, cortafuegos, token, copias de seguridad y prueba de restauración. **Captura 24/7** |
| 4 | Viewer web: mapa, lista de buques, línea temporal, aviso de huecos, selector de zona y reproducción de rutas |
| 5 | Zonas configurables: varias zonas, editor (coordenadas, polígono o GeoJSON, ratón), activar y desactivar |
| 6 | Archivo: cierre de segmentos, catálogo, consultas entre segmentos, compresión .zst y movimiento verificado |
| 7 | Análisis TFG: subzonas, escalas y tiempos de espera, exportación CSV/Excel, gráficos. Usar «atracado» con SOG < 0,5 kn para coincidir con el muestreo |
| 8 | (Opcional) Reparación de huecos entre dos Collectors de la misma zona |

Tras la Fase 3 se retira la captura por GitHub Actions y el código antiguo pasa
a `legacy/`.
