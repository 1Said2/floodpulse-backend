import math

def get_utm_epsg(lat: float, lon: float) -> str:
    """
    Calcula el EPSG métrico correspondiente (Zona UTM) para unas coordenadas.
    Aplica para cualquier parte del mundo.
    """
    # La zona UTM se calcula agregando 180 a la longitud y dividiendo por 6
    zone = math.floor((lon + 180) / 6) + 1
    
    # El EPSG base para UTM WGS84: 32600 para hemisferio Norte, 32700 para Sur
    hemisphere = 32600 if lat >= 0 else 32700
    
    epsg_code = hemisphere + zone
    return f"EPSG:{epsg_code}"
