# Arranca el motor de riesgo FloodPulse en http://localhost:8000
# Ejecutar:  powershell -ExecutionPolicy Bypass -File .\start.ps1
Set-Location $PSScriptRoot
if (-not (Test-Path ".\venv\Scripts\python.exe")) { Write-Host "Primero ejecuta .\setup.ps1" -ForegroundColor Red; exit 1 }
# EE_PROJECT solo hace falta si NO pasas rainfall_mm (modo lluvia real via Google Earth Engine)
# $env:EE_PROJECT = "tu-proyecto-gcp"
Write-Host "Motor de riesgo -> http://localhost:8000/docs  (Ctrl+C para detener)" -ForegroundColor Green
& .\venv\Scripts\python.exe -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
