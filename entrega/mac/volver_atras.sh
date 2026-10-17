#!/bin/bash
# BOE Sanciones — vuelve a la versión anterior a la última actualización.
# Restaura el código, el .env y la base de datos desde la última copia de seguridad que hizo actualizar.sh
# (en ~/boe-sanciones-copias). Lo que se haya hecho en la aplicación DESPUÉS de actualizar se pierde.
#
#   bash volver_atras.sh                 usa la última copia y detecta la instalación
#   bash volver_atras.sh /ruta/instalada usa esa carpeta
#   --si                                 no pregunta
#   --sin-captacion                      no arranca worker/beat (solo base de datos, API y web)

set -u
COPIAS="$HOME/boe-sanciones-copias"
DESTINO=""
PREGUNTAR=1
SIN_CAPTACION=0
for a in "$@"; do
  case "$a" in --si) PREGUNTAR=0 ;; --sin-captacion) SIN_CAPTACION=1 ;; *) DESTINO="$a" ;; esac
done

fallo() { printf '\n    ERROR %s\n' "$*"; exit 1; }
docker info >/dev/null 2>&1 || fallo "Docker no está abierto."

if [ -z "$DESTINO" ]; then
  DESTINO="$(docker ps -a --filter 'label=com.docker.compose.service=postgres' \
    --format '{{.Label "com.docker.compose.project.working_dir"}}' | sort -u | sed '/^$/d')"
  [ "$(printf '%s\n' "$DESTINO" | wc -l | tr -d ' ')" -eq 1 ] && [ -n "$DESTINO" ] \
    || fallo "No encuentro una única instalación. Indica la carpeta: bash volver_atras.sh /ruta/instalada"
fi
[ -f "$DESTINO/docker-compose.yml" ] || fallo "$DESTINO no parece una instalación."

DUMP="$(ls -1t "$COPIAS"/bd-*.dump 2>/dev/null | head -1)"
CODIGO="$(ls -1t "$COPIAS"/codigo-*.tar.gz 2>/dev/null | head -1)"
[ -n "$DUMP" ] && [ -n "$CODIGO" ] || fallo "No hay copias de seguridad en $COPIAS"

printf 'Instalación:     %s\nBase de datos:   %s\nCódigo y .env:   %s\n' "$DESTINO" "$DUMP" "$CODIGO"
if [ "$PREGUNTAR" -eq 1 ]; then
  printf 'Se perderá todo lo hecho en la aplicación desde esa copia. ¿Continuar? [s/N] '
  read -r r < /dev/tty
  case "$r" in s|S|si|SI|Si|sí|Sí) ;; *) echo "Cancelado."; exit 0 ;; esac
fi

cd "$DESTINO" || fallo "No puedo entrar en $DESTINO"
docker compose stop celery-worker celery-beat backend frontend >/dev/null 2>&1 || true
docker compose up -d postgres >/dev/null 2>&1 || fallo "No arranca la base de datos."

# El .env guardado dice qué usuario/base tenía la instalación anterior.
TMP_ENV="$(mktemp)"
tar -xzOf "$CODIGO" ./.env > "$TMP_ENV" 2>/dev/null || cp .env "$TMP_ENV"
PGUSER="$(grep -E '^POSTGRES_USER=' "$TMP_ENV" | tail -1 | cut -d= -f2-)"; PGUSER="${PGUSER:-boe}"
PGDB="$(grep -E '^POSTGRES_DB=' "$TMP_ENV" | tail -1 | cut -d= -f2-)"; PGDB="${PGDB:-boe_sanciones}"
rm -f "$TMP_ENV"

for _ in $(seq 1 30); do docker compose exec -T postgres pg_isready -U "$PGUSER" >/dev/null 2>&1 && break; sleep 2; done

echo "==> Restaurando la base de datos"
docker compose exec -T postgres psql -U "$PGUSER" -d "$PGDB" -q -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;' \
  || fallo "No se pudo limpiar la base de datos."
docker compose exec -T postgres pg_restore -U "$PGUSER" -d "$PGDB" --no-owner < "$DUMP" \
  || printf '    AVISO pg_restore terminó con avisos (suele ser normal). Comprueba los datos.\n'

echo "==> Restaurando el código y el .env"
rm -rf backend/app backend/alembic frontend/src
tar -xzf "$CODIGO" -C "$DESTINO" || fallo "No se pudo restaurar el código."

echo "==> Arrancando la versión anterior"
if [ "$SIN_CAPTACION" -eq 1 ]; then
  docker compose up -d --build postgres migrate backend frontend || fallo "No arranca. Envía este registro."
else
  docker compose up -d --build || fallo "No arranca. Envía este registro."
fi
printf '\nListo. Versión anterior restaurada. Abre http://localhost:3000\n'
