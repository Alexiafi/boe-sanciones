#!/bin/bash
# Construye el paquete limpio para entregar a la clienta: dist/boe-sanciones-AAAA-MM-DD.zip
#
# Parte de una LISTA DE LO QUE ENTRA (no de "todo menos lo que sobra"): lo interno del repo
# (.git, .venv, .serena, .cursor, decks, deliverables, PLAN, AGENTS, tests, claves sueltas...) no puede colarse.
# El .env sale de tu .env con los ajustes de coste/velocidad aplicados y duplicados quitados.
#
#   scripts/empaquetar.sh               paquete para Windows (ACTUALIZAR.bat) usando ./.env
#   scripts/empaquetar.sh --env RUTA    usa otro .env como origen
#   scripts/empaquetar.sh --mac         paquete para macOS (actualizar.sh) en vez de Windows
#
# Termina con un informe de comprobaciones; si alguna falla no deja zip.

set -euo pipefail

RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
cd "$RAIZ"

ENV_ORIGEN=".env"
PLATAFORMA="windows"
while [ $# -gt 0 ]; do
  case "$1" in
    --env) ENV_ORIGEN="${2:?falta la ruta del .env}"; shift 2 ;;
    --mac) PLATAFORMA="mac"; shift ;;
    *) echo "Opcion desconocida: $1"; exit 1 ;;
  esac
done
[ -f "$ENV_ORIGEN" ] || { echo "No existe $ENV_ORIGEN"; exit 1; }

# Ajustes que el paquete fuerza en el .env de la clienta (coste y velocidad).
AJUSTES='OPENAI_MODEL=gpt-5.4-nano,OPENAI_REASONING_EFFORT=low,OPENAI_CONCURRENCY=6,DESCARGA_WORKERS=8'

FECHA="$(date +%Y-%m-%d)"
NOMBRE="boe-sanciones-$FECHA"
[ "$PLATAFORMA" = "mac" ] && NOMBRE="boe-sanciones-mac-$FECHA"
SALIDA="$RAIZ/dist"
TMP="$(mktemp -d)"
STAGE="$TMP/$NOMBRE"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$STAGE" "$SALIDA"

FALLOS=0
bien() { printf '  OK     %s\n' "$*"; }
mal()  { printf '  FALLO  %s\n' "$*"; FALLOS=$((FALLOS+1)); }
nota() { printf '  AVISO  %s\n' "$*"; }

echo "==> Copiando lo que entra en el paquete"
COMUN=(--exclude='__pycache__' --exclude='*.pyc' --exclude='.DS_Store')

mkdir -p "$STAGE/backend" "$STAGE/frontend" "$STAGE/docs" "$STAGE/searxng"
rsync -a "${COMUN[@]}" \
  --exclude='/.venv' --exclude='/.pytest_cache' --exclude='/data' --exclude='/tests' \
  --exclude='/pytest.ini' --exclude='/celerybeat-schedule*' \
  backend/ "$STAGE/backend/"
rsync -a "${COMUN[@]}" \
  --exclude='/node_modules' --exclude='/.next' --exclude='/tsconfig.tsbuildinfo' --exclude='/.env*' \
  --exclude='*.test.ts' --exclude='*.test.tsx' --exclude='/vitest.config.ts' --exclude='/vitest.setup.ts' \
  frontend/ "$STAGE/frontend/"
rsync -a searxng/ "$STAGE/searxng/"
cp docker-compose.yml .env.example README.md "$STAGE/"
cp docs/GUIA_OPERATIVA.md docs/LIMITES.md "$STAGE/docs/"
if [ "$PLATAFORMA" = "windows" ]; then
  cp entrega/actualizar.ps1 entrega/volver_atras.ps1 "$STAGE/"
  # .bat y LEEME con saltos de linea de Windows
  for f in ACTUALIZAR.bat VOLVER_ATRAS.bat LEEME.txt; do perl -pe 's/\r?\n/\r\n/' "entrega/$f" > "$STAGE/$f"; done
  SCRIPTS="actualizar.ps1 volver_atras.ps1 ACTUALIZAR.bat VOLVER_ATRAS.bat"
else
  cp entrega/mac/actualizar.sh entrega/mac/volver_atras.sh entrega/mac/LEEME.txt "$STAGE/"
  chmod +x "$STAGE/actualizar.sh" "$STAGE/volver_atras.sh"
  SCRIPTS="actualizar.sh volver_atras.sh"
fi

echo "==> Preparando el .env"
awk -v ov="$AJUSTES" '
BEGIN { n = split(ov, o, ","); for (i = 1; i <= n; i++) { k = o[i]; sub(/=.*/, "", k); v[k] = o[i] } }
{ lines[NR] = $0
  if ($0 !~ /^[[:space:]]*#/ && $0 ~ /^[A-Za-z_][A-Za-z0-9_]*=/) { k = $0; sub(/=.*/, "", k); last[k] = NR } }
END {
  for (i = 1; i <= NR; i++) {
    l = lines[i]
    if (l !~ /^[[:space:]]*#/ && l ~ /^[A-Za-z_][A-Za-z0-9_]*=/) {
      k = l; sub(/=.*/, "", k)
      if (last[k] != i) continue
      if (k in v) { print v[k]; seen[k] = 1; continue }
    }
    print l
  }
  first = 1
  for (k in v) if (!(k in seen)) {
    if (first) { print ""; print "# Coste y velocidad de la captación (ver docs/GUIA_OPERATIVA.md)"; first = 0 }
    print v[k]
  }
}' "$ENV_ORIGEN" > "$STAGE/.env"
chmod 600 "$STAGE/.env"

valor() { grep -E "^$1=" "$STAGE/.env" | tail -1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//'; }

{
  printf 'BOE Sanciones — paquete %s\n' "$(date '+%Y-%m-%d %H:%M')"
  ULTIMA="$(ls backend/alembic/versions/[0-9]*.py | sort | tail -1)"
  printf 'Esquema de base de datos (Alembic): %s\n' "$(grep -E '^revision' "$ULTIMA" | head -1 | sed -E "s/.*= *['\"]([^'\"]+)['\"].*/\1/")"
  if git rev-parse --short HEAD >/dev/null 2>&1; then
    SUCIO=""; [ -n "$(git status --porcelain)" ] && SUCIO=" + cambios sin confirmar en git"
    printf 'Base: %s%s\n' "$(git rev-parse --short HEAD)" "$SUCIO"
  fi
} > "$STAGE/VERSION.txt"

echo
echo "==> Comprobaciones"

# 1. Nada interno
PROHIBIDO="$(find "$STAGE" \( -name .git -o -name .venv -o -name node_modules -o -name __pycache__ -o -name .DS_Store \
  -o -name '*.pyc' -o -name .openai_apikey -o -name .serena -o -name .cursor -o -name '.tmp_*' -o -name deliverables \
  -o -name AGENTS.md -o -name CLAUDE.md -o -name PLAN.md -o -name tests -o -name data -o -name .next -o -name '*.docx' \
  -o -name '*.key' -o -name '*.pptx' -o -name '*.log' -o -name '*.sql' -o -name '*.dump' \) -print)"
if [ -z "$PROHIBIDO" ]; then bien "No hay carpetas ni ficheros internos"; else mal "Ficheros que no deben ir:"; echo "$PROHIBIDO" | sed 's/^/           /'; fi

OTROS_ENV="$(find "$STAGE" -name '.env*' ! -path "$STAGE/.env" ! -path "$STAGE/.env.example" -print)"
if [ -z "$OTROS_ENV" ]; then bien "Solo hay .env y .env.example"; else mal "Otros .env en el paquete:"; echo "$OTROS_ENV" | sed 's/^/           /'; fi

# 2. Ningún secreto fuera del .env
SECRETOS=0
for k in OPENAI_API_KEY DATAFORSEO_LOGIN DATAFORSEO_PASSWORD SERPER_API_KEY TAVILY_API_KEY SMTP_PASSWORD EMISOR_IBAN; do
  val="$(valor "$k")"
  [ "${#val}" -ge 6 ] || continue
  HITS="$(grep -rIlF -- "$val" "$STAGE" 2>/dev/null | grep -v "^$STAGE/.env$" || true)"
  if [ -n "$HITS" ]; then mal "El valor de $k aparece fuera del .env:"; echo "$HITS" | sed 's/^/           /'; SECRETOS=1; fi
done
[ "$SECRETOS" -eq 0 ] && bien "Ninguna clave ni contraseña fuera del .env"

# 3. Referencias internas en textos (aviso, no bloquea)
INTERNO="$(grep -rIil -E 'serena|\.cursor/|claude|anthropic|codex|lenguajenatural|avacaondata|alexiafi|/Users/administrador' "$STAGE" \
  --exclude='.env' --exclude-dir=node_modules 2>/dev/null || true)"
if [ -z "$INTERNO" ]; then bien "Sin menciones a herramientas o personas internas"; else nota "Menciones internas en:"; echo "$INTERNO" | sed "s|$STAGE/|           |"; fi

# 4. Lo imprescindible está
for f in docker-compose.yml .env backend/Dockerfile backend/requirements.txt backend/requirements-test.txt \
         backend/alembic.ini backend/scripts/migrate.py backend/app/main.py backend/app/assets/en_plazo_logo.jpg.b64 \
         frontend/Dockerfile frontend/package.json frontend/package-lock.json frontend/src/app/layout.tsx \
         searxng/settings.yml docs/GUIA_OPERATIVA.md LEEME.txt VERSION.txt $SCRIPTS; do
  [ -e "$STAGE/$f" ] || mal "Falta $f"
done
bien "Ficheros imprescindibles presentes"

# 5. Todas las migraciones del repo van en el paquete
if diff -rq backend/alembic/versions "$STAGE/backend/alembic/versions" --exclude='__pycache__' >/dev/null 2>&1; then
  bien "Migraciones: las $(ls "$STAGE"/backend/alembic/versions/[0-9]*.py | wc -l | tr -d ' ') del repo"
else
  mal "Las migraciones del paquete no coinciden con las del repo"
fi

# 6. .env: valores obligatorios
for k in OPENAI_API_KEY DATABASE_URL DATABASE_URL_SYNC REDIS_URL EMISOR_NOMBRE EMISOR_CIF EMISOR_DIRECCION EMISOR_EMAIL \
         EMISOR_IBAN FACTURA_SERIE DOCUMENTOS_DIR; do
  [ -n "$(valor "$k")" ] || mal ".env: $k vacío"
done
[ "$(valor OPENAI_MODEL)" = "gpt-5.4-nano" ] || mal ".env: OPENAI_MODEL no es gpt-5.4-nano"
[ "$(valor OPENAI_EXTRACTION_ENABLED)" = "true" ] || nota ".env: OPENAI_EXTRACTION_ENABLED no es true (la captación no extraerá)"
[ "$(valor DOCUMENTOS_DIR)" = "/app/data/documentos" ] || mal ".env: DOCUMENTOS_DIR debe ser /app/data/documentos"
[ "$(valor HISTORICO_BACKFILL_ENABLED)" != "true" ] || nota ".env: HISTORICO_BACKFILL_ENABLED=true (el backfill de 4 años quedaría habilitado)"
DUP="$(grep -E '^[A-Za-z_][A-Za-z0-9_]*=' "$STAGE/.env" | cut -d= -f1 | sort | uniq -d)"
[ -z "$DUP" ] && bien ".env sin claves duplicadas" || mal ".env con claves duplicadas: $DUP"
bien ".env: modelo $(valor OPENAI_MODEL), esfuerzo $(valor OPENAI_REASONING_EFFORT), concurrencia $(valor OPENAI_CONCURRENCY), email real $(valor EMAIL_SENDING_ENABLED)"
case "$(valor FACTURA_SERIE)" in *[!A-Za-z0-9-]*) nota ".env: FACTURA_SERIE='$(valor FACTURA_SERIE)' lleva símbolos; el número de factura queda feo (confirmar con la clienta)";; esac

# 7. Sintaxis de scripts y de docker-compose
if [ "$PLATAFORMA" = "windows" ]; then
  # Windows PowerShell 5.1 lee un .ps1 sin BOM como ANSI: cualquier caracter no ASCII se estropea.
  for s in $SCRIPTS LEEME.txt; do
    if LC_ALL=C grep -q '[^[:print:][:space:]]' "$STAGE/$s"; then mal "$s tiene caracteres no ASCII"; else bien "$s solo ASCII"; fi
  done
  grep -q $'\r' "$STAGE/ACTUALIZAR.bat" && bien "ACTUALIZAR.bat con saltos de linea de Windows" || mal "ACTUALIZAR.bat sin CRLF"
else
  for s in $SCRIPTS; do bash -n "$STAGE/$s" 2>/dev/null && bien "Sintaxis de $s" || mal "Error de sintaxis en $s"; done
fi
if docker compose --project-directory "$STAGE" -f "$STAGE/docker-compose.yml" config -q 2>/dev/null; then
  bien "docker-compose.yml válido con el .env del paquete"
else
  mal "docker compose config falla con el .env del paquete"
fi

echo
if [ "$FALLOS" -ne 0 ]; then
  echo "==> $FALLOS fallo(s). No se genera el zip."
  exit 1
fi

echo "==> Creando el zip"
ZIP="$SALIDA/$NOMBRE.zip"
rm -f "$ZIP" "$ZIP.sha256"
(cd "$TMP" && zip -r -X -q "$ZIP" "$NOMBRE")
unzip -tq "$ZIP" >/dev/null && bien "El zip se puede abrir sin errores"
(cd "$SALIDA" && shasum -a 256 "$NOMBRE.zip" > "$NOMBRE.zip.sha256")
printf '\n  %s\n  %s MB · %s ficheros · sha256 %s\n' "$ZIP" \
  "$(du -m "$ZIP" | cut -f1)" "$(unzip -Z1 "$ZIP" | grep -vc '/$')" "$(cut -c1-16 "$ZIP.sha256")…"
echo
echo "  Contenido de primer nivel:"
unzip -Z1 "$ZIP" | awk -F/ 'NF>=2 && $2!="" {print $2}' | sort -u | sed 's/^/    /'
