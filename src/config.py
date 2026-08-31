# src/config.py

# Parámetros del modelo matemático (Día 2 y posteriores)
# El CRS ahora se calcula dinámicamente en utils.py, por lo que no se fija aquí.

MODEL_CONFIG = {
    # Factores de Calibración IMERG vs Pluviómetro
    "calibration": {
        "sierra": 1.1417,
        "costa": 5.1149
    },
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
        "max_rainfall_mm": 25.0,
        # Si un punto está más lejos que esto de un cauce, el riesgo por distancia cae a 0.
        "safe_distance_m": 500.0,
        # Asumimos que un TWI muy alto (ej. > 15) es propensión máxima a acumular agua.
        "max_twi": 15.0
    }
}
