import os
import json
import numpy as np
import geopandas as gpd
from shapely.geometry import box
import whitebox
import rioxarray
import rasterio
from rasterio.mask import mask
from src.config import MODEL_CONFIG

def create_grid(bbox: list, resolution_m: int = 100, crs_metric: str = MODEL_CONFIG["crs_metric"]) -> gpd.GeoDataFrame:
    """
    Crea una grilla regular de micro-sectores sobre el bounding box dado.
    """
    minx, miny, maxx, maxy = bbox
    # Crear un GeoDataFrame con el BBox original en WGS84
    bbox_poly = box(minx, miny, maxx, maxy)
    gdf_bbox = gpd.GeoDataFrame({"geometry": [bbox_poly]}, crs="EPSG:4326")
    
    # Reproyectar a métrico para iterar en metros
    gdf_metric = gdf_bbox.to_crs(crs_metric)
    m_minx, m_miny, m_maxx, m_maxy = gdf_metric.total_bounds
    
    grid_cells = []
    # Generar celdas de resolution_m x resolution_m
    x = m_minx
    while x < m_maxx:
        y = m_miny
        while y < m_maxy:
            cell = box(x, y, x + resolution_m, y + resolution_m)
            grid_cells.append(cell)
            y += resolution_m
        x += resolution_m
        
    grid_gdf = gpd.GeoDataFrame({"geometry": grid_cells}, crs=crs_metric)
    # Volver a WGS84 para mantener compatibilidad con otras capas, o mantener en métrico.
    # Conservaremos la grilla original en WGS84, pero calcularemos el centroide en métrico.
    grid_gdf["centroid"] = grid_gdf.geometry.centroid
    grid_gdf = grid_gdf.to_crs("EPSG:4326")
    grid_gdf["centroid"] = grid_gdf["centroid"].to_crs("EPSG:4326") # Aunque centroid era GeoSeries, al proyectar grid_gdf, la columna centroid no se reproyecta automáticamente, mejor calculamos de nuevo en EPSG:4326 si es necesario o guardamos las coordenadas.
    
    # Limpiar
    grid_gdf = grid_gdf.drop(columns=["centroid"])
    return grid_gdf

def calculate_twi(dem_da, tmp_dir: str = "tmp") -> str:
    """
    Usa WhiteboxTools para calcular el TWI a partir de un DEM.
    Guarda archivos temporales y retorna la ruta del raster TWI resultante.
    """
    os.makedirs(tmp_dir, exist_ok=True)
    
    dem_path = os.path.join(tmp_dir, "dem.tif")
    dem_da.rio.to_raster(dem_path)
    
    wbt = whitebox.WhiteboxTools()
    wbt.set_working_dir(os.path.abspath(tmp_dir))
    wbt.verbose = False
    
    # 1. Rellenar depresiones (Breach Depressions) para un flujo continuo
    wbt.breach_depressions("dem.tif", "dem_breached.tif")
    # 2. Dirección de flujo (D8)
    wbt.d8_pointer("dem_breached.tif", "d8_pntr.tif")
    # 3. Acumulación de flujo (Área de captación específica)
    wbt.d8_flow_accumulation("dem_breached.tif", "flow_accum.tif", out_type="specific contributing area")
    # 4. Pendiente (Slope)
    wbt.slope("dem_breached.tif", "slope.tif")
    # 5. Topographic Wetness Index (TWI)
    wbt.wetness_index("flow_accum.tif", "slope.tif", "twi.tif")
    
    return os.path.join(tmp_dir, "twi.tif")

def get_twi_for_grid(grid_gdf: gpd.GeoDataFrame, twi_tif_path: str, crs_metric: str = MODEL_CONFIG["crs_metric"]) -> np.ndarray:
    """
    Extrae el TWI promedio para cada celda de la grilla usando zonal stats o muestreo de puntos.
    """
    # Proyectar a métrico para hallar el centroide real, luego volver a 4326 para muestrear el TWI
    metric_gdf = grid_gdf.to_crs(crs_metric)
    centroids_metric = metric_gdf.geometry.centroid
    centroids_wgs84 = gpd.GeoSeries(centroids_metric, crs=crs_metric).to_crs("EPSG:4326")
    
    coords = [(geom.x, geom.y) for geom in centroids_wgs84]
    
    twi_values = []
    with rasterio.open(twi_tif_path) as src:
        for val in src.sample(coords):
            v = val[0]
            # Manejar NoData o valores extremos
            if v < -9999 or np.isnan(v):
                twi_values.append(0.0)
            else:
                twi_values.append(float(v))
                
    return np.array(twi_values)

def calculate_distance_to_channel(grid_gdf: gpd.GeoDataFrame, waterways_gdf: gpd.GeoDataFrame, crs_metric: str = MODEL_CONFIG["crs_metric"]) -> np.ndarray:
    """
    Calcula la distancia mínima desde cada celda al cauce más cercano en metros.
    """
    if waterways_gdf.empty:
        return np.full(len(grid_gdf), MODEL_CONFIG["thresholds"]["safe_distance_m"])
        
    grid_metric = grid_gdf.to_crs(crs_metric)
    water_metric = waterways_gdf.to_crs(crs_metric)
    
    # Unir todas las vías de agua en una sola geometría para cálculo rápido
    water_union = water_metric.geometry.unary_union
    
    # Calcular distancia desde el centroide de cada celda
    distances = grid_metric.geometry.centroid.distance(water_union)
    return distances.values

def calculate_imperviousness(grid_gdf: gpd.GeoDataFrame, landcover_da) -> np.ndarray:
    """
    Calcula el % de área impermeable (Clase 50 en ESA WorldCover) por celda.
    """
    # Guardar raster temporalmente para usar rasterio.mask
    tmp_path = "tmp/lc.tif"
    os.makedirs("tmp", exist_ok=True)
    landcover_da.rio.to_raster(tmp_path)
    
    imperv_ratios = []
    with rasterio.open(tmp_path) as src:
        for geom in grid_gdf.geometry:
            try:
                # Recortar el raster con el polígono de la celda
                out_image, _ = mask(src, [geom], crop=True)
                data = out_image[0]
                # Ignorar nodata (ej. 0)
                valid_pixels = data[data > 0]
                if len(valid_pixels) == 0:
                    imperv_ratios.append(0.0)
                    continue
                
                # Clase 50 es "Built-up"
                built_pixels = (valid_pixels == 50).sum()
                ratio = built_pixels / len(valid_pixels)
                imperv_ratios.append(ratio)
            except ValueError:
                # Polígono no solapa con el raster
                imperv_ratios.append(0.0)
                
    return np.array(imperv_ratios)

def compute_flood_risk(rainfall_mm: float, dem_da, landcover_da, waterways_gdf, bbox: list) -> tuple:
    """
    Motor matemático que combina todo.
    Devuelve: (riesgo_global_maximo, grid_geojson_dict)
    """
    # 1. Crear grilla
    grid_gdf = create_grid(bbox, resolution_m=100)
    
    # 2. Calcular factores crudos
    twi_tif = calculate_twi(dem_da)
    twi_vals = get_twi_for_grid(grid_gdf, twi_tif)
    dist_vals = calculate_distance_to_channel(grid_gdf, waterways_gdf)
    imperv_vals = calculate_imperviousness(grid_gdf, landcover_da)
    
    # 3. Normalizar de 0 a 1 usando umbrales
    th = MODEL_CONFIG["thresholds"]
    w = MODEL_CONFIG["weights"]
    
    # Lluvia (0 a 1)
    rain_norm = min(rainfall_mm / th["max_rainfall_mm"], 1.0)
    
    # Distancia (inversa: más cerca = más riesgo)
    # Si dist == 0 -> riesgo 1. Si dist >= safe_distance -> riesgo 0.
    dist_norm = np.clip(1.0 - (dist_vals / th["safe_distance_m"]), 0.0, 1.0)
    
    # TWI (0 a 1)
    twi_norm = np.clip(twi_vals / th["max_twi"], 0.0, 1.0)
    
    # Impermeabilidad ya está de 0 a 1
    imperv_norm = imperv_vals
    
    # 4. Suma Ponderada (0 a 100)
    risk_scores = (
        rain_norm * w["rainfall"] +
        twi_norm * w["twi"] +
        dist_norm * w["distance"] +
        imperv_norm * w["impervious"]
    ) * 100.0
    
    # Agregar resultados a la grilla
    grid_gdf["risk_score"] = risk_scores.round(2)
    grid_gdf["twi_raw"] = twi_vals.round(2)
    grid_gdf["dist_m"] = dist_vals.round(1)
    grid_gdf["imperv_pct"] = (imperv_vals * 100).round(1)
    
    # Obtener el riesgo global máximo
    max_risk = float(grid_gdf["risk_score"].max())
    
    # Convertir a GeoJSON dictionary
    grid_geojson = json.loads(grid_gdf.to_json())
    
    return max_risk, grid_geojson
