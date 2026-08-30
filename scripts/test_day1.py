import sys
import os

# Asegurar que src esté en el path para importarlo
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.config import get_sector_config
from src.data_fetcher import fetch_rainfall, fetch_dem, fetch_land_cover, fetch_osm_network
import whitebox

def run_tests():
    print("Iniciando pruebas del Día 1...\n")
    
    # 1. Obtener config del sector por defecto
    try:
        sector_id = "ajavi"
        sector_cfg = get_sector_config(sector_id)
        print(f"[*] Sector '{sector_id}' configurado exitosamente.")
        print(f"    Nombre: {sector_cfg['name']}")
        print(f"    Centro: {sector_cfg['lat']}, {sector_cfg['lon']}")
        print(f"    BBox: {sector_cfg['bbox']}\n")
    except Exception as e:
        print(f"[ERROR] Falló la configuración del sector: {e}")
        return

    # 2. Descargar lluvia de Open-Meteo
    try:
        print("[*] Obteniendo datos de precipitación (Open-Meteo)...")
        rain_data = fetch_rainfall(sector_cfg["lat"], sector_cfg["lon"], "2025-04-07", "2025-04-08")
        if "hourly" in rain_data and "precipitation" in rain_data["hourly"]:
            total_rain = sum([r for r in rain_data["hourly"]["precipitation"] if r is not None])
            print(f"    [EXITO] Precipitación total encontrada en las fechas: {total_rain:.2f} mm\n")
        else:
            print("    [ADVERTENCIA] Respuesta de Open-Meteo inesperada.\n")
    except Exception as e:
        print(f"[ERROR] Falló la obtención de lluvia: {e}\n")

    # 3. Descargar DEM
    try:
        print("[*] Obteniendo modelo de elevación (Copernicus DEM)...")
        dem = fetch_dem(sector_cfg["bbox"])
        print(f"    [EXITO] DEM descargado exitosamente.")
        print(f"    Shape: {dem.shape}, Resolucion (aprox): {dem.rio.resolution()}\n")
    except Exception as e:
        print(f"[ERROR] Falló la obtención del DEM: {e}\n")

    # 4. Descargar Land Cover
    try:
        print("[*] Obteniendo cobertura de suelo (ESA WorldCover)...")
        land_cover = fetch_land_cover(sector_cfg["bbox"])
        print(f"    [EXITO] Land Cover descargado exitosamente.")
        print(f"    Shape: {land_cover.shape}, Resolucion (aprox): {land_cover.rio.resolution()}\n")
    except Exception as e:
        print(f"[ERROR] Falló la obtención del Land Cover: {e}\n")

    # 5. Descargar OSM Network
    try:
        print("[*] Obteniendo red de drenaje (OpenStreetMap)...")
        osm_gdf = fetch_osm_network(sector_cfg["bbox"])
        if osm_gdf.empty:
            print("    [ADVERTENCIA] Se devolvió un GeoDataFrame vacío (posible colector embovedado).")
        else:
            print(f"    [EXITO] Vías de agua encontradas: {len(osm_gdf)}")
        print("\n")
    except Exception as e:
        print(f"[ERROR] Falló la obtención de la red de OSM: {e}\n")
        
    # 6. Preparar Whitebox (Forzando la inicialización para descargar el binario)
    try:
        print("[*] Inicializando WhiteboxTools (puede descargar binario)...")
        wbt = whitebox.WhiteboxTools()
        print(f"    [EXITO] Directorio del ejecutable: {wbt.exe_path}")
    except Exception as e:
        print(f"[ERROR] Falló la inicialización de Whitebox: {e}")

    print("Pruebas del Día 1 finalizadas.")

if __name__ == "__main__":
    run_tests()
