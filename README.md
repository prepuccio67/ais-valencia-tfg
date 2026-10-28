# Sistema AIS – Puerto de València (TFG)

Captura 24/7 de posiciones AIS de buques para estudiar los tiempos de espera en
las terminales de contenedores del Puerto de València.

- **Collector:** programa sin pantalla que escucha dos fuentes AIS (OpenSeaFeed
  y aisstream.io), guarda una muestra de posiciones en SQLite y ofrece una API.
- **Viewer:** visor web con mapa (llegará en la Fase 4).

Documentación: [DISEÑO.md](DISEÑO.md) · [ROADMAP.md](ROADMAP.md) ·
[DECISIONES.md](DECISIONES.md) · [LIMITACIONES.md](LIMITACIONES.md).
La versión anterior (GitHub Actions + CSV) sigue en `captura_ais.py` y
`procesar.py` hasta que el servidor esté capturando.

---

## Arrancar en tu PC (Windows)

Todo se pega en **PowerShell**, dentro de la carpeta del proyecto:

```powershell
cd C:\Users\marco\Desktop\TFG\captura_AIS
```

### 1. Solo la primera vez (en el PC de Marcos ya está hecho)

Requiere Python 3.12 (`winget install Python.Python.3.12 --scope user`).

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env
```

Abre `.env` con el Bloc de notas y rellénalo:
- `DATA_DIR`: carpeta de datos, por ejemplo `C:/Users/marco/Desktop/TFG/ais_datos`.
- `API_TOKEN`: un token largo. Para generarlo:
  `.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"`
- `AISSTREAM_API_KEY`: tu clave de aisstream.io.

### 2. Arrancar y parar

| Qué | Comando |
|---|---|
| Arrancar (hasta que lo pares) | `.venv\Scripts\python.exe -m collector.main` |
| Prueba de N minutos | `.venv\Scripts\python.exe -m collector.main --minutes 30` |
| Parar | `Ctrl + C` (guarda lo pendiente antes de salir) |
| Tests automáticos | `.venv\Scripts\python.exe -m unittest discover -s tests -t .` |

### 3. Comprobar que funciona

Con el Collector en marcha, abre en el navegador (sustituye `TU_TOKEN` por el de tu `.env`):

- `http://127.0.0.1:5080/api/health?token=TU_TOKEN` → `"status": "ok"`
- `http://127.0.0.1:5080/api/zone?zone=VALENCIA&token=TU_TOKEN` → estadísticas de la zona
- `http://127.0.0.1:5080/api/gaps?zone=VALENCIA&token=TU_TOKEN` → huecos registrados

## Dónde quedan los datos

```
DATA_DIR/
├── Zones/VALENCIA/zone.json          definición de la zona
├── Zones/VALENCIA/current.db         base de datos SQLite (se abre con "DB Browser for SQLite")
├── Zones/VALENCIA/archive-catalog.json
└── logs/collector.log                registro (conexiones, caídas, huecos)
```

En la base, las vistas `v_position`, `v_gap` y `v_event` muestran las horas
como texto legible (UTC).

## En el servidor (Fase 3)

Se documentará al desplegar: servicio `systemd` con arranque y reinicio
automáticos, cortafuegos, copias de seguridad y acceso por túnel SSH.
