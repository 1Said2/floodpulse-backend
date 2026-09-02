# src/config.py

# Parámetros del modelo matemático (Día 2 y posteriores)
# El CRS ahora se calcula dinámicamente en utils.py, por lo que no se fija aquí.

MODEL_CONFIG = {
    # Factores de Calibración IMERG vs Pluviómetro
    # Pesos de la fórmula aditiva (suma = 1.0)
    "weights": {
        "rainfall": 0.40,
        "twi": 0.20,
        "distance": 0.25,
        "impervious": 0.15
    },
    
    # Pesos para la Susceptibilidad Estática (suma = 1.0) en fórmula multiplicativa
    "susceptibility_weights": {
        "twi": 0.33,
        "distance": 0.42,
        "impervious": 0.25
    },
    
    "formula": {
        "use_multiplicative": True
    },
    
    # Factores de Calibración IMERG/CHIRPS vs Pluviómetro (Basado en eventos reales 1,2,3,5)
    "calibration": {
        "sierra": 2.22,
        "costa": 2.14
    },
    
    # Umbrales para normalizar de 0 a 1
    "thresholds": {
        # INAMHI define sus advertencias de "lluvia muy alta" en acumulados de 45mm/24h.
        "max_rainfall_mm": 45.0,
        # Si un punto está más lejos que esto de un cauce, el riesgo por distancia cae a 0.
        "safe_distance_m": 500.0,
        # TWI suele rondar de 5 a 25. 20.0 es un umbral empírico alto para saturar el riesgo por humedad.
        "max_twi": 20.0
    },

    # Umbral global para emitir alerta
    "predicted_flood": {
        "risk_threshold": 60.0
    }
}
