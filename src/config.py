# src/config.py

# Parámetros del modelo matemático (Día 2 y posteriores)
# El CRS ahora se calcula dinámicamente en utils.py, por lo que no se fija aquí.

MODEL_CONFIG = {
    # Factores de Calibración IMERG vs Pluviómetro
    # Pesos de la fórmula (suma = 1.0)
    "weights": {
        "rainfall": 0.40,
        "twi": 0.20,
        "distance": 0.25,
        "impervious": 0.15
    },
    
    # Factores de Calibración IMERG vs Pluviómetro (Valores Originales Conservadores)
    "calibration": {
        "sierra": 1.1417,
        "costa": 5.1149
    },
    
    # Umbrales para normalizar de 0 a 1
    "thresholds": {
        # INAMHI define sus advertencias de "lluvia muy alta" en acumulados de 45mm/24h.
        "max_rainfall_mm": 45.0,
        # Si un punto está más lejos que esto de un cauce, el riesgo por distancia cae a 0.
        "safe_distance_m": 500.0,
        # Asumimos que un TWI muy alto (ej. > 15) es propensión máxima a acumular agua.
        "max_twi": 15.0
    },

    # Umbral global para emitir alerta
    "predicted_flood": {
        "risk_threshold": 60.0
    }
}
