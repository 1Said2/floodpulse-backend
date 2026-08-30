import sys
import os

# Asegurar que src esté en el path para importarlo
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.config import get_sector_config
from src.data_fetcher import fetch_rainfall, fetch_dem, fetch_land_cover, fetch_osm_network
from src.risk_model import compute_flood_risk

def run_day2():
    print("Iniciando pruebas del Día 2 (Cálculo del Índice de Riesgo)...\n")
    
    # 1. Configuración del sector
    sector_id = "ajavi"
    sector_cfg = get_sector_config(sector_id)
    print(f"[*] Sector '{sector_id}': {sector_cfg['name']}\n")

    # 2. Obtener datos crudos (Día 1)
    print("[*] Descargando datasets crudos (Lluvia, DEM, LandCover, OSM)...")
    
    # Precipitacion
    rain_data = fetch_rainfall(sector_cfg["lat"], sector_cfg["lon"], "2025-04-07", "2025-04-08")
    total_rain_mm = 0.0
    if "hourly" in rain_data and "precipitation" in rain_data["hourly"]:
        total_rain_mm = sum([r for r in rain_data["hourly"]["precipitation"] if r is not None])
    print(f"    Lluvia acumulada: {total_rain_mm:.2f} mm")
    
    # DEM
    dem_da = fetch_dem(sector_cfg["bbox"])
    
    # Land Cover
    landcover_da = fetch_land_cover(sector_cfg["bbox"])
    
    # Vías de agua
    fallback = sector_cfg.get("fallback_waterway")
    waterways_gdf = fetch_osm_network(sector_cfg["bbox"], fallback_coords=fallback)
    
    print("\n[*] Todos los datos listos. Iniciando motor matemático...")
    
    # 3. Calcular el riesgo (Día 2)
    max_risk, grid_geojson = compute_flood_risk(
        rainfall_mm=total_rain_mm,
        dem_da=dem_da,
        landcover_da=landcover_da,
        waterways_gdf=waterways_gdf,
        bbox=sector_cfg["bbox"]
    )
    
    print("\n================================================")
    print(f"  RIESGO GLOBAL DEL SECTOR '{sector_id.upper()}': {max_risk:.1f} / 100")
    print("================================================\n")
    
    print(f"[*] Detalles del mapa de calor generados (GeoJSON):")
    print(f"    Número de micro-sectores en la grilla: {len(grid_geojson['features'])}")
    
    # Mostrar una muestra del micro-sector con más riesgo
    features = grid_geojson['features']
    highest_risk_feature = max(features, key=lambda x: x['properties']['risk_score'])
    props = highest_risk_feature['properties']
    
    print("\n    Micro-sector con más riesgo:")
    print(f"      - Puntaje de Riesgo: {props['risk_score']}")
    print(f"      - Distancia a cauce: {props['dist_m']} m")
    print(f"      - TWI (Topographic): {props['twi_raw']}")
    print(f"      - Impermeabilidad  : {props['imperv_pct']} %")

if __name__ == "__main__":
    run_day2()
