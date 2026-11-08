# Instrucciones para Claude Code — sistema AIS del TFG

Este repositorio es la herramienta de datos del TFG de Marcos (GGTL, UPV): captura AIS
del Puerto de València y análisis de tiempos de espera en las terminales de contenedores.
Marcos sabe poco de programación: explica los pasos en lenguaje sencillo y en castellano.

## Al terminar cada sesión de trabajo (obligatorio)
Otra conversación de Claude (el proyecto «TFG» en claude.ai, que hace de tutor académico)
lee estos archivos para saber qué se ha hecho aquí. Antes de dar por terminada una sesión
en la que haya cambiado algo:

1. **`ROADMAP.md`**: mueve lo terminado a «Hecho», actualiza «En curso» y «Pendiente» y
   cambia la fecha de «Última actualización».
2. **`DECISIONES.md`**: añade una entrada `D-xx · fecha · título` por cada decisión nueva.
3. **`METODO.md`** y **`LIMITACIONES.md`**: actualízalos si cambia un método o aparece una
   limitación nueva.
4. **`../md/00_estado_TFG.md`** (fuera del repositorio, en `Desktop\TFG\md`):
   - añade una línea en «Hecho» con la fecha y un resumen de una frase;
   - actualiza «Pendiente esta semana» y la fecha de «Última actualización»;
   - si hay resultados con cifras (escalas, esperas, error de la ETA, CO₂…), anótalos en
     una línea con la fecha y el periodo de datos que cubren.
5. Haz commit de los cambios de documentación junto con el código.

## Nunca
- Escribas en estos archivos claves, tokens ni contenido de `.env` o `clave_api.txt`
  (el repositorio es público).
- Incluyas datos internos de la empresa de prácticas de Marcos ni nombres de sus clientes.
