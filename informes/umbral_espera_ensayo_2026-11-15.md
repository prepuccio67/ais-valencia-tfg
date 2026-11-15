# Umbral de espera de `escalas-v3`: ensayo con histéresis (15/11/2026)

Ensayo de **solo lectura** en el servidor, con datos del 29/10 al 15/11/2026 a las 20:40 UTC, sin
programar nada. En todas las variantes se aplica lo ya aprobado de `escalas-v3`: área de espera de
25 NM, espera viva mientras el buque esté en el área y unión de esperas partidas (72 h, sin otro
puerto entre medias). Las líneas temporales completas están en
`umbral_espera_ensayo_lineas_2026-11-15.txt`.

## Las cuatro reglas ensayadas
| Regla | La espera EMPIEZA | La espera CONTINÚA |
|---|---|---|
| **1,0 kn** | < 1 kn en el área | < 1 kn en el área |
| **3,9 kn** | < 3,9 kn en el área | < 3,9 kn en el área |
| **Histéresis** (la que pedía Marcos) | < 1 kn, o «fondeado» a < 3,9 kn | < 3,9 kn en el área |
| Histéresis + merodeo sostenido | como la histéresis, o ≥ 2 h seguidas en el área a < 3,9 kn | < 3,9 kn en el área |

**Espera en fondeadero:** tiempo dentro de los **fondeaderos oficiales** de la Resolución de la APV de
10/11/2020 (BOE-A-2020-15569): fondeo norte (39° 26,170′–27,251′ N; 0° 12,714′–14,804′ W) y fondeo sur
(39° 23,000′–24,297′ N; 0° 12,714′–17,029′ W). «Fondea» = al menos 1 h dentro.

## Resultados (escalas OK de portacontenedores iniciadas desde el 08/11 a las 17:05)
| Regla | n | Esperan ≥ 1 h | ≥ 3 h | Mediana | Media | P90 | Media de los que esperan ≥ 1 h |
|---|---|---|---|---|---|---|---|
| 1,0 kn | 27 | 59,3 % | 51,9 % | 3,1 h | 11,9 h | 36,7 h | 20,0 h |
| 3,9 kn | 26 | 69,2 % | 61,5 % | 5,9 h | 14,0 h | 40,1 h | 20,1 h |
| **Histéresis** | 27 | **59,3 %** | **55,6 %** | **3,4 h** | **12,7 h** | **40,1 h** | **21,4 h** |
| Histéresis + merodeo ≥ 2 h | 27 | 63,0 % | 59,3 % | 4,4 h | 13,1 h | 40,1 h | 20,8 h |

**Por terminal (histéresis):** MSC n = 17, 70,6 % ≥ 1 h, mediana 5,5 h; CSP n = 4, 75 %, mediana
21,1 h; APM n = 6, 16,7 %, mediana 0 h.
**Por eslora (histéresis):** < 150 m n = 4, 50 %; 150–200 m n = 5, 40 %; 200–300 m n = 10, 60 %;
≥ 300 m n = 8, 75 % (mediana 3,7 h, P90 6,6 h).

### Espera en fondeadero frente a la APV
| | APV 1.er semestre 2026 | AIS, histéresis, desde el 08/11 (n = 27) | AIS, histéresis, todo el periodo desde el 29/10 (n = 107) |
|---|---|---|---|
| % que fondea | 37,8 % | 18,5 % | **31,8 %** |
| Espera media de los que fondean | ≈ 44,8 h | 27,9 h | **51,0 h** |
| Buques ≥ 300 m que fondean (APV: ULCS y VLCS) | 8–12 % | **0 %** (0 de 8) | — |

- La espera en fondeadero **no depende de la zona de aproximación**: los dos fondeaderos oficiales
  están dentro del rectángulo VALENCIA. Por eso se puede medir desde el 29/10, con 107 escalas. Con
  ese periodo, **el AIS y la APV se parecen bastante** (31,8 % frente a 37,8 %; 51,0 h frente a 44,8 h).
- Con las tres reglas sale casi lo mismo en el fondeadero: el umbral solo cambia la espera fuera de él.

## Los 6 buques de 300 m o más que «esperan» con 3,9 kn
Ninguno entra en un fondeadero oficial (0 h los seis). **Esperan a la deriva o merodeando a 5–22 NM
al este**, fuera de la Zona II.

| Buque | Dónde y cómo esperó | 3,9 kn | Histéresis | 1,0 kn |
|---|---|---|---|---|
| TEXAS TRIUMPH (366 m, CSP) | 40 h a la deriva a 9–22 NM al E, casi siempre a < 1 kn | 40,1 h | 40,1 h | 40,1 h |
| MSC GAYANE (314 m, MSC) | 7 h a 13–16 NM al E, alternando < 1 kn y 1–3 kn | 7,1 h | 6,6 h | 6,6 h |
| MSC PAMELA (337 m, MSC) | ≈ 6 h a 7–12 NM al E, casi todo a 1–2 kn, con un rato a < 1 kn | 6,3 h | 5,7 h | 5,7 h |
| MSC NAIROBI X (300 m, MSC) | ≈ 4 h a 5–9 NM al E, entre < 1 y 3 kn | 4,4 h | 3,1 h | 3,1 h |
| HMM PERIDOT (336 m, CSP) | 2 h quieto (< 1 kn) a 8 NM al E, tras frenar 0,7 h | 2,7 h | 2,0 h | 2,0 h |
| ZIM XIAMEN (300 m, APM) | 5,6 h **alejándose despacio** (1,3–3,8 kn) de 12 a 22 NM al E y volviendo; nunca baja de 1 kn | 5,6 h | **0 h** | **0 h** |

**Qué dicen estos casos:**
- **La frenada de llegada sí se cuenta con 3,9 kn, pero pesa poco**: entre 0,3 y 0,7 h por buque
  (PAMELA, PERIDOT, NAIROBI X). La histéresis la quita.
- **La diferencia con la APV no se explica por el umbral, sino por el lugar.** Los buques grandes
  esperan de verdad (TEXAS TRIUMPH, 40 h), pero a la deriva fuera de la Zona II, donde la APV no lo
  cuenta como fondeo. En el fondeadero oficial, el AIS da 0 de 8, igual que el 8–12 % de la APV.
- **El caso dudoso es el «merodeo lento sin pararse»** (ZIM XIAMEN): el buque hace tiempo moviéndose a
  ≈ 2 kn sin llegar a pararse. Con la histéresis no cuenta como espera.

## Fichas de las 9 escalas que pasaban a DUDOSA con 3,9 kn
| Buque | Qué hizo | v2 | 3,9 kn | Histéresis | Lectura |
|---|---|---|---|---|---|
| MSC MELINE (301 m, MSC) | 14 min a 1–2 kn a 16 NM; navega a 13 kn hasta 5 NM y allí espera ≈ 10 h (< 1 kn a ratos) | 10,2 h OK | 12,1 h DUDOSA | **10,4 h OK** | Con 3,9 kn, la espera empezaba en un frenazo antes de seguir navegando: error. La histéresis acierta |
| OOCL HONG KONG (400 m, CSP) | 1 h a 2–3 kn a 13–14 NM, hueco de 5,8 h y llegada a 5–6 kn. Nunca baja de 1 kn | 0 h OK | 9,4 h DUDOSA | **0 h OK** | Aproximación lenta, no una espera parada |
| CHENNAI EXPRESS (304 m, APM) | 2,7 h a 1,6–1,8 kn a 11–14 NM y luego directo a 12 kn | 0 h OK | 2,9 h DUDOSA | **0 h OK** | Merodeo lento sin pararse (como ZIM XIAMEN) |
| MSC JASPER VIII (333 m, MSC) | Casi un día a 1,3–3,6 kn a 14 NM al E, con huecos de 6 y 11 h; luego < 1 kn 23 min a 7 NM | 0,6 h OK | 26,3 h DUDOSA | **1,5 h OK** | Probable espera larga en movimiento que la histéresis no ve. Con huecos tan largos, no se puede asegurar |
| MSC MANZANILLO V (294 m, MSC) | 1 h a 1–3,8 kn a 12–14 NM, hueco de 3,9 h y llegada a 11 kn | 0 h OK | 6,3 h DUDOSA | **0 h OK** | Sin datos para saber qué hizo en el hueco |
| ZIM ATLANTIC (262 m, CSP) | Espera ≈ 12 h a 13–15 NM al E (< 1 kn la mayor parte) | 9,9 h OK | 12,0 h DUDOSA | **11,7 h OK** | Con 3,9 kn salía «llegada no observada» por empezar 16 min antes. La histéresis acierta |
| NICARAGUA EXPRESS (270 m, APM) | Espera a 22–25 NM al E (< 1 kn), hueco de 2,3 h, vuelve y espera a 7 NM | 11,9 h OK | 13,4 h DUDOSA | 12,8 h DUDOSA | El hueco de 2,3 h (> 2 h) es real. Dudosa con cualquier regla |
| ELBIA (134 m, APM) | Fondeo sur 1,5 h; sale a 12 kn y merodea a 2 kn alejándose hasta 25 NM; hueco de 8 h; vuelve y atraca | 0 h OK | 17,7 h DUDOSA | 17,3 h DUDOSA | Espera real de ≈ 20 h con un hueco grande. Dudosa con cualquier regla |
| MSC NICOLA MASTRO (399 m, MSC) | ≈ 10 h a 2,2–3,4 kn a 22–25 NM al E, con huecos de 3–6 h; después 3 h a < 1 kn a 7 NM | 2,3 h OK | 22,0 h DUDOSA | **4,3 h OK** | Como JASPER VIII: probable espera en movimiento lejos, no medible con seguridad |

**Resumen:** con la histéresis, 7 de las 9 vuelven a ser OK. En 3 (MELINE, ZIM ATLANTIC y, en parte,
NICOLA MASTRO) la espera mejora respecto a v2. Las 2 que siguen dudosas lo son por huecos de señal
reales. En 4 (OOCL, CHENNAI, JASPER VIII, MANZANILLO) el buque **merodea despacio sin pararse**: la
histéresis no lo cuenta como espera.

## Recomendación
- **Histéresis** como regla principal: la espera empieza al pararse (< 1 kn o «fondeado») y continúa
  mientras el buque derive o merodee a < 3,9 kn en el área. Quita la frenada de llegada y los falsos
  inicios, y es fácil de explicar.
- **Contar aparte el «merodeo lento sin pararse»** (horas a < 3,9 kn en el área, sin bajar de 1 kn),
  como indicador de «espera en movimiento»: interesa para el JIT y las emisiones, aunque no sea
  espera parada.
- **Dar siempre dos esperas:** «en fondeadero oficial», comparable con la APV y medible desde el 29/10,
  y «total en el área de espera».
- **No adoptar** la variante «histéresis + merodeo sostenido»: recupera ZIM XIAMEN, pero no JASPER VIII
  ni NICOLA MASTRO (los huecos cortan el tramo), vuelve dudosas a CHENNAI EXPRESS y ZIM ATLANTIC, y
  complica el método.

No se ha cambiado ningún método, ni el código, ni los datos.
