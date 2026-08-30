"""
Configuraciones del backend de FloodPulse.
Define los sectores, parámetros y coordenadas de referencia.
"""

from typing import Dict, Any

# Sectores por defecto para evaluación y backtesting
SECTORS: Dict[str, Dict[str, Any]] = {
    "ajavi": {
        "name": "Redondel de Ajaví, Ibarra",
        "description": "Sector de prueba principal, intersección Mariano Acosta y Heleodoro Ayala.",
        # Coordenadas centrales
        "lat": 0.35502,
        "lon": -78.12463,
        # Tamaño del bounding box en grados (~1 km de lado) o un radio para buscar.
        # Para simplificar, definiremos un offset para el bounding box (aprox. 500m)
        "bbox_offset": 0.005, 
    }
}

def get_sector_config(sector_id: str) -> Dict[str, Any]:
    """Obtiene la configuración de un sector dado."""
    if sector_id not in SECTORS:
        raise ValueError(f"Sector '{sector_id}' no encontrado en la configuración.")
    
    sector = SECTORS[sector_id].copy()
    
    # Calcular Bounding Box [min_lon, min_lat, max_lon, max_lat]
    lat = sector["lat"]
    lon = sector["lon"]
    offset = sector["bbox_offset"]
    
    sector["bbox"] = [
        lon - offset, # minx
        lat - offset, # miny
        lon + offset, # maxx
        lat + offset  # maxy
    ]
    
    return sector
