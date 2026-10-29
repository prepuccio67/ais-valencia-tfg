# Abre un túnel SSH al servidor y el visor con mapa en el navegador.
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
Start-Process "http://127.0.0.1:${puertoLocal}/?token=$token"
Write-Host "Listo: visor abierto en el navegador (http://127.0.0.1:${puertoLocal}/)."
Write-Host "Mientras uses el visor, no cierres la ventana negra de SSH."
