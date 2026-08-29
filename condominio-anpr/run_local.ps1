# ─────────────────────────────────────────────────────────────
#  Arranque local en WINDOWS (PowerShell) del Sistema Condominio ANPR.
#  Equivalente a run_local.sh para Linux/macOS.
#
#  Qué hace:
#    1. Crea el entorno virtual .venv si no existe.
#    2. Instala/actualiza las dependencias.
#    3. Crea .env la primera vez, con SECRET_KEY aleatoria y la clave de admin.
#    4. Levanta el servidor en http://localhost:8000
#
#  Uso (en PowerShell, dentro de la carpeta condominio-anpr):
#    $env:ADMIN_PASSWORD='Eos5566!!!'; .\run_local.ps1     # 1ª vez: fija la clave
#    .\run_local.ps1                                        # siguientes veces
#    $env:PORT=9000; .\run_local.ps1                        # otro puerto
#
#  El .env NUNCA se sube al repo: la clave queda solo en esta PC.
# ─────────────────────────────────────────────────────────────
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$Port = if ($env:PORT) { $env:PORT } else { "8000" }

# Buscar Python.
$Py = $null
foreach ($c in @("python", "py", "python3")) {
  if (Get-Command $c -ErrorAction SilentlyContinue) { $Py = $c; break }
}
if (-not $Py) {
  Write-Error "No se encontró Python 3. Instálalo desde https://python.org (marca 'Add to PATH')."
  exit 1
}

# 1) Entorno virtual.
if (-not (Test-Path ".venv")) {
  Write-Host "> Creando entorno virtual (.venv)..."
  & $Py -m venv .venv
}
$VenvPy = ".\.venv\Scripts\python.exe"

# 2) Dependencias.
Write-Host "> Instalando dependencias..."
& $VenvPy -m pip install --quiet --upgrade pip
& $VenvPy -m pip install --quiet -r requirements.txt

# 3) Configuración inicial (.env solo local; nunca se sube al repo).
if (-not (Test-Path ".env")) {
  Copy-Item ".env.example" ".env"

  $NewSecret = & $VenvPy -c "import secrets; print(secrets.token_urlsafe(48))"

  $NewPass = $env:ADMIN_PASSWORD
  if (-not $NewPass) {
    $sec = Read-Host "> Define la contraseña del usuario admin" -AsSecureString
    $NewPass = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto(
      [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
  }

  # Reescribir línea por línea (evita problemas de escape con !, $, etc.).
  $out = foreach ($line in (Get-Content ".env")) {
    if ($line -match '^SECRET_KEY=') { "SECRET_KEY=$NewSecret" }
    elseif (($line -match '^ADMIN_PASSWORD=') -and $NewPass) { "ADMIN_PASSWORD=$NewPass" }
    else { $line }
  }
  Set-Content ".env" $out -Encoding UTF8
  Write-Host "> Se creó .env (SECRET_KEY aleatoria; contraseña de admin fijada). No se sube al repo."
}

# 4) Arrancar.
Write-Host "> Servidor en http://localhost:$Port  (Ctrl+C para detener)"
Write-Host "  Usuario: admin   Clave: la que definiste en ADMIN_PASSWORD"
& $VenvPy -m uvicorn app.main:app --host 0.0.0.0 --port $Port
