# -*- coding: utf-8 -*-
"""
Procesado de los datos AIS -> escalas y tiempos de espera -> cuadro de mando.

Lee   datos/posiciones_*.csv y datos/estaticos_*.csv  (los genera captura_ais.py)
      zonas.json                                       (recinto portuario, terminales, parametros)
Crea  salidas/escalas.csv     -> una fila por escala (para analizar en Excel)
      salidas/cobertura.csv   -> posiciones recibidas por hora (para ver huecos)
      docs/index.html         -> cuadro de mando (se abre con el navegador)

Uso:  python procesar.py
Solo usa librerias estandar de Python (no hay que instalar nada).

METODO (resumen para la memoria del TFG)
Cada posicion se clasifica en una zona:
  - ATRACADO : dentro del recinto portuario y velocidad <= 0,5 nudos
  - MANIOBRA : dentro del recinto portuario y en movimiento
  - FONDEO   : fuera del recinto y velocidad <= 1 nudo (o estado AIS 1 = fondeado)
  - NAVEGANDO: el resto
Una ESCALA empieza en el primer punto de FONDEO o, si el buque entra directo,
en el primer ATRACADO. Termina cuando el buque, ya atracado, vuelve a estar
fuera del recinto.
  Tiempo de espera   = hora de atraque - hora de llegada al fondeo (0 si entra directo)
  Tiempo de estancia = ultima hora atracado - hora de atraque
La precision depende de la frecuencia de captura (en la nube, ~30 min).
"""
import csv, glob, json, math, os, statistics
from collections import defaultdict, Counter
from datetime import datetime, timedelta, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
DATOS = os.path.join(BASE, "datos")
SALIDAS = os.path.join(BASE, "salidas")
DOCS = os.path.join(BASE, "docs")


# ---------------------------------------------------------------- utilidades
def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def hora(v):
    try:
        return datetime.strptime(v[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def dentro(lat, lon, poligono):
    """Punto en poligono (ray casting). Poligono = [[lat, lon], ...]."""
    res = False
    n = len(poligono)
    for i in range(n):
        y1, x1 = poligono[i]
        y2, x2 = poligono[(i + 1) % n]
        if (y1 > lat) != (y2 > lat):
            x_corte = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
            if lon < x_corte:
                res = not res
    return res


def millas(a, b):
    """Distancia en millas nauticas entre dos puntos (formula del haversine)."""
    la1, lo1, la2, lo2 = map(math.radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 3440.065 * math.asin(math.sqrt(h))


def fmt(t):
    return t.strftime("%Y-%m-%d %H:%M") if t else ""


# ---------------------------------------------------------------- lectura
def leer_zonas():
    with open(os.path.join(BASE, "zonas.json"), encoding="utf-8") as f:
        return json.load(f)


def leer_estaticos():
    fichas = {}
    for ruta in sorted(glob.glob(os.path.join(DATOS, "estaticos_*.csv"))):
        with open(ruta, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                m = r.get("mmsi")
                if not m:
                    continue
                prev = fichas.get(m, {})
                # nos quedamos con el ultimo valor no vacio de cada campo
                for k, v in r.items():
                    if v not in (None, "", "None", "0", "0.0") or k not in prev:
                        prev[k] = v
                fichas[m] = prev
    return fichas


def leer_posiciones():
    pos = defaultdict(list)
    for ruta in sorted(glob.glob(os.path.join(DATOS, "posiciones_*.csv"))):
        with open(ruta, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                t = hora(r.get("hora_recepcion_utc"))
                lat, lon = num(r.get("lat")), num(r.get("lon"))
                if t is None or lat is None or lon is None:
                    continue
                pos[r["mmsi"]].append({
                    "t": t, "lat": lat, "lon": lon,
                    "sog": num(r.get("velocidad_nudos")),
                    "nav": num(r.get("estado_navegacion")),
                    "nombre": (r.get("nombre") or "").strip()})
    for m in pos:
        pos[m].sort(key=lambda p: p["t"])
        estimar_velocidad(pos[m])
    return pos


def estimar_velocidad(puntos):
    """Las posiciones sacadas de las fichas no traen velocidad. Se estima con el
    desplazamiento respecto a la posicion anterior del mismo buque (distancia / tiempo),
    solo si entre ambas hay entre 3 minutos y 3 horas. Si no se puede, queda sin
    velocidad y ese punto solo sirve para saber que el buque sigue en la zona."""
    for i, p in enumerate(puntos):
        p["estimada"] = False
        if p["sog"] is not None or i == 0:
            continue
        ant = puntos[i - 1]
        horas = (p["t"] - ant["t"]).total_seconds() / 3600
        if 0.05 <= horas <= 3:
            p["sog"] = round(millas(ant, p) / horas, 2)
            p["estimada"] = True


# ---------------------------------------------------------------- clasificacion
def clasificar(p, zonas):
    par = zonas["parametros"]
    sog = p["sog"] if p["sog"] is not None else 99
    if dentro(p["lat"], p["lon"], zonas["recinto_portuario"]):
        if sog <= par["velocidad_max_atracado_nudos"]:
            terminal = "Sin asignar"
            for t in zonas.get("terminales", []):
                if dentro(p["lat"], p["lon"], t["poligono"]):
                    terminal = t["nombre"]
                    break
            return "ATRACADO", terminal
        return "MANIOBRA", None
    if sog <= par["velocidad_max_fondeo_nudos"] or p["nav"] == 1:
        return "FONDEO", None
    return "NAVEGANDO", None


def huecos_globales(pos, horas_min=2):
    """Periodos sin NINGUNA posicion recibida (fallo de captura)."""
    tiempos = sorted({p["t"].replace(second=0) for lst in pos.values() for p in lst})
    huecos = []
    for a, b in zip(tiempos, tiempos[1:]):
        if (b - a) > timedelta(hours=horas_min):
            huecos.append((a, b))
    return tiempos[0] if tiempos else None, tiempos[-1] if tiempos else None, huecos


def detectar_escalas(mmsi, puntos, zonas, inicio_datos, huecos, fin_datos=None):
    par = zonas["parametros"]
    hueco_max = timedelta(hours=par["hueco_max_horas"])
    max_fondeo = timedelta(days=par["dias_max_fondeo_sin_atraque"])
    escalas, actual, previo = [], None, None

    def censurada(t):
        if inicio_datos and t - inicio_datos < timedelta(hours=1):
            return True
        return any(b <= t < b + timedelta(hours=1) for _, b in huecos)

    def cerrar(motivo):
        nonlocal actual
        if actual:
            actual["cierre"] = motivo
            escalas.append(actual)
        actual = None

    for p in puntos:
        t = p["t"]
        if p["sog"] is None and p["nav"] is None:
            # punto sin velocidad: solo confirma que el buque sigue aqui
            if actual and previo and t - previo <= hueco_max:
                if actual["t_atraque"] and dentro(p["lat"], p["lon"], zonas["recinto_portuario"]):
                    actual["t_ultimo_atracado"] = t
                previo = t
            continue
        zona, terminal = clasificar(p, zonas)
        # hueco largo sin datos de este buque -> la escala se da por cerrada
        if actual and previo and t - previo > hueco_max:
            cerrar("hueco de datos" if not actual["t_atraque"] else "salida")
        # fondeo demasiado largo sin atracar -> no era una espera para atracar
        if actual and not actual["t_atraque"] and actual["t_fondeo"] and t - actual["t_fondeo"] > max_fondeo:
            cerrar("fondeo sin atraque")

        if zona == "FONDEO":
            if actual and actual["t_atraque"]:
                cerrar("salida")
            if not actual:
                actual = {"mmsi": mmsi, "t_fondeo": t, "t_fin_fondeo": t, "t_atraque": None,
                          "t_ultimo_atracado": None, "terminal": None, "censurada": censurada(t)}
            elif not actual["t_atraque"]:
                actual["t_fin_fondeo"] = t
        elif zona == "ATRACADO":
            if not actual:
                actual = {"mmsi": mmsi, "t_fondeo": None, "t_fin_fondeo": None, "t_atraque": t,
                          "t_ultimo_atracado": t, "terminal": terminal, "censurada": censurada(t)}
            else:
                if not actual["t_atraque"]:
                    actual["t_atraque"] = t
                    actual["terminal"] = terminal
                actual["t_ultimo_atracado"] = t
        elif zona == "NAVEGANDO":
            if actual and actual["t_atraque"]:
                cerrar("salida")
        previo = t
    if actual:
        # si el buque lleva mas de "hueco_max" sin aparecer, ya se fue (salida no observada)
        if fin_datos and previo and fin_datos - previo > hueco_max:
            cerrar("salida" if actual["t_atraque"] else "fondeo sin atraque")
        else:
            actual["cierre"] = "en curso"
            escalas.append(actual)
    return escalas


# ---------------------------------------------------------------- calculo
def calcular():
    zonas = leer_zonas()
    par = zonas["parametros"]
    fichas = leer_estaticos()
    pos = leer_posiciones()
    inicio, fin, huecos = huecos_globales(pos)

    def ficha(m):
        f = fichas.get(m, {})
        nombre = (f.get("nombre") or "").strip() or next((p["nombre"] for p in pos.get(m, []) if p["nombre"]), "")
        return {"nombre": nombre, "imo": f.get("imo", ""), "tipo": num(f.get("tipo_buque")),
                "eslora": num(f.get("eslora_m")), "calado": num(f.get("calado_m")),
                "destino": f.get("destino", "")}

    def incluido(fi):
        tmin, tmax = par["tipos_buque_incluidos"]
        if fi["tipo"] is None or not (tmin <= fi["tipo"] <= tmax):
            return False
        if fi["eslora"] is not None and fi["eslora"] < par["eslora_minima_m"]:
            return False
        return True

    escalas, excluidos = [], Counter()
    for m, puntos in pos.items():
        fi = ficha(m)
        if not incluido(fi):
            excluidos["sin ficha" if fi["tipo"] is None else "otro tipo/eslora"] += 1
            continue
        for e in detectar_escalas(m, puntos, zonas, inicio, huecos, fin):
            e.update(fi)
            if e["t_atraque"]:
                e["espera_h"] = round((e["t_atraque"] - e["t_fondeo"]).total_seconds() / 3600, 1) if e["t_fondeo"] else 0.0
                e["estancia_h"] = round((e["t_ultimo_atracado"] - e["t_atraque"]).total_seconds() / 3600, 1)
            else:
                e["espera_h"] = None
                e["estancia_h"] = None
            # valida para estadisticas: ha atracado y no empezo a mitad (sin censura)
            e["valida"] = bool(e["t_atraque"]) and not e["censurada"]
            escalas.append(e)
    escalas.sort(key=lambda e: e["t_fondeo"] or e["t_atraque"])

    # estado actual (ultimo punto de cada buque incluido, si es reciente)
    ahora = []
    if fin:
        for m, puntos in pos.items():
            fi = ficha(m)
            p = puntos[-1]
            if fin - p["t"] > timedelta(hours=2):
                continue
            zona, terminal = clasificar(p, zonas)
            ahora.append({"mmsi": m, "nombre": fi["nombre"], "lat": p["lat"], "lon": p["lon"],
                          "zona": zona, "incluido": incluido(fi), "eslora": fi["eslora"]})

    # puntos de atraque (para calibrar las terminales): buques incluidos parados en el recinto
    calib = Counter()
    for m, puntos in pos.items():
        if not incluido(ficha(m)):
            continue
        for p in puntos:
            if clasificar(p, zonas)[0] == "ATRACADO":
                calib[(round(p["lat"], 4), round(p["lon"], 4))] += 1

    # cobertura por hora
    cob = Counter(p["t"].strftime("%Y-%m-%d %H:00") for lst in pos.values() for p in lst)
    return {"zonas": zonas, "escalas": escalas, "ahora": ahora, "calib": calib, "cobertura": cob,
            "inicio": inicio, "fin": fin, "huecos": huecos, "excluidos": excluidos,
            "n_buques": len(pos)}


# ---------------------------------------------------------------- salidas
def guardar_csv(r):
    os.makedirs(SALIDAS, exist_ok=True)
    cols = ["mmsi", "imo", "nombre", "tipo", "eslora", "calado", "destino", "terminal",
            "t_fondeo", "t_fin_fondeo", "t_atraque", "t_ultimo_atracado",
            "espera_h", "estancia_h", "censurada", "valida", "cierre"]
    with open(os.path.join(SALIDAS, "escalas.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(cols)
        for e in r["escalas"]:
            fila = []
            for c in cols:
                v = e.get(c)
                if isinstance(v, datetime):
                    v = fmt(v)
                elif isinstance(v, float):
                    v = str(v).replace(".", ",")   # Excel en castellano
                fila.append("" if v is None else v)
            w.writerow(fila)
    with open(os.path.join(SALIDAS, "cobertura.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["hora_utc", "posiciones"])
        for k in sorted(r["cobertura"]):
            w.writerow([k, r["cobertura"][k]])


def resumen(r):
    val = [e for e in r["escalas"] if e["valida"]]
    esperas = [e["espera_h"] for e in val]

    def bloque(lista):
        es = [e["espera_h"] for e in lista]
        return {"n": len(es),
                "mediana": round(statistics.median(es), 1) if es else None,
                "media": round(statistics.mean(es), 1) if es else None}

    # por semana (lunes) de atraque
    sem = defaultdict(list)
    for e in val:
        lunes = (e["t_atraque"] - timedelta(days=e["t_atraque"].weekday())).strftime("%Y-%m-%d")
        sem[lunes].append(e)
    por_semana = [{"semana": k, **bloque(v)} for k, v in sorted(sem.items())]

    ter = defaultdict(list)
    for e in val:
        ter[e["terminal"] or "Sin asignar"].append(e)
    por_terminal = [{"terminal": k, **bloque(v)} for k, v in sorted(ter.items())]

    def tramo(e):
        L = e["eslora"]
        if L is None:
            return "Desconocida"
        return "< 200 m" if L < 200 else ("200–299 m" if L < 300 else "≥ 300 m")
    orden = ["< 200 m", "200–299 m", "≥ 300 m", "Desconocida"]
    tr = defaultdict(list)
    for e in val:
        tr[tramo(e)].append(e)
    por_eslora = [{"tramo": k, **bloque(tr[k])} for k in orden if tr.get(k)]

    limites = [(0, 0.05, "Sin espera"), (0.05, 6, "0–6 h"), (6, 12, "6–12 h"), (12, 24, "12–24 h"),
               (24, 48, "24–48 h"), (48, 1e9, "> 48 h")]
    histo = [{"tramo": et, "n": sum(1 for x in esperas if a <= x < b)} for a, b, et in limites]

    cob = r["cobertura"]
    horas_totales = int((r["fin"] - r["inicio"]).total_seconds() // 3600) + 1 if r["inicio"] else 0
    dias = Counter()
    for k, v in cob.items():
        dias[k[:10]] += v

    return {
        "actualizado": fmt(datetime.now(timezone.utc)),
        "inicio": fmt(r["inicio"]), "fin": fmt(r["fin"]),
        "horas_con_datos": len(cob), "horas_totales": horas_totales,
        "n_huecos": len(r["huecos"]),
        "huecos": [[fmt(a), fmt(b)] for a, b in r["huecos"]][-20:],
        "n_buques": r["n_buques"],
        "excluidos": dict(r["excluidos"]),
        "kpi": {**bloque(val),
                "con_espera_pct": round(100 * sum(1 for x in esperas if x > 0.05) / len(esperas)) if esperas else None,
                "p90": round(sorted(esperas)[int(0.9 * (len(esperas) - 1))], 1) if esperas else None,
                "fondeados_ahora": sum(1 for a in r["ahora"] if a["incluido"] and a["zona"] == "FONDEO"),
                "atracados_ahora": sum(1 for a in r["ahora"] if a["incluido"] and a["zona"] == "ATRACADO"),
                "en_curso": sum(1 for e in r["escalas"] if e["cierre"] == "en curso"),
                "total_detectadas": len(r["escalas"])},
        "por_semana": por_semana, "por_terminal": por_terminal, "por_eslora": por_eslora,
        "histograma": histo,
        "cobertura_dia": [{"dia": k, "n": dias[k]} for k in sorted(dias)],
        "ahora": r["ahora"],
        "calib": [[la, lo, n] for (la, lo), n in r["calib"].most_common(3000)],
        "zonas": {"recinto": r["zonas"]["recinto_portuario"],
                  "terminales": r["zonas"].get("terminales", [])},
        "escalas": [{
            "nombre": e["nombre"], "mmsi": e["mmsi"], "eslora": e["eslora"],
            "terminal": e["terminal"] or "", "fondeo": fmt(e["t_fondeo"]), "atraque": fmt(e["t_atraque"]),
            "espera_h": e["espera_h"], "estancia_h": e["estancia_h"], "estado": e["cierre"],
            "valida": e["valida"]} for e in r["escalas"][-200:]][::-1],
    }


def guardar_html(datos):
    os.makedirs(DOCS, exist_ok=True)
    with open(os.path.join(BASE, "plantilla_cuadro.html"), encoding="utf-8") as f:
        plantilla = f.read()
    js = json.dumps(datos, ensure_ascii=False).replace("</", "<\\/")
    with open(os.path.join(DOCS, "index.html"), "w", encoding="utf-8") as f:
        f.write(plantilla.replace("/*__DATOS__*/null", js))
    with open(os.path.join(DOCS, "datos.json"), "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False)


if __name__ == "__main__":
    r = calcular()
    guardar_csv(r)
    d = resumen(r)
    guardar_html(d)
    k = d["kpi"]
    print(f"Datos: {d['inicio']} -> {d['fin']} UTC | buques vistos: {d['n_buques']}")
    print(f"Escalas detectadas: {k['total_detectadas']} | validas: {k['n']} | "
          f"espera mediana: {k['mediana']} h | en curso: {k['en_curso']}")
    print("Creados: salidas/escalas.csv, salidas/cobertura.csv, docs/index.html")
