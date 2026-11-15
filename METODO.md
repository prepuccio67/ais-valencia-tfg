# Método de análisis (módulos 7c)

Documento de trabajo para el capítulo de metodología del TFG. Cada módulo se
propone aquí **antes** de programarlo; el código solo se escribe cuando el método
está aprobado. Las marcas **[VERIFICAR]** señalan lo que aún no se ha podido
confirmar en la fuente original, con indicación de dónde comprobarlo.

| Módulo | Versión del método | Estado |
|---|---|---|
| 7c.1 Precisión de la ETA declarada | `eta-v1` | **Aprobado como provisional (15/11/2026), pendiente del tutor** (D-20); programado, pendiente de desplegar |
| 7c.2 Combustible, CO₂ y coste EU ETS de la espera | `emisiones-v1` | Pendiente |
| 7c.3 Escenarios de llegada *just in time* | `jit-v1` | Pendiente |
| Escalas: completar con la zona de aproximación | `escalas-v2` | **Aprobado y desplegado (11/11/2026, D-19)** |

---

## Escalas: completar los huecos con la zona de aproximación (`escalas-v2`)

### 1. Problema
- `escalas-v1` (D-15) solo lee la zona VALENCIA, cuyo borde este está en 0,00° de
  longitud, a unas 10–15 NM del puerto.
- Muchos portacontenedores **esperan a la deriva justo al este de ese borde**. Mientras
  están fuera, para `escalas-v1` no existen: la escala sale DUDOSA («sin señal» o
  «llegada no observada») o, peor, sale **OK con una espera más corta de la real**,
  porque solo se ve el último tramo dentro del rectángulo.
- Desde el 08/11/2026 a las 17:04 UTC la zona `APROXIMACION` (D-18) sí los ve.

### 2. Cambio propuesto (lo único que cambia)
- A la trayectoria de cada buque de carga se añaden las posiciones de `APROXIMACION`
  que están **fuera del rectángulo VALENCIA y dentro de un «área de espera ampliada»**:
  39,25–39,60 N y 0,36 W–**0,25 E** (el rectángulo VALENCIA con el borde este movido
  unas 12 NM; en total, ≈25 NM al este del puerto).
- Todo lo demás es igual que en `escalas-v1`: la clasificación (atracado, esperando,
  navegando), las reglas de inicio y fin de escala, y los umbrales de calidad (1 h para
  dar la llegada por vista y 2 h para «sin señal»).
- **Por qué un área limitada y no toda la zona de aproximación:** para no contar como
  «espera en València» a un buque parado en Castellón, Ibiza o Barcelona. Los límites
  norte y sur son los de VALENCIA, así que Castellón (39,97 N) queda fuera.
- **Por qué 0,25 E:** en el ensayo, los buques que esperaban fuera estaban entre 0,00 y
  0,17 E, y el resultado fue **idéntico** con el borde en 0,15, 0,25 o 0,50 E. Se elige
  0,25 E para dejar margen sin acercarse a Ibiza.
- **Precisión:** la zona de aproximación guarda al momento el paso de «en marcha» a
  «parado» y al revés. El inicio y el fin de la espera tienen la misma precisión que en
  VALENCIA, siempre que el buque se oiga en ese momento. Si no, la precisión es de hasta
  60 min, el intervalo de un buque parado en esa zona.
- **Transparencia:** cada escala indicará cuántas posiciones vienen de la zona de
  aproximación (columna nueva `puntos_aprox` en la tabla y en el CSV). `escalas-v1` se
  podrá seguir calculando (parámetro `fill_zone: null`) para comparar las dos versiones
  en el TFG.

### 3. Ensayo (11/11/2026, solo lectura, datos hasta las 18:45 UTC)
Se calcularon las escalas con las dos versiones sin guardar nada.

- **Escalas anteriores al 08/11: idénticas** en las dos versiones (no hay datos de
  aproximación con que completarlas).
- **Escalas de portacontenedores con atraque desde el 08/11 17:04: 19, de las que
  cambian 4.**

| Buque | `escalas-v1` | `escalas-v2` | Puntos añadidos |
|---|---|---|---|
| MSC GAYANE | DUDOSA (sin señal 2,5 h), espera 0,5 h | **OK, espera 7,1 h** | 8 |
| MSC ARUSHI R. | OK, espera 0,6 h | **OK, espera 5,1 h** | 6 |
| CMA CGM INNOVATION | OK, espera 1,6 h | **DUDOSA, espera ≥ 31,1 h** (ya esperaba cuando empezó la zona de aproximación y tuvo un hueco de 4 h) | 29 |
| TEXAS TRIUMPH | EN CURSO, sin espera | **EN CURSO, espera 40,1 h** | 41 |

- **Lectura:** de las 12 escalas OK de `escalas-v1` en ese periodo, **2 tenían la espera
  muy subestimada** (0,6 h frente a 5,1 h y 1,6 h frente a 31 h o más). Es un sesgo
  sistemático hacia esperas más cortas, no un error aleatorio.
- La muestra es de solo 3 días: las cifras indican la dirección del sesgo, no su
  tamaño.

**Comprobación caso a caso (posiciones, velocidad y ETA declarada; 11/11/2026).**
- **CMA CGM INNOVATION:** parado (0,1–0,7 kn) entre 0,08 y 0,14 E desde el 08/11 a las
  17:00 hasta el 09/11 a las 19:16; arranca a 11 kn a las 21:01 y atraca el 10/11 a
  la 01:15. El 08/11 a las 21:58 cambió su ETA a «10/11 00:00»: sabía que iba a esperar.
  `v1` solo vio la pausa final junto a la bocana (1,6 h).
- **TEXAS TRIUMPH:** llega a 11,7 kn y se para a 0,04 E el 09/11 a las 18:03 (su ETA
  declarada era las 19:00). Espera a la deriva entrando y saliendo del rectángulo hasta
  el 11/11 a las 10:09 y atraca a las 13:17. `v1` partió esa espera en dos por un hueco
  de 12 h fuera del rectángulo y no le asignó espera.
- **MSC GAYANE:** llega a 13 kn y se queda a 0,5–3 kn junto al borde desde las 02:51
  (ETA declarada: 03:00) hasta las 09:55. `v1` solo vio media hora.
- **MSC ARUSHI R.:** caso ambiguo. Sale del puerto el 10/11 por la mañana, se para
  unas 3 h a 0,07 E y vuelve a atracar a las 17:17. `v2` da 5,1 h porque, como `v1`
  (D-15), cuenta la espera desde la primera parada hasta que arranca definitivamente
  hacia el puerto, con los ≈1,6 h de desplazamiento entre las dos paradas incluidos.
- **Conclusión:** en los cuatro casos `v2` se ajusta a lo que hizo el buque y `v1` no.
  La diferencia no es ruido: `v1` no ve la parte de la espera que ocurre al este de
  0,00°. La ETA declarada coincide con la llegada a la zona de espera, no con el
  atraque, igual que en el diagnóstico del apartado 7c.1 §3.

### 4. Consecuencias para el TFG
- Las esperas calculadas con datos **anteriores al 08/11** probablemente están
  **subestimadas**, y no se pueden corregir, porque esos días no había zona de
  aproximación. Se dirá en la memoria (LIMITACIONES.md).
- Para los resultados finales conviene usar las escalas con atraque **desde el 08/11**,
  calculadas con `escalas-v2`. Hay que decidirlo con el tutor, junto con la fecha de
  corte [pendiente].
- `escalas-v2` también beneficia a 7c.1 (la llegada a la zona de espera se ve mejor) y a
  7c.2 (el tiempo de espera, y con él el combustible y el CO₂, sería mayor).

### 5. Aprobado el 11/11/2026: decisiones tomadas (D-19)
- **Periodo de las esperas (opción A).** Las estadísticas de espera (media, mediana,
  percentiles, histograma) usan solo las escalas que **empiezan desde el 08/11/2026 a
  las 17:05 UTC** (parámetro `wait_stats_from`). Antes de esa hora no había zona de
  aproximación y las esperas pueden estar recortadas. Las escalas anteriores siguen
  sirviendo para contar escalas, medir la estancia en el muelle y analizar la ETA.
- **Definición de espera (se mantiene la de D-15).** Va desde la primera parada fuera
  del recinto hasta que el buque arranca definitivamente hacia el puerto, con los
  desplazamientos cortos entre paradas incluidos (caso de MSC ARUSHI R.): es tiempo
  perdido aunque el buque se mueva un poco.
- **Esperas de menos de 1 h.** En el área ampliada la posición de un buque parado se
  guarda cada 60 min, así que una espera de menos de 1 h no se mide con precisión.
  Fijar un umbral mínimo de 1 h para contar una espera está **pendiente de decidir**
  (no se ha programado). En el ensayo no hubo ninguna escala OK con espera entre 0 y 1 h.
- **Ensayo con el código definitivo (11/11/2026, datos hasta las 19:03 UTC, solo
  lectura):** 11 escalas de portacontenedores empiezan después del corte: 7 OK y 4 en
  curso, ninguna dudosa; 4 usan posiciones de la zona de aproximación. Esperas de las
  7 OK: mediana 7,1 h con `escalas-v2` frente a 3,3 h con `escalas-v1` sobre el mismo
  periodo; entre las 6 que esperaron, media 15,5 h y mediana 13,4 h. **Son solo 7
  escalas en 3 días**: sirven para comprobar el método, no como resultado. Además, las
  escalas que empiezan y terminan en tan pocos días son, por fuerza, las de espera
  corta (las largas siguen en curso), así que estas cifras subirán.

### 6. Qué se ha programado
- `collector/port_calls.py`: leer las posiciones de la zona de relleno y mezclarlas
  según el apartado 2 (unas 40 líneas).
- Parámetros en `subzones.geojson` (`method`): `version: "escalas-v2"`,
  `fill_zone: "APROXIMACION"` y `fill_box_east: 0.25`.
- Columna `puntos_aprox` en `analysis.db`, la API, el CSV y el cuadro de escalas.
- Tests: con `fill_zone: null` el resultado debe ser idéntico a `escalas-v1`, y además
  hay casos como los de MSC GAYANE y un buque parado en Castellón, que no debe contar.
- Columnas nuevas en el resumen: `wait_calls` (escalas usadas para las esperas) y la
  media y la mediana solo entre los buques que esperaron.
- Despliegue con tu «sí»: `git pull`, añadir los parámetros al `subzones.geojson` del
  servidor y reiniciar el Collector (unos segundos, registrado), para que cargue el
  código nuevo.

---

## 7c.1 Precisión de la ETA declarada (`eta-v1`)

### 1. Pregunta

¿Cuánto se equivoca la hora estimada de llegada (**ETA**, *Estimated Time of
Arrival*) que los buques portacontenedores declaran por AIS al venir a València,
y con cuánta antelación es fiable? La respuesta alimenta el escenario C del
módulo 7c.3: un buque solo puede ajustar su velocidad si se sabe con tiempo
cuándo debe llegar.

### 2. Qué es la ETA del AIS (fuente y formato)

- La ETA viaja en el **mensaje AIS 5** (datos estáticos y del viaje), que un buque
  de clase A emite **cada 6 minutos**. Su formato es «MMDDHHMM UTC»: mes, día,
  hora y minuto, **en UTC y sin año** (ITU, 2014, según la transcripción de USCG
  Navigation Center, s. f.).
- **Valores «no disponible»** del estándar: mes 0, día 0, hora 24 o minuto 60
  (ITU, 2014).
- **La escribe la tripulación a mano.** La OMI indica que el destino y la ETA se
  introducen «al inicio del viaje» y se mantienen actualizados «según sea
  necesario» (OMI, 2015, anexo). También recomienda escribir el destino con el
  código UN/LOCODE (València = `ESVLC`) e incluso usar el campo para «puerto de
  salida y siguiente puerto».
- **Se sabe que estos campos manuales tienen errores** (Harati-Mokhtari et al.,
  2007). En 2026 todavía se debatía en la OMI cómo mejorar su fiabilidad (ICS,
  2026) [VERIFICAR autores y fecha del documento MSC 111/19/6].
- **Referencia local:** un estudio con datos del propio Puerto de València midió un
  error absoluto medio de 1066 min (unas 18 h) en la ETA de partida, frente a 13 min
  con un modelo predictivo (Valero et al., 2021) [VERIFICAR en el artículo qué ETA
  de partida usan, la del AIS o la que comunica el consignatario, y en qué tabla
  aparece la cifra].

> **¿Qué es UTC?** Es la hora universal, sin horario de verano. En València, en
> invierno, son las 12:00 locales cuando en UTC son las 11:00. Todo el sistema
> trabaja en UTC.

### 3. Qué datos tenemos realmente (diagnósticos del 04/11 y del 15/11/2026)

**Cómo se guarda la ETA.**
- El Collector guarda en `voyage_data` cada **cambio** de destino, calado o ETA,
  con la hora a la que llegó. Si la ETA no cambia, no se añade fila: sigue
  vigente la anterior.
- El año lo deduce el Collector al recibir el mensaje: elige la primera fecha que
  no quede más de 30 días en el pasado (`collector/messages.py`, función
  `clean_eta`). Por ejemplo, el 30/12 una ETA «01-02» se entiende como 2 de enero
  del año siguiente. Así queda resuelto el cambio de año.

**Diagnóstico del 15/11/2026** (ensayo de solo lectura en el servidor con el código de
`eta-v1`, escalas `escalas-v2`; datos del 29/10 a las 19:18 al 15/11 a las 18:37 UTC):

| Indicador | Valor |
|---|---|
| Filas en `voyage_data`, zona VALENCIA | 1261, de 295 buques (1181 con ETA válida) |
| Filas en `voyage_data`, zona APROXIMACION (desde el 08/11 a las 17:04) | 4403, de 872 buques (3030 con ETA válida) |
| ETA que ya había pasado (más de 1 h) cuando el buque la emitió | 14 % en VALENCIA y 18 % en APROXIMACION |
| Escalas de portacontenedores (MSC, CSP, APM) | 152; 142 con alguna ETA válida antes del atraque |
| ETA en punto (minuto :00) entre los casos utilizables | 62,5 % |

**Casos utilizables por horizonte** (definición `ZONA_ESPERA`, regla de caducidad
aprobada), separando las llegadas anteriores y posteriores a la zona de aproximación:

| Horizonte | Llegadas hasta el 08/11 17:05 (110) | Llegadas desde el 08/11 17:05 (42) | Motivo principal de descarte después |
|---|---|---|---|
| Última ETA | 64 | 24 | ETA caducada (15) |
| 72 h | 0 | 0 | buque no visto (35) |
| 48 h | 0 | 3 | buque no visto (33) |
| 24 h | 1 | 7 | buque no visto (23) |
| 12 h | 1 | 12 | buque no visto (16) |
| 6 h | 3 | 8 | buque no visto (24) |
| 2 h | 7 | 17 | ETA caducada (12) |
| 1 h | 39 | 21 | ETA caducada (14) |
| 0 h | 64 | 24 | ETA caducada (15) |

- La zona de aproximación hace medibles los horizontes de 6 a 48 h, que antes no
  existían. El de 72 h sigue sin casos: a 72 h vista el buque está fuera del
  rectángulo de aproximación o en una zona sin receptores (cobertura «a islas»).
- Con una semana de datos, los horizontes largos tienen muy pocos casos.

**Diagnóstico del 04/11/2026** (histórico; anterior a la zona APROXIMACION y a
`escalas-v2`; consulta de solo lectura, datos del 29/10 al 04/11/2026):

| Indicador | Valor |
|---|---|
| Filas en `voyage_data` (todos los buques) | 451, de 174 buques |
| Filas con ETA válida | 437 (en 14 la ETA venía «no disponible») |
| Filas con hora o minuto «no disponible» (24 / 60) | 0 |
| Buques de carga de 100 m o más con datos | 87 (252 filas; mediana de 3 cambios por buque) |
| ETA que ya había pasado cuando se emitió | 52 de 252 (21 %): ETA sin actualizar tras llegar |
| ETA a más de 30 días vista | 1 |
| Escalas con atraque en terminales de contenedores | 43 (17 OK, 18 dudosas, 8 en curso) |
| … con espera fuera y alguna ETA antes de fondear | 25 de 31 |

**Destinos declarados.** Aparecen `ESVLC`, `VALENCIA`, `ESVLC>ESBCN`,
`ESBCN>ESVLC`, `MAPTM>ESVLC`, `ESVLC-MACAS` y hasta erratas como `ESVLS>MAPTM`.
El signo `>` se usa como «origen > destino». Esto sigue la recomendación de usar el
campo para el puerto de salida y el siguiente (OMI, 2015), aunque el uso del
símbolo `>` es una convención del sector que no aparece en la resolución
[VERIFICAR en SN/Circ.244].

**Tres hallazgos que condicionan el método.**

1. **La ETA declarada se refiere casi siempre a la llegada a la zona de espera, no
   al atraque.**
   - Justo al entrar en espera, la mediana de (ETA − entrada en el fondeadero) es de
     **+0,3 h**, y la mitad de las escalas quedan dentro de ±1 h.
   - Durante la espera, la ETA casi **nunca se actualiza** (0 cambios en 21 de 25
     escalas). Comparada con el atraque, el error es básicamente la duración de la
     espera.
   - Hay excepciones, como MSC LAURA y ONE MANEUVER, cuya ETA coincide con el atraque
     (diferencia de −1,5 h y −0,4 h) y no con el fondeo.
2. **Con la zona de captura actual no se pueden medir los horizontes de 6 a 72 h
   antes de la llegada a la zona de espera.**
   - El rectángulo de captura llega a unas 10–15 millas náuticas del puerto
     (39,25–39,60 N; 0,36 W–0,00), unos 50–70 min de navegación a 13 nudos.
   - Antes de eso, el buque está fuera de cobertura y no recibimos su ETA. De 31
     escalas con espera, a 6 h vista solo había una ETA utilizable; a 1 h vista, 14.
3. **Hay pocas escalas.** Con 6 días de datos, todo resultado es provisional y está
   pensado para recalcularse al acumular semanas.

### 4. Definición de «llegada real»

Se calculan las tres opciones y se recomienda una. Cada una responde a una
pregunta distinta.

| Código | Llegada real | Cómo se obtiene | Qué mide |
|---|---|---|---|
| **`ZONA_ESPERA`** (recomendada) | **Llegada a la zona de espera**: la entrada en espera (fondeadero o deriva) si el buque espera, o la entrada en el recinto portuario si atraca directamente | `t_anchor_in`, o la primera posición dentro de `PUERTO` | Si la ETA acierta **el suceso que la tripulación declara** |
| `RECINTO` | Entrada en el recinto portuario (con práctico, camino del muelle) | Primera posición dentro de `PUERTO` tras la espera | Si la ETA acierta la entrada efectiva en puerto |
| `ATRAQUE` | Hora de atraque | `t_berth` | La distancia entre lo que declara el buque y cuándo puede operar la terminal: es la **brecha de información** que interesa al JIT |

> **Cambio de nombre (11/11/2026).** Esta definición se llamaba `AGUAS` («llegada a
> aguas del puerto»). Se renombra a `ZONA_ESPERA` porque los buques que esperan a la
> deriva al este de 0,00° no están en las aguas del puerto en sentido legal: el límite
> este de la Zona II queda más al oeste, en 0° 12,714′ W (vértice 39° 28,000′ N
> 0° 12,714′ W). **Comprobado el 15/11/2026** en la Resolución de 19 de octubre de 2021
> de la Autoridad Portuaria de Valencia, Pliego de prescripciones particulares del
> servicio de practicaje en el Puerto de Valencia (BOE-A-2021-18011, 04/11/2021),
> prescripción 3.ª. La definición no cambia, solo el nombre.

**Por qué se recomienda `ZONA_ESPERA`:**
- Es el suceso al que se refiere la ETA en la práctica, según el hallazgo 1. Medir
  la ETA contra el atraque mezclaría dos cosas: si el buque estima bien su llegada
  y cuánto le hace esperar el puerto.
- Encaja con la Guía JIT de la OMI. La Guía toma como hito clave la hora solicitada
  de llegada al punto de embarque del práctico (*RTA Pilot Boarding Place*), previa
  al atraque (GloMEEP y GIA, 2020, anexo 1, p. 47).
- El fondeadero y la entrada del recinto son la mejor aproximación de ese punto que
  tenemos. Según el mismo pliego (BOE-A-2021-18011), el punto recomendado de embarque
  de prácticos está «en los alrededores» de **39° 25,188′ N 0° 15,903′ W**. Se anota
  solo como referencia: **no** se usa como definición de llegada, que sigue siendo
  `ZONA_ESPERA`. Todavía no se dibuja en el visor.

**`ATRAQUE`** se calcula y se presenta aparte. No es un error de la ETA, sino la
información que le falta al buque para un JIT. Se conecta directamente con 7c.3.

### 5. ETA vigente en cada horizonte

> **¿Qué es un horizonte?** Es la antelación con la que miramos la ETA. «A 24 h»
> significa «qué ETA declaraba el buque 24 horas antes de llegar».

Para cada escala, cada definición de llegada *T* y cada horizonte
*h* ∈ {72, 48, 24, 12, 6, 2, 1, 0} h:

1. **Momento de referencia:** *t_ref = T − h*. Se añaden los horizontes de 2, 1 y
   0 h porque son los únicos medibles hoy con `ZONA_ESPERA`.
2. **ETA vigente:** la de la última fila de `voyage_data` del buque con hora
   ≤ *t_ref*.
3. **Comprobación de que el buque estaba a la vista:** se exige que haya alguna
   posición o mensaje del buque en [*t_ref − W*, *t_ref*], con *W* = 2 h
   (parámetro).
   - Esto es necesario porque `voyage_data` solo guarda cambios mientras el buque
     está en cobertura. Si no lo vemos, no sabemos si cambió la ETA mientras estaba
     fuera.
   - Se leen las ETA y las posiciones de las **dos zonas** (VALENCIA y
     APROXIMACION): la de aproximación es la que recibe la ETA horas antes de llegar.

**Indicador «última ETA» (añadido el 15/11/2026, D-20).** Además de los horizontes fijos,
para cada escala y definición se toma **la última ETA válida emitida antes de la llegada
real**: se busca hacia atrás desde *T* la fila más reciente que pase los mismos filtros
(destino València, no caducada, no imposible, buque a la vista en las 2 h anteriores a
*T*). Se presenta en la misma tabla, con su **antelación** (cuántas horas antes de llegar
se emitió). Sirve para comparar con Rosa et al. (2026), que comparan la última ETA con la
entrada en la jurisdicción del puerto, y con Chu et al. (2024).

### 6. Error y signo

**e = ETA declarada − llegada real** (en horas)

- **e > 0:** el buque llegó **antes** de lo que declaraba. Ejemplo: ETA 14:00,
  llega 12:30 → e = +1,5 h.
- **e < 0:** llegó **más tarde** de lo declarado. Ejemplo: ETA 14:00, llega 17:00
  → e = −3 h.

> **Criterio (15/11/2026, D-20):** e = ETA − llegada real (positivo = el buque llegó
> antes de lo declarado), el mismo que Rosa et al. (2026) y que el texto de Chu et al.
> (2024). Ojo: la fórmula del sesgo de Chu et al. (2024, ec. 5) usa el signo contrario
> (ATA − ETA); al comparar sesgos con ese artículo hay que invertir el signo.

### 7. Filtros y motivos de descarte

Cada combinación escala × definición × horizonte queda con un estado. Se cuentan
y se publican todos, no solo los utilizables.

| Estado | Regla | Entra en las estadísticas |
|---|---|---|
| `USABLE` | Pasa todos los filtros | Sí |
| `ANTES_CAPTURA` | *t_ref* anterior al inicio de los datos | No |
| `SIN_COBERTURA` | Buque no visto en [*t_ref − W*, *t_ref*] | No |
| `SIN_ETA` | No hay ETA, o es «no disponible» (mes 0, día 0, hora 24, minuto 60) | No |
| `DESTINO_OTRO` | El último puerto del destino declarado no es València | No |
| `DESTINO_DUDOSO` | València aparece, pero no como último puerto (`ESVLC-MACAS`), o el destino está vacío | No; se informa aparte |
| `ETA_CADUCADA` | La ETA ya había pasado más de 1 h antes de *t_ref* (tripulación que no la actualizó) | No; se informa su porcentaje y se calcula una variante que la incluye |
| `ETA_IMPOSIBLE` | ETA a más de 30 días de *t_ref* | No |
| `ESCALA_EXCLUIDA` | Escala `EXCLUIDA` en `escalas-v1` (sin atraque o espera de más de 10 días) | No |
| `LLEGADA_NO_VISTA` | No se observó el suceso de llegada de esa definición (p. ej., el buque apareció ya fondeado) | No |

> **Regla de caducidad: punto a decidir con el tutor (ensayo del 15/11/2026).** Se ha
> programado tal como está aprobada: caducada si la ETA ya había pasado más de 1 h antes
> de *t_ref* (`caducada_referencia: "t_ref"`). Tiene un efecto no previsto: un buque que
> llega con más de 1 h de **retraso** queda como «caducada» en los horizontes de 0–1 h,
> así que los retrasos se excluyen justo donde más importan. Con `ATRAQUE` se nota mucho:
> el 82–85 % de los casos sale «caducada», porque casi todos los buques atracan más tarde
> de su ETA. La alternativa programada, `"emision"`, considera caducada la ETA solo si ya
> había pasado cuando el buque la emitió (la misma idea que el diagnóstico del 04/11).
> Cambia 901 de 4104 casos. Con ella, el MAE de `ZONA_ESPERA` a 0 h pasa de 2,1 h a 2,9 h
> y la proporción en ±1 h baja del 72 % al 61 %. Cambiar de regla es editar un parámetro.

**Reglas del destino.**
- Se pasa a mayúsculas y se trocea por `>`, `=>`, `->`, `>>` y `-`. Se toma el
  **último** trozo.
- Es València si coincide con `ESVLC`, `ES VLC`, `VLC`, `VALENCIA` o `VALENCIA
  PORT`, o si se diferencia de `ESVLC` en una sola letra (`ESVLS`). La lista es un
  parámetro editable.

**Escalas incluidas.**
- Solo las de las terminales de contenedores (MSC, CSP y APM), como en
  `escalas-v1`: el tipo AIS no distingue portacontenedores.
- Las escalas son las de `escalas-v2` (D-19). Se incluyen las escalas OK, las DUDOSAS
  y las EN CURSO cuyo suceso de llegada se haya observado. Para la ETA solo importa haber visto la llegada; una salida
  no vista no afecta. Además se calcula la variante «solo OK».

**Sospecha de hora local.**
- Algunas tripulaciones podrían escribir la hora local en lugar de UTC, lo que daría
  errores de −1 h en invierno o −2 h en verano.
- No se corrige buque a buque. Se revisará si el reparto de errores tiene picos en
  esos valores y, si los hay, se señalará como resultado a revisar.

### 8. Indicadores

Por horizonte, por definición de llegada y por terminal (y en total):

| Indicador | Fórmula | Explicación sencilla |
|---|---|---|
| *n* | número de casos `USABLE` | Cuántas escalas sostienen la cifra. Con *n* < 5 se muestra «pocos datos» |
| Error medio (sesgo) | (1/*n*) Σ eᵢ | Si los buques tienden a llegar antes (+) o después (−). Errores de signo contrario se compensan |
| Mediana del error | valor central de los eᵢ ordenados | El caso «típico»; un buque con un error enorme no la mueve |
| Error absoluto medio (MAE) | (1/*n*) Σ \|eᵢ\| | Cuánto se equivoca de media, sin importar el signo. Ejemplo: errores de +2 y −2 h dan un error medio de 0 pero un MAE de 2 h |
| Raíz del error cuadrático medio (RMSE) | √((1/*n*) Σ eᵢ²) | Como el MAE, pero castiga más los errores grandes. Lo usan Chu et al. (2024). Añadido el 15/11/2026 (D-20) |
| % dentro de ±0,5, ±1, ±2 y ±6 h | casos con \|eᵢ\| ≤ *k* / *n* | Qué parte de las ETA sería útil para planificar con esa tolerancia. ±0,5 h es el criterio de puntualidad de Rosa et al. (2026) y Michaelides et al. (2019); ±1 h, el de Chu et al. (2024) |
| Percentiles 10 y 90 | valores que dejan por debajo el 10 % y el 90 % de los errores | El rango donde cae el 80 % central de los casos. Ejemplo: P10 = −3 h y P90 = +1 h |
| Intervalo de confianza al 90 % de la mediana (si *n* ≥ 10) | *bootstrap* con 2000 remuestreos | Cuánto podría cambiar la mediana con otras escalas parecidas: una forma de medir la incertidumbre por tener pocos datos |
| % de ETA caducadas | casos `ETA_CADUCADA` / casos con ETA | Cuántas tripulaciones no actualizan la ETA |
| % de ETA en punto (minuto 00) | — | Precisión con la que se declara: si casi todas acaban en :00, la ETA se redondea a la hora |
| Antelación mediana (solo «última ETA») | mediana de *T* − hora de emisión | Con cuánto tiempo se emitió la última ETA válida |

> **Por qué no basta la media (Rosa et al., 2026):** los errores son asimétricos (pocos
> retrasos muy grandes), así que la media puede engañar. Por eso se dan también la
> mediana y los porcentajes dentro de cada banda.

> **¿Qué es un percentil?** Ordenamos los errores de menor a mayor. El percentil
> 90 es el valor que deja por debajo al 90 % de ellos. Para la mediana y los
> percentiles se usa el mismo cálculo que en el resto del cuadro de mando,
> equivalente a PERCENTIL.INC de Excel.
>
> **¿Qué es un *bootstrap*?** Se repite el cálculo 2000 veces, sacando cada vez las
> escalas «al azar con reemplazo» de las que tenemos. El intervalo es el rango
> donde cae el 90 % de esas medianas. No necesita suponer ninguna forma concreta
> para el reparto de los errores.

### 9. Parámetros (archivo `parametros_7c.json`, sección `eta`)

El archivo vive en `Zones/VALENCIA/parametros_7c.json` del servidor. Si no existe, se copia
el de ejemplo, `config-ejemplo/zones/VALENCIA/parametros_7c.json`, que es el que está en el
repositorio. Al cambiar cualquier parámetro, el cálculo se rehace solo.

Ninguno irá escrito en el código. Cada uno llevará su valor, unidad, motivo o
fuente y fecha.

| Parámetro | Valor propuesto | Unidad | Motivo |
|---|---|---|---|
| `horizontes_h` | 72, 48, 24, 12, 6, 2, 1, 0 | h | Encargo del TFG más los horizontes medibles hoy |
| `definicion_principal` | `ZONA_ESPERA` | — | Apartado 4 |
| `ventana_vista_h` (*W*) | 2 | h | Un buque fondeado se guarda cada 10 min y uno en marcha cada minuto; 2 h deja margen para pequeños huecos de recepción |
| `caducada_tolerancia_h` | 1 | h | Una ETA que ya pasó hace menos de 1 h puede ser simplemente un retraso |
| `eta_max_dias` | 30 | días | La misma ventana que usa el Collector para deducir el año |
| `bandas_h` | **0,5**, 1, 2, 6 | h | ±0,5 h: Rosa et al. (2026) y Michaelides et al. (2019); ±1 h: Chu et al. (2024); ±2 y ±6 h: encargo del TFG (15/11/2026) |
| `min_n` | 5 | escalas | Por debajo no se muestran cifras, solo «pocos datos» |
| `destinos_valencia` | `ESVLC`, `ES VLC`, `VLC`, `VALENCIA`, `VALENCIA PORT` | — | Valores observados y UN/LOCODE |
| `bootstrap_remuestreos` | 2000 | — | Habitual; con tan pocos datos el cálculo es instantáneo (semilla fija: resultado repetible) |
| `ultima_eta` | sí | — | Indicador «última ETA» (15/11/2026) |
| `caducada_referencia` | `t_ref` | — | La regla aprobada; alternativa `emision` pendiente de decidir (apartado 7) |
| `bootstrap_min_n` | 10 | escalas | Intervalo de confianza de la mediana solo con 10 casos o más |
| `llegada_vista_h` | 1 | h | La entrada en el recinto cuenta como vista si hay una posición fuera menos de 1 h antes |

### 10. Resultados y dónde se verán (programado el 15/11/2026, pendiente de desplegar)

> **Estado de lo programado:** módulo, tabla, API y apartado del cuadro de mando hechos,
> con 10 tests. **No se han hecho todavía:** el gráfico del error por horizonte (mediana y
> banda P10–P90; de momento los valores salen en la tabla) y la capa del punto de
> embarque de prácticos en el visor.

- **Tabla `eta_obs` en `analysis.db`**, recalculable como `port_call`. Tiene una
  fila por escala × definición × horizonte, con estado, ETA, hora de la
  declaración, destino tal cual, error y `method_version = 'eta-v1'`.
- **API:** `GET /api/eta_accuracy?zone=VALENCIA`, en JSON o con `&format=csv`
  (CSV para Excel, con `;` y coma decimal).
- **Cuadro de mando `/escalas`**, con un nuevo apartado:
  - cifras clave: MAE y % dentro de ±1 h en el horizonte medible más largo;
  - el error por horizonte (mediana y banda P10–P90);
  - la tabla de casos y de descartes por motivo;
  - un aviso fijo de que son pocos datos.
- **Código:** un módulo nuevo `collector/eta_accuracy.py`, con sus tests, que solo
  lee `voyage_data`, `position` y `port_call`. **No se toca la captura.**
- `eta_obs` se rehace en el mismo momento que las escalas, dentro del mismo archivo.
  Si el cálculo de la ETA fallara, las escalas se guardan igual y el error queda anotado.
- La API admite `&variante=solo_ok` o `&variante=con_caducadas`, y `&tabla=indicadores`
  para descargar los indicadores en CSV en lugar de los casos.

### 11. Cobertura: ampliar la captura con una zona de aproximación (requiere tu permiso)

**El límite.**
- Sin ampliar la captura, para la llegada a la zona de espera (`ZONA_ESPERA`) solo se
  pueden medir horizontes de 0–2 h.
- Los horizontes largos (6–72 h) solo existen hoy frente al atraque (`ATRAQUE`), y
  únicamente para los buques que ya estaban esperando.

**La posible solución.**
- Añadir una segunda zona, **«APROXIMACIÓN»**, mucho más grande pero con muestreo
  grueso, por ejemplo una posición cada 30 min en marcha y cada 60 min parado.
- Cada zona tiene su propio muestreo en su `zone.json`: **no hay que tocar el código
  de captura**, solo su configuración. *Corrección (08/11/2026):* el editor de zonas
  de la Fase 5 no permitía cambiar el muestreo; se ha añadido ese parámetro a la API
  del editor (D-18) para crear la zona con la recarga ordenada de siempre.
- Además, esta zona daría la velocidad de aproximación que necesita 7c.3.

| Opción | Alcance | Horizonte cubierto (a 12,5 kn) | Buques a la vez (estimación) | Almacenamiento (estimación) |
|---|---|---|---|---|
| 0. Sin cambios | 10–15 NM | ≈ 1 h | — | ≈ 0,4 GB/año (actual) |
| A. Aproximación media | ≈ 150 NM (37,0–42,0 N; 3,5 W–2,9 E) | ≈ 12 h | 300–800 | + 0,3–0,9 GB/año |
| B. Mediterráneo occidental | ≈ 300 NM, incluye el Estrecho y Baleares | ≈ 24 h | 1000–2500 | + 1–3 GB/año |

**Cautelas de esta estimación.**
- Las cifras de buques y de almacenamiento son **estimaciones mías**, sin medir.
  Supongo unos 60 bytes por posición y el muestreo de 30/60 min. Lo correcto es
  medirlo antes de decidir, con una prueba de 1 h en tu PC que solo cuente mensajes
  sin guardarlos.
- Los receptores AIS terrestres cubren unas decenas de millas desde la costa. Lejos
  de ella habrá huecos, así que el horizonte real se medirá, no se supondrá.
- Los límites de tamaño de zona o de volumen de las fuentes gratuitas (aisstream y
  OpenSeaFeed) están por confirmar [VERIFICAR en sus condiciones de uso].
- **Los datos no se recuperan hacia atrás:** cada semana sin la zona de
  aproximación es una semana sin horizontes largos.

No haré nada de esto sin tu «sí».

**Elegida: opción A, rectángulo completo (08/11/2026, D-18).** Zona `APROXIMACION`,
37,0–42,0 N; 3,5 W–2,9 E (32 grados²), con 1 posición cada 30 min en marcha y 1 cada
60 min parado, más los eventos (arranca/para y cambio de estado AIS). Todos los cambios
de destino, calado y ETA (mensaje AIS 5) se guardan siempre, como en VALENCIA.

**Desplegada el 08/11/2026 a las 17:04 UTC.** En la primera media hora (17:05–17:35)
guardó 296 posiciones y 269 cambios de destino/calado/ETA (250 con ETA válida), sin
huecos ni errores, y VALENCIA siguió igual (324 posiciones frente a 327 la media hora
anterior). Los primeros horizontes largos de 7c.1 se podrán calcular cuando se acumulen
semanas de datos.

**Cifras medidas** (prueba de 1 h en el PC, domingo 08/11/2026 de 15:28 a 16:28 UTC,
`scripts/prueba_aproximacion.py`; resultado completo en
`informes/prueba_aproximacion_2026-11-08.json`):

| Indicador | aisstream | OpenSeaFeed | Total |
|---|---|---|---|
| Mensajes por hora en el rectángulo | 9.318 | 6.747 | 16.065 |
| … dentro de VALENCIA | 2.249 | 1.486 | 3.735 |
| Buques distintos | 955 | 947 | 967 |
| Mensajes AIS 5 (ETA) por hora | 2.048 | 1.311 | 3.359 |
| Mensajes por minuto | | | mediana 259, pico 826 |

- **Alcance real:** máximo 189 NM; la cobertura va «a islas» (València, Palma,
  Barcelona, Cartagena, Alicante e Ibiza), con muy pocos buques entre 30 y 100 NM
  (tabla en LIMITACIONES.md). Un buque con destino València apareció a 158 NM a
  10,8 kn, unas 15 h antes de llegar.
- **Lo que se guardaría en esa hora:** 1.366 posiciones (la mayoría, la primera de
  cada buque) y 352 cambios de destino/calado/ETA. Ocupación medida: 71,5 bytes por
  fila en SQLite.
- **Almacenamiento:** 1,1 GB/año si cada hora fuera como la primera (caso pesimista,
  medido); **0,45–0,6 GB/año** en régimen normal (*estimación* a partir de las
  posiciones guardadas tras los primeros 10 min).
- **Repetidos de aisstream:** 395 mensajes idénticos repetidos en la hora (159 dentro
  de VALENCIA). No los causa el solape de las dos zonas: en la misma hora el servidor,
  suscrito solo a VALENCIA, contó 2.245 mensajes de aisstream frente a los 2.249 de la
  prueba. No afectan a las posiciones guardadas (la base no admite dos con el mismo
  buque y la misma hora, y el muestreo ignora la copia).
- **Límites de las fuentes:** OpenSeaFeed admite en el nivel libre rectángulos de hasta
  30.000 grados² (su especificación OpenAPI); aisstream publica un máximo de 3
  conexiones por cuenta, pero no límites de tamaño de zona ni de mensajes [VERIFICAR:
  no publicados].

### 12. Limitaciones previstas (se pasarán a LIMITACIONES.md al implementar)

- **Muestra pequeña y de pocos días.** Las cifras son provisionales.
- **Horizontes largos sin medir** si no se amplía la captura (apartado 11).
- **ETA manual.** Puede estar desactualizada, en hora local o referida a otro punto.
  Solo se detectan los casos evidentes.
- **El punto de embarque de prácticos** se aproxima con el fondeadero y el recinto.
- **«Portacontenedores»** se identifica por la terminal donde atraca, no por el
  tipo AIS.
- **ETA del AIS frente a ETA oficial.** La ETA del AIS la teclea la tripulación; los
  estudios de comparación (Rosa et al., 2026; Chu et al., 2024) usan la ETA comunicada
  oficialmente al puerto. Las comparaciones son orientativas.

### Bibliografía (7c.1)

- GloMEEP Project Coordination Unit & Global Industry Alliance for Low Carbon
  Shipping. (2020). *Just in time arrival guide: Barriers and potential
  solutions*. International Maritime Organization.
  https://greenvoyage2050.imo.org/wp-content/uploads/2021/01/GIA-just-in-time-hires.pdf
  [VERIFICAR la autoría exacta en la portadilla]
- Chu, Z., Yan, R., & Wang, S. (2024). Evaluation and prediction of punctuality of
  vessel arrival at port: A case study of Hong Kong. *Maritime Policy & Management,
  51*(6), 1096–1124. https://doi.org/10.1080/03088839.2023.2217168
- Harati-Mokhtari, A., Wall, A., Brooks, P., & Wang, J. (2007). Automatic
  Identification System (AIS): Data reliability and human error implications.
  *The Journal of Navigation, 60*(3), 373–389.
  https://doi.org/10.1017/S0373463307004298
- International Chamber of Shipping. (2026). *Revision of the Revised guidelines
  for the onboard operational use of shipborne automatic identification systems
  (AIS) (resolution A.1106(29))* (MSC 111/19/6). https://www.ics-shipping.org/submission/msc-111-19-6-revision-of-the-revised-guidelines-for-the-onboard-operational-use-of-shipborne-automatic-identification-systems-ais-resolution-a-110629/
  [VERIFICAR autores y fecha]
- International Maritime Organization. (2015). *Revised guidelines for the
  onboard operational use of shipborne automatic identification systems (AIS)*
  (Resolución A.1106(29), adoptada el 2 de diciembre de 2015).
  https://wwwcdn.imo.org/localresources/en/OurWork/Safety/Documents/AIS/Resolution%20A.1106(29).pdf
- International Maritime Organization. (s. f.). *Guidance on the use of the
  UN/LOCODE in the destination field in AIS messages* (SN/Circ.244).
  https://www.navcen.uscg.gov/sites/default/files/pdf/NAIS/IMO_SN_Circ244_AIS_UNLOCODE.pdf
  [VERIFICAR año]
- International Telecommunication Union. (2014). *Technical characteristics for
  an automatic identification system using time division multiple access in the
  VHF maritime mobile frequency band* (Recomendación ITU-R M.1371-5).
  https://www.itu.int/rec/R-REC-M.1371 [VERIFICAR el año en la ficha de la ITU]
- Michaelides, M. P., Herodotou, H., Lind, M., & Watson, R. T. (2019). Port-2-port
  communication enhancing short sea shipping performance: The case study of Cyprus
  and the Eastern Mediterranean. *Sustainability, 11*(7), Artículo 1912.
  https://doi.org/10.3390/su11071912 [VERIFICAR: datos tomados de la bibliografía de
  Rosa et al. (2026), sin comprobar en el original]
- Resolución de 19 de octubre de 2021, de la Autoridad Portuaria de Valencia, por la que
  se aprueba el Pliego de prescripciones particulares del servicio de practicaje en el
  Puerto de Valencia. *Boletín Oficial del Estado*, 4 de noviembre de 2021
  (BOE-A-2021-18011).
- Rosa, L., Borges, F., Isbaex, C., Vásquez, C. L., & Batista, T. (2026). Ship arrival
  patterns at the port of Sines: A comparative analysis of ETA and ATA. *Case Studies
  on Transport Policy, 23*, Artículo 101705. https://doi.org/10.1016/j.cstp.2026.101705
- U.S. Coast Guard Navigation Center. (s. f.). *AIS Class A ship static and voyage
  related data (Message 5)*. Recuperado el 4 de noviembre de 2026, de
  https://www.navcen.uscg.gov/ais-class-a-static-voyage-message-5
- Valero, C. I., Ivancos Pla, E., Vaño, R., Garro, E., Boronat, F., & Palau, C. E.
  (2021). Design and development of an AIoT architecture for introducing a vessel
  ETA cognitive service in a legacy port management solution. *Sensors, 21*(23),
  8133. https://doi.org/10.3390/s21238133
