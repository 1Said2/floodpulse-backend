import requests
import osmnx as ox
from pystac_client import Client
import planetary_computer as pc
import rioxarray
import xarray as xr
import geopandas as gpd

def fetch_rainfall_forecast(lat: float, lon: float, hours_ahead: int = 24) -> float:
    """
    Obtiene el PRONÓSTICO de precipitación de Open-Meteo.
    Predice la lluvia futura, otorgando margen de anticipación al modelo.
    Devuelve la lluvia acumulada esperada en las próximas `hours_ahead` horas.
    """
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "precipitation",
        "forecast_days": 2, # Traemos 2 días para tener suficiente margen horario
        "timezone": "UTC"
    }
    
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    data = resp.json()
    
    # Sumamos solo las próximas horas desde ahora
    import datetime
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    
    times = data["hourly"]["time"]
    precips = data["hourly"]["precipitation"]
    
    total_forecast = 0.0
    hours_counted = 0
    for t_str, p in zip(times, precips):
        if p is None:
            continue
        t_dt = datetime.datetime.fromisoformat(t_str + "+00:00")
        if t_dt > now_utc:
            total_forecast += p
            hours_counted += 1
            if hours_counted >= hours_ahead:
                break
                
    return total_forecast
def fetch_rainfall_archive(lat: float, lon: float, start_date: str, end_date: str) -> float:
    """
    Obtiene precipitación histórica desde el modelo de reanálisis de Open-Meteo.
    Se utiliza en ensamble con GPM IMERG para cubrir las fallas de detección de nubes cálidas.
    """
    url = "https://archive-api.open-meteo.com/v1/archive"
    # start_date y end_date deben estar en formato YYYY-MM-DD
    # Extraer solo la fecha si viene con hora (ej. 2023-06-03T00:00:00Z -> 2023-06-03)
    start = start_date[:10]
    end = end_date[:10]
    
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start,
        "end_date": end,
        "hourly": "precipitation",
        "timezone": "UTC"
    }
    
    resp = requests.get(url, params=params)
    if resp.status_code != 200:
        print(f"Error Open-Meteo archive: {resp.text}")
        return 0.0
        
    data = resp.json()
    precips = data.get("hourly", {}).get("precipitation", [])
    
    # Sumar toda la precipitación de la ventana
    total = sum(p for p in precips if p is not None)
    return total

def fetch_rainfall_gpm(bbox: list, start_date: str, end_date: str) -> float:
    """
    Obtiene precipitación acumulada satelital OBSERVADA de NASA GPM IMERG.
    Utiliza Google Earth Engine para backtesting y lluvia pasada reciente.
    """
    import ee
    from datetime import datetime, timezone
    
    try:
        import os
        # GEE requiere explícitamente el project_id en nuevas versiones
        # Puedes establecerlo como variable de entorno EE_PROJECT o poner el ID directamente abajo.
        project_id = os.environ.get("EE_PROJECT")
        if project_id:
            ee.Initialize(project=project_id)
        else:
            # Fallback en caso de no usar variables de entorno
            ee.Initialize(project='gen-lang-client-0564385440')
    except Exception as e:
        raise RuntimeError("Error inicializando Google Earth Engine. Asegúrate de configurar el project_id válido.") from e
        
    start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
        
    end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=timezone.utc)
        
    from datetime import timedelta
    # filterDate in GEE is exclusive for the end date, so we add 1 day to include it
    end_date_gee = (end_dt + timedelta(days=1)).strftime("%Y-%m-%d")
        
    now = datetime.now(timezone.utc)
    diff_days = (now - start_dt).days
    
    # Para backtesting (evento > 3.5 meses), usamos Final Run V07.
    # Para consultas recientes, Early/Late Run (GEE suele mapear V06 o colecciones en RT).
    collection_id = 'NASA/GPM_L3/IMERG_V07' if diff_days > 110 else 'NASA/GPM_L3/IMERG_V06'
    
    geom = ee.Geometry.Rectangle(bbox)
    
    collection = ee.ImageCollection(collection_id) \
        .filterDate(start_date, end_date_gee) \
        .select('precipitation')
        
    # Verificar si la colección está vacía (posiblemente porque V07 aún no existe para esta fecha)
    if collection.size().getInfo() == 0:
        # Fallback a V06 o Early Run (V06 usaba precipitationCal, pero verifiquemos si V07 ER usa precipitation)
        # Asumiremos precipitation para simplificar y si falla, lo ajustaremos.
        # En la mayoría de las colecciones IMERG_V07 la banda principal es 'precipitation'.
        collection = (ee.ImageCollection('NASA/GPM_L3/IMERG_V06')
            .filterDate(start_date, end_date_gee)
            .select('precipitationCal')
            .map(lambda img: img.rename(['precipitation'])))
            
    # La banda precipitation está en mm/hr. 
    # Cada imagen es de 30 min (0.5 hrs).
    def calc_mm(image):
        return image.multiply(0.5).copyProperties(image, ["system:time_start"])
        
    total_mm_image = collection.map(calc_mm).sum()
    
    # Reducción espacial: usamos MAX para capturar el pico convectivo
    stats = total_mm_image.reduceRegion(
        reducer=ee.Reducer.max(),
        geometry=geom,
        scale=1000, # Reducimos la escala de muestreo a 1km para que Geometrías pequeñas (<10km) logren capturar el valor del pixel subyacente
        maxPixels=1e9
    )
    
    val = stats.getInfo().get('precipitation')
    return float(val) if val is not None else 0.0

def fetch_dem(bbox: list) -> xr.DataArray:
    """
    Descarga Copernicus DEM GLO-30 desde Planetary Computer (vía STAC).
    Retorna un DataArray de xarray recortado a la zona (bbox = [minx, miny, maxx, maxy]).
    """
    catalog = Client.open("https://planetarycomputer.microsoft.com/api/stac/v1", modifier=pc.sign_inplace)
    search = catalog.search(
        collections=["cop-dem-glo-30"],
        bbox=bbox
    )
    items = list(search.items())
    if not items:
        raise ValueError("No se encontró cobertura de Copernicus DEM para este bbox.")
    
    # Toma el primer item encontrado
    item = items[0]
    asset = item.assets["data"]
    
    # Abre y recorta a los límites solicitados
    rds = rioxarray.open_rasterio(asset.href)
    minx, miny, maxx, maxy = bbox
    cropped = rds.rio.clip_box(minx=minx, miny=miny, maxx=maxx, maxy=maxy, crs="EPSG:4326")
    return cropped

def fetch_land_cover(bbox: list) -> xr.DataArray:
    """
    Descarga ESA WorldCover 10m desde Planetary Computer.
    """
    catalog = Client.open("https://planetarycomputer.microsoft.com/api/stac/v1", modifier=pc.sign_inplace)
    search = catalog.search(
        collections=["esa-worldcover"],
        bbox=bbox
    )
    items = list(search.items())
    if not items:
        raise ValueError("No se encontró cobertura de ESA WorldCover para este bbox.")
    
    item = items[0]
    asset = item.assets["map"]
    
    rds = rioxarray.open_rasterio(asset.href)
    minx, miny, maxx, maxy = bbox
    cropped = rds.rio.clip_box(minx=minx, miny=miny, maxx=maxx, maxy=maxy, crs="EPSG:4326")
    return cropped

from shapely.geometry import LineString

def fetch_osm_network(bbox: list, fallback_coords: list = None) -> gpd.GeoDataFrame:
    """
    Descarga la red de drenaje usando OSMnx (canales, ríos, etc.).
    Si falla o devuelve vacío, usa el fallback si está disponible.
    """
    # Cambiar el endpoint principal a uno más estable y bajar el timeout
    ox.settings.overpass_endpoint = 'https://overpass.kumi.systems/api/interpreter'
    ox.settings.timeout = 30
    
    minx, miny, maxx, maxy = bbox
    # bbox en OSMnx 2.x es (north, south, east, west) -> (maxy, miny, maxx, minx)
    # Ajustamos a la sintaxis esperada (north, south, east, west)
    
    tags = {
        "waterway": True,
        "natural": ["water"]
    }
    
    gdf = gpd.GeoDataFrame()
    try:
        # Importante: usar features_from_bbox (no graph)
        gdf = ox.features_from_bbox(bbox=(minx, miny, maxx, maxy), tags=tags)
    except ox._errors.InsufficientResponseError:
        print("ADVERTENCIA: No se encontraron elementos de agua en OSM para esta zona. (Puede ser canal embovedado/subterráneo).")
    except Exception as e:
        error_msg = str(e).lower()
        if "timeout" in error_msg or "time out" in error_msg or "timed out" in error_msg:
            print("ERROR CRÍTICO: La consulta a OSM falló por Timeout de red, no por falta de datos.")
            raise RuntimeError(f"OSM Timeout: {e}") from e
        else:
            print(f"ERROR CRÍTICO: Error inesperado consultando OSM: {e}")
            raise RuntimeError(f"OSM Error: {e}") from e
        
    if gdf.empty:
        if fallback_coords:
            print("INFO: La consulta a OSM retornó vacío (sin cauces naturales). Utilizando geometría de respaldo manual (fallback)...")
            line = LineString(fallback_coords)
            # Crear un GDF mínimo con el LineString
            gdf = gpd.GeoDataFrame({"waterway": ["fallback"]}, geometry=[line], crs="EPSG:4326")
        else:
            print("ADVERTENCIA: La consulta a OSM retornó vacío y no hay fallback disponible. Distancia a cauce será 0.")
            
    return gdf
