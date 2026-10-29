# Abre un túnel SSH al servidor y el navegador con la API (y el visor, desde la Fase 4).
# Uso (PowerShell, en la carpeta captura_AIS):   .\deploy\abrir_visor.ps1
# Para cerrar el túnel: cierra la ventana negra de SSH que se abre.
# Requiere el alias "ais-oracle" en %USERPROFILE%\.ssh\config (lo crea la Fase 3).
$puertoLocal = 5081   # 5081 para no chocar con un Collector de prueba en el PC (5080)

Write-Host "Leyendo el token del servidor..."
$token = (ssh ais-oracle "sudo grep '^API_TOKEN=' /opt/ais/.env | cut -d= -f2").Trim()
if (-not $token) { Write-Host "No se pudo leer el token. ¿Está encendido el servidor?"; exit 1 }

Write-Host "Abriendo el túnel SSH (ventana aparte)..."
Start-Process ssh -ArgumentList "-N -L ${puertoLocal}:127.0.0.1:5080 ais-oracle"
Start-Sleep -Seconds 3
Start-Process "http://127.0.0.1:${puertoLocal}/api/health?token=$token"
Write-Host "Listo. Otras direcciones útiles (añade &token=... si el navegador lo pide):"
Write-Host "  http://127.0.0.1:${puertoLocal}/api/zone?zone=VALENCIA"
Write-Host "  http://127.0.0.1:${puertoLocal}/api/gaps?zone=VALENCIA"
