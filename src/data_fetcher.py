import requests
import osmnx as ox
from pystac_client import Client
import planetary_computer as pc
import rioxarray
import xarray as xr
import geopandas as gpd

def fetch_rainfall(lat: float, lon: float, start_date: str = None, end_date: str = None) -> dict:
    """
    Obtiene datos de precipitación de Open-Meteo.
    Si se especifican fechas, usa la API de datos históricos para backtesting.
    Caso contrario, trae pronóstico (y datos de 1 día atrás).
    """
    if start_date and end_date:
        url = "https://archive-api.open-meteo.com/v1/archive"
        params = {
            "latitude": lat,
            "longitude": lon,
            "start_date": start_date,
            "end_date": end_date,
            "hourly": "precipitation",
            "timezone": "America/Guayaquil"
        }
    else:
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": lat,
            "longitude": lon,
            "hourly": "precipitation",
            "past_days": 1,
            "forecast_days": 2,
            "timezone": "America/Guayaquil"
        }
    
    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.json()

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

def fetch_osm_network(bbox: list) -> gpd.GeoDataFrame:
    """
    Descarga vías de drenaje (waterway) y cuerpos de agua desde OpenStreetMap usando osmnx.
    """
    minx, miny, maxx, maxy = bbox
    # En OSMnx 2.x, el orden es (left, bottom, right, top) es decir (minx, miny, maxx, maxy)
    
    tags = {
        "waterway": True,
        "natural": ["water"]
    }
    
    try:
        # Importante: usar features_from_bbox (no graph)
        gdf = ox.features_from_bbox(bbox=(minx, miny, maxx, maxy), tags=tags)
        
        if gdf.empty:
            print("ADVERTENCIA: La consulta a OSM retornó vacío. Posible causa: tramos embovedados o no mapeados.")
        return gdf
    except ox._errors.InsufficientResponseError:
        print("ADVERTENCIA: No se encontraron elementos de agua en OSM para esta zona. (Puede ser canal embovedado/subterráneo).")
        return gpd.GeoDataFrame()
    except Exception as e:
        print(f"ADVERTENCIA: Error consultando OSM: {e}")
        return gpd.GeoDataFrame()
