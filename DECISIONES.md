# Registro de decisiones

Cada entrada recoge: fecha, decisión, alternativas consideradas y motivo. Las
fuentes de la Fase 0 se consultaron el 28/10/2026.

---

## D-01 · 27/10/2026 · Abandonar GitHub Actions como capturador principal
- **Decisión:** migrar la captura a un servidor encendido 24/7.
- **Alternativas:** seguir con GitHub Actions cada 30 min; usar el PC personal.
- **Motivo:** el primer día GitHub ejecutó muy pocas de las tareas programadas.
  Hubo unos 70 min de datos en 21 h, con huecos de hasta 7 h. El PC no está
  siempre encendido. GitHub Actions sigue funcionando hasta que el servidor
  capture, porque algunos datos son mejor que ninguno.

## D-02 · 28/10/2026 · Fuente doble: OpenSeaFeed + aisstream.io a la vez
- **Decisión:** capturar de las dos fuentes al mismo tiempo, guardando de qué
  fuente procede cada posición.
- **Alternativas:** solo OpenSeaFeed (la del tutor); solo aisstream; una
  principal y otra de reserva.
- **Motivo:**
  - Las dos son gratuitas y usan el mismo formato de mensajes, así que el coste
    extra es mínimo.
  - OpenSeaFeed se declara «early development», no tiene garantía de servicio y
    no sabemos qué receptor cubre València.
  - aisstream tampoco ofrece garantía de servicio.
  - Con las dos a la vez, la caída de una no deja hueco, y se puede comparar su
    cobertura para la memoria.
- **Fuentes:** [openseafeed.com](https://www.openseafeed.com/),
  [API OpenSeaFeed](https://openseafeed.com/docs.html),
  [README OpenSeaFeed](https://github.com/BetterInc/openseafeed) (datos CC BY 4.0),
  [documentación aisstream](https://aisstream.io/documentation).

## D-03 · 28/10/2026 · Oracle Cloud con cuenta de pago por uso
- **Decisión:** usar Oracle Cloud y pasar la cuenta a pago por uso (Pay As You
  Go), con alerta de presupuesto y cuotas. Decidido por Marcos.
- **Alternativas:** cuenta solo Always Free (gratuita); otro proveedor de pago
  (unos 4–5 €/mes); una Raspberry Pi en casa.
- **Motivo:**
  - Oracle puede recuperar las máquinas Always Free «inactivas»: menos del 20 %
    de CPU (percentil 95) y de red durante 7 días, y en A1 también de memoria.
    Un capturador AIS cumple ese perfil.
  - Oracle comunicó que la recuperación afecta a clientes «Always Free only»;
    lo hemos visto citado en su foro, no en la documentación [VERIFICAR].
  - Lo Always Free sigue siendo gratis tras pasar a pago por uso.
  - Los presupuestos solo avisan (se revisan cada 24 h) y no bloquean el gasto,
    de ahí las cuotas.
- **Fuentes:** [Always Free Resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm),
  [Budgets](https://docs.oracle.com/en-us/iaas/Content/Billing/Concepts/budgetsoverview.htm),
  [FAQ Free Tier](https://www.oracle.com/cloud/free/faq/),
  [foro Oracle](https://community.oracle.com/customerconnect/discussion/672339).

## D-04 · 28/10/2026 · Python + aiohttp + SQLite + Leaflet (propuesta)
- **Decisión:** el Collector y la API en Python 3.12 con `aiohttp`, una SQLite
  por zona y un visor web con Leaflet.
- **Alternativas:** C#/.NET como el tutor; FastAPI; PostgreSQL/PostGIS.
- **Motivo:**
  - Ya hay código en Python y el servidor es Linux.
  - `aiohttp` cubre a la vez el cliente WebSocket con compresión y el servidor
    HTTP, con una sola dependencia.
  - SQLite reproduce el diseño del tutor (un archivo por zona y periodo) sin
    servidor de base de datos, que en 1 GB de RAM sería una carga.

## D-05 · 28/10/2026 · Muestreo en lugar de guardar todos los mensajes (propuesta)
- **Decisión:**
  - 1 posición por minuto si el buque se mueve y 1 cada 10 min si está parado;
  - siempre al cambiar el estado de navegación o al pasar de parado a en marcha
    (o al revés).
- **Alternativas:** guardar todo (unas 10 veces más volumen); intervalo fijo
  para todos.
- **Motivo:** los tiempos de espera se miden en horas, así que con precisión de
  minutos basta. Las reglas por evento conservan las horas exactas de atraque y
  salida. Volumen estimado: unos 6 MB/día.

## D-06 · 28/10/2026 · Acceso al visor por túnel SSH (propuesta)
- **Decisión:** la API solo escucha dentro del servidor y se accede mediante un
  túnel SSH. Además, el token es obligatorio.
- **Alternativas:** HTTPS público con token.
- **Motivo:** solo hay que abrir un puerto (22). No hace falta dominio ni
  certificado. La API no queda expuesta a Internet.

## D-07 · 28/10/2026 · Datos en un disco separado del sistema (propuesta)
- **Decisión:** un block volume de 100 GB montado en `/srv/ais`.
- **Alternativas:** todo en el disco de arranque.
- **Motivo:** si hubiera que recrear la máquina, los datos se conectan a la
  nueva sin copiarlos. Además facilita mover segmentos (fase 6).

## D-08 · 28/10/2026 · Histéresis de velocidad 0,3 / 0,5 kn en el muestreo
- **Decisión:**
  - un buque parado pasa a «en movimiento» con ≥ 0,5 kn;
  - uno en movimiento pasa a «parado» con < 0,3 kn.
  - El cambio de estado se guarda siempre, aunque llegue a menos de 10 s del guardado anterior: queda pendiente y se guarda con el mensaje siguiente.
- **Alternativas:** un único umbral de 0,5 kn; una histéresis de 0,5 / 1,0 kn (primera versión).
- **Motivo:**
  - Con un único umbral, un buque atracado cuya velocidad «tiembla» alrededor de 0,5 kn dispararía un guardado en cada mensaje.
  - Con 0,5 / 1,0 kn, un desatraque lento (0,5–1,0 kn, con remolcadores) no se registraba como evento y la hora de salida quedaba sesgada hacia tarde.
  - 0,5 kn coincide con el umbral de «atracado» del análisis de escalas.

## D-09 · 28/10/2026 · Revisión adversarial del código antes de desplegar
- **Decisión:** antes de dejar el Collector capturando 24/7, revisarlo con varios revisores automáticos independientes. Cada uno se centró en un aspecto: captura, robustez, base de datos, API y calidad del dato. Después, un verificador escéptico intentó refutar cada hallazgo ejecutando pruebas.
- **Resultado:**
  - 1.ª ronda: 25 hallazgos, de los que se confirmaron 22 (1 de gravedad alta: conexión que podía quedarse colgada sin capturar) y se refutaron 3.
  - 2.ª ronda, de verificación de las correcciones: 13 resueltas del todo, 6 parciales y 11 problemas nuevos (2 de gravedad alta en el reintento de escrituras).
  - Todo quedó corregido y cubierto por tests automáticos: 56 en total.
- **Alternativas:** solo tests escritos por el autor.
- **Motivo:** cada dato perdido es irrecuperable. Los fallos de robustez (cortes de red, base bloqueada, disco lleno) no aparecen en una prueba corta, pero sí en 6 meses de funcionamiento.

## D-10 · 28/10/2026 · Las posiciones sin hora de la fuente se descartan
- **Decisión:**
  - Se guarda la hora AIS que da la fuente y, aparte, la hora de recepción.
  - Las posiciones sin hora, con más de 15 min de antigüedad o más de 2 min en el futuro se descartan y se cuentan en el registro de sucesos.
  - Esas posiciones tampoco cuentan como cobertura.
- **Alternativas:** usar la hora de recepción cuando falte la de la fuente.
- **Motivo:** OpenSeaFeed reenvía las últimas posiciones conocidas al conectar. Sin la hora original, una posición antigua pasaría por actual y falsearía las horas de llegada y salida.

## D-11 · 29/10/2026 · Máquina Ampere A1 (ARM) en lugar de E2.1.Micro
- **Decisión:**
  - Máquina VM.Standard.A1.Flex con 1 OCPU, 6 GB de RAM y Ubuntu 24.04 Minimal (aarch64), en Oracle Madrid (eu-madrid-1).
  - Cuenta pasada a pago por uso, con alerta de presupuesto de 1 €.
  - Collector `VALENCIA-01` capturando desde el 29/10/2026 a las 19:33 UTC.
- **Alternativas:** VM.Standard.E2.1.Micro (1 GB de RAM); esperar a que haya capacidad.
- **Motivo:**
  - Al crear la E2.1.Micro, Oracle respondió «Out of capacity», y Madrid solo tiene una zona de disponibilidad.
  - La A1 también es Always Free (hasta 2 OCPU y 12 GB en total) y tenía capacidad.
  - El código es Python puro y funciona igual en ARM: los 56 tests pasan en el servidor.
  - Con 1 OCPU y 6 GB se usa la mitad de lo gratuito y queda margen para un segundo Collector.
- **Nota:** al pasar a pago por uso, Oracle retiene temporalmente 100 USD (unos 93 €) en la tarjeta para verificarla y los libera después ([documentación oficial](https://docs.oracle.com/iaas/Content/Billing/Tasks/changingpaymentmethod.htm)).

## D-12 · 29/10/2026 · Visor web servido por el propio Collector
- **Decisión:**
  - El visor es una página web (HTML + JavaScript + Leaflet 1.9.4) que sirve el
    Collector en `/`. Se abre por el túnel SSH con `deploy/abrir_visor.ps1`.
  - La página no contiene datos: los pide a la API con el token.
  - Leaflet se incluye dentro del proyecto (`viewer/vendor`), comprobado con su
    huella SHA-256 oficial, en lugar de cargarlo desde una CDN.
- **Alternativas:** aplicación de escritorio como la del tutor (WPF); una web
  aparte en GitHub Pages; frameworks como React.
- **Motivo:**
  - No hay que instalar nada: sirve cualquier navegador.
  - Los datos nunca salen a Internet: solo viajan por el túnel cifrado.
  - Con JavaScript sencillo, sin frameworks, el código se puede leer y
    defender.
  - Al no usar una CDN (un servidor externo que reparte librerías), el visor no
    depende de terceros, salvo para las teselas del mapa de OpenStreetMap.

## D-13 · 29/10/2026 · Cambios de zona aplicados con recarga ordenada en caliente
- **Decisión:**
  - Al crear, editar, activar o desactivar una zona, se valida y se escribe su
    `zone.json`. Después el Collector se para de forma ordenada (guardando todo)
    y vuelve a arrancar dentro del mismo proceso, en 1–2 s.
  - La pausa queda registrada como hueco `maintenance` y el cambio de geometría
    como suceso `zone_config_changed`, con la versión anterior y la nueva.
  - Los cambios solo se aceptan con el token en la cabecera HTTP, no en la
    dirección web.
- **Alternativas:** cambiar cada pieza en marcha (suscripciones, trabajadores,
  bases) sin parar; obligar a reiniciar el servicio a mano.
- **Motivo:**
  - La recarga reutiliza el arranque y la parada, que ya están probados
    (reinicio de la máquina, cortes de red), en lugar de añadir lógica nueva y
    delicada.
  - Una pausa de 1–2 s, registrada, es aceptable para cambios que se hacen muy
    pocas veces.
  - Exigir el token en la cabecera impide que otra página abierta en el
    navegador pueda modificar las zonas.
- **Límites:** rectángulo envolvente de 25 grados² como máximo, 200 vértices y
  ningún polígono que se cruce consigo mismo. Una zona enorme saturaría la
  máquina, y un polígono «en lazo» no delimita un área con sentido.
