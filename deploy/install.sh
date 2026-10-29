#!/usr/bin/env bash
# Instalación (o actualización) del Collector AIS en Ubuntu 24.04. DISEÑO.md §7.
# Se puede ejecutar varias veces sin romper nada:
#     sudo bash /opt/ais/deploy/install.sh
# La primera vez se usa así (descarga el código y lo instala):
#     curl -fsSL https://raw.githubusercontent.com/prepuccio67/ais-valencia-tfg/main/deploy/install.sh | sudo bash
set -euo pipefail

REPO_URL="https://github.com/prepuccio67/ais-valencia-tfg.git"
APP=/opt/ais            # código
DATA=/srv/ais           # datos (disco aparte: block volume)
SVC_USER=ais

say() { echo -e "\n=== $* ==="; }
[ "$(id -u)" -eq 0 ] || { echo "Ejecuta con sudo"; exit 1; }

say "1/9 Paquetes del sistema"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q python3-venv git sqlite3 zstd unattended-upgrades >/dev/null
# actualizaciones de seguridad automáticas
dpkg-reconfigure -f noninteractive unattended-upgrades >/dev/null

say "2/9 Hora del sistema en UTC y sincronizada (NTP)"
timedatectl set-timezone UTC
timedatectl set-ntp true || true

say "3/9 Memoria de reserva (swap de 2 GB)"
if ! swapon --show | grep -q /swapfile; then
    fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
    grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
swapon --show

say "4/9 Usuario de servicio '$SVC_USER' (sin contraseña ni acceso por SSH)"
id -u "$SVC_USER" >/dev/null 2>&1 || useradd --system --home-dir "$DATA" --shell /usr/sbin/nologin "$SVC_USER"
# el usuario ubuntu puede leer los datos y las copias (para descargarlas al PC)
id -u ubuntu >/dev/null 2>&1 && usermod -aG "$SVC_USER" ubuntu

say "5/9 Carpeta de datos $DATA"
if mountpoint -q "$DATA"; then
    echo "OK: $DATA es un disco montado: $(df -h "$DATA" | tail -1)"
elif [ "${ALLOW_NO_VOLUME:-0}" = "1" ]; then
    echo "AVISO: $DATA no es un disco aparte (ALLOW_NO_VOLUME=1)"
    mkdir -p "$DATA"
else
    echo "ERROR: $DATA no está montado. Monta antes el block volume (README, Fase 3)."
    echo "       Para instalar igualmente en el disco de arranque: ALLOW_NO_VOLUME=1 sudo -E bash install.sh"
    exit 1
fi
mkdir -p "$DATA/logs" "$DATA/backup-staging"
chown -R "$SVC_USER:$SVC_USER" "$DATA"
chmod 2750 "$DATA" "$DATA/backup-staging"

say "6/9 Código en $APP"
if [ -d "$APP/.git" ]; then
    git -C "$APP" pull --ff-only
else
    git clone --depth 50 "$REPO_URL" "$APP"
fi
git -C "$APP" log --oneline -1

say "7/9 Entorno de Python"
[ -x "$APP/venv/bin/python" ] || python3 -m venv "$APP/venv"
"$APP/venv/bin/pip" install -q --upgrade pip
"$APP/venv/bin/pip" install -q -r "$APP/requirements.txt"
"$APP/venv/bin/python" -m unittest discover -s "$APP/tests" -t "$APP" 2>&1 | tail -3

say "8/9 Configuración (.env, solo legible por '$SVC_USER')"
if [ ! -f "$APP/.env" ]; then
    TOKEN="$("$APP/venv/bin/python" -c 'import secrets; print(secrets.token_urlsafe(32))')"
    cat > "$APP/.env" <<EOF
COLLECTOR_ID=VALENCIA-01
DATA_DIR=$DATA
API_HOST=127.0.0.1
API_PORT=5080
API_TOKEN=$TOKEN
AISSTREAM_API_KEY=
OPENSEAFEED_API_KEY=
BACKUP_PAR_URL=
EOF
    echo "Creado $APP/.env con un token nuevo"
fi
chown root:"$SVC_USER" "$APP/.env"
chmod 640 "$APP/.env"

say "9/9 Servicios systemd"
install -m 644 "$APP/deploy/ais-collector.service" /etc/systemd/system/
install -m 644 "$APP/deploy/ais-backup.service" /etc/systemd/system/
install -m 644 "$APP/deploy/ais-backup.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now ais-backup.timer
systemctl enable ais-collector
systemctl restart ais-collector
sleep 5
systemctl --no-pager --lines=8 status ais-collector || true

echo
echo "Instalación terminada. Comprobar:  sudo journalctl -u ais-collector -n 30"
grep -q '^AISSTREAM_API_KEY=$' "$APP/.env" && echo "PENDIENTE: falta AISSTREAM_API_KEY (deploy/set_secret.sh)" || true
grep -q '^BACKUP_PAR_URL=$' "$APP/.env" && echo "PENDIENTE: falta BACKUP_PAR_URL (copias fuera de la máquina)" || true
