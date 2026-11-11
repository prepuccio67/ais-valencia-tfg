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
- **Cobertura «a islas» lejos de la costa (zona de aproximación, D-18).** Las
  dos fuentes son redes de receptores en tierra: se oye bien a los buques cerca
  de los puertos con receptor y casi nada en mar abierto entre ellos. Prueba de
  1 h del 08/11/2026 (15:28–16:28 UTC) en el rectángulo de aproximación
  (37,0–42,0 N; 3,5 W–2,9 E), buques distintos según su distancia al puerto de
  València:

  | Distancia (NM) | 0–15 | 15–30 | 30–50 | 50–75 | 75–100 | 100–125 | 125–150 | > 150 |
  |---|---|---|---|---|---|---|---|---|
  | Buques | 216 | 20 | 4 | 32 | 33 | 117 | 327 | 224 |

  - Casi todos los mensajes salen de seis «islas»: València, Palma, Barcelona,
    Cartagena, Alicante e Ibiza. Tarragona y Castellón apenas aparecen y el
    mar entre València y Baleares queda casi vacío.
  - Consecuencia: la ETA con antelación se capta cuando el buque pasa cerca de
    una de esas islas (p. ej. Cartagena o Ibiza, a 8–15 h de València), no de
    forma continua. Entre una isla y la llegada habrá huecos de horas en la
    trayectoria, y la velocidad de aproximación (7c.3) se medirá solo en los
    tramos con señal.
  - Es una foto de una hora de un domingo por la tarde: la cobertura puede
    cambiar si se conectan o desconectan receptores. *Medida:* `coverage_minute`
    de la zona `APROXIMACION` y el script `scripts/prueba_aproximacion.py`.
- **Licencias:** los datos de OpenSeaFeed son CC BY 4.0 (hay que citarlos).
  aisstream no publica condiciones de uso [VERIFICAR con aisstream].
- **Las dos fuentes no ven lo mismo.** En la prueba de 30 min del 28/10/2026:
  - aisstream: 1.093 mensajes con hora válida, unos 31 buques por minuto y un
    retraso medio de unos 6,5 s;
  - OpenSeaFeed: 656 mensajes, unos 21 buques por minuto y un retraso medio de
    unos 3,4 s.
  - Se guarda la primera fuente que trae cada dato. La columna `source_id` dice
    de cuál viene, así que se puede medir la aportación de cada una.
- **Repeticiones al conectar.** OpenSeaFeed reenvía las últimas posiciones
  conocidas al suscribirse. Se aceptan las de menos de 15 min, que llevan su
  hora original; las demás se descartan (unas 100 por conexión) y se anotan en
  el registro de sucesos.

## Huecos
- **Huecos ya registrados en la versión 0 (GitHub Actions):** unos 70 min de
  datos en las primeras 21 h, con huecos de hasta 7 h. Esos días tienen
  cobertura muy parcial.
- **Huecos desde el servidor:** se registran con su motivo (tabla `gap`). Las
  escalas que coinciden con un hueco se marcan (`overlaps_gap`).

## Precisión
- **Muestreo:** como mucho 1 posición por minuto en movimiento y 1 cada 10 min
  parado, más todos los cambios de estado. Un buque parado pasa a «en
  movimiento» con 0,5 kn y vuelve a «parado» por debajo de 0,3 kn. Las horas de
  atraque y salida tienen una precisión de alrededor de 1 minuto, siempre que
  la fuente reciba los mensajes.
- **Un cambio de estado muy rápido** (menos de 10 s después del último
  guardado) se guarda con el mensaje siguiente. Si el buque deja de emitir
  justo entonces, ese evento se pierde: es un caso raro.
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

## Archivo de segmentos
- **Frontera entre segmentos.** El cierre se hace unos segundos después de las
  00:00 UTC del 1 de enero. Una posición recibida con retraso (hasta 15 min)
  puede quedar en el segmento siguiente al de su hora. Las consultas abren por
  eso los dos segmentos vecinos, así que no se pierde nada. Basta con tenerlo en
  cuenta si se abre un archivo `.db` a mano con DB Browser.
- **Zonas desactivadas:** no cierran su segmento hasta el siguiente arranque o
  recarga del Collector, porque no tienen nada que escribir.
- **Segmentos comprimidos:** la primera consulta que los necesita tarda un poco
  más, porque los descomprime en `archive/cache/`. Esa copia se borra si pasan
  7 días sin usarla.

## Escalas y tiempos de espera (Fase 7)
- **Esperas sin terminar (censura).** Mientras un buque sigue esperando, su
  escala está «EN CURSO» y no entra en las medianas. Con pocos días de datos,
  las esperas largas aún no han acabado y **las medianas salen más bajas de lo
  real**. *Medida:* el cuadro de mando avisa y muestra aparte quién espera
  ahora. Con más datos se puede usar un análisis de supervivencia
  (Kaplan-Meier), que sí aprovecha las esperas sin terminar.
- **Llegada o salida no vistas.** Si el buque aparece ya parado (al empezar la
  captura, tras un hueco o porque se le oye mal a la deriva lejos de la costa),
  no se sabe cuándo llegó: la escala se marca DUDOSA y no entra en las
  estadísticas.
- **El borde este del rectángulo VALENCIA corta la zona de deriva (comprobado el
  11/11/2026).** De las 15 escalas de portacontenedores dudosas que no se deben al
  arranque de la captura, **12** pierden la señal o «aparecen» ya paradas a menos de
  ≈2 NM del borde este (0,00° de longitud). Los buques que esperan a la deriva salen
  un poco del rectángulo y desaparecen de VALENCIA, aunque se sigan oyendo. Solo 2
  (CMA CGM LOIRE y WEC CORNEILLE) son huecos reales de recepción dentro del
  fondeadero, y 1 (YAKOOT) está justo en el límite de 2 h. Desde el 08/11 la zona
  `APROXIMACION` los sigue viendo: en los dos casos posteriores (MSC GAYANE y
  MSC ADITI) tiene 3 y 10 posiciones durante el hueco, todas fuera de VALENCIA, entre
  0,01° y 0,10° E. *Mitigación posible:* completar los huecos de VALENCIA con las
  posiciones de `APROXIMACION` en el cálculo de escalas (cambio de método, requiere
  aprobación); los datos anteriores al 08/11 no se pueden recuperar.
- **Esperas subestimadas con `escalas-v1` (ensayo del 11/11/2026).** El mismo borde
  hace que algunas escalas salgan OK con una espera mucho más corta de la real: solo
  se ve el último tramo dentro del rectángulo. En las 12 escalas OK de
  portacontenedores con atraque entre el 08/11 y el 11/11 hubo 2 casos: MSC ARUSHI R.
  (0,6 h frente a 5,1 h) y CMA CGM INNOVATION (1,6 h frente a 31 h o más). Es un sesgo
  hacia esperas más cortas. Las esperas anteriores al 08/11 no se pueden corregir.
  *Mitigación:* `escalas-v2` (D-19) completa las trayectorias con la zona de
  aproximación, y las estadísticas de espera usan solo las escalas iniciadas desde el
  08/11/2026 a las 17:05 UTC.
- **Con `escalas-v2`, las esperas al este del rectángulo tienen menos resolución.**
  Allí un buque parado se guarda cada 60 min (el arranque y la parada, al momento si se
  oyen). Una espera de menos de 1 h no se mide con precisión, y la hora de inicio o de
  fin puede tener hasta 60 min de error si el buque no se oía en ese instante.
- **«Zona de espera» no es «aguas del puerto».** Parte de la espera a la deriva ocurre
  fuera de la Zona II del puerto [VERIFICAR su límite este en el BOE]. Por eso la
  llegada de referencia de la ETA se llama `ZONA_ESPERA` y no «aguas del puerto».
- **Periodo corto para las esperas.** Al contar solo desde el 08/11, las primeras
  semanas hay pocas escalas, y las que ya han terminado son las de espera corta.
- **Recintos de las terminales dibujados con los datos** de los primeros 3 días
  y con los rótulos de OpenStreetMap. MSC y CSP son claros (cada una solo recibe
  a sus navieras). **APM se redibujó el 06/11/2026** sobre imagen de satélite
  (D-17): cubre todo el espigón de contenedores. Queda por confirmar con el plano
  oficial si la cara oeste de la punta es de APM [VERIFICAR]. Además, ahí atracan
  también buques pequeños (ELBIA, 134 m; MSM DON, 105 m) y de carga rodada (ECO
  PONENTE) que podrían no ser portacontenedores y que ahora cuentan como escalas
  de APM.
- **El tipo AIS 70–79 («carga») no distingue portacontenedores** de graneleros,
  ro-ro o carga general. Por eso las estadísticas «de contenedores» se basan en
  la terminal donde atraca el buque, no en su tipo.
- **«Esperando» incluye la deriva:** muchos buques no fondean, sino que esperan
  parados o a la deriva mar adentro. Cuentan como espera, con su lugar anotado
  (`FONDEO` o `DERIVA`). No se distingue una espera por congestión de una por
  otros motivos (órdenes de la naviera, *slow steaming*, avería…).
- **La hora de inicio de la espera** tiene una precisión de unos 10 minutos (un
  buque parado se guarda cada 10 min). Las horas de atraque y desatraque, de
  alrededor de 1 minuto, porque el cambio de movimiento se registra al momento.
