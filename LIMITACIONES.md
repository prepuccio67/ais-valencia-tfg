# Limitaciones de los datos

Lista viva de limitaciones que habrá que explicar en la memoria y ante el
tribunal. Cada una indica cómo se mide o se mitiga.

## Cobertura y fuentes
- **Datos terrestres de redes colaborativas.** Ni OpenSeaFeed ni aisstream
  garantizan cobertura ni funcionamiento. Un buque solo aparece si algún
  receptor de su red lo oye. No sabemos qué receptor cubre València en
  OpenSeaFeed. *Medida:* se guardan los mensajes por minuto y fuente
  (`coverage_minute`).
- **Cobertura desigual dentro del rectángulo.** En los 7 días previos al
  28/10/2026, la celda del puerto tuvo mucha más actividad que la de la zona de
  fondeo sur (520 frente a 143 buques en el mapa de cobertura de OpenSeaFeed).
  Podría haber buques fondeados lejos que se oigan peor.
- **Licencias:** los datos de OpenSeaFeed son CC BY 4.0 (hay que citarlos).
  aisstream no publica condiciones de uso [VERIFICAR con aisstream].

## Huecos
- **Huecos ya registrados en la versión 0 (GitHub Actions):** unos 70 min de
  datos en las primeras 21 h, con huecos de hasta 7 h. Esos días tienen
  cobertura muy parcial.
- **Huecos desde el servidor:** se registran con su motivo (tabla `gap`). Las
  escalas que coinciden con un hueco se marcan (`overlaps_gap`).

## Precisión
- **Muestreo:** como mucho 1 posición por minuto en movimiento y 1 cada 10 min
  parado, más todos los cambios de estado. Las horas de atraque y salida tienen
  una precisión de alrededor de 1 minuto, siempre que la fuente reciba los
  mensajes.
- **Hora del mensaje:** la hora que da la fuente es la de recepción en su red;
  el AIS solo transmite el segundo dentro del minuto. Se guarda también nuestra
  hora de recepción para medir el retraso, que fue de unos 3 s de mediana en la
  prueba del 28/10/2026.
- **Posición GPS:** puede tener errores o saltos ocasionales.

## Lo que el AIS no da (o da mal)
- **Calado, destino y ETA** los introduce la tripulación a mano: a menudo están
  desactualizados o vacíos. La ETA no incluye el año.
- **Estado de navegación** (fondeado, amarrado…): también es manual y a veces
  no se actualiza. Por eso las escalas se calculan sobre todo con la velocidad
  y la posición.
- **Naviera, terminal asignada, carga y motivo de la espera:** el AIS no los
  da. La naviera se completa a mano con fuentes públicas (tabla `operator`).
- **Las dimensiones** pueden estar mal configuradas en el equipo AIS del buque.
- **Un MMSI** puede reutilizarse o cambiar de buque. El IMO es más fiable,
  pero no siempre viene.

## Método
- Las terminales y el fondeadero se dibujan a partir de los propios datos, así
  que la asignación de terminal depende de esa calibración.
- Una escala que empezó antes de tener datos, o que no ha terminado, se marca
  como censurada y no entra en las estadísticas de espera.
