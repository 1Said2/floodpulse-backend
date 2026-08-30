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
        # El evento de backtesting es la noche del 7 y madrugada del 8 de abril de 2025.
        # Pedimos ambos días para capturar el acumulado completo. Open-Meteo usa la zona horaria America/Guayaquil 
        # (UTC-5) para alinear correctamente los días.
        rain_data = fetch_rainfall(sector_cfg["lat"], sector_cfg["lon"], "2025-04-07", "2025-04-08")
        if "hourly" in rain_data and "precipitation" in rain_data["hourly"]:
            total_rain = sum([r for r in rain_data["hourly"]["precipitation"] if r is not None])
            print(f"    [EXITO] Precipitación total encontrada en las fechas: {total_rain:.2f} mm")
            
            # EXPLICACIÓN DE LA DISCREPANCIA (25.60mm vs 40.8mm)
            # INAMHI midió 40.8mm con un pluviómetro en una estación puntual. 
            # Open-Meteo usa modelos de reanálisis (ej. ERA5) que calculan un promedio sobre 
            # celdas de una grilla amplia (~10-30km). Este promedio espacial típicamente "suaviza" 
            # las tormentas convectivas locales intensas, resultando en una subestimación del pico puntual.
            print("    [NOTA] INAMHI reportó 40.8mm para este evento. La diferencia es esperada, ya que Open-Meteo")
            print("           promedia lluvia sobre una grilla espacial amplia (aprox 10-30km), suavizando")
            print("           las tormentas locales, a diferencia del pluviómetro puntual de INAMHI.\n")
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
        fallback = sector_cfg.get("fallback_waterway")
        osm_gdf = fetch_osm_network(sector_cfg["bbox"], fallback_coords=fallback)
        if osm_gdf.empty:
            print("    [ADVERTENCIA] Se devolvió un GeoDataFrame vacío y no hubo fallback válido.")
        else:
            print(f"    [EXITO] Vías de agua obtenidas: {len(osm_gdf)} (puede incluir fallback si OSM falló)")
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
