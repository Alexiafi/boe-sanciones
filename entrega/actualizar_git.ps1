# BOE Sanciones - actualiza ESTA carpeta desde git (Windows). Lo lanza ACTUALIZAR.bat de la raiz.
#
#   ACTUALIZAR.bat                     (doble clic) descarga la ultima version publicada y la instala
#   -Si                                no pregunta
#   -SinCaptacion                      solo base de datos, API y web (sin worker/beat: no toca BOE ni OpenAI)
#   -Forzar                            reconstruye aunque ya este al dia
#
# Descarga solo la ultima version de la rama 'produccion' (sin historial). Antes de tocar nada hace copia de la
# base de datos y del codigo en %USERPROFILE%\boe-sanciones-copias (VOLVER_ATRAS.bat la restaura).
# Nunca toca el .env ni backend\data (contratos y facturas): git no los gestiona.
# La carpeta debe estar conectada antes con CONECTAR.bat (una sola vez).
# Fichero solo ASCII a proposito: Windows PowerShell 5.1 lee mal los acentos de un script sin BOM.

param(
  [switch]$Si,
  [switch]$SinCaptacion,
  [switch]$Forzar
)

$ErrorActionPreference = 'Continue'
$Rama   = 'produccion'
$Raiz   = (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)).TrimEnd('\')
$Fecha  = Get-Date -Format 'yyyy-MM-dd_HHmm'
$Copias = Join-Path $HOME 'boe-sanciones-copias'
New-Item -ItemType Directory -Force -Path $Copias | Out-Null
$Log = Join-Path $Copias "actualizacion-$Fecha.log"
try { Start-Transcript -Path $Log -Append | Out-Null } catch { }

function Paso($t)  { Write-Host ""; Write-Host "==> $t" -ForegroundColor Cyan }
function Ok($t)    { Write-Host "    OK    $t" -ForegroundColor Green }
function Aviso($t) { Write-Host "    AVISO $t" -ForegroundColor Yellow }
function Fallo($t) {
  Write-Host ""
  Write-Host "    ERROR $t" -ForegroundColor Red
  Write-Host "    Registro completo: $Log"
  try { Stop-Transcript | Out-Null } catch { }
  exit 1
}
function Confirmar($t) {
  if ($Si) { return $true }
  $r = Read-Host "$t [s/N]"
  return ($r -match '^[sS]')
}

Write-Host "Carpeta: $Raiz"
Write-Host "Registro de esta ejecucion: $Log"

# ---------------------------------------------------------------- 0. requisitos
Paso "Comprobando requisitos"
$Git = $null
if (Get-Command git -ErrorAction SilentlyContinue) { $Git = 'git' }
else {
  foreach ($c in @("$env:ProgramFiles\Git\cmd\git.exe", "${env:ProgramFiles(x86)}\Git\cmd\git.exe", "$env:LOCALAPPDATA\Programs\Git\cmd\git.exe")) {
    if ($c -and (Test-Path $c)) { $Git = $c; break }
  }
}
if (-not $Git) { Fallo "Falta Git. En PowerShell: winget install --id Git.Git -e   (y vuelve a lanzar)" }
function G { & $Git -C $Raiz @args }

if (-not (Test-Path (Join-Path $Raiz '.git'))) { Fallo "Esta carpeta no esta conectada a git. Usa CONECTAR.bat (una sola vez)." }
if (-not (Test-Path (Join-Path $Raiz '.env'))) { Fallo "No hay .env en $Raiz." }
if (-not (Test-Path (Join-Path $Raiz 'docker-compose.yml'))) { Fallo "$Raiz no parece una instalacion (falta docker-compose.yml)." }
Ok "Git: $Git"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  Fallo "No se encuentra el comando 'docker'. Abre Docker Desktop y vuelve a lanzar."
}
function DockerListo { docker info *> $null; return ($LASTEXITCODE -eq 0) }
if (-not (DockerListo)) {
  Aviso "Docker no esta abierto. Lo abro y espero (hasta 3 min)..."
  $exe = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
  if (Test-Path $exe) { Start-Process $exe }
  for ($i = 0; $i -lt 36; $i++) { Start-Sleep -Seconds 5; if (DockerListo) { break } }
  if (-not (DockerListo)) { Fallo "Docker Desktop no arranca. Abrelo a mano y vuelve a lanzar este script." }
}
Ok "Docker funcionando"

try {
  $unidad  = New-Object System.IO.DriveInfo((Split-Path -Qualifier $Raiz))
  $LibreMB = [int][Math]::Floor($unidad.AvailableFreeSpace / 1MB)
} catch { $LibreMB = 100000 }
if ($LibreMB -lt 3000) { Fallo "Menos de 3 GB libres en el disco. Libera espacio antes de actualizar." }
Ok ("Espacio en disco: {0} GB libres" -f [int]($LibreMB / 1024))

# La base de datos en marcha tiene que ser la de ESTA carpeta: el nombre de la carpeta decide el volumen.
function Ruta-Local($p) {
  if (-not $p) { return $null }
  if (Test-Path -LiteralPath $p) { return (Resolve-Path -LiteralPath $p).ProviderPath.TrimEnd('\') }
  if ($p -match '^/(?:run/desktop/mnt/host|mnt)/([a-zA-Z])/(.*)$') {
    $c = $Matches[1].ToUpper() + ':\' + ($Matches[2] -replace '/', '\')
    if (Test-Path -LiteralPath $c) { return $c.TrimEnd('\') }
  }
  return $null
}
$Otras = @()
$HayPrevia = $false
foreach ($id in @(docker ps -a -q --filter 'label=com.docker.compose.service=postgres' 2>$null | Where-Object { $_ })) {
  $json = docker inspect $id --format '{{json .Config.Labels}}' 2>$null
  if (-not $json) { continue }
  $ruta = Ruta-Local (($json | ConvertFrom-Json).'com.docker.compose.project.working_dir')
  if ($ruta -and ($ruta -ieq $Raiz)) { $HayPrevia = $true } elseif ($ruta) { $Otras += $ruta }
}
if ((-not $HayPrevia) -and ($Otras.Count -gt 0)) {
  Fallo ("La instalacion que esta en marcha es otra carpeta: " + ($Otras -join ', ') + ". Lanza ACTUALIZAR.bat desde esa carpeta.")
}

# ---------------------------------------------------------------- 1. descargar
Paso "Descargando la ultima version publicada"
G fetch -q --depth 1 origin $Rama
if ($LASTEXITCODE -ne 0) { Fallo "No se pudo descargar de GitHub (sin internet o sin acceso con la clave). No se ha tocado nada." }
$Nuevo  = ((G rev-parse FETCH_HEAD) | Out-String).Trim()
$Actual = ((G rev-parse -q --verify HEAD 2>$null) | Out-String).Trim()
$Desc   = ((G log -1 --date=short --format=%h__%cd__%s FETCH_HEAD) | Out-String).Trim() -replace '__', '  '
Ok "Version publicada: $Desc"
if ($Actual) {
  $DescActual = ((G log -1 --date=short --format=%h__%cd__%s HEAD) | Out-String).Trim() -replace '__', '  '
  Write-Host "    Version instalada: $DescActual"
} else {
  Write-Host "    Primera actualizacion por git en esta carpeta."
}
if (($Actual -eq $Nuevo) -and (-not $Forzar)) {
  Ok "Ya esta al dia. No hay nada que hacer."
  try { Stop-Transcript | Out-Null } catch { }
  exit 0
}
$Cambios = @(G status --porcelain --untracked-files=no 2>$null | Where-Object { $_ })
if ($Actual -and ($Cambios.Count -gt 0)) {
  Aviso ("Hay {0} fichero(s) de codigo cambiados a mano en esta carpeta; se sustituyen (quedan en la copia):" -f $Cambios.Count)
  $Cambios | Select-Object -First 10 | ForEach-Object { Write-Host "          $_" }
}

# ---------------------------------------------------------------- 2. confirmacion
$PgUser = 'boe'; $PgDb = 'boe_sanciones'
foreach ($l in [System.IO.File]::ReadAllLines((Join-Path $Raiz '.env'))) {
  if ($l -match '^POSTGRES_USER=(.+)$') { $PgUser = $Matches[1].Trim().Trim('"') }
  if ($l -match '^POSTGRES_DB=(.+)$')   { $PgDb = $Matches[1].Trim().Trim('"') }
}

Paso "Plan"
Write-Host "    Actualizar: $Raiz"
Write-Host "      1. Para la captacion y la web (la base de datos y el .env NO se borran)."
Write-Host "      2. Copia de seguridad de la base de datos y del codigo actual en $Copias"
Write-Host "      3. Pone el codigo nuevo. El .env y backend\data (contratos y facturas) no se tocan."
Write-Host "      4. Reconstruye y arranca; aplica las migraciones de la base de datos."
Write-Host "      5. Comprueba que todo responde y que no se ha perdido ningun cliente."
if (-not (Confirmar "    Continuar?")) { Write-Host "Cancelado. No se ha tocado nada."; try { Stop-Transcript | Out-Null } catch { }; exit 0 }

Set-Location $Raiz

function Psql($sql) {
  $r = docker compose exec -T postgres psql -U $PgUser -d $PgDb -At -c $sql 2>$null
  if ($LASTEXITCODE -ne 0) { return '' }
  return (($r | Out-String).Trim())
}

# ------------------------------------------------------- 3. parar captacion y copias
$AntesVersion = ''; $AntesClientes = ''; $AntesDocs = ''; $AntesSanc = ''
if ($HayPrevia) {
  Paso "Parando captacion, API y web"
  docker compose stop celery-worker celery-beat backend frontend *> $null
  docker compose up -d postgres *> $null
  if ($LASTEXITCODE -ne 0) { Fallo "No arranca la base de datos." }
  for ($i = 0; $i -lt 30; $i++) {
    docker compose exec -T postgres pg_isready -U $PgUser *> $null
    if ($LASTEXITCODE -eq 0) { break }
    Start-Sleep -Seconds 2
  }
  Ok "Captacion parada; la base de datos sigue encendida"

  if ((Psql "SELECT to_regclass('public.alembic_version') IS NOT NULL") -eq 't') {
    $AntesVersion  = Psql 'SELECT version_num FROM alembic_version'
    $AntesClientes = Psql 'SELECT count(*) FROM clientes'
    $AntesDocs     = Psql 'SELECT count(*) FROM documentos_comerciales'
    $AntesSanc     = Psql 'SELECT count(*) FROM sancionados'

    Paso "Copia de seguridad de la base de datos"
    $TamMB = 0
    $t = Psql 'SELECT pg_database_size(current_database())/1024/1024'
    if ($t -match '^\d+$') { $TamMB = [int]$t }
    $Dump = Join-Path $Copias "bd-$Fecha.dump"
    $extra = ''
    if ($LibreMB -le ($TamMB + 2048)) {
      $extra = '--exclude-table-data=documento_archivos'
      Aviso "Poco espacio ($LibreMB MB libres, BD de $TamMB MB): copia sin los PDF originales archivados"
    }
    docker compose exec -T postgres sh -c "pg_dump -U $PgUser -d $PgDb -Fc $extra -f /tmp/boe-backup.dump"
    if ($LASTEXITCODE -ne 0) { Fallo "Fallo la copia de seguridad. No se ha tocado nada mas." }
    $idpg = (docker compose ps -q postgres | Select-Object -First 1)
    docker cp "${idpg}:/tmp/boe-backup.dump" $Dump
    docker compose exec -T postgres rm -f /tmp/boe-backup.dump *> $null
    if ((-not (Test-Path $Dump)) -or ((Get-Item $Dump).Length -lt 1000)) {
      Remove-Item $Dump -ErrorAction SilentlyContinue
      Fallo "La copia de seguridad no se ha generado bien. No se ha tocado nada mas."
    }
    Ok ("Copia de seguridad: {0} ({1} MB)" -f $Dump, [int]((Get-Item $Dump).Length / 1MB))
    Write-Host ("    Antes: esquema {0} - {1} clientes - {2} sancionados - {3} contratos/facturas" -f $AntesVersion, $AntesClientes, $AntesSanc, $AntesDocs)
  } else {
    Aviso "La base de datos existe pero esta vacia (sin esquema). Se creara al arrancar."
  }
}

Paso "Copia del codigo y .env actuales"
$CopiaCodigo = Join-Path $Copias "codigo-$Fecha"
robocopy $Raiz $CopiaCodigo /E /XD "$Raiz\backend\data" "$Raiz\backend\.venv" "$Raiz\frontend\node_modules" "$Raiz\frontend\.next" "$Raiz\.git" "__pycache__" /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { Fallo "No se pudo copiar el codigo actual." }
if ($Actual) { Set-Content -Path (Join-Path $CopiaCodigo 'VERSION-GIT.txt') -Value $Actual -Encoding Ascii }
Ok $CopiaCodigo

# ---------------------------------------------------------------- 4. codigo nuevo
Paso "Poniendo el codigo nuevo"
G reset -q --hard FETCH_HEAD
if ($LASTEXITCODE -ne 0) { Fallo "git no pudo poner la version nueva. Para volver atras: VOLVER_ATRAS.bat" }
# Restos del paquete zip de la instalacion anterior (ya copiados arriba): se quitan si git no los gestiona.
foreach ($f in @('actualizar.ps1', 'volver_atras.ps1', 'LEEME.txt', 'VERSION.txt')) {
  $p = Join-Path $Raiz $f
  if (Test-Path $p) {
    G ls-files --error-unmatch $f *> $null
    if ($LASTEXITCODE -ne 0) { Remove-Item $p -Force -ErrorAction SilentlyContinue }
  }
}
Ok "Codigo en la version $Desc (backend\data y .env intactos)"

# ---------------------------------------------------------------- 5. construir y arrancar
Paso "Construyendo y arrancando (varios minutos; no cierres la ventana)"
if ($SinCaptacion) {
  docker compose up -d --build postgres migrate backend frontend
} else {
  docker compose up -d --build
}
if ($LASTEXITCODE -ne 0) {
  Write-Host ""
  Write-Host "    Fallo la construccion. Tus datos estan a salvo (copia en $Copias)."
  Write-Host "    Para volver a la version anterior: VOLVER_ATRAS.bat"
  Fallo "docker compose no pudo arrancar. Envia el registro."
}

Paso "Esperando a que responda (las migraciones se aplican aqui)"
function Responde($url) {
  try { $r = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 10; return ($r.StatusCode -eq 200) } catch { return $false }
}
$Listo = $false
for ($i = 0; $i -lt 90; $i++) {
  if (Responde 'http://localhost:8000/api/health') { $Listo = $true; break }
  Start-Sleep -Seconds 4
}
if (-not $Listo) { Fallo "La API no responde tras 6 min. Mira: docker compose logs migrate backend" }

# ---------------------------------------------------------------- 6. comprobaciones
Paso "Comprobaciones"
$Problemas = 0
function Mal($t) { Aviso $t; $script:Problemas++ }
function Primera-Palabra($salida) {
  foreach ($l in @($salida)) { if ("$l" -match '^([0-9a-z_]+)') { return $Matches[1] } }
  return ''
}

$VersionNueva = Primera-Palabra (docker compose exec -T backend alembic current 2>$null)
$Cabeza       = Primera-Palabra (docker compose exec -T backend alembic heads 2>$null)
if ($VersionNueva -and ($VersionNueva -eq $Cabeza)) { Ok "Base de datos al dia: $VersionNueva" } else { Mal "Migraciones: actual='$VersionNueva' esperada='$Cabeza'" }

if ($AntesClientes -ne '') {
  $dCli = Psql 'SELECT count(*) FROM clientes'
  $dDoc = Psql 'SELECT count(*) FROM documentos_comerciales'
  $dSan = Psql 'SELECT count(*) FROM sancionados'
  if ($dCli -eq $AntesClientes) { Ok "Clientes: $dCli (antes $AntesClientes)" } else { Mal "Clientes: $dCli, antes $AntesClientes" }
  if ($dDoc -eq $AntesDocs) { Ok "Contratos/facturas: $dDoc (antes $AntesDocs)" } else { Mal "Contratos/facturas: $dDoc, antes $AntesDocs" }
  if (($dSan -match '^\d+$') -and ([int]$dSan -ge [int]$AntesSanc)) { Ok "Sancionados: $dSan (antes $AntesSanc)" } else { Mal "Sancionados: $dSan, antes $AntesSanc" }
}

if (Responde 'http://localhost:3000') { Ok "Web: http://localhost:3000" } else { Mal "La web no responde en el puerto 3000 (puede tardar un minuto mas)" }

if (-not $SinCaptacion) {
  $enMarcha = @(docker compose ps --status running --services 2>$null)
  foreach ($s in @('celery-worker', 'celery-beat')) {
    if ($enMarcha -contains $s) { Ok "$s en marcha" } else { Mal "$s no esta en marcha" }
  }
  $Modelo = ((docker compose exec -T celery-worker printenv OPENAI_MODEL 2>$null) | Out-String).Trim()
  if ($Modelo -eq 'gpt-5.4-nano') { Ok "Modelo de OpenAI: $Modelo" } else { Mal "Modelo de OpenAI es '$Modelo' (deberia ser gpt-5.4-nano)" }
} else {
  Aviso "Modo -SinCaptacion: worker y beat NO arrancados (no se captura nada ni se llama a OpenAI)."
}

$ReinicioOk = $true
foreach ($s in @('postgres', 'redis', 'backend', 'frontend', 'celery-worker', 'celery-beat')) {
  $cid = (docker compose ps -q $s 2>$null | Select-Object -First 1)
  if (-not $cid) { continue }
  $pol = ((docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' $cid 2>$null) | Out-String).Trim()
  if ($pol -ne 'unless-stopped') { $ReinicioOk = $false; Mal "$s sin reinicio automatico (politica '$pol')" }
}
if ($ReinicioOk) { Ok "Los servicios se reinician solos tras apagar o reiniciar Docker" }

Paso "Resultado"
if ($Problemas -eq 0) { Write-Host "    TODO CORRECTO. Version $Desc. Abre http://localhost:3000" -ForegroundColor Green }
else { Write-Host "    Terminado con $Problemas aviso(s) arriba. Revisalos antes de dar la instalacion por buena." -ForegroundColor Yellow }
Write-Host "    Copias de seguridad: $Copias  (para volver atras: VOLVER_ATRAS.bat)"
try { Stop-Transcript | Out-Null } catch { }
if ($Problemas -eq 0) { exit 0 } else { exit 2 }
