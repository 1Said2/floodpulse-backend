# src/config.py

# Parámetros del modelo matemático (Día 2 y posteriores)
# El CRS ahora se calcula dinámicamente en utils.py, por lo que no se fija aquí.

MODEL_CONFIG = {
    # Factores de Calibración IMERG vs Pluviómetro
    # Pesos de la fórmula (suma = 1.0)
    "weights": {
        "rainfall": 0.717,     # Softmax de 2.8298
        "distance": 0.203,     # Softmax de 1.5695
        "twi": 0.067,          # Softmax de 0.4615
        "impervious": 0.013    # Softmax de -1.1907
    },
    
    # Factores de calibración regional satélite vs Open-Meteo
    "calibration": {
        "costa": 3.27,
        "sierra": 4.03,
        "amazonia": 11.42
    },
    
    # Umbrales para normalizar de 0 a 1
    "thresholds": {
        # Si la lluvia supera este umbral, el factor de lluvia será 1.0 (máximo riesgo)
        "max_rainfall_mm": 25.0,
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
