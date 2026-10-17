#!/bin/bash
# BOE Sanciones — instala o actualiza el software desde esta carpeta.
#
#   bash actualizar.sh                  detecta sola la instalación existente (la de Docker) y la actualiza
#   bash actualizar.sh /ruta/instalada  actualiza esa carpeta concreta
#   bash actualizar.sh --si             no pregunta (para ejecutarlo sin supervisión)
#   bash actualizar.sh --sin-captacion  levanta solo base de datos, API y web (sin worker/beat: no toca BOE ni OpenAI)
#
# Si no hay ninguna instalación previa, instala desde cero en esta misma carpeta.
# Nunca borra la base de datos ni los contratos/facturas generados (backend/data).

set -u

AQUI="$(cd "$(dirname "$0")" && pwd)"
FECHA="$(date +%Y-%m-%d_%H%M)"
COPIAS="$HOME/boe-sanciones-copias"
LOG="$COPIAS/actualizacion-$FECHA.log"
DESTINO=""
SIN_CAPTACION=0
PREGUNTAR=1

for a in "$@"; do
  case "$a" in
    --sin-captacion) SIN_CAPTACION=1 ;;
    --si) PREGUNTAR=0 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) DESTINO="$a" ;;
  esac
done

mkdir -p "$COPIAS" && chmod 700 "$COPIAS"
exec > >(tee -a "$LOG") 2>&1

paso()  { printf '\n==> %s\n' "$*"; }
ok()    { printf '    OK    %s\n' "$*"; }
aviso() { printf '    AVISO %s\n' "$*"; }
fallo() { printf '\n    ERROR %s\n' "$*"; printf '    Registro completo: %s\n' "$LOG"; exit 1; }

confirmar() {
  [ "$PREGUNTAR" -eq 0 ] && return 0
  printf '%s [s/N] ' "$1"
  read -r r < /dev/tty
  case "$r" in s|S|si|SI|Si|sí|Sí) return 0 ;; *) return 1 ;; esac
}

head -1 "$AQUI/VERSION.txt" 2>/dev/null || echo "BOE Sanciones"
printf 'Registro de esta ejecución: %s\n' "$LOG"

# ---------------------------------------------------------------- 0. requisitos
paso "Comprobando requisitos"
for c in docker curl rsync awk tar gzip; do
  command -v "$c" >/dev/null 2>&1 || fallo "Falta el comando '$c'."
done
if ! docker info >/dev/null 2>&1; then
  aviso "Docker no está abierto. Lo abro y espero (hasta 3 min)..."
  open -a Docker 2>/dev/null || true
  for _ in $(seq 1 36); do
    sleep 5
    docker info >/dev/null 2>&1 && break
  done
  docker info >/dev/null 2>&1 || fallo "Docker Desktop no arranca. Ábrelo a mano y vuelve a lanzar este script."
fi
docker compose version >/dev/null 2>&1 || fallo "Falta 'docker compose' (Docker Desktop reciente)."
ok "Docker funcionando"

LIBRE_KB="$(df -k "$HOME" | awk 'NR==2 {print $4}')"
[ "${LIBRE_KB:-0}" -gt 3000000 ] || fallo "Menos de 3 GB libres en el disco. Libera espacio antes de actualizar."
ok "Espacio en disco: $((LIBRE_KB / 1024 / 1024)) GB libres"

# ------------------------------------------------- 1. localizar la instalación
paso "Buscando la instalación existente"
if [ -z "$DESTINO" ]; then
  CANDIDATOS="$(docker ps -a --filter 'label=com.docker.compose.service=postgres' \
    --format '{{.Label "com.docker.compose.project.working_dir"}}' 2>/dev/null | sort -u | sed '/^$/d')"
  VALIDOS=""
  while IFS= read -r d; do
    [ -n "$d" ] && [ -f "$d/docker-compose.yml" ] && [ -d "$d/backend" ] && VALIDOS="$VALIDOS$d
"
  done <<EOF
$CANDIDATOS
EOF
  VALIDOS="$(printf '%s' "$VALIDOS" | sed '/^$/d')"
  N="$(printf '%s' "$VALIDOS" | sed '/^$/d' | wc -l | tr -d ' ')"
  if [ -z "$VALIDOS" ]; then
    DESTINO="$AQUI"
    ok "No hay instalación previa: instalación desde cero en $DESTINO"
  elif [ "$N" -eq 1 ]; then
    DESTINO="$VALIDOS"
    ok "Instalación encontrada: $DESTINO"
  else
    printf '    Hay varias instalaciones:\n'
    i=1; while IFS= read -r d; do printf '      %s) %s\n' "$i" "$d"; i=$((i+1)); done <<EOF
$VALIDOS
EOF
    printf '    Cuál actualizo (número)? '
    read -r n < /dev/tty
    DESTINO="$(printf '%s\n' "$VALIDOS" | sed -n "${n}p")"
    [ -n "$DESTINO" ] || fallo "Opción no válida."
  fi
fi
[ -d "$DESTINO" ] || fallo "No existe la carpeta $DESTINO"
DESTINO="$(cd "$DESTINO" && pwd)"
ok "Carpeta de trabajo: $DESTINO"

EN_SITIO=0
[ "$DESTINO" = "$AQUI" ] && EN_SITIO=1
HAY_PREVIA=0
[ "$EN_SITIO" -eq 0 ] && [ -f "$DESTINO/docker-compose.yml" ] && HAY_PREVIA=1
if [ "$EN_SITIO" -eq 1 ] && docker ps -a --filter 'label=com.docker.compose.service=postgres' \
     --format '{{.Label "com.docker.compose.project.working_dir"}}' | grep -qx "$DESTINO"; then
  HAY_PREVIA=1
fi

# ------------------------------------------------------- 2. el .env, antes de tocar nada
NUEVO_ENV="$AQUI/.env"
[ -f "$NUEVO_ENV" ] || fallo "Este paquete no trae .env. Pide uno nuevo."
VIEJO_ENV="$DESTINO/.env"
ENV_FINAL="$(mktemp)"
CLAVES_BD='POSTGRES_USER|POSTGRES_PASSWORD|POSTGRES_DB|DATABASE_URL|DATABASE_URL_SYNC'

if [ "$EN_SITIO" -eq 0 ] && [ -f "$VIEJO_ENV" ]; then
  # El .env del paquete manda, salvo las credenciales de la base de datos: el volumen ya se creó con las suyas.
  awk -F= -v claves="^($CLAVES_BD)\$" '
    NR==FNR { if ($1 ~ claves) viejo[$1]=$0; next }
    ($1 in viejo) { print viejo[$1]; delete viejo[$1]; next }
    { print }
  ' "$VIEJO_ENV" "$NUEVO_ENV" > "$ENV_FINAL"

  paso "Diferencias entre el .env actual y el que trae el paquete"
  awk -F= '
    function enmascara(k, v) {
      if (v == "") return "(vacío)"
      if (k ~ /KEY|PASSWORD|TOKEN|SECRET|LOGIN|USER/) return substr(v,1,3) "… (" length(v) " caracteres)"
      return v
    }
    function lee(f, dest,    l, k, v) {
      while ((getline l < f) > 0) {
        if (l ~ /^[[:space:]]*#/ || l !~ /=/) continue
        k = l; sub(/=.*/, "", k)
        v = l; sub(/^[^=]*=/, "", v)
        dest[k] = v
      }
      close(f)
    }
    BEGIN {
      lee(ARGV[1], a); lee(ARGV[2], b); ARGV[1]=""; ARGV[2]=""
      n = 0
      for (k in a) keys[k]=1
      for (k in b) keys[k]=1
      for (k in keys) {
        if (k ~ /^(POSTGRES_USER|POSTGRES_PASSWORD|POSTGRES_DB|DATABASE_URL|DATABASE_URL_SYNC)$/) continue
        if ((k in a) && (k in b) && a[k] == b[k]) continue
        if (!(k in a))      printf "      + %-42s nuevo: %s\n", k, enmascara(k, b[k])
        else if (!(k in b)) printf "      - %-42s se quita (tenía %s)\n", k, enmascara(k, a[k])
        else                printf "      ~ %-42s %s  ->  %s\n", k, enmascara(k, a[k]), enmascara(k, b[k])
        n++
      }
      if (n == 0) print "      (ninguna)"
    }
  ' "$VIEJO_ENV" "$ENV_FINAL" | sort
  printf '    (Las credenciales de Postgres se conservan tal como estaban. Copia del .env actual en %s)\n' "$COPIAS"
else
  cp "$NUEVO_ENV" "$ENV_FINAL"
fi

# ------------------------------------------------------------ 3. confirmación
paso "Plan"
if [ "$HAY_PREVIA" -eq 1 ]; then
  cat <<EOF
    Actualizar la instalación de: $DESTINO
      1. Para la captación y la web (la base de datos y el .env NO se borran).
      2. Copia de seguridad de la base de datos y del código actual en $COPIAS
      3. Pone el código nuevo y el .env de arriba. backend/data (contratos y facturas) no se toca.
      4. Reconstruye y arranca; aplica las migraciones de la base de datos.
      5. Comprueba que todo responde y que no se ha perdido ningún cliente.
EOF
else
  cat <<EOF
    Instalar desde cero en: $DESTINO
      Construye y arranca todo (la primera vez tarda unos 10 min: descarga imágenes).
EOF
fi
confirmar "    ¿Continuar?" || { rm -f "$ENV_FINAL"; echo "Cancelado. No se ha tocado nada."; exit 0; }

cd "$DESTINO" || fallo "No puedo entrar en $DESTINO"
PSQL() { docker compose exec -T postgres psql -U "${PGUSER:-boe}" -d "${PGDB:-boe_sanciones}" -At -c "$1" 2>/dev/null; }

# Usuario/base de datos reales (los del .env que se queda)
PGUSER="$(grep -E '^POSTGRES_USER=' "$ENV_FINAL" | tail -1 | cut -d= -f2-)"; PGUSER="${PGUSER:-boe}"
PGDB="$(grep -E '^POSTGRES_DB=' "$ENV_FINAL" | tail -1 | cut -d= -f2-)"; PGDB="${PGDB:-boe_sanciones}"

ANTES_VERSION=""; ANTES_CLIENTES=""; ANTES_DOCS=""; ANTES_SANC=""
if [ "$HAY_PREVIA" -eq 1 ]; then
  # --------------------------------------------------- 4. parar captación y copia
  paso "Parando captación, API y web"
  docker compose stop celery-worker celery-beat backend frontend >/dev/null 2>&1 || true
  docker compose up -d postgres >/dev/null 2>&1 || fallo "No arranca la base de datos."
  for _ in $(seq 1 30); do
    docker compose exec -T postgres pg_isready -U "$PGUSER" >/dev/null 2>&1 && break
    sleep 2
  done
  ok "Captación parada; la base de datos sigue encendida"

  if [ "$(PSQL "SELECT to_regclass('public.alembic_version') IS NOT NULL")" = "t" ]; then
    ANTES_VERSION="$(PSQL 'SELECT version_num FROM alembic_version')"
    ANTES_CLIENTES="$(PSQL 'SELECT count(*) FROM clientes')"
    ANTES_DOCS="$(PSQL 'SELECT count(*) FROM documentos_comerciales')"
    ANTES_SANC="$(PSQL 'SELECT count(*) FROM sancionados')"

    paso "Copia de seguridad de la base de datos"
    TAM_MB="$(PSQL 'SELECT pg_database_size(current_database())/1024/1024')"
    TAM_MB="${TAM_MB:-0}"
    LIBRE_MB=$((LIBRE_KB / 1024))
    DUMP="$COPIAS/bd-$FECHA.dump"
    if [ "$LIBRE_MB" -gt $((TAM_MB + 2048)) ]; then
      docker compose exec -T postgres pg_dump -U "$PGUSER" -d "$PGDB" -Fc > "$DUMP" \
        || { rm -f "$DUMP"; fallo "Falló la copia de seguridad. No se ha tocado nada más."; }
      ok "Copia completa: $DUMP ($(du -h "$DUMP" | cut -f1 | tr -d ' '))"
    else
      aviso "Poco espacio ($LIBRE_MB MB libres, BD de $TAM_MB MB): copia sin los PDF originales archivados"
      docker compose exec -T postgres pg_dump -U "$PGUSER" -d "$PGDB" -Fc --exclude-table-data=documento_archivos > "$DUMP" \
        || { rm -f "$DUMP"; fallo "Falló la copia de seguridad. No se ha tocado nada más."; }
      ok "Copia (sin PDF archivados): $DUMP ($(du -h "$DUMP" | cut -f1 | tr -d ' '))"
    fi
    chmod 600 "$DUMP"
    printf '    Antes: versión de esquema %s · %s clientes · %s sancionados · %s contratos/facturas\n' \
      "$ANTES_VERSION" "$ANTES_CLIENTES" "$ANTES_SANC" "$ANTES_DOCS"
  else
    aviso "La base de datos existe pero está vacía (sin esquema). Se creará al arrancar."
  fi

  paso "Copia del código y .env actuales"
  CODIGO="$COPIAS/codigo-$FECHA.tar.gz"
  tar -czf "$CODIGO" -C "$DESTINO" \
    --exclude='./backend/data' --exclude='./backend/.venv' --exclude='./frontend/node_modules' \
    --exclude='./frontend/.next' --exclude='./.git' --exclude='__pycache__' . \
    || fallo "No se pudo copiar el código actual."
  chmod 600 "$CODIGO"
  ok "$CODIGO"
fi

# ---------------------------------------------------------- 5. poner el código nuevo
if [ "$EN_SITIO" -eq 0 ]; then
  paso "Copiando el código nuevo"
  rsync -a \
    --exclude='/.env' --exclude='/backend/data/' --exclude='/backend/.venv/' \
    --exclude='/frontend/node_modules/' --exclude='/frontend/.next/' \
    "$AQUI"/ "$DESTINO"/ || fallo "Falló la copia del código."
  # Carpetas de código: se sincronizan borrando lo que ya no existe (módulos antiguos). Nada más se borra.
  for d in backend/app backend/alembic backend/scripts frontend/src frontend/public searxng; do
    [ -d "$AQUI/$d" ] && { mkdir -p "$DESTINO/$d"; rsync -a --delete "$AQUI/$d"/ "$DESTINO/$d"/ || fallo "Falló la copia de $d."; }
  done
  find "$DESTINO/backend" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
  ok "Código actualizado (backend/data intacto)"
fi
cp "$ENV_FINAL" "$DESTINO/.env" && chmod 600 "$DESTINO/.env" && rm -f "$ENV_FINAL"
ok ".env puesto"

# ------------------------------------------------------------ 6. construir y arrancar
paso "Construyendo y arrancando (varios minutos; no cierres la ventana)"
if [ "$SIN_CAPTACION" -eq 1 ]; then
  docker compose up -d --build postgres migrate backend frontend || FALLO_ARRANQUE=1
else
  docker compose up -d --build || FALLO_ARRANQUE=1
fi
if [ "${FALLO_ARRANQUE:-0}" -eq 1 ]; then
  printf '\n    Falló la construcción. Tus datos están a salvo (copia en %s).\n' "$COPIAS"
  printf '    Para volver a la versión anterior: bash "%s/volver_atras.sh"\n' "$AQUI"
  fallo "docker compose no pudo arrancar. Envía el registro de arriba."
fi

paso "Esperando a que responda (las migraciones se aplican aquí)"
LISTO=0
for _ in $(seq 1 90); do
  curl -fsS http://localhost:8000/api/health >/dev/null 2>&1 && { LISTO=1; break; }
  sleep 4
done
[ "$LISTO" -eq 1 ] || fallo "La API no responde tras 6 min. Mira: docker compose logs migrate backend"

# ------------------------------------------------------------ 7. comprobaciones
paso "Comprobaciones"
PROBLEMAS=0
mal() { aviso "$*"; PROBLEMAS=$((PROBLEMAS+1)); }

VERSION_NUEVA="$(docker compose exec -T backend alembic current 2>/dev/null | grep -Eo '^[0-9a-z_]+' | head -1)"
CABEZA="$(docker compose exec -T backend alembic heads 2>/dev/null | grep -Eo '^[0-9a-z_]+' | head -1)"
if [ -n "$VERSION_NUEVA" ] && [ "$VERSION_NUEVA" = "$CABEZA" ]; then ok "Base de datos al día: $VERSION_NUEVA"; else mal "Migraciones: actual='$VERSION_NUEVA' esperada='$CABEZA'"; fi

if [ -n "$ANTES_CLIENTES" ]; then
  D_CLI="$(PSQL 'SELECT count(*) FROM clientes')"
  D_DOC="$(PSQL 'SELECT count(*) FROM documentos_comerciales')"
  D_SAN="$(PSQL 'SELECT count(*) FROM sancionados')"
  [ "$D_CLI" = "$ANTES_CLIENTES" ] && ok "Clientes: $D_CLI (antes $ANTES_CLIENTES)" || mal "Clientes: $D_CLI, antes $ANTES_CLIENTES"
  [ "$D_DOC" = "$ANTES_DOCS" ] && ok "Contratos/facturas: $D_DOC (antes $ANTES_DOCS)" || mal "Contratos/facturas: $D_DOC, antes $ANTES_DOCS"
  [ "$D_SAN" -ge "$ANTES_SANC" ] 2>/dev/null && ok "Sancionados: $D_SAN (antes $ANTES_SANC)" || mal "Sancionados: $D_SAN, antes $ANTES_SANC"
fi

curl -fsS -o /dev/null http://localhost:3000 && ok "Web: http://localhost:3000" || mal "La web no responde en el puerto 3000 (puede tardar un minuto más)"

if [ "$SIN_CAPTACION" -eq 0 ]; then
  for s in celery-worker celery-beat; do
    docker compose ps --status running --services 2>/dev/null | grep -qx "$s" && ok "$s en marcha" || mal "$s no está en marcha"
  done
  MODELO="$(docker compose exec -T celery-worker printenv OPENAI_MODEL 2>/dev/null | tr -d '\r')"
  [ "$MODELO" = "gpt-5.4-nano" ] && ok "Modelo de OpenAI: $MODELO" || mal "Modelo de OpenAI es '$MODELO' (debería ser gpt-5.4-nano)"
else
  aviso "Modo --sin-captacion: worker y beat NO arrancados (no se captura nada ni se llama a OpenAI)."
fi

REINICIO_OK=1
for s in postgres redis backend frontend celery-worker celery-beat; do
  id="$(docker compose ps -q "$s" 2>/dev/null)"
  [ -n "$id" ] || continue
  pol="$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' "$id" 2>/dev/null)"
  [ "$pol" = "unless-stopped" ] || { REINICIO_OK=0; mal "$s sin reinicio automático (política '$pol')"; }
done
[ "$REINICIO_OK" -eq 1 ] && ok "Los servicios se reinician solos tras apagar o reiniciar Docker"

if [ "$(uname)" = "Darwin" ]; then
  if grep -qiE '"(AutoStart|OpenAtLogin)"[[:space:]]*:[[:space:]]*true' \
       "$HOME/Library/Group Containers/group.com.docker/settings-store.json" "$HOME/Library/Group Containers/group.com.docker/settings.json" 2>/dev/null; then
    ok "Docker Desktop arranca al iniciar sesión"
  else
    mal "Docker Desktop NO arranca solo al iniciar sesión: Docker Desktop -> Settings -> General -> 'Start Docker Desktop when you sign in to your computer'"
  fi
fi

paso "Resultado"
if [ "$PROBLEMAS" -eq 0 ]; then
  printf '    TODO CORRECTO. Abre http://localhost:3000\n'
else
  printf '    Terminado con %s aviso(s) arriba. Revísalos antes de dar la instalación por buena.\n' "$PROBLEMAS"
fi
if [ "$SIN_CAPTACION" -eq 0 ]; then
  printf '    Al arrancar, el worker se pone al día solo con los últimos 10 días (tarda unos minutos y usa OpenAI).\n'
  printf '    Se puede seguir en la web: Operación.\n'
fi
printf '    Copias de seguridad: %s\n' "$COPIAS"
[ "$PROBLEMAS" -eq 0 ]
