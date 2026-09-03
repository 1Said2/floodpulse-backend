"""
Script para derivar factores de calibración de satélites (IMERG y CHIRPS)
usando los 4 eventos históricos verificados con pluviómetros.
"""

import sys
import os
import numpy as np

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from src.data_fetcher import fetch_rainfall_gpm, fetch_rainfall_chirps

# Eventos verificados de 24h
EVENTOS = [
    {
        "nombre": "Ajaví", 
        "region": "sierra",
        "bbox": [-78.1296, 0.3500, -78.1196, 0.3600],
        "start": "2025-04-07", 
        "end": "2025-04-08",
        "real_mm": 40.8
    },
    {
        "nombre": "Malacatos", 
        "region": "sierra",
        "bbox": [-79.2104, -3.9995, -79.2004, -3.9895],
        "start": "2025-03-10", 
        "end": "2025-03-11",
        "real_mm": 76.6
    },
    {
        "nombre": "Esmeraldas", 
        "region": "costa",
        "bbox": [-79.6574, 0.9618, -79.6474, 0.9718],
        "start": "2023-06-03", 
        "end": "2023-06-04",
        "real_mm": 100.0
    },
    {
        "nombre": "Guayaquil Yaku", 
        "region": "costa",
        "bbox": [-79.8839, -2.1982, -79.8739, -2.1882],
        "start": "2023-03-23", 
        "end": "2023-03-24",
        "real_mm": 199.5
    }
]

def main():
    print("Derivando factores de calibración con 4 eventos confirmados...\n")
    
    resultados = {"imerg": {}, "chirps": {}}
    
    for ev in EVENTOS:
        print(f"[{ev['region'].upper()}] Evento: {ev['nombre']} (Lluvia real: {ev['real_mm']} mm)")
        
        try:
            val_imerg = fetch_rainfall_gpm(ev["bbox"], ev["start"], ev["end"])
            val_chirps = fetch_rainfall_chirps(ev["bbox"], ev["start"], ev["end"])
        except Exception as e:
            print(f"Error descargando datos satelitales: {e}")
            val_imerg = 0.0
            val_chirps = 0.0
            
        if val_imerg > 0:
            ratio_imerg = ev["real_mm"] / val_imerg
            print(f"  IMERG  -> detectado: {val_imerg:6.1f} mm | Razón: {ratio_imerg:5.2f}")
            resultados["imerg"].setdefault(ev["region"], []).append(ratio_imerg)
        else:
            print(f"  IMERG  -> detectado: 0.0 mm | EXCLUIDO")
            
        if val_chirps > 0:
            ratio_chirps = ev["real_mm"] / val_chirps
            print(f"  CHIRPS -> detectado: {val_chirps:6.1f} mm | Razón: {ratio_chirps:5.2f}\n")
            resultados["chirps"].setdefault(ev["region"], []).append(ratio_chirps)
        else:
            print(f"  CHIRPS -> detectado: 0.0 mm | EXCLUIDO\n")
        
    print("=== Análisis de Dispersión ===")
    
    # Evaluar si la dispersión justifica un factor
    import scipy.stats as st
    
    for sat in ["imerg", "chirps"]:
        for reg, ratios in resultados[sat].items():
            if len(ratios) == 0:
                print(f"[{sat.upper()} - {reg}] Sin datos válidos. Se recomienda factor = 1.0")
                continue
                
            n = len(ratios)
            mean_ratio = np.mean(ratios)
            
            if n > 1:
                std_dev_sample = np.std(ratios, ddof=1)
                t_crit = st.t.ppf(0.975, n - 1)
                margin = t_crit * (std_dev_sample / np.sqrt(n))
                ic_lower = mean_ratio - margin
                ic_upper = mean_ratio + margin
                print(f"[{sat.upper()} - {reg}] Media: {mean_ratio:.2f} (n={n}), IC 95%: [{ic_lower:.2f}, {ic_upper:.2f}]")
                if ic_lower <= 1.0 <= ic_upper:
                    print(f"  -> El IC 95% contiene 1.0. Se recomienda factor = 1.0")
                else:
                    print(f"  -> Se recomienda factor = {mean_ratio:.2f}")
            else:
                print(f"[{sat.upper()} - {reg}] Media: {mean_ratio:.2f} (n=1). Insuficiente para IC. Se recomienda factor = 1.0")

if __name__ == "__main__":
    main()
