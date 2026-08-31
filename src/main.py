import json
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import FastAPI, Query, HTTPException
from pydantic import BaseModel

from src.utils import get_utm_epsg
from src.data_fetcher import fetch_rainfall_forecast, fetch_rainfall_gpm, fetch_dem, fetch_land_cover, fetch_osm_network
from src.risk_model import compute_flood_risk

app = FastAPI(title="FloodPulse API", description="Motor de Riesgo de Inundación Hiperlocal")

class RiskResponse(BaseModel):
    lat: float
    lon: float
    risk_score: float
    timestamp: str
    components: dict
    grid_geojson: dict

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
    # 1. Calcular Bounding Box y CRS dinámico
    bbox = [lon - bbox_offset_deg, lat - bbox_offset_deg, lon + bbox_offset_deg, lat + bbox_offset_deg]
    crs_metric = get_utm_epsg(lat, lon)
    
    # 2. Descargar Rasters de PC (Satélite) para Elevación y cobertura
    try:
        dem_da = fetch_dem(bbox)
        landcover_da = fetch_land_cover(bbox)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching satellite data: {e}")
        
    # Calcular si es Costa o Sierra basado en elevación media
    mean_elevation = float(dem_da.mean().item())
    region = "sierra" if mean_elevation > 1000 else "costa"
    
    # 3. Obtener Precipitación (Arquitectura Híbrida calibrada)
    from src.config import MODEL_CONFIG
    factor = MODEL_CONFIG["calibration"].get(region, 1.0)
    
    final_rainfall = 0.0
    if rainfall_mm is not None:
        final_rainfall = rainfall_mm
    else:
        try:
            # Lluvia ya caída (observada por GPM IMERG en las últimas horas) calibrada
            start = event_start or (datetime.now(timezone.utc) - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
            end = event_end or datetime.now(timezone.utc).strftime("%Y-%m-%d")
            rain_gpm = fetch_rainfall_gpm(bbox, start, end) * factor
            
            # Lluvia histórica de Open-Meteo (Ensamble para cubrir ceguera a nubes cálidas)
            # Solo la consultamos si tenemos fechas históricas explícitas, para no retrasar llamadas en vivo,
            # o podemos consultarla siempre. El endpoint de archive-api tiene delay de unos días, así que 
            # si es en vivo (no event_start), el forecast lo cubrirá.
            rain_archive = 0.0
            if event_start and event_end:
                from src.data_fetcher import fetch_rainfall_archive
                rain_archive = fetch_rainfall_archive(lat, lon, start, end)
                
            rain_observed = max(rain_gpm, rain_archive)
            
            # Lluvia futura (pronóstico Open-Meteo próximas horas)
            # Solo la agregamos si estamos pidiendo datos "en vivo" (es decir, no pasamos fechas históricas explícitas)
            rain_forecast = 0.0
            if not event_start and not event_end:
                rain_forecast = fetch_rainfall_forecast(lat, lon, hours_ahead=24)
                
            final_rainfall = rain_observed + rain_forecast
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error fetching hybrid rainfall data: {e}")
        
    # 4. Manejar Fallback y descargar OSM
    fallback_list = None
    if fallback_waterway_coords:
        try:
            fallback_list = json.loads(fallback_waterway_coords)
            if not isinstance(fallback_list, list) or len(fallback_list) < 2:
                raise ValueError()
        except:
            raise HTTPException(status_code=400, detail="fallback_waterway_coords debe ser un JSON string de coordenadas válido: [[lon,lat], [lon,lat]]")
            
    waterways_gdf = fetch_osm_network(bbox, fallback_coords=fallback_list)
    
    # 5. Motor Matemático
    try:
        max_risk, grid_geojson = compute_flood_risk(
            rainfall_mm=final_rainfall,
            dem_da=dem_da,
            landcover_da=landcover_da,
            waterways_gdf=waterways_gdf,
            bbox=bbox,
            crs_metric=crs_metric
        )
    except Exception as e:
         raise HTTPException(status_code=500, detail=f"Error computing risk model: {e}")
    
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
            "imperviousness_pct": props.get("imperv_pct", 0)
        }
        
    return RiskResponse(
        lat=lat,
        lon=lon,
        risk_score=max_risk,
        timestamp=datetime.now(timezone.utc).isoformat(),
        components=components,
        grid_geojson=grid_geojson
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
    # Asumimos que riesgo > 60 significa predicción de inundación
    predicted_flood = risk_score > 60.0
    
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
        "details": result.components
    }
