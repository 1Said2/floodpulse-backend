import os
import json
import numpy as np
import geopandas as gpd
from shapely.geometry import box
import whitebox
import rioxarray
import rasterio
from rasterio.mask import mask
import tempfile
import threading
from src.config import MODEL_CONFIG

wbt_lock = threading.Lock()

def create_grid(bbox: list, crs_metric: str, resolution_m: int = 100) -> gpd.GeoDataFrame:
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

def calculate_twi(dem_da, crs_metric: str, tmp_dir: str = "tmp", extract_streams: bool = False) -> tuple:
    """
    Usa WhiteboxTools para calcular el TWI a partir de un DEM.
    Guarda archivos temporales y retorna la ruta del raster TWI resultante y opcionalmente la distancia a cauces.
    """
    os.makedirs(tmp_dir, exist_ok=True)
    
    # Reproyectar a métrico antes de WBT para cálculos topográficos físicos reales
    dem_da = dem_da.rio.reproject(crs_metric, resolution=30)
    
    dem_path = os.path.join(tmp_dir, "dem.tif")
    dem_da.rio.to_raster(dem_path)
    
    wbt = whitebox.WhiteboxTools()
    wbt.set_working_dir(os.path.abspath(tmp_dir))
    wbt.verbose = False
    
    with wbt_lock:
        # 1. Rellenar depresiones (Breach Depressions) para un flujo continuo
        wbt.breach_depressions("dem.tif", "dem_breached.tif")
        # 2. Dirección de flujo (D8)
        wbt.d8_pointer("dem_breached.tif", "d8_pntr.tif")
        # 3. Acumulación de flujo (Área de captación específica para TWI)
        wbt.d8_flow_accumulation("dem_breached.tif", "flow_accum_sca.tif", out_type="specific contributing area")
        
        # 3.5 Extracción de cauces topográficos (Fallback OSM)
        if extract_streams:
            wbt.d8_flow_accumulation("dem_breached.tif", "flow_accum_cells.tif", out_type="cells")
            wbt.extract_streams("flow_accum_cells.tif", "streams.tif", threshold=50.0, zero_background=True)
            wbt.euclidean_distance("streams.tif", "dist_to_stream.tif")
            
        # 4. Pendiente (Slope)
        wbt.slope("dem_breached.tif", "slope.tif")
        # 5. Topographic Wetness Index (TWI)
        wbt.wetness_index("flow_accum_sca.tif", "slope.tif", "twi.tif")
    
    dist_path = os.path.join(tmp_dir, "dist_to_stream.tif") if extract_streams else None
    return os.path.join(tmp_dir, "twi.tif"), dist_path

def get_twi_for_grid(grid_gdf: gpd.GeoDataFrame, twi_tif_path: str, crs_metric: str) -> np.ndarray:
    """
    Extrae el TWI promedio para cada celda de la grilla usando zonal stats o muestreo de puntos.
    """
    # Proyectar a métrico para hallar el centroide real y samplear sobre el raster TWI que ahora está en métrico
    metric_gdf = grid_gdf.to_crs(crs_metric)
    centroids_metric = metric_gdf.geometry.centroid
    
    coords = [(geom.x, geom.y) for geom in centroids_metric]
    
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

def calculate_distance_to_channel(grid_gdf: gpd.GeoDataFrame, waterways_gdf: gpd.GeoDataFrame, crs_metric: str) -> np.ndarray:
    """
    Calcula la distancia mínima desde cada celda al cauce más cercano en metros.
    """
    if waterways_gdf.empty:
        # Esto en la jerarquía OSM -> DEM -> Fallback casi nunca se ejecuta directo de OSM vacío
        return np.full(len(grid_gdf), 9999.0)
        
    grid_metric = grid_gdf.to_crs(crs_metric)
    water_metric = waterways_gdf.to_crs(crs_metric)
    
    # Unir todas las vías de agua en una sola geometría para cálculo rápido
    water_union = water_metric.geometry.union_all()
    
    # Calcular distancia desde el centroide de cada celda
    distances = grid_metric.geometry.centroid.distance(water_union)
    return distances.values

def get_distance_from_raster(grid_gdf: gpd.GeoDataFrame, dist_tif_path: str, crs_metric: str) -> np.ndarray:
    """
    Extrae la distancia euclidiana al cauce topográfico derivado del DEM.
    """
    metric_gdf = grid_gdf.to_crs(crs_metric)
    centroids_metric = metric_gdf.geometry.centroid
    
    coords = [(geom.x, geom.y) for geom in centroids_metric]
    
    dist_values = []
    with rasterio.open(dist_tif_path) as src:
        for val in src.sample(coords):
            v = val[0]
            if v < 0 or np.isnan(v):
                dist_values.append(9999.0) # Se usa un valor muy alto para que clip lo reduzca a safe_distance luego
            else:
                dist_values.append(float(v))
                
    return np.array(dist_values)

def calculate_imperviousness(grid_gdf: gpd.GeoDataFrame, landcover_da, tmp_dir: str) -> np.ndarray:
    """
    Calcula el % de área impermeable (Clase 50 en ESA WorldCover) por celda.
    """
    # Guardar raster temporalmente para usar rasterio.mask
    tmp_path = os.path.join(tmp_dir, "lc.tif")
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

from shapely.geometry import LineString

def compute_flood_risk(rainfall_mm: float, dem_da, landcover_da, waterways_gdf, bbox: list, crs_metric: str, fallback_coords: list = None, lat: float = None, lon: float = None) -> tuple:
    """
    Motor matemático que combina todo.
    Devuelve: (max_risk, point_risk, grid_geojson_dict, waterway_source)
    """
    # 1. Crear grilla
    grid_gdf = create_grid(bbox, crs_metric=crs_metric, resolution_m=100)
    
    # 1.5 Variables dinámicas y de escala
    bbox_offset_deg = (bbox[2] - bbox[0]) / 2.0
    # A5: safe_distance_m escala con el bbox (~ la mitad del ancho). Ej. offset 0.005 -> 250m aprox
    safe_distance_m = bbox_offset_deg * 111320 * 0.45
    
    extract_streams = waterways_gdf.empty
    waterway_source = "osm" if not extract_streams else "dem_derived"
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # 2. Calcular factores crudos
        twi_tif, dist_tif = calculate_twi(dem_da, crs_metric=crs_metric, tmp_dir=tmpdir, extract_streams=extract_streams)
        twi_vals = get_twi_for_grid(grid_gdf, twi_tif, crs_metric=crs_metric)
        
        if extract_streams:
            has_streams = False
            streams_path = os.path.join(tmpdir, "streams.tif")
            if os.path.exists(streams_path):
                with rasterio.open(streams_path) as src:
                    streams_data = src.read(1)
                    # A3: Comprobación topográfica real en vez del valor centinela
                    has_streams = (streams_data > 0).any()
            
            if has_streams:
                dist_vals = get_distance_from_raster(grid_gdf, dist_tif, crs_metric=crs_metric)
                # Aplicamos límite manual a los píxeles anómalos o muy lejanos
                dist_vals = np.clip(dist_vals, 0, safe_distance_m)
            else:
                if fallback_coords:
                    waterway_source = "fallback"
                    print("INFO: DEM sin cauces topográficos (terreno plano/saturado). Usando fallback manual.")
                    fallback_gdf = gpd.GeoDataFrame({"waterway": ["fallback"]}, geometry=[LineString(fallback_coords)], crs="EPSG:4326")
                    dist_vals = calculate_distance_to_channel(grid_gdf, fallback_gdf, crs_metric=crs_metric)
                else:
                    dist_vals = np.full(len(grid_gdf), safe_distance_m)
        else:
            dist_vals = calculate_distance_to_channel(grid_gdf, waterways_gdf, crs_metric=crs_metric)
            
        imperv_vals = calculate_imperviousness(grid_gdf, landcover_da, tmp_dir=tmpdir)
    
    # 3. Normalizar de 0 a 1 usando umbrales
    th = MODEL_CONFIG["thresholds"]
    w = MODEL_CONFIG["weights"]
    
    # A4: Normalización Logarítmica para la lluvia (evita saturación prematura y separa 51 vs 289 vs 579)
    # f(r) = ln(1 + r/r0) / ln(1 + r_max/r0)
    r_max = th.get("max_rainfall_mm", 150.0)
    r0 = 25.0
    rain_capped = min(rainfall_mm, r_max)
    rain_norm = np.log(1.0 + rain_capped / r0) / np.log(1.0 + r_max / r0)
    
    # Distancia (inversa: más cerca = más riesgo)
    dist_norm = np.clip(1.0 - (dist_vals / safe_distance_m), 0.0, 1.0)
    
    # TWI (0 a 1)
    # TWI ahora es absoluto y físicamente realista. Se normaliza contra el max_twi fijo de config.py
    dynamic_max_twi = th["max_twi"]
    
    twi_norm = np.clip(twi_vals / dynamic_max_twi, 0.0, 1.0)
    
    # Impermeabilidad ya está de 0 a 1
    imperv_norm = imperv_vals
    
    # 4. Cálculo del Riesgo
    formula_cfg = MODEL_CONFIG.get("formula", {})
    if formula_cfg.get("use_multiplicative", False):
        # Riesgo = Amenaza × Susceptibilidad
        sw = MODEL_CONFIG.get("susceptibility_weights", {"twi": 0.33, "distance": 0.42, "impervious": 0.25})
        susceptibilidad = (
            twi_norm * sw["twi"] +
            dist_norm * sw["distance"] +
            imperv_norm * sw["impervious"]
        )
        risk_scores = rain_norm * susceptibilidad * 100.0
    else:
        # Suma Ponderada Original (0 a 100)
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
    
    from shapely.geometry import Point
    point_risk = max_risk
    if lat is not None and lon is not None:
        p = Point(lon, lat)
        contains_idx = grid_gdf.geometry.contains(p)
        if contains_idx.any():
            point_risk = float(grid_gdf.loc[contains_idx, "risk_score"].iloc[0])
        else:
            distances = grid_gdf.geometry.centroid.distance(p)
            point_risk = float(grid_gdf.loc[distances.idxmin(), "risk_score"])
    
    # Convertir a GeoJSON dictionary
    grid_geojson = json.loads(grid_gdf.to_json())
    
    return max_risk, point_risk, grid_geojson, waterway_source
