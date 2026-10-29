#!/usr/bin/env bash
# Pasa los datos de /srv/ais (disco de arranque) a un block volume nuevo y lo monta en /srv/ais.
# Uso: sudo bash migrar_a_volumen.sh /dev/sdb
# Seguridad: solo actúa si el disco indicado está VACÍO; la carpeta antigua se conserva.
set -euo pipefail
DEV="${1:?indica el disco, p. ej. /dev/sdb}"
DATA=/srv/ais
OLD=/srv/ais.disco-arranque
TMP=/mnt/ais-nuevo

[ "$(id -u)" -eq 0 ] || { echo "Ejecuta con sudo"; exit 1; }
mountpoint -q "$DATA" && { echo "$DATA ya es un disco montado: nada que hacer"; exit 0; }
[ -b "$DEV" ] || { echo "$DEV no existe"; exit 1; }
if blkid "$DEV" >/dev/null 2>&1 || [ -n "$(lsblk -n -o NAME "$DEV" | tail -n +2)" ]; then
    echo "ABORTO: $DEV no está vacío (tiene sistema de archivos o particiones)"; exit 1
fi

echo "=== 1/6 Formato ext4 de $DEV (disco vacío) ==="
mkfs.ext4 -q -L ais-datos "$DEV"
UUID="$(blkid -s UUID -o value "$DEV")"
echo "UUID=$UUID"

echo "=== 2/6 Parada del Collector ==="
systemctl stop ais-collector
systemctl stop ais-backup.timer

echo "=== 3/6 Copia de los datos ==="
mkdir -p "$TMP"
mount "$DEV" "$TMP"
cp -a "$DATA/." "$TMP/"
for db in "$DATA"/Zones/*/current.db; do
    rel="${db#$DATA/}"
    a="$(sqlite3 "$db" 'SELECT COUNT(*) FROM position')"
    b="$(sqlite3 "$TMP/$rel" 'SELECT COUNT(*) FROM position')"
    ok="$(sqlite3 "$TMP/$rel" 'PRAGMA integrity_check')"
    echo "$rel: posiciones original=$a copia=$b integridad=$ok"
    [ "$a" = "$b" ] && [ "$ok" = "ok" ] || { echo "ABORTO: la copia no coincide"; umount "$TMP"; systemctl start ais-collector; exit 1; }
done
umount "$TMP"

echo "=== 4/6 Montaje permanente en $DATA (por UUID) ==="
mv "$DATA" "$OLD"
mkdir -p "$DATA"
grep -q "$UUID" /etc/fstab || echo "UUID=$UUID $DATA ext4 defaults,nofail 0 2" >> /etc/fstab
systemctl daemon-reload
mount "$DATA"
chown ais:ais "$DATA"
chmod 2750 "$DATA"
df -h "$DATA"

echo "=== 5/6 Servicios actualizados y arranque ==="
install -m 644 /opt/ais/deploy/ais-collector.service /etc/systemd/system/
install -m 644 /opt/ais/deploy/ais-backup.service /etc/systemd/system/
systemctl daemon-reload
systemctl start ais-collector
systemctl start ais-backup.timer
sleep 10
systemctl is-active ais-collector

echo "=== 6/6 Hecho. Copia antigua conservada en $OLD (se puede borrar más adelante) ==="
