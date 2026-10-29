#!/usr/bin/env bash
# Guarda un secreto en /opt/ais/.env leyéndolo de la entrada estándar, para que
# nunca aparezca en la línea de comandos ni en el historial. Uso (desde el PC):
#   type clave_api.txt | ssh servidor "sudo bash /opt/ais/deploy/set_secret.sh AISSTREAM_API_KEY"
set -euo pipefail
NAME="${1:?indica el nombre: AISSTREAM_API_KEY, OPENSEAFEED_API_KEY o BACKUP_PAR_URL}"
case "$NAME" in AISSTREAM_API_KEY|OPENSEAFEED_API_KEY|BACKUP_PAR_URL) ;; *) echo "nombre no permitido"; exit 1;; esac
ENV=/opt/ais/.env
IFS= read -r VALUE || true
VALUE="$(printf '%s' "$VALUE" | tr -d '\r\n')"
[ -n "$VALUE" ] || { echo "valor vacío"; exit 1; }
TMP="$(mktemp)"
grep -v "^$NAME=" "$ENV" > "$TMP" || true
printf '%s=%s\n' "$NAME" "$VALUE" >> "$TMP"
cat "$TMP" > "$ENV" && rm -f "$TMP"
echo "$NAME guardado (${#VALUE} caracteres)"
