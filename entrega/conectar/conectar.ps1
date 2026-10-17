# BOE Sanciones - conecta la instalacion de este PC a git (una sola vez). Lo lanza CONECTAR.bat.
#
# 1. Instala Git si falta (pregunta antes).
# 2. Guarda la clave de solo lectura en %USERPROFILE%\.ssh\boe-sanciones (no toca otras claves ni ~/.ssh/config).
# 3. Localiza la instalacion en marcha (etiquetas de Docker) y la conecta a git EN LA MISMA CARPETA:
#    el nombre de la carpeta decide el volumen de la base de datos, asi que nunca se usa otra.
# 4. Comprueba el acceso y lanza la primera actualizacion (entrega\actualizar_git.ps1: copia de seguridad,
#    codigo nuevo, reconstruccion y comprobaciones). Despues, para actualizar basta ACTUALIZAR.bat en esa carpeta.
# Fichero solo ASCII a proposito (Windows PowerShell 5.1).

param(
  [string]$Destino = ""
)

$ErrorActionPreference = 'Continue'
$Aqui   = (Split-Path -Parent $MyInvocation.MyCommand.Path).TrimEnd('\')
$Repo   = 'git@github.com:Alexiafi/boe-sanciones.git'
$Rama   = 'produccion'
$DirSsh = Join-Path $HOME '.ssh\boe-sanciones'

function Paso($t)  { Write-Host ""; Write-Host "==> $t" -ForegroundColor Cyan }
function Ok($t)    { Write-Host "    OK    $t" -ForegroundColor Green }
function Aviso($t) { Write-Host "    AVISO $t" -ForegroundColor Yellow }
function Fallo($t) { Write-Host ""; Write-Host "    ERROR $t" -ForegroundColor Red; exit 1 }

# ---------------------------------------------------------------- 1. Git
Paso "Git"
function Buscar-Git {
  if (Get-Command git -ErrorAction SilentlyContinue) { return 'git' }
  foreach ($c in @("$env:ProgramFiles\Git\cmd\git.exe", "${env:ProgramFiles(x86)}\Git\cmd\git.exe", "$env:LOCALAPPDATA\Programs\Git\cmd\git.exe")) {
    if ($c -and (Test-Path $c)) { return $c }
  }
  return $null
}
$Git = Buscar-Git
if (-not $Git) {
  $r = Read-Host "    Git no esta instalado. Lo instalo ahora con winget? [s/N]"
  if ($r -notmatch '^[sS]') { Fallo "Sin Git no se puede seguir. Instala Git (winget install --id Git.Git -e) y vuelve a lanzar." }
  winget install --id Git.Git -e --source winget
  $Git = Buscar-Git
  if (-not $Git) { Fallo "Git no aparece tras instalarlo. Cierra esta ventana y vuelve a lanzar CONECTAR.bat." }
}
Ok "Git: $Git"

# ---------------------------------------------------------------- 2. clave de solo lectura
Paso "Clave de acceso (solo lectura)"
foreach ($f in @('id_boe', 'known_hosts')) {
  if (-not (Test-Path (Join-Path $Aqui $f))) { Fallo "Falta el fichero $f junto a este script. Pide el paquete de conexion otra vez." }
}
New-Item -ItemType Directory -Force -Path $DirSsh | Out-Null
Copy-Item (Join-Path $Aqui 'id_boe') (Join-Path $DirSsh 'id_boe') -Force
Copy-Item (Join-Path $Aqui 'known_hosts') (Join-Path $DirSsh 'known_hosts') -Force
Ok "Guardada en $DirSsh"
# Ruta con barras normales y ~ para el ssh que trae Git (funciona aunque el usuario tenga espacios en el nombre).
$SshCmd = 'ssh -i ~/.ssh/boe-sanciones/id_boe -o IdentitiesOnly=yes -o UserKnownHostsFile=~/.ssh/boe-sanciones/known_hosts'

# ---------------------------------------------------------------- 3. localizar la instalacion
function Ruta-Local($p) {
  if (-not $p) { return $null }
  if (Test-Path -LiteralPath $p) { return (Resolve-Path -LiteralPath $p).ProviderPath.TrimEnd('\') }
  if ($p -match '^/(?:run/desktop/mnt/host|mnt)/([a-zA-Z])/(.*)$') {
    $c = $Matches[1].ToUpper() + ':\' + ($Matches[2] -replace '/', '\')
    if (Test-Path -LiteralPath $c) { return $c.TrimEnd('\') }
  }
  return $null
}

Paso "Buscando la instalacion"
docker info *> $null
if ($LASTEXITCODE -ne 0) { Fallo "Docker no esta abierto. Abre Docker Desktop, espera a que arranque y vuelve a lanzar." }
if (-not $Destino) {
  $validos = @()
  $ids = @(docker ps -a -q --filter 'label=com.docker.compose.service=postgres' 2>$null | Where-Object { $_ })
  foreach ($id in $ids) {
    $json = docker inspect $id --format '{{json .Config.Labels}}' 2>$null
    if (-not $json) { continue }
    $ruta = Ruta-Local (($json | ConvertFrom-Json).'com.docker.compose.project.working_dir')
    if ($ruta -and (Test-Path (Join-Path $ruta 'docker-compose.yml')) -and ($validos -notcontains $ruta)) { $validos += $ruta }
  }
  if ($validos.Count -eq 1) {
    $Destino = $validos[0]
  } elseif ($validos.Count -gt 1) {
    Write-Host "    Hay varias instalaciones:"
    for ($i = 0; $i -lt $validos.Count; $i++) { Write-Host ("      {0}) {1}" -f ($i + 1), $validos[$i]) }
    $n = Read-Host "    Cual conecto (numero)"
    if ($n -match '^\d+$' -and [int]$n -ge 1 -and [int]$n -le $validos.Count) { $Destino = $validos[[int]$n - 1] }
    if (-not $Destino) { Fallo "Opcion no valida." }
  } else {
    $Destino = Read-Host "    No encuentro la instalacion. Escribe la ruta completa de su carpeta (o Enter para cancelar)"
    if (-not $Destino) { Fallo "Cancelado: no se ha tocado nada." }
  }
}
if (-not (Test-Path (Join-Path $Destino 'docker-compose.yml'))) { Fallo "$Destino no parece una instalacion (falta docker-compose.yml)." }
$Destino = (Resolve-Path -LiteralPath $Destino).ProviderPath.TrimEnd('\')
if (-not (Test-Path (Join-Path $Destino '.env'))) { Fallo "No hay .env en $Destino." }
Ok "Instalacion: $Destino"

# ---------------------------------------------------------------- 4. conectar la carpeta
Paso "Conectando la carpeta a git"
function G { & $Git -C $Destino @args }
if (-not (Test-Path (Join-Path $Destino '.git'))) {
  G init -q
  if ($LASTEXITCODE -ne 0) { Fallo "git init fallo." }
}
# Sin conversion de saltos de linea: los scripts se ejecutan dentro de contenedores Linux.
G config core.autocrlf false
G config core.sshCommand $SshCmd
G remote remove origin *> $null
G remote add origin $Repo
Ok "Origen: $Repo (rama $Rama)"

Paso "Comprobando el acceso a GitHub"
$ref = (G ls-remote origin $Rama) | Out-String
if (($LASTEXITCODE -ne 0) -or ($ref -notmatch '[0-9a-f]{40}')) {
  Fallo "No hay acceso al repositorio con la clave (o la rama '$Rama' no existe). Avisa a quien te dio este paquete."
}
Ok "Acceso correcto"

# El script de actualizacion viene de la version publicada; se coge sin tocar nada mas de la carpeta.
G fetch -q --depth 1 origin $Rama
if ($LASTEXITCODE -ne 0) { Fallo "No se pudo descargar la version publicada." }
G checkout FETCH_HEAD -- entrega/actualizar_git.ps1
if ($LASTEXITCODE -ne 0) { Fallo "La version publicada no trae entrega/actualizar_git.ps1." }

Paso "Primera actualizacion por git"
& (Join-Path $Destino 'entrega\actualizar_git.ps1')
