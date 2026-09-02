# FloodPulse Backend - instalacion en Windows
# Ejecutar desde esta carpeta:  powershell -ExecutionPolicy Bypass -File .\setup.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "== FloodPulse Backend: instalacion ==" -ForegroundColor Cyan
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { Write-Host "No se encontro 'python' en el PATH. Instala Python 3.11 o 3.12 desde python.org (marca 'Add to PATH')." -ForegroundColor Red; exit 1 }
python --version

if (-not (Test-Path ".\venv")) {
    Write-Host "Creando entorno virtual venv..." -ForegroundColor Yellow
    python -m venv venv
}
& .\venv\Scripts\python.exe -m pip install --upgrade pip
Write-Host "Instalando dependencias (geopandas, rasterio, osmnx, whitebox...). Puede tardar varios minutos." -ForegroundColor Yellow
& .\venv\Scripts\python.exe -m pip install -r requirements.txt

Write-Host "Descargando el binario de WhiteboxTools (solo la primera vez)..." -ForegroundColor Yellow
& .\venv\Scripts\python.exe -c "import whitebox; w = whitebox.WhiteboxTools(); print('WhiteboxTools OK:', w.version().splitlines()[0])"

Write-Host ""
Write-Host "Listo. Para arrancar el motor de riesgo:  .\start.ps1   (Swagger en http://localhost:8000/docs)" -ForegroundColor Green
