import requests
import osmnx as ox
from pystac_client import Client
import planetary_computer as pc
import rioxarray
import xarray as xr
import geopandas as gpd

# Último error por fuente externa. main.py lo lee para devolver `warnings`
# al dashboard en vez de fallar en silencio (las funciones de lluvia devuelven 0.0 si algo falla).
LAST_ERRORS: dict = {}


def _set_error(fuente: str, msg):
    LAST_ERRORS[fuente] = str(msg)[:300]
    print(f"[{fuente}] {LAST_ERRORS[fuente]}")


def _clear_error(fuente: str):
    LAST_ERRORS.pop(fuente, None)

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
    
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        _clear_error("open-meteo-forecast")
    except (requests.exceptions.RequestException, ValueError) as e:
        _set_error("open-meteo-forecast", f"{resp.text[:200] if 'resp' in locals() and hasattr(resp, 'text') else str(e)}")
        return 0.0
    
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
    
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        _clear_error("open-meteo-archive")
    except (requests.exceptions.RequestException, ValueError) as e:
        _set_error("open-meteo-archive", f"{resp.text[:200] if 'resp' in locals() and hasattr(resp, 'text') else str(e)}")
        return 0.0
        
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
        _clear_error("gee")
    except Exception as e:
        # Sin credenciales (earthengine authenticate) o sin proyecto: lluvia observada = 0,
        # el ensamble sigue con Open-Meteo. main.py lo reporta en `warnings`.
        _set_error("gee", f"Earth Engine no disponible ({str(e).splitlines()[0]}). "
                          f"Ejecuta 'earthengine authenticate' o pasa rainfall_mm.")
        return 0.0
        
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
    
    try:
        val = stats.getInfo().get('precipitation')
        return float(val) if val is not None else 0.0
    except Exception as e:
        _set_error("gee", f"Error GEE getInfo: {e}")
        return 0.0

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

# Servidores Overpass en orden de preferencia. kumi.systems (el original) suele
# devolver 502/timeout; se prueban en cadena hasta que uno responda.
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
OVERPASS_TIMEOUT_S = 30


class OSMUnavailable(RuntimeError):
    """Ningún servidor Overpass respondió (no significa que no haya cauces)."""


def fetch_osm_network(bbox: list, fallback_coords: list = None) -> gpd.GeoDataFrame:
    """
    Descarga la red de drenaje usando OSMnx (canales, ríos, etc.), probando varios
    servidores Overpass. Si TODOS fallan:
      - con fallback_coords -> usa el trazado manual (y deja aviso en LAST_ERRORS["osm"])
      - sin fallback        -> lanza OSMUnavailable (main.py responde 503 con detalle)
    Si OSM responde pero no hay elementos, usa fallback si existe.
    """
    ox.settings.requests_timeout = OVERPASS_TIMEOUT_S
    # Desactivar la verificación de rate limit (que causa esperas de 60s si falla el endpoint /status)
    ox.settings.overpass_rate_limit = False
    ox.settings.use_cache = True

    minx, miny, maxx, maxy = bbox
    tags = {
        "waterway": True,
        "natural": ["water"],
    }

    # Prevenir reintentos automáticos de requests/urllib3 (cada uno esperaría el timeout completo)
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    original_post = requests.post
    original_get = requests.get

    def custom_request(method):
        def wrapper(*args, **kwargs):
            session = requests.Session()
            retries = Retry(total=0, connect=0, read=0)
            adapter = HTTPAdapter(max_retries=retries)
            session.mount('http://', adapter)
            session.mount('https://', adapter)
            return session.request(method, *args, **kwargs)
        return wrapper

    requests.post = custom_request('POST')
    requests.get = custom_request('GET')

    gdf = gpd.GeoDataFrame()
    errores = []
    respondio = False
    try:
        for url in OVERPASS_ENDPOINTS:
            ox.settings.overpass_url = url
            host = url.split("/")[2]
            try:
                gdf = ox.features_from_bbox(bbox=(minx, miny, maxx, maxy), tags=tags)
                respondio = True
                _clear_error("osm")
                print(f"INFO: OSM OK via {host} ({len(gdf)} elementos)")
                break
            except ox._errors.InsufficientResponseError:
                respondio = True
                _clear_error("osm")
                print(f"ADVERTENCIA: {host} respondió pero no hay elementos de agua en la zona "
                      f"(puede ser canal embovedado/subterráneo).")
                break
            except Exception as e:
                msg = f"{host}: {str(e)[:120]}"
                errores.append(msg)
                print(f"ADVERTENCIA: fallo Overpass {msg} -> probando siguiente servidor")
    finally:
        requests.post = original_post
        requests.get = original_get

    if not respondio:
        detalle = " | ".join(errores)
        if fallback_coords:
            _set_error("osm", f"Ningún servidor Overpass respondió; se usó el trazado manual (fallback). {detalle}")
            return gpd.GeoDataFrame({"waterway": ["fallback"]},
                                    geometry=[LineString(fallback_coords)], crs="EPSG:4326")
        _set_error("osm", f"Ningún servidor Overpass respondió y no hay fallback. {detalle}")
        raise OSMUnavailable(f"OpenStreetMap (Overpass) no disponible: {detalle}")

    if gdf.empty:
        if fallback_coords:
            print("INFO: OSM sin cauces en la zona. Utilizando geometría de respaldo manual (fallback)...")
            gdf = gpd.GeoDataFrame({"waterway": ["fallback"]},
                                   geometry=[LineString(fallback_coords)], crs="EPSG:4326")
        else:
            _set_error("osm", "OSM no tiene cauces mapeados en la zona y no se envió fallback_waterway_coords: "
                              "la distancia al cauce se toma como 'segura' (500 m) y el riesgo puede subestimarse.")

    return gdf
