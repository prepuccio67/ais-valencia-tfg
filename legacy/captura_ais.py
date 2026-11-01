# -*- coding: utf-8 -*-
"""
Captura de datos AIS del Puerto de Valencia (TFG - tiempos de espera)
Fuente: aisstream.io (gratuito). Guarda dos CSV por dia en la carpeta "datos":
  - posiciones_AAAA-MM-DD.csv  -> donde esta cada buque y a que velocidad
  - estaticos_AAAA-MM-DD.csv   -> quien es cada buque (IMO, tipo, eslora, destino)

Dos formas de usarlo:
  1) En tu PC, sin parar:          python captura_ais.py
  2) En la nube, por tandas:       python captura_ais.py --minutos 7
     (GitHub lo lanza solo cada 30 min; ver LEEME.md)

La clave se lee de la variable de entorno AISSTREAM_API_KEY (nube) o, si no
existe, del archivo clave_api.txt (PC). Para pararlo en el PC: Ctrl + C
"""
import argparse, asyncio, csv, json, os, sys, time
from datetime import datetime, timezone

try:
    import websockets
except ImportError:
    sys.exit("Falta la libreria 'websockets'. Ejecuta:  pip install websockets")

# Rectangulo de captura [latitud, longitud]: puerto + zona de fondeo (ajustable)
ZONA = [[39.25, -0.36], [39.60, 0.00]]
URL = "wss://stream.aisstream.io/v0/stream"
BASE = os.path.dirname(os.path.abspath(__file__))
CARPETA = os.path.join(BASE, "datos")

# Aclarado de datos: como mucho 1 posicion por buque cada N segundos.
# Un buque en movimiento emite cada 2-10 s; para medir esperas de horas sobra.
SEGUNDOS_ENTRE_POSICIONES = 60

COLS_POS = ["hora_recepcion_utc", "hora_ais_utc", "mmsi", "nombre", "lat", "lon",
            "velocidad_nudos", "rumbo", "proa", "estado_navegacion"]
COLS_EST = ["hora_recepcion_utc", "mmsi", "imo", "nombre", "indicativo", "tipo_buque",
            "eslora_m", "manga_m", "calado_m", "destino"]


def leer_clave():
    clave = os.environ.get("AISSTREAM_API_KEY", "").strip()
    if clave:
        return clave
    ruta = os.path.join(BASE, "clave_api.txt")
    if not os.path.exists(ruta):
        sys.exit("No hay clave: crea clave_api.txt con tu clave de aisstream.io "
                 "o define la variable AISSTREAM_API_KEY")
    clave = open(ruta, encoding="utf-8").read().strip()
    if not clave or "PEGA" in clave:
        sys.exit("clave_api.txt esta vacio: pega tu clave de aisstream.io")
    return clave


def campo(d, *nombres):
    """Busca un campo sin importar mayusculas/minusculas."""
    if not isinstance(d, dict):
        return None
    bajos = {k.lower(): v for k, v in d.items()}
    for n in nombres:
        if n.lower() in bajos:
            return bajos[n.lower()]
    return None


def escribir(prefijo, columnas, fila):
    os.makedirs(CARPETA, exist_ok=True)
    dia = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ruta = os.path.join(CARPETA, f"{prefijo}_{dia}.csv")
    nuevo = not os.path.exists(ruta)
    with open(ruta, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if nuevo:
            w.writerow(columnas)
        w.writerow(fila)


class Estado:
    def __init__(self, cada=SEGUNDOS_ENTRE_POSICIONES):
        self.cada = cada
        self.pos = 0
        self.est = 0
        self.ultima_pos = {}      # mmsi -> instante (s) de la ultima posicion guardada
        self.fichas_pos = 0       # posiciones obtenidas de las fichas (sin velocidad)
        self.firma_est = {}       # mmsi -> (dia, datos) de la ultima ficha guardada
        self._cargar_fichas_de_hoy()

    def _cargar_fichas_de_hoy(self):
        """Evita repetir fichas ya guardadas hoy (importante en el modo por tandas)."""
        dia = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        ruta = os.path.join(CARPETA, f"estaticos_{dia}.csv")
        if not os.path.exists(ruta):
            return
        with open(ruta, encoding="utf-8") as f:
            for fila in csv.DictReader(f):
                datos = [fila[c] for c in COLS_EST[2:]]
                self.firma_est[_mmsi_clave(fila["mmsi"])] = (dia, tuple(datos))


def _mmsi_clave(m):
    try:
        return int(m)
    except (TypeError, ValueError):
        return m


def _txt(v):
    return "" if v is None else str(v)


def procesar(msg, st):
    ahora_dt = datetime.now(timezone.utc)
    ahora = ahora_dt.strftime("%Y-%m-%d %H:%M:%S")
    tipo = msg.get("MessageType")
    meta = msg.get("MetaData", {}) or {}
    cuerpo = (msg.get("Message", {}) or {}).get(tipo, {}) or {}
    mmsi = _mmsi_clave(campo(meta, "MMSI") or campo(cuerpo, "UserID"))
    nombre = (campo(meta, "ShipName") or "").strip()

    if tipo == "PositionReport":
        t = time.time()
        if t - st.ultima_pos.get(mmsi, 0) < st.cada:
            return
        st.ultima_pos[mmsi] = t
        escribir("posiciones", COLS_POS, [
            ahora, campo(meta, "time_utc"), mmsi, nombre,
            campo(meta, "latitude") or campo(cuerpo, "Latitude"),
            campo(meta, "longitude") or campo(cuerpo, "Longitude"),
            campo(cuerpo, "Sog"), campo(cuerpo, "Cog"), campo(cuerpo, "TrueHeading"),
            campo(cuerpo, "NavigationalStatus")])
        st.pos += 1
    elif tipo == "ShipStaticData":
        posicion_de_ficha(msg, st, mmsi, nombre, ahora)
        dim = campo(cuerpo, "Dimension") or {}
        a, b, c, d = (campo(dim, x) for x in "ABCD")
        eslora = (a or 0) + (b or 0) if (a or b) else None
        manga = (c or 0) + (d or 0) if (c or d) else None
        datos = [campo(cuerpo, "ImoNumber"), (campo(cuerpo, "Name") or nombre).strip(),
                 (campo(cuerpo, "CallSign") or "").strip(), campo(cuerpo, "Type"),
                 eslora, manga, campo(cuerpo, "MaximumStaticDraught"),
                 (campo(cuerpo, "Destination") or "").strip()]
        # Solo se guarda la ficha si es nueva hoy o ha cambiado (p. ej. destino o calado)
        firma = (ahora_dt.strftime("%Y-%m-%d"), tuple(map(_txt, datos)))
        if st.firma_est.get(mmsi) == firma:
            return
        st.firma_est[mmsi] = firma
        escribir("estaticos", COLS_EST, [ahora, mmsi] + datos)
        st.est += 1


def posicion_de_ficha(msg, st, mmsi, nombre, ahora):
    """La fuente no retransmite todas las posiciones, pero cada ficha trae la ultima
    posicion conocida del buque. Se guarda SIN velocidad (marcada como 'ficha') si no
    hay una posicion real reciente de ese buque. procesar.py la trata aparte."""
    meta = msg.get("MetaData", {}) or {}
    lat, lon = campo(meta, "latitude"), campo(meta, "longitude")
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return
    (la1, lo1), (la2, lo2) = ZONA
    if not (min(la1, la2) <= lat <= max(la1, la2) and min(lo1, lo2) <= lon <= max(lo1, lo2)):
        return
    if time.time() - st.ultima_pos.get(mmsi, 0) < st.cada:
        return
    escribir("posiciones", COLS_POS, [ahora, "ficha " + str(campo(meta, "time_utc") or ""),
                                      mmsi, nombre, lat, lon, "", "", "", ""])
    st.fichas_pos += 1


async def capturar(minutos=None, cada=SEGUNDOS_ENTRE_POSICIONES):
    clave = leer_clave()
    st = Estado(cada)
    fin = time.time() + minutos * 60 if minutos else None
    espera = 5
    while fin is None or time.time() < fin:
        try:
            async with websockets.connect(URL, ping_interval=20, ping_timeout=20) as ws:
                await ws.send(json.dumps({
                    "APIKey": clave,
                    "BoundingBoxes": [ZONA],
                    "FilterMessageTypes": ["PositionReport", "ShipStaticData"]}))
                print(f"[{datetime.now():%H:%M:%S}] Conectado. Capturando...", flush=True)
                espera = 5
                while fin is None or time.time() < fin:
                    restante = None if fin is None else max(1, fin - time.time())
                    try:
                        texto = await asyncio.wait_for(ws.recv(), timeout=restante)
                    except asyncio.TimeoutError:
                        break
                    msg = json.loads(texto)
                    if "error" in msg:
                        print("Error del servidor:", msg["error"], flush=True)
                        break
                    procesar(msg, st)
                    total = st.pos + st.est
                    if total and total % 200 == 0:
                        print(f"[{datetime.now():%H:%M:%S}] posiciones: {st.pos} | fichas: {st.est}", flush=True)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(f"[{datetime.now():%H:%M:%S}] Conexion perdida ({e}). Reintento en {espera} s", flush=True)
            if fin is not None and time.time() + espera >= fin:
                break
            await asyncio.sleep(espera)
            espera = min(espera * 2, 300)
    print(f"Fin de la tanda: {st.pos} posiciones, {st.fichas_pos} posiciones de ficha "
          f"y {st.est} fichas guardadas.", flush=True)
    return st


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Captura AIS Puerto de Valencia")
    p.add_argument("--minutos", type=float, default=None,
                   help="Capturar solo N minutos y terminar (modo nube). Sin esto, captura sin parar.")
    p.add_argument("--cada-segundos", type=int, default=SEGUNDOS_ENTRE_POSICIONES,
                   help="Guardar como mucho 1 posicion por buque cada N segundos (por defecto 60)")
    args = p.parse_args()
    try:
        asyncio.run(capturar(args.minutos, args.cada_segundos))
    except KeyboardInterrupt:
        print("\nCaptura detenida. Los datos estan en la carpeta 'datos'.")
