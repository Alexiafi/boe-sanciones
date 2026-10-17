# BOE Sanciones - vuelve a la version anterior a la ultima actualizacion (Windows).
# Restaura el codigo, el .env y la base de datos desde la ultima copia de seguridad que hizo actualizar.ps1
# (en %USERPROFILE%\boe-sanciones-copias). Lo que se haya hecho en la aplicacion DESPUES de actualizar se pierde.
#
#   VOLVER_ATRAS.bat                   usa la ultima copia y detecta la instalacion
#   -Destino C:\ruta\instalada         usa esa carpeta
#   -Si                                no pregunta
#   -SinCaptacion                      no arranca worker/beat (solo base de datos, API y web)
# Fichero solo ASCII a proposito (Windows PowerShell 5.1).

param(
  [string]$Destino = "",
  [switch]$Si,
  [switch]$SinCaptacion
)

$ErrorActionPreference = 'Continue'
$Copias = Join-Path $HOME 'boe-sanciones-copias'
function Fallo($t) { Write-Host ""; Write-Host "    ERROR $t" -ForegroundColor Red; exit 1 }

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Fallo "No se encuentra docker." }
docker info *> $null
if ($LASTEXITCODE -ne 0) { Fallo "Docker no esta abierto." }

function Ruta-Local($p) {
  if (-not $p) { return $null }
  if (Test-Path -LiteralPath $p) { return (Resolve-Path -LiteralPath $p).ProviderPath.TrimEnd('\') }
  if ($p -match '^/(?:run/desktop/mnt/host|mnt)/([a-zA-Z])/(.*)$') {
    $c = $Matches[1].ToUpper() + ':\' + ($Matches[2] -replace '/', '\')
    if (Test-Path -LiteralPath $c) { return $c.TrimEnd('\') }
  }
  return $null
}

if (-not $Destino) {
  $validos = @()
  $ids = @(docker ps -a -q --filter 'label=com.docker.compose.service=postgres' 2>$null | Where-Object { $_ })
  foreach ($id in $ids) {
    $json = docker inspect $id --format '{{json .Config.Labels}}' 2>$null
    if (-not $json) { continue }
    $ruta = Ruta-Local (($json | ConvertFrom-Json).'com.docker.compose.project.working_dir')
    if ($ruta -and (Test-Path (Join-Path $ruta 'docker-compose.yml')) -and ($validos -notcontains $ruta)) { $validos += $ruta }
  }
  if ($validos.Count -ne 1) { Fallo "No encuentro una unica instalacion. Indica la carpeta: -Destino C:\ruta\instalada" }
  $Destino = $validos[0]
}
if (-not (Test-Path (Join-Path $Destino 'docker-compose.yml'))) { Fallo "$Destino no parece una instalacion." }

$Dump   = Get-ChildItem $Copias -Filter 'bd-*.dump' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$Codigo = Get-ChildItem $Copias -Directory -Filter 'codigo-*' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ((-not $Dump) -or (-not $Codigo)) { Fallo "No hay copias de seguridad en $Copias" }

Write-Host "Instalacion:    $Destino"
Write-Host "Base de datos:  $($Dump.FullName)"
Write-Host "Codigo y .env:  $($Codigo.FullName)"
if (-not $Si) {
  $r = Read-Host "Se perdera todo lo hecho en la aplicacion desde esa copia. Continuar? [s/N]"
  if ($r -notmatch '^[sS]') { Write-Host "Cancelado."; exit 0 }
}

Set-Location $Destino
docker compose stop celery-worker celery-beat backend frontend *> $null
docker compose up -d postgres *> $null
if ($LASTEXITCODE -ne 0) { Fallo "No arranca la base de datos." }

# El .env guardado dice que usuario/base tenia la instalacion anterior.
$PgUser = 'boe'; $PgDb = 'boe_sanciones'
$envGuardado = Join-Path $Codigo.FullName '.env'
if (Test-Path $envGuardado) {
  foreach ($l in [System.IO.File]::ReadAllLines($envGuardado)) {
    if ($l -match '^POSTGRES_USER=(.+)$') { $PgUser = $Matches[1].Trim() }
    if ($l -match '^POSTGRES_DB=(.+)$')   { $PgDb = $Matches[1].Trim() }
  }
}
for ($i = 0; $i -lt 30; $i++) {
  docker compose exec -T postgres pg_isready -U $PgUser *> $null
  if ($LASTEXITCODE -eq 0) { break }
  Start-Sleep -Seconds 2
}

Write-Host "==> Restaurando la base de datos"
docker compose exec -T postgres psql -U $PgUser -d $PgDb -q -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;'
if ($LASTEXITCODE -ne 0) { Fallo "No se pudo limpiar la base de datos." }
$idpg = (docker compose ps -q postgres | Select-Object -First 1)
docker cp $Dump.FullName "${idpg}:/tmp/boe-restore.dump"
docker compose exec -T postgres pg_restore -U $PgUser -d $PgDb --no-owner /tmp/boe-restore.dump
if ($LASTEXITCODE -ne 0) { Write-Host "    AVISO pg_restore termino con avisos (suele ser normal). Comprueba los datos." -ForegroundColor Yellow }
docker compose exec -T postgres rm -f /tmp/boe-restore.dump *> $null

Write-Host "==> Restaurando el codigo y el .env"
foreach ($d in @('backend\app', 'backend\alembic', 'frontend\src')) {
  if (Test-Path (Join-Path $Destino $d)) { Remove-Item (Join-Path $Destino $d) -Recurse -Force }
}
robocopy $Codigo.FullName $Destino /E /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { Fallo "No se pudo restaurar el codigo." }

Write-Host "==> Arrancando la version anterior"
if ($SinCaptacion) { docker compose up -d --build postgres migrate backend frontend } else { docker compose up -d --build }
if ($LASTEXITCODE -ne 0) { Fallo "No arranca. Envia este registro." }
Write-Host ""
Write-Host "Listo. Version anterior restaurada. Abre http://localhost:3000" -ForegroundColor Green
