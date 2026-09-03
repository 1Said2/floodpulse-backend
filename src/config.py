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
    
    # Factores de Calibración
    # Extraídos de eventos validados.
    "calibration": {
        # Con 2 eventos por región (n=2), el IC 95% de la media muestral contiene 1.0
        # No hay evidencia estadística para aplicar factores correctivos.
        "imerg": {"sierra": 1.0, "costa": 1.0, "oriente": 1.0},
        "chirps": {"sierra": 1.0, "costa": 1.0, "oriente": 1.0}
    },
    
    # Umbrales para normalizar de 0 a 1
    "thresholds": {
        # Techo logarítmico (A4). Eventos severos de 300+ mm seguirán creciendo asintóticamente hacia 1.0, pero bajamos el r_max a 150.0 para que 45mm no quede subrepresentado.
        "max_rainfall_mm": 150.0,
        # (A5) safe_distance_m ya no es estático; se calcula dinámicamente en risk_model.py en función del bbox.
        # TWI suele rondar de 5 a 25. 20.0 es un umbral empírico alto para saturar el riesgo por humedad.
        "max_twi": 20.0
    },

    # Umbral global para emitir alerta
    "predicted_flood": {
        # El umbral óptimo (Youden) derivado tras corregir a point_risk (AUC 0.810) con lluvia extrema (113.2 mm).
        # Este umbral implica un piso implícito de ~21 mm de lluvia diaria para que una zona de muy alta susceptibilidad pueda emitir alerta.
        "risk_threshold": 31.16
    }
}
