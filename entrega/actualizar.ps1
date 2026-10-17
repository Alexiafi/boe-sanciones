# BOE Sanciones - instala o actualiza el software desde esta carpeta (Windows).
#
#   ACTUALIZAR.bat                     (doble clic) detecta la instalacion existente y la actualiza
#   -Destino C:\ruta\instalada         actualiza esa carpeta concreta
#   -Si                                no pregunta
#   -SinCaptacion                      solo base de datos, API y web (sin worker/beat: no toca BOE ni OpenAI)
#
# Si no hay instalacion previa, instala desde cero en esta misma carpeta.
# Nunca borra la base de datos ni los contratos/facturas generados (backend\data).
# Fichero solo ASCII a proposito: Windows PowerShell 5.1 lee mal los acentos de un script sin BOM.

param(
  [string]$Destino = "",
  [switch]$Si,
  [switch]$SinCaptacion
)

$ErrorActionPreference = 'Continue'
$Aqui   = (Split-Path -Parent $MyInvocation.MyCommand.Path).TrimEnd('\')
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

$v = Get-Content (Join-Path $Aqui 'VERSION.txt') -TotalCount 1 -ErrorAction SilentlyContinue
if ($v) { Write-Host $v }
Write-Host "Registro de esta ejecucion: $Log"

# ---------------------------------------------------------------- 0. requisitos
Paso "Comprobando requisitos"
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
docker compose version *> $null
if ($LASTEXITCODE -ne 0) { Fallo "Falta 'docker compose' (Docker Desktop reciente)." }
Ok "Docker funcionando"

try {
  $unidad  = New-Object System.IO.DriveInfo((Split-Path -Qualifier $HOME))
  $LibreMB = [int][Math]::Floor($unidad.AvailableFreeSpace / 1MB)
} catch { $LibreMB = 100000 }
if ($LibreMB -lt 3000) { Fallo "Menos de 3 GB libres en el disco. Libera espacio antes de actualizar." }
Ok ("Espacio en disco: {0} GB libres" -f [int]($LibreMB / 1024))

# ------------------------------------------------- 1. localizar la instalacion
function Ruta-Local($p) {
  if (-not $p) { return $null }
  if (Test-Path -LiteralPath $p) { return (Resolve-Path -LiteralPath $p).ProviderPath.TrimEnd('\') }
  if ($p -match '^/(?:run/desktop/mnt/host|mnt)/([a-zA-Z])/(.*)$') {
    $c = $Matches[1].ToUpper() + ':\' + ($Matches[2] -replace '/', '\')
    if (Test-Path -LiteralPath $c) { return $c.TrimEnd('\') }
  }
  return $null
}

Paso "Buscando la instalacion existente"
$validos = @()
if (-not $Destino) {
  $ids = @(docker ps -a -q --filter 'label=com.docker.compose.service=postgres' 2>$null | Where-Object { $_ })
  foreach ($id in $ids) {
    $json = docker inspect $id --format '{{json .Config.Labels}}' 2>$null
    if (-not $json) { continue }
    $wd = ($json | ConvertFrom-Json).'com.docker.compose.project.working_dir'
    $ruta = Ruta-Local $wd
    if ($ruta -and (Test-Path (Join-Path $ruta 'docker-compose.yml')) -and (Test-Path (Join-Path $ruta 'backend')) -and ($validos -notcontains $ruta)) {
      $validos += $ruta
    }
  }
  if ($validos.Count -eq 1) {
    $Destino = $validos[0]
  } elseif ($validos.Count -gt 1) {
    Write-Host "    Hay varias instalaciones:"
    for ($i = 0; $i -lt $validos.Count; $i++) { Write-Host ("      {0}) {1}" -f ($i + 1), $validos[$i]) }
    $n = Read-Host "    Cual actualizo (numero)"
    if ($n -match '^\d+$' -and [int]$n -ge 1 -and [int]$n -le $validos.Count) { $Destino = $validos[[int]$n - 1] }
    if (-not $Destino) { Fallo "Opcion no valida." }
  } elseif ($ids.Count -gt 0) {
    Aviso "Hay contenedores de BOE Sanciones pero no he podido localizar su carpeta."
    $Destino = Read-Host "    Escribe la ruta completa de la carpeta instalada (o Enter para cancelar)"
    if (-not $Destino) { Fallo "Cancelado: no se ha tocado nada." }
  } else {
    $Destino = $Aqui
    Ok "No hay instalacion previa: instalacion desde cero en $Destino"
  }
}
if (-not (Test-Path -LiteralPath $Destino)) { Fallo "No existe la carpeta $Destino" }
$Destino = (Resolve-Path -LiteralPath $Destino).ProviderPath.TrimEnd('\')
Ok "Carpeta de trabajo: $Destino"

$EnSitio = ($Destino -ieq $Aqui)
$HayPrevia = $false
if ((-not $EnSitio) -and (Test-Path (Join-Path $Destino 'docker-compose.yml'))) { $HayPrevia = $true }
if ($EnSitio -and ($validos -contains $Destino)) { $HayPrevia = $true }

# ------------------------------------------------------- 2. el .env, antes de tocar nada
$utf8 = New-Object System.Text.UTF8Encoding($false)
$ClavesBD = @('POSTGRES_USER', 'POSTGRES_PASSWORD', 'POSTGRES_DB', 'DATABASE_URL', 'DATABASE_URL_SYNC')

function Leer-Lineas($ruta) { return [System.IO.File]::ReadAllLines($ruta, $utf8) }
function Es-Asignacion($l) { return (($l -notmatch '^\s*#') -and ($l.IndexOf('=') -ge 1)) }
function Mapa-Env($lineas) {
  $m = New-Object System.Collections.Specialized.OrderedDictionary
  foreach ($l in $lineas) {
    if (Es-Asignacion $l) {
      $i = $l.IndexOf('=')
      $m[$l.Substring(0, $i).Trim()] = $l.Substring($i + 1)
    }
  }
  return $m
}
function Mascara($k, $val) {
  if ([string]::IsNullOrEmpty($val)) { return '(vacio)' }
  if ($k -match 'KEY|PASSWORD|TOKEN|SECRET|LOGIN|USER') {
    return ($val.Substring(0, [Math]::Min(3, $val.Length)) + '... (' + $val.Length + ' caracteres)')
  }
  return $val
}

$NuevoEnv = Join-Path $Aqui '.env'
if (-not (Test-Path $NuevoEnv)) { Fallo "Este paquete no trae .env. Pide uno nuevo." }
$ViejoEnv = Join-Path $Destino '.env'
$LineasNuevo = Leer-Lineas $NuevoEnv
$EnvFinal = New-Object System.Collections.Generic.List[string]

if ((-not $EnSitio) -and (Test-Path $ViejoEnv)) {
  # El .env del paquete manda, salvo las credenciales de la base de datos: el volumen ya se creo con las suyas.
  $Viejo = Mapa-Env (Leer-Lineas $ViejoEnv)
  foreach ($l in $LineasNuevo) {
    $linea = $l
    if (Es-Asignacion $l) {
      $k = $l.Substring(0, $l.IndexOf('=')).Trim()
      if (($ClavesBD -contains $k) -and $Viejo.Contains($k)) { $linea = $k + '=' + $Viejo[$k] }
    }
    $EnvFinal.Add($linea)
  }
  $Nuevo = Mapa-Env $EnvFinal.ToArray()

  Paso "Diferencias entre el .env actual y el que trae el paquete"
  $claves = @(@($Viejo.Keys) + @($Nuevo.Keys)) | Select-Object -Unique | Sort-Object
  $nd = 0
  foreach ($k in $claves) {
    if ($ClavesBD -contains $k) { continue }
    $enV = $Viejo.Contains($k)
    $enN = $Nuevo.Contains($k)
    if ($enV -and $enN -and ($Viejo[$k] -ceq $Nuevo[$k])) { continue }
    if (-not $enV)     { Write-Host ("      + {0,-42} nuevo: {1}" -f $k, (Mascara $k $Nuevo[$k])) }
    elseif (-not $enN) { Write-Host ("      - {0,-42} se quita (tenia {1})" -f $k, (Mascara $k $Viejo[$k])) }
    else               { Write-Host ("      ~ {0,-42} {1}  ->  {2}" -f $k, (Mascara $k $Viejo[$k]), (Mascara $k $Nuevo[$k])) }
    $nd++
  }
  if ($nd -eq 0) { Write-Host "      (ninguna)" }
  Write-Host "    (Las credenciales de Postgres se conservan tal como estaban. Copia del .env actual en $Copias)"
} else {
  foreach ($l in $LineasNuevo) { $EnvFinal.Add($l) }
}
$MapaFinal = Mapa-Env $EnvFinal.ToArray()
$PgUser = $MapaFinal['POSTGRES_USER']; if (-not $PgUser) { $PgUser = 'boe' }
$PgDb   = $MapaFinal['POSTGRES_DB'];   if (-not $PgDb)   { $PgDb = 'boe_sanciones' }

# ------------------------------------------------------------ 3. confirmacion
Paso "Plan"
if ($HayPrevia) {
  Write-Host "    Actualizar la instalacion de: $Destino"
  Write-Host "      1. Para la captacion y la web (la base de datos y el .env NO se borran)."
  Write-Host "      2. Copia de seguridad de la base de datos y del codigo actual en $Copias"
  Write-Host "      3. Pone el codigo nuevo y el .env de arriba. backend\data (contratos y facturas) no se toca."
  Write-Host "      4. Reconstruye y arranca; aplica las migraciones de la base de datos."
  Write-Host "      5. Comprueba que todo responde y que no se ha perdido ningun cliente."
} else {
  Write-Host "    Instalar desde cero en: $Destino"
  Write-Host "      Construye y arranca todo (la primera vez tarda unos 10 min: descarga imagenes)."
}
if (-not (Confirmar "    Continuar?")) { Write-Host "Cancelado. No se ha tocado nada."; try { Stop-Transcript | Out-Null } catch { }; exit 0 }

Set-Location $Destino

function Psql($sql) {
  $r = docker compose exec -T postgres psql -U $PgUser -d $PgDb -At -c $sql 2>$null
  if ($LASTEXITCODE -ne 0) { return '' }
  return (($r | Out-String).Trim())
}

$AntesVersion = ''; $AntesClientes = ''; $AntesDocs = ''; $AntesSanc = ''
if ($HayPrevia) {
  # --------------------------------------------------- 4. parar captacion y copia
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

  Paso "Copia del codigo y .env actuales"
  $CopiaCodigo = Join-Path $Copias "codigo-$Fecha"
  robocopy $Destino $CopiaCodigo /E /XD "$Destino\backend\data" "$Destino\backend\.venv" "$Destino\frontend\node_modules" "$Destino\frontend\.next" "$Destino\.git" "__pycache__" /NFL /NDL /NJH /NJS /NP | Out-Null
  if ($LASTEXITCODE -ge 8) { Fallo "No se pudo copiar el codigo actual." }
  Ok $CopiaCodigo
}

# ---------------------------------------------------------- 5. poner el codigo nuevo
if (-not $EnSitio) {
  Paso "Copiando el codigo nuevo"
  robocopy $Aqui $Destino /E /XD "$Aqui\backend\data" "$Destino\backend\data" "$Destino\backend\.venv" "$Destino\frontend\node_modules" "$Destino\frontend\.next" /XF .env /NFL /NDL /NJH /NJS /NP | Out-Null
  if ($LASTEXITCODE -ge 8) { Fallo "Fallo la copia del codigo." }
  # Carpetas de codigo: se sincronizan borrando lo que ya no existe (modulos antiguos). Nada mas se borra.
  foreach ($d in @('backend\app', 'backend\alembic', 'backend\scripts', 'frontend\src', 'frontend\public', 'searxng')) {
    if (Test-Path (Join-Path $Aqui $d)) {
      robocopy (Join-Path $Aqui $d) (Join-Path $Destino $d) /MIR /NFL /NDL /NJH /NJS /NP | Out-Null
      if ($LASTEXITCODE -ge 8) { Fallo "Fallo la copia de $d." }
    }
  }
  Ok "Codigo actualizado (backend\data intacto)"
}
# .env en UTF-8 sin BOM y con saltos de linea \n (lo que espera Docker Compose)
[System.IO.File]::WriteAllText((Join-Path $Destino '.env'), (($EnvFinal -join "`n") + "`n"), $utf8)
Ok ".env puesto"

# ------------------------------------------------------------ 6. construir y arrancar
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

# ------------------------------------------------------------ 7. comprobaciones
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

$AutoArranque = $false
try {
  $run = Get-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -ErrorAction SilentlyContinue
  if ($run -and ($run.PSObject.Properties.Name -contains 'Docker Desktop')) { $AutoArranque = $true }
  foreach ($f in @("$env:APPDATA\Docker\settings-store.json", "$env:APPDATA\Docker\settings.json")) {
    if ((Test-Path $f) -and ((Get-Content $f -Raw) -match '(?i)"(AutoStart|OpenAtLogin)"\s*:\s*true')) { $AutoArranque = $true }
  }
} catch { }
if ($AutoArranque) { Ok "Docker Desktop arranca al iniciar sesion" }
else { Mal "Docker Desktop NO arranca solo al iniciar sesion: Docker Desktop -> Settings (engranaje) -> General -> 'Start Docker Desktop when you sign in to your computer'" }

Paso "Resultado"
if ($Problemas -eq 0) { Write-Host "    TODO CORRECTO. Abre http://localhost:3000" -ForegroundColor Green }
else { Write-Host "    Terminado con $Problemas aviso(s) arriba. Revisalos antes de dar la instalacion por buena." -ForegroundColor Yellow }
if (-not $SinCaptacion) {
  Write-Host "    Al arrancar, el worker se pone al dia solo con los ultimos 10 dias (tarda unos minutos y usa OpenAI)."
  Write-Host "    Se puede seguir en la web: Operacion."
}
Write-Host "    Copias de seguridad: $Copias"
try { Stop-Transcript | Out-Null } catch { }
if ($Problemas -eq 0) { exit 0 } else { exit 2 }
