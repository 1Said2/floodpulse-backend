# Prueba rapida del motor: Malacatos con 20 mm de lluvia forzada (no necesita Earth Engine).
# La primera llamada tarda ~30-90 s (descarga DEM/WorldCover y corre WhiteboxTools).
$url = "http://localhost:8000/risk?lat=-3.994537&lon=-79.205415&rainfall_mm=20"
Write-Host "GET $url" -ForegroundColor Cyan
$t = Measure-Command { $script:r = Invoke-RestMethod -Uri $url -TimeoutSec 300 }
Write-Host ("risk_score = {0}   celdas = {1}   ({2:n0} s)" -f $r.risk_score, $r.grid_geojson.features.Count, $t.TotalSeconds) -ForegroundColor Green
$r.components | Format-List
