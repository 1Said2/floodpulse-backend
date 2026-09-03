import json
import time
import traceback
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.utils import get_utm_epsg
from src import data_fetcher
from src.data_fetcher import (
    fetch_rainfall_forecast, fetch_rainfall_gpm, fetch_dem, fetch_land_cover,
    fetch_osm_network, OSMUnavailable, LAST_ERRORS,
)
from src.risk_model import compute_flood_risk

import sys
# Suprimir el molesto error "Error in sys.excepthook" provocado por WhiteboxTools al destruirse en Windows
original_excepthook = sys.excepthook
def silent_excepthook(exc_type, exc_value, exc_traceback):
    if exc_type.__name__ == "FileNotFoundError" and "WBT_log.txt" in str(exc_value):
        pass # Ignorar error de borrado de log de WhiteboxTools
    elif exc_type.__name__ == "PermissionError":
        pass # Ignorar errores de borrado temporal de WhiteboxTools en Windows
    else:
        original_excepthook(exc_type, exc_value, exc_traceback)
sys.excepthook = silent_excepthook

app = FastAPI(title="FloodPulse API", description="Motor de Riesgo de Inundación Hiperlocal")


# ---------------------------------------------------------------- errores
# Cualquier excepción no controlada se convierte en JSON *dentro* del middleware
# de CORS. Si se dejara escapar, Starlette la atraparía en su capa más externa
# (fuera de CORS) y el navegador solo vería "Failed to fetch".
@app.middleware("http")
async def errores_como_json(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={
                "detail": f"Internal Error: {type(exc).__name__}: {exc}",
                "tipo": type(exc).__name__,
                "traceback": traceback.format_exc().splitlines()[-6:],
            },
        )


# CORS: permite que el dashboard (Astro en localhost:4321 / Vercel) consuma /risk
# directamente desde el navegador. Debe añadirse DESPUÉS del middleware de errores
# para que lo envuelva (el último add_middleware es el más externo).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------- modelos
class RiskResponse(BaseModel):
    lat: float
    lon: float
    risk_score: float
    timestamp: str
    components: dict
    grid_geojson: dict
    alert_threshold: float
    # Avisos no fatales (GEE sin credenciales, Overpass caído y se usó fallback, etc.)
    # El dashboard los muestra como notificaciones.
    warnings: List[str] = []
    # Tiempos por etapa en segundos, para saber qué es lo lento.
    timing_s: dict = {}


# ---------------------------------------------------------------- estado
@app.get("/health", tags=["estado"])
def health():
    """Sin cálculo: sirve para que el dashboard y el monitor comprueben que el motor está arriba."""
    return {"ok": True, "servicio": "riesgo", "hora": datetime.now(timezone.utc).isoformat()}


@app.get("/diagnostico", tags=["estado"])
def diagnostico():
    """
    Prueba cada dependencia externa con timeouts cortos y devuelve qué funciona.
    Úsalo antes de la demo o cuando /risk devuelva errores.
    """
    import requests

    resultados = {}

    def probar(nombre, fn):
        t0 = time.time()
        try:
            detalle = fn()
            resultados[nombre] = {"ok": True, "detalle": detalle, "segundos": round(time.time() - t0, 1)}
        except Exception as e:  # noqa: BLE001
            resultados[nombre] = {"ok": False, "detalle": f"{type(e).__name__}: {str(e)[:200]}",
                                  "segundos": round(time.time() - t0, 1)}

    def _pc():
        r = requests.get("https://planetarycomputer.microsoft.com/api/stac/v1", timeout=8)
        r.raise_for_status()
        return "Planetary Computer (DEM + WorldCover) responde"

    def _open_meteo():
        r = requests.get("https://api.open-meteo.com/v1/forecast",
                         params={"latitude": -3.99, "longitude": -79.2, "hourly": "precipitation", "forecast_days": 1},
                         timeout=8)
        r.raise_for_status()
        return "Open-Meteo (pronóstico) responde"

    def _overpass():
        vivos, muertos = [], []
        for url in data_fetcher.OVERPASS_ENDPOINTS:
            host = url.split("/")[2]
            try:
                r = requests.get(url.replace("/interpreter", "/status"), timeout=8)
                (vivos if r.status_code == 200 else muertos).append(f"{host} ({r.status_code})")
            except Exception as e:  # noqa: BLE001
                muertos.append(f"{host} ({type(e).__name__})")
        if not vivos:
            raise RuntimeError("ningún servidor Overpass responde: " + ", ".join(muertos))
        return f"vivos: {', '.join(vivos)}" + (f" | caídos: {', '.join(muertos)}" if muertos else "")

    def _gee():
        import os
        import ee
        project_id = os.environ.get("EE_PROJECT") or "gen-lang-client-0564385440"
        ee.Initialize(project=project_id)
        return f"Earth Engine autenticado (proyecto {project_id}); lluvia observada IMERG disponible"

    def _whitebox():
        import whitebox
        w = whitebox.WhiteboxTools()
        w.verbose = False
        return "WhiteboxTools " + w.version().splitlines()[0]

    probar("planetary_computer", _pc)
    probar("open_meteo", _open_meteo)
    probar("overpass_osm", _overpass)
    probar("earth_engine", _gee)
    probar("whitebox", _whitebox)

    ok_minimo = resultados["planetary_computer"]["ok"] and resultados["whitebox"]["ok"]
    return {
        "ok": ok_minimo,
        "resumen": ("Listo para /risk con rainfall_mm" if ok_minimo else
                    "Falta algo esencial (DEM/WorldCover o WhiteboxTools)"),
        "lluvia_real_disponible": resultados["earth_engine"]["ok"] and resultados["open_meteo"]["ok"],
        "checks": resultados,
        "ultimos_errores": dict(LAST_ERRORS),
    }


# ---------------------------------------------------------------- riesgo
@app.get("/risk", response_model=RiskResponse)
def evaluate_risk(
    lat: float = Query(..., description="Latitud del punto central"),
    lon: float = Query(..., description="Longitud del punto central"),
    bbox_offset_deg: float = Query(0.005, description="Tamaño del offset para el bounding box (0.005 = ~500m)"),
    rainfall_mm: Optional[float] = Query(None, description="Lluvia explícita en mm. Si se provee, no llama a Open-Meteo ni GPM."),
    event_start: Optional[str] = Query(None, description="Fecha inicio ISO8601 (ej. 2025-04-07)."),
    event_end: Optional[str] = Query(None, description="Fecha fin ISO8601 (ej. 2025-04-08)."),
    fallback_waterway_coords: Optional[str] = Query(None, description="JSON string con lista de coords [[lon,lat],...]")
):
    if bbox_offset_deg < 0.002:
        raise HTTPException(
            status_code=400,
            detail=f"bbox_offset_deg demasiado pequeño ({bbox_offset_deg}): por debajo de 0.002 la detección de cauces OSM se degrada silenciosamente y el riesgo puede subestimarse. Usa 0.005 (default) o mayor."
        )

    warnings: List[str] = []
    timing: dict = {}
    t_total = time.time()

    # 1. Calcular Bounding Box y CRS dinámico
    bbox = [lon - bbox_offset_deg, lat - bbox_offset_deg, lon + bbox_offset_deg, lat + bbox_offset_deg]
    bbox_4x = [lon - bbox_offset_deg*4, lat - bbox_offset_deg*4, lon + bbox_offset_deg*4, lat + bbox_offset_deg*4]
    crs_metric = get_utm_epsg(lat, lon)

    # 2. Descargar Rasters de PC (Satélite) para Elevación y cobertura
    t0 = time.time()
    try:
        dem_da = fetch_dem(bbox_4x)
        landcover_da = fetch_land_cover(bbox)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Error descargando datos satelitales (Planetary Computer: DEM/WorldCover). "
                   f"¿Hay internet / firewall? -> {type(e).__name__}: {e}"
        )
    timing["satelite_s"] = round(time.time() - t0, 1)

    # Calcular si es Costa o Sierra basado en elevación media
    mean_elevation = float(dem_da.mean().item())
    region = "sierra" if mean_elevation > 1000 else "costa"

    # 3. Obtener Precipitación (Arquitectura Híbrida calibrada)
    from src.config import MODEL_CONFIG
    
    # Factores separados por fuente. Por defecto 1.0 si no se ha calibrado
    factor_imerg = MODEL_CONFIG["calibration"].get("imerg", {}).get(region, 1.0)
    factor_chirps = MODEL_CONFIG["calibration"].get("chirps", {}).get(region, 1.0)

    t0 = time.time()
    final_rainfall = 0.0
    rain_detail = {}
    if rainfall_mm is not None:
        final_rainfall = rainfall_mm
        rain_detail = {"modo": "manual", "rainfall_mm": rainfall_mm}
    else:
        try:
            start = event_start or (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
            end = event_end or datetime.now(timezone.utc).strftime("%Y-%m-%d")

            # Lluvia ya caída (observada por GPM IMERG en las últimas horas) calibrada
            rain_gpm = fetch_rainfall_gpm(bbox, start, end) * factor_imerg
            if "gee" in LAST_ERRORS:
                warnings.append("Lluvia observada (IMERG) = 0: " + LAST_ERRORS["gee"])

            # Lluvia histórica de Open-Meteo y CHIRPS
            rain_archive = 0.0
            rain_chirps = 0.0
            if event_start and event_end:
                from src.data_fetcher import fetch_rainfall_archive, fetch_rainfall_chirps
                rain_archive = fetch_rainfall_archive(lat, lon, start, end)
                if "open-meteo-archive" in LAST_ERRORS:
                    warnings.append("Open-Meteo histórico falló: " + LAST_ERRORS["open-meteo-archive"])
                    
                rain_chirps = fetch_rainfall_chirps(bbox, start, end) * factor_chirps
                if "chirps" in LAST_ERRORS:
                    warnings.append("CHIRPS histórico falló: " + LAST_ERRORS["chirps"])

            rain_observed = max(rain_gpm, rain_archive, rain_chirps)

            # Lluvia futura (pronóstico Open-Meteo próximas horas) solo en modo "en vivo"
            rain_forecast = 0.0
            if not event_start and not event_end:
                rain_forecast = fetch_rainfall_forecast(lat, lon, hours_ahead=24)
                if "open-meteo-forecast" in LAST_ERRORS:
                    warnings.append("Open-Meteo pronóstico falló: " + LAST_ERRORS["open-meteo-forecast"])

            final_rainfall = rain_observed + rain_forecast
            rain_detail = {
                "modo": "real",
                "region": region,
                "factor_imerg": factor_imerg,
                "factor_chirps": factor_chirps,
                "gpm_imerg_mm": round(rain_gpm, 2),
                "chirps_mm": round(rain_chirps, 2),
                "open_meteo_archivo_mm": round(rain_archive, 2),
                "open_meteo_pronostico_24h_mm": round(rain_forecast, 2),
                "ventana": f"{start} a {end}",
            }
            if final_rainfall == 0.0:
                warnings.append("Todas las fuentes de lluvia devolvieron 0 mm. Como el modelo es multiplicativo, el riesgo calculado es 0.")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Error obteniendo lluvia híbrida: {type(e).__name__}: {e}")
    timing["lluvia_s"] = round(time.time() - t0, 1)

    # 4. Manejar Fallback y descargar OSM
    fallback_list = None
    if fallback_waterway_coords:
        try:
            fallback_list = json.loads(fallback_waterway_coords)
            if not isinstance(fallback_list, list) or len(fallback_list) < 2:
                raise ValueError()
        except Exception:
            raise HTTPException(status_code=400, detail="fallback_waterway_coords debe ser un JSON string de coordenadas válido: [[lon,lat], [lon,lat]]")

    t0 = time.time()
    try:
        # Ya no le pasamos el fallback_list aquí para forzar el flujo OSM -> DEM -> Fallback
        waterways_gdf = fetch_osm_network(bbox)
    except OSMUnavailable as e:
        # En vez de arrojar 503, creamos un GeoDataFrame vacío para obligar al motor a extraer el DEM.
        waterways_gdf = gpd.GeoDataFrame()
        if "osm" in LAST_ERRORS:
            warnings.append(LAST_ERRORS["osm"])
    
    # Este source inicial es tentativo, la decisión final ocurre dentro de compute_flood_risk
    waterway_source = "osm" if not waterways_gdf.empty else "dem_derived"
    
    timing["osm_s"] = round(time.time() - t0, 1)

    # 5. Motor Matemático
    t0 = time.time()
    try:
        max_risk, point_risk, grid_geojson, final_waterway_source = compute_flood_risk(
            rainfall_mm=final_rainfall,
            dem_da=dem_da,
            landcover_da=landcover_da,
            waterways_gdf=waterways_gdf,
            bbox=bbox,
            crs_metric=crs_metric,
            fallback_coords=fallback_list,
            lat=lat,
            lon=lon
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en el motor matemático (WhiteboxTools/TWI): {type(e).__name__}: {e}")
    timing["modelo_s"] = round(time.time() - t0, 1)
    timing["total_s"] = round(time.time() - t_total, 1)

    # Extraer la celda de máximo riesgo para llenar 'components'
    features = grid_geojson.get("features", [])
    components = {}
    if features:
        highest = max(features, key=lambda x: x['properties']['risk_score'])
        props = highest['properties']
        components = {
            "rainfall_mm": final_rainfall,
            "twi_max": props.get("twi_raw", 0),
            "distance_to_channel_m": props.get("dist_m", 0),
            "imperviousness_pct": props.get("imperv_pct", 0),
            "region": region,
            "waterway_source": final_waterway_source,
            "rainfall_detail": rain_detail,
            "max_risk_in_bbox": max_risk,
        }

    return RiskResponse(
        lat=lat,
        lon=lon,
        risk_score=point_risk,
        timestamp=datetime.now(timezone.utc).isoformat(),
        components=components,
        grid_geojson=grid_geojson,
        alert_threshold=MODEL_CONFIG["predicted_flood"]["risk_threshold"],
        warnings=warnings,
        timing_s=timing,
    )


@app.get("/validation")
def validate_historical_event(
    lat: float,
    lon: float,
    event_window_start: str,
    event_window_end: str,
    ground_truth_flooded: bool,
    bbox_offset_deg: float = 0.005,
    fallback_waterway_coords: Optional[str] = None
):
    """
    Endpoint para validación de backtesting.
    Llama a la misma lógica de riesgo para una ventana histórica y la compara con la verdad de campo.
    """
    # Reutilizar el flujo de /risk internamente
    try:
        result = evaluate_risk(
            lat=lat,
            lon=lon,
            bbox_offset_deg=bbox_offset_deg,
            rainfall_mm=None, # Forzamos a que descargue lluvia usando la ventana
            event_start=event_window_start,
            event_end=event_window_end,
            fallback_waterway_coords=fallback_waterway_coords
        )
    except HTTPException as e:
        raise e

    risk_score = result.risk_score

    # Lógica de validación muy sencilla
    alert_threshold = MODEL_CONFIG["predicted_flood"]["risk_threshold"]
    predicted_flood = risk_score > alert_threshold

    # Determinamos la métrica
    status = "True Negative"
    if predicted_flood and ground_truth_flooded:
        status = "True Positive (Hit)"
    elif predicted_flood and not ground_truth_flooded:
        status = "False Positive (False Alarm)"
    elif not predicted_flood and ground_truth_flooded:
        status = "False Negative (Miss)"

    return {
        "event_window": f"{event_window_start} to {event_window_end}",
        "location": {"lat": lat, "lon": lon},
        "ground_truth_flooded": ground_truth_flooded,
        "predicted_risk_score": risk_score,
        "predicted_flood": predicted_flood,
        "validation_status": status,
        "details": result.components,
        "warnings": result.warnings,
    }
