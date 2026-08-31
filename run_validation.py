import ee
import json
from src.main import validate_historical_event
import os

# Asegurar que el entorno de GEE esté inicializado
try:
    ee.Initialize(project='gen-lang-client-0564385440')
except Exception as e:
    print(f"Advertencia: No se pudo inicializar GEE directamente, intentando usar fallback o variable de entorno. Error: {e}")

# Coordenadas manuales (embovedado) para Ajaví, Ibarra
fallback_ajavi = json.dumps([[-78.12, 0.35], [-78.13, 0.36]]) 

fallback_salinas = json.dumps([[-80.965, -2.215], [-80.960, -2.216]])

events = [
    # {"name": "Ajaví, Ibarra", "lat": 0.35502, "lon": -78.12463, "start": "2025-04-07", "end": "2025-04-08", "real": 40.8, "fallback": fallback_ajavi},
    # {"name": "Malacatos, Loja", "lat": -3.994537, "lon": -79.205415, "start": "2025-03-10", "end": "2025-03-11", "real": 40.0, "fallback": None},
    # {"name": "Esmeraldas (Centro)", "lat": 0.959, "lon": -79.654, "start": "2023-06-03", "end": "2023-06-04", "real": 100.0, "fallback": None},
    # {"name": "Portoviejo", "lat": -1.056, "lon": -80.455, "start": "2025-02-19", "end": "2025-02-20", "real": 89.5, "fallback": None},
    {"name": "Salinas", "lat": -2.2155, "lon": -80.9632, "start": "2025-02-22", "end": "2025-02-23", "real": 77.5, "fallback": fallback_salinas},
    # {"name": "Guayaquil (Yaku)", "lat": -2.1932, "lon": -79.8789, "start": "2023-03-23", "end": "2023-03-24", "real": 199.5, "fallback": None},
    # {"name": "Guayaquil (Peor 2025)", "lat": -2.1932, "lon": -79.8789, "start": "2025-04-01", "end": "2025-04-03", "real": 275.2, "fallback": None},
    # {"name": "Guayaquil (C4 Jun 2026)", "lat": -2.1932, "lon": -79.8789, "start": "2026-06-07", "end": "2026-06-09", "real": 62.67, "fallback": None},
]

print(f"{'Location':<25} | {'Date':<20} | {'Real mm':<10} | {'Calib mm':<10} | {'Risk Score':<10} | {'High Risk?':<10}")
print("-" * 100)

for ev in events:
    try:
        res = validate_historical_event(
            lat=ev["lat"],
            lon=ev["lon"],
            event_window_start=ev["start"],
            event_window_end=ev["end"],
            ground_truth_flooded=True,
            fallback_waterway_coords=ev.get("fallback")
        )
        
        calib_mm = round(res["details"].get("rainfall_mm", 0), 1)
        risk = round(res["predicted_risk_score"], 1)
        is_high = "YES" if res["predicted_flood"] else "NO"
        
        print(f"{ev['name']:<25} | {ev['start']} to {ev['end']:<10} | {ev['real']:<10} | {calib_mm:<10} | {risk:<10} | {is_high:<10}")
    except Exception as e:
        print(f"Error for {ev['name']}: {e}")
