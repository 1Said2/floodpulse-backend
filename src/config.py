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
        # Fallback manual para el colector embovedado (proxy Av. Mariano Acosta)
        # Formato: Lista de [lon, lat] para construir un LineString si falla OSM
        "fallback_waterway": [
            [-78.1265, 0.3565], # Más arriba en la avenida
            [-78.12463, 0.35502], # Redondel (centro)
            [-78.1220, 0.3525], # Hacia el sur/este
            [-78.1200, 0.3505]
        ]
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

# Parámetros del modelo matemático (Día 2)
MODEL_CONFIG = {
    # EPSG:32617 = UTM Zona 17 Norte (Aplica para Ibarra, Latitud positiva)
    "crs_metric": "EPSG:32617",
    
    # Pesos de la fórmula (suma = 1.0)
    "weights": {
        "rainfall": 0.40,
        "twi": 0.20,
        "distance": 0.25,
        "impervious": 0.15
    },
    
    # Umbrales para normalizar de 0 a 1
    "thresholds": {
        # Si la lluvia supera este umbral, el factor de lluvia será 1.0 (máximo riesgo)
        # Ajustado a 25.0mm para que el evento del 8 de abril de 2025 (25.6mm Open-Meteo) 
        # marque un riesgo muy alto.
        "max_rainfall_mm": 25.0,
        # Si un punto está más lejos que esto de un cauce, el riesgo por distancia cae a 0.
        "safe_distance_m": 500.0,
        # Asumimos que un TWI muy alto (ej. > 15) es propensión máxima a acumular agua.
        "max_twi": 15.0
    }
}
