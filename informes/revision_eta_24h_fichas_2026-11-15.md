# Revisión manual de los 9 casos con error de ETA de más de 24 h (15/11/2026)

Consultas de **solo lectura** en el servidor, sobre los datos del 29/10 al 15/11/2026 a las
19:20 UTC. La lista sale de `eta_revision_24h_2026-11-15.csv` (`eta-v1`, regla «emisión»,
definición `ZONA_ESPERA`). Todas las horas están en UTC. Las líneas temporales completas,
tramo a tramo y en las dos zonas, están en `revision_eta_24h_lineas_2026-11-15.txt`.

**Cómo leer las fichas**
- *Fondeadero*: la subzona dibujada. *VALENCIA-mar*: dentro del rectángulo VALENCIA, fuera del
  fondeadero. *Espera ampliada*: al este de 0,00° y hasta 0,25° E (D-19). *Lejos*: fuera de las dos.
- *Parado*: menos de 1 nudo, el umbral de «esperando» de las escalas. *Merodeo*: moverse
  despacio, a 1–8 nudos, por la zona de espera sin ir a ningún sitio.
- *Hueco*: más de 2 h sin ninguna posición en ninguna de las dos zonas.

---

## 1. TRADEWIND (CSP, 145 m) — error de la lista: −162,6 h

- **ETA:** una sola en todo el periodo, enviada el 06/11 a las 17:08: destino `ESVLC`, ETA
  06/11 18:00. No la cambió nunca.
- **Llegada real:** entra en el fondeadero y se para el **06/11 a las 17:41** (AIS «fondeado» desde
  las 18:27). **La ETA acertó con 19 minutos de diferencia.**
- **Espera:** fondeado del 06/11 17:41 al 12/11 09:20 (≈136 h). Hay un hueco de 2,3 h el 10/11.
- **Salida sin atracar:** el 12/11 a las 10:00 sale a 11–12 kn hacia el SE y pasa casi 24 h a la
  deriva (1–3 kn) a **25–31 NM al SE** (39,08–39,14 N), fuera del rectángulo VALENCIA y del área
  ampliada. Tiene huecos de 2,2, 2,9 y **13,0 h** (12/11 20:21 → 13/11 09:18).
- **Vuelta:** el 13/11 a las 09:18 vuelve a 10 kn, fondea a las 12:37 y atraca en CSP el 15/11 a las
  03:01.
- **Escalas (`escalas-v2`):** dos escalas. La primera va del 06/11 17:41 al 12/11 09:26 y sale
  «EXCLUIDA: sin atraque»; la segunda empieza el 13/11 a las 12:37, con 37,5 h de espera.
- **¿Partió `escalas-v2` en dos la misma espera? Sí. Por qué:** el método cierra una escala como
  «se fue sin atracar» cuando, tras la última posición parada, el buque pasa más de 12 h
  (`max_gap_h`) sin volver a pararse en la zona. TRADEWIND se fue a esperar a 25–30 NM, donde
  ni VALENCIA ni el área ampliada lo ven: desde la última posición en VALENCIA (12/11 10:44) hasta la
  siguiente (13/11 10:42) pasan unas 24 h. La segunda escala empieza en el segundo fondeo, y
  `eta-v1` compara con esa «llegada» una ETA que en realidad era de la primera.
- **Conclusión:** **error de escala**. La ETA era buena. La espera real fue de unas **200 h**
  (06/11 17:41 → 15/11 02:04), no 37,5 h.

## 2. MSC YUXIN (MSC) — −84,2 h

- **ETA:** 10/11 18:00 (`ESVLC`), enviada el 10/11. Vuelve a enviarla el 13/11 a las 17:13, sin
  cambios. El 14/11 a las 13:18 cambia a `ESBCN`.
- **Llegada real:** llega a 10 kn y se para al este del borde el **10/11 a las 17:48**. **La ETA
  acertó (+0,2 h).**
- **Espera:** merodeando y parado al este de 0,00°, dentro del área ampliada, del 10/11 17:48 al
  13/11 ≈ 10:16. `escalas-v2` lo ve gracias a la zona de aproximación (88 posiciones) y la escala
  sale **OK con 64,5 h**.
- **Después:** atraca en MSC el 13/11 a las 11:33 y sale del puerto a las 18:34. Pasa 11 h
  merodeando al este (1–10 kn) y **vuelve a atracar en MSC** el 14/11 a las 06:46. Esa segunda
  estancia es otra escala (atraque directo, OK).
- **Por qué sale en la lista:** la segunda escala (llegada el 14/11 a las 06:14) hereda la ETA del
  10/11, que era de la primera. En los horizontes de 24–72 h, el momento de referencia cae
  **durante la escala anterior**.
- **Conclusión:** **ETA de la escala anterior** asignada a la siguiente. No es un error de la ETA:
  esa primera escala tiene error +0,2 h.

## 3. EVER GIFTED (CSP) — −77,1 h

- **ETA:** 10/11 14:30 (destino `FRFOS > ESVLC`), enviada el 10/11 a las 01:36 a 160 NM, frente a
  Barcelona. **No la actualiza hasta el 13/11 a las 12:54** (a 13/11 17:00).
- **Llegada real:** se para el **10/11 a las 15:40** (AIS «fondeado» desde las 16:03), en
  VALENCIA-mar, junto al fondeadero. **La ETA acertó (−1,2 h).**
- **Espera:** fondeado 41 h, hasta el 12/11 a las 09:25. Después merodea 1–10 kn al este, sale a
  27–35 NM al E el 13/11 de madrugada (fuera del área ampliada), vuelve y sigue merodeando hasta
  el 13/11 a las 18:00. Atraca en CSP el 13/11 a las 21:43.
- **Escalas:** la primera (10/11 15:40 → 12/11 14:42) sale «EXCLUIDA: sin atraque»; la segunda
  (13/11 19:33) solo tiene 0,4 h de espera.
- **Por qué se parte:** después del 12/11 a las 14:42 el buque ya no se para (va a 1,5–10 kn) durante
  más de 12 h, y el método lo da por ido.
- **Conclusión:** **error de escala** (merodeo de más de 12 h). La espera real fue de unas
  **76 h** (10/11 15:40 → 13/11 20:00), no 0,4 h. Además, la tripulación tardó casi tres días en actualizar la ETA.

## 4. TROUPER (MSC; buque rápido de línea corta, 17 kn) — −76,1 h

- **Rotación vista:** València → Barcelona → València.
  - 12/11: llega a València, entra en el recinto a las 04:45 y atraca en MSC a las 05:11 (ETA 04:30,
    actualizada a las 02:41: **error −0,25 h**). Sale el 13/11 a las 02:04.
  - 13/11 00:40: destino `ESBCN`, ETA 13/11 12:00. Fondea frente a Barcelona a las 12:34
    (acierta) y luego queda «amarrado».
  - 14/11 16:37: destino `ESVLC`, ETA 15/11 06:00, cambiada a las 19:03 a 15/11 08:00. Fondea en
    València el **15/11 a las 08:38** (**error −0,6 h**).
- **Por qué sale en la lista:** solo en el horizonte de 72 h. El momento de referencia (12/11 a las
  08:38) cae cuando el buque estaba **atracado en València en la escala anterior**, con la ETA de
  esa escala (12/11 04:30) todavía puesta.
- **Conclusión:** **ETA de la escala anterior**. Las dos ETA reales del buque son muy buenas.

## 5. MSC FEBE (MSC) — +46,6 h

- **ETA:** enviada el 01/11 a las 06:53 (la primera vez que lo oímos, al llegar): `VALENCIA`, ETA
  **03/11 07:00**. El 01/11 a las 14:56 la cambia a 04/11 01:00.
- **Llegada real:** fondea el **01/11 a las 08:23**, dos días antes de la ETA.
- **Espera:** fondeado 48,5 h. Sale del fondeadero el **03/11 a las 09:01** y atraca en MSC a las
  13:37.
- **Lectura:** la ETA (03/11 07:00) coincide con el final de la espera y el camino al muelle, no
  con la llegada: es la hora a la que la tripulación esperaba **atracar**. Ya se había visto un caso así
  el 04/11 (hallazgo 1 de METODO.md).
- **Conclusión:** **ETA de atraque**. Comparada con el atraque, el error sería de unas −6,6 h; con la
  salida del fondeadero, de −2 h.

## 6. MSC ANZIO II (MSC) — −42,1 h

- **ETA:** 11/11 19:00 (`ESVLC`), enviada el 11/11 a las 00:36, unas 18 h antes de llegar. Hay
  algunos mensajes sin ETA a las 05:00–05:06.
- **Llegada real:** fondea el **11/11 a las 18:01**. **La ETA acertó (+1,0 h).**
- **Espera:** fondeado hasta el 12/11 a las 08:58. Después merodea 1–6 kn entre el fondeadero y el
  área ampliada **durante unas 26 h** casi sin pararse, y atraca en MSC el 13/11 a las 13:39.
- **Escalas:** la primera (11/11 18:01 → 13/11 01:36) sale «EXCLUIDA: sin atraque»; la segunda,
  **OK, como atraque directo con 0 h de espera**.
- **Conclusión:** **error de escala** (merodeo de más de 12 h). La espera real fue de unas
  **43,6 h**. Esta escala entra hoy en las estadísticas de espera de `escalas-v2` **como 0 h**.

## 7. CMA CGM HARMONY (CSP) — −34,7 h

- **ETA:** 11/11 20:00 (`ESVLC`), enviada el 11/11 a las 01:59. Antes iba a `ESBCN`. **No la
  actualiza hasta el 13/11 a las 17:35** (a 14/11 01:00).
- **Llegada real:** se para el **11/11 a las 18:37**, al este del puerto. **La ETA acertó (+1,4 h).**
- **Espera:** a la deriva o merodeando a 1–7 kn al este de 0,00°, casi siempre dentro del área
  ampliada (la zona de aproximación aporta 48 + 26 posiciones). Sale del fondeo el 14/11 a la 01:33
  y atraca en CSP a las 02:56.
- **Escalas:** la primera (11/11 18:37 → 12/11 14:31) sale «EXCLUIDA: sin atraque»; la segunda
  empieza el 13/11 a las 06:43, con 18,8 h de espera. Se parte porque entre el 12/11 a las 14:31 y el
  13/11 a las 06:29 el buque va a 1,2–7,4 kn durante 16 h y el método lo da por ido.
- **Conclusión:** **error de escala**. La espera real fue de unas **55 h**, no 18,8 h.

## 8. ONE MANEUVER (CSP) — +30,4 h

- **ETA:** enviada el 01/11 a las 03:33 (al llegar): `ESVLC`, ETA **02/11 11:00**.
- **Llegada real:** fondea el **01/11 a las 04:37**. Espera 29,4 h y **atraca en CSP el 02/11 a las
  11:25**: 25 min después de la ETA.
- **Conclusión:** **ETA de atraque**, igual que en el diagnóstico del 04/11.

## 9. WEC CORNEILLE (MSC) — −27,1 h

- **ETA:** 31/10 14:00, enviada a las 13:28. Fondea el **31/10 a las 13:59**: **acierta al minuto**.
- **Visita en dos estancias:**
  - fondeado hasta el 01/11 a las 07:17 (con un hueco de 2,6 h); atraca en MSC a las 10:27; sale
    del puerto a las 16:35;
  - **vuelve a fondear** a las 17:04 y espera 24,9 h; atraca otra vez en MSC el 02/11 a las 18:33.
- La ETA se va actualizando durante la segunda espera (02/11 04:00 → 08:00 → 16:00).
- **Por qué sale en la lista:** en los horizontes de 12 y 24 h de la segunda escala, el momento de
  referencia cae **durante la primera**, con su ETA del 31/10.
- **Conclusión:** **ETA de la escala anterior**.

---

## Tabla final

| Buque | Qué creo que pasó | Tipo | ¿Hay que cambiar algún método? |
|---|---|---|---|
| TRADEWIND | Llegó a su hora (ETA +0,3 h), esperó 136 h, se fue a esperar a 25–30 NM al SE sin señal 24 h y volvió a fondear. Espera real ≈ 200 h | **Error de escala** | Sí: escalas (unir esperas interrumpidas) y `eta-v1` (no usar la ETA de la escala anterior) |
| MSC YUXIN | Llegó a su hora (+0,2 h), esperó 64,5 h, atracó, salió 11 h y volvió a atracar. La segunda escala hereda la ETA de la primera | **ETA de la escala anterior** | Sí: `eta-v1` |
| EVER GIFTED | Llegó a su hora (−1,2 h), fondeó 41 h y merodeó otras 30 h (a ratos fuera del área ampliada) antes de atracar. Espera real ≈ 76 h | **Error de escala** | Sí: escalas (merodeo) y `eta-v1` |
| TROUPER | Rotación València → Barcelona → València con ETA muy buenas (−0,25 y −0,6 h). A 72 h vista se usó la ETA de la escala anterior | **ETA de la escala anterior** | Sí: `eta-v1` |
| MSC FEBE | Llegó dos días antes de su ETA, que era la de salir del fondeadero y atracar | **ETA de atraque** | No hay que quitarla: es lo que declaró. Conviene clasificar y contar estos casos (ver abajo) |
| MSC ANZIO II | Llegó a su hora (+1,0 h), fondeó 15 h y merodeó 26 h antes de atracar. Espera real ≈ 43,6 h; `escalas-v2` la cuenta como atraque directo (0 h) | **Error de escala** | Sí: escalas y `eta-v1` |
| CMA CGM HARMONY | Llegó a su hora (+1,4 h) y esperó ≈ 55 h a la deriva y merodeando al este del borde | **Error de escala** | Sí: escalas y `eta-v1` |
| ONE MANEUVER | Fondeó 30 h; su ETA era la del atraque (25 min de diferencia) | **ETA de atraque** | Igual que MSC FEBE |
| WEC CORNEILLE | Llegó al minuto (ETA 0,0 h), atracó, salió, volvió a fondear y atracó otra vez. La segunda escala hereda la ETA de la primera | **ETA de la escala anterior** | Sí: `eta-v1` |

**Ninguno de los 9 es un retraso real ni una ETA olvidada.** En los 7 casos de «error de escala» o
«ETA de la escala anterior», la ETA de la tripulación **acertó la llegada real con un margen de
−1,2 a +1,4 h**. El error de más de 24 h lo crea el método.

## Qué métodos convendría cambiar (propuestas, sin aplicar)

1. **Escalas (`escalas-v2` → posible `escalas-v3`): unir las esperas interrumpidas.** Ahora una
   espera se da por terminada («se fue sin atracar») si el buque pasa más de 12 h sin pararse por
   debajo de 1 nudo. Los portacontenedores **merodean** a 1–8 kn durante horas, o se alejan a
   esperar más lejos. Se mide en el servidor: **12 escalas «EXCLUIDA: sin atraque», de las que 7 van
   seguidas de una escala del mismo buque que atraca en menos de 72 h**, todas en terminales de
   contenedores y todas desde el 10/11 (TRADEWIND, PAOLO, EVER GIFTED, MSC ANZIO II, CMA CGM
   HARMONY, ELBIA, COSCO SHANGHAI). **Esto subestima las esperas**: MSC ANZIO II cuenta como 0 h
   en lugar de ≈ 44 h, EVER GIFTED como 0,4 h en lugar de ≈ 76 h y PAOLO como 6,4 h en lugar de
   ≈ 68 h. Dos ideas, por decidir:
   - que el merodeo dentro del área de espera (fondeadero o área ampliada) a menos de unos 8 kn
     mantenga viva la espera;
   - unir una escala «EXCLUIDA: sin atraque» con la siguiente del mismo buque si empieza en menos
     de X h (por ejemplo 48–72 h) y el buque no ha declarado otro puerto entre medias.
2. **`eta-v1`: no usar la ETA de la escala anterior.** Regla nueva: la ETA debe haberse
   **emitido después del final de la escala anterior** del mismo buque, y el momento de
   referencia también debe caer después; si no, el caso queda con un estado nuevo
   (`ESCALA_ANTERIOR`). Arregla MSC YUXIN, TROUPER y WEC CORNEILLE, y lo que quede de los
   demás después del punto 1.
3. **`eta-v1`: contar las «ETA de atraque».** No se deben quitar (es lo que declaró la tripulación),
   pero conviene marcar los casos cuya ETA está mucho más cerca del atraque que de la llegada
   (como MSC FEBE y ONE MANEUVER) y dar su porcentaje. Es un resultado en sí mismo: qué
   parte de los buques declara la hora de atraque en lugar de la de llegada.

No he cambiado ningún método, ni el código, ni los datos.
