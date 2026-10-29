# Descarga al PC las copias de seguridad del servidor (segunda copia, fuera de Oracle).
# Uso (PowerShell, en la carpeta captura_AIS):   .\deploy\descargar_copias.ps1
# Solo descarga lo que falte; se puede ejecutar tantas veces como se quiera.
$destino = Join-Path $env:USERPROFILE "Desktop\TFG\copias_servidor"
New-Item -ItemType Directory -Force $destino | Out-Null
Write-Host "Descargando copias a $destino ..."
# scp copia la carpeta entera; las copias son pequeñas (unos MB al mes)
scp -r -p "ais-oracle:/srv/ais/backup-staging/*" "$destino"
if ($LASTEXITCODE -eq 0) {
    Write-Host "Hecho. Archivos:"
    Get-ChildItem -Recurse $destino -File | Select-Object FullName, Length, LastWriteTime | Format-Table -AutoSize
} else {
    Write-Host "Error al descargar (¿servidor encendido? ¿alias ais-oracle configurado?)"
}
