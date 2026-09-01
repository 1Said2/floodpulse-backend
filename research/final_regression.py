import sys
import os
sys.path.append(r"c:\Users\micha\Documents\floodpulse-backend")
import json
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score
from src.main import evaluate_risk
from src.config import MODEL_CONFIG
from src.data_fetcher import fetch_rainfall_archive

CSV_IN = r"C:\Users\micha\.gemini\antigravity-ide\brain\91d1d6a8-6e87-4801-8f0f-75b091b84d10\scratch\imerg_progress.csv"
CSV_OM = r"C:\Users\micha\.gemini\antigravity-ide\brain\91d1d6a8-6e87-4801-8f0f-75b091b84d10\scratch\openmeteo_progress.csv"

# Eventos verificados (Positivos)
fallback_ajavi = json.dumps([[-78.12, 0.35], [-78.13, 0.36]])
fallback_salinas = json.dumps([[-80.965, -2.215], [-80.960, -2.216]])

positives = [
    {"name": "Ajaví", "lat": 0.35502, "lon": -78.12463, "start": "2025-04-07", "end": "2025-04-08", "fallback": fallback_ajavi},
    {"name": "Malacatos", "lat": -3.994537, "lon": -79.205415, "start": "2025-03-10", "end": "2025-03-11", "fallback": None},
    {"name": "Esmeraldas", "lat": 0.959, "lon": -79.654, "start": "2023-06-03", "end": "2023-06-04", "fallback": None},
    {"name": "Portoviejo", "lat": -1.056, "lon": -80.455, "start": "2025-02-19", "end": "2025-02-20", "fallback": None},
    {"name": "Salinas", "lat": -2.2155, "lon": -80.9632, "start": "2025-02-22", "end": "2025-02-23", "fallback": fallback_salinas},
    {"name": "Guayaquil Yaku", "lat": -2.1932, "lon": -79.8789, "start": "2023-03-23", "end": "2023-03-24", "fallback": None},
    {"name": "Guayaquil Peor", "lat": -2.1932, "lon": -79.8789, "start": "2025-04-01", "end": "2025-04-03", "fallback": None},
    {"name": "Guayaquil C4", "lat": -2.1932, "lon": -79.8789, "start": "2026-06-07", "end": "2026-06-09", "fallback": None},
]

def format_date(year, month, day):
    from datetime import datetime, timedelta
    try:
        start_date = f"{year}-{month:02d}-{day:02d}"
        d = datetime(year, month, day)
        end_date = (d + timedelta(days=1)).strftime('%Y-%m-%d')
    except:
        start_date = f"{year}-{month:02d}-{day-1:02d}"
        end_date = f"{year}-{month:02d}-{day:02d}"
    return start_date, end_date

def get_openmeteo_data(df):
    if os.path.exists(CSV_OM):
        return pd.read_csv(CSV_OM)
        
    print("Descargando historial de Open-Meteo (esto es muy rápido)...")
    results = []
    for idx, row in df.iterrows():
        year = int(row['year'])
        month = int(row['month'])
        day = int(row['day'])
        lat = row['lat']
        lon = row['lon']
        
        start_date, end_date = format_date(year, month, day)
        om_rain = fetch_rainfall_archive(lat, lon, start_date, end_date)
        
        rec = row.to_dict()
        rec['om_max_24'] = om_rain
        results.append(rec)
        
    df_om = pd.DataFrame(results)
    df_om.to_csv(CSV_OM, index=False)
    return df_om

def extract_features(ev_list, label, rain_source_col=None, df_ref=None):
    data = []
    for ev in ev_list:
        try:
            res = evaluate_risk(
                lat=ev["lat"],
                lon=ev["lon"],
                bbox_offset_deg=0.005,
                rainfall_mm=None,
                event_start=ev["start"],
                event_end=ev["end"],
                fallback_waterway_coords=ev.get("fallback")
            )
            
            grid_features = res.grid_geojson["features"]
            best_cell = max(grid_features, key=lambda f: f["properties"]["risk_score"])
            props = best_cell["properties"]
            th = MODEL_CONFIG["thresholds"]
            
            # En positivos, extraemos la lluvia real del evento para la validación
            rain = res.components["rainfall_mm"]
            
            # Si es un negativo y tenemos datos de referencia, usamos la lluvia del dataset en vez de la de la API (para simular el pasado real)
            if df_ref is not None and "station_name" in ev:
                # Buscar en el df_ref por nombre de estacion y fecha
                name = ev["station_name"]
                year = int(ev["start"][:4])
                match = df_ref[(df_ref["station_name"] == name) & (df_ref["year"] == year)]
                if not match.empty:
                    rain = match.iloc[0][rain_source_col]
                    
            rain_norm = min(rain / th["max_rainfall_mm"], 1.0)
            twi_norm = np.clip(props["twi_raw"] / th["max_twi"], 0.0, 1.0)
            dist_norm = np.clip(1.0 - (props["dist_m"] / th["safe_distance_m"]), 0.0, 1.0)
            imperv_norm = props["imperv_pct"] / 100.0
            
            data.append({
                "name": ev["name"],
                "region": ev.get("region", "Desconocida"),
                "rain_norm": rain_norm,
                "twi_norm": twi_norm,
                "dist_norm": dist_norm,
                "imperv_norm": imperv_norm,
                "is_flood": label
            })
        except Exception as e:
            # print(f"Error extracting {ev['name']}: {e}")
            pass
    return data

if __name__ == "__main__":
    if not os.path.exists(CSV_IN):
        print("Aún no termina el Paso 2 (IMERG).")
        sys.exit(1)
        
    df_raw = pd.read_csv(CSV_IN)
    # Descargar open meteo para complementar
    df_om = get_openmeteo_data(df_raw)
    
    # Combinar
    df_raw['om_max_24'] = df_om['om_max_24']
    
    # Evaluar años 2000-2013 (porque IMERG no existía antes de 2000)
    df_2000 = df_raw[df_raw['year'] >= 2000].copy()
    
    print("\n--- COMPARACIÓN SATÉLITE (IMERG) vs MODELO (OPEN-METEO) ---")
    print("Correlación con INAMHI (Verdad de campo):")
    
    # Error medio absoluto
    mae_imerg = (df_2000['max_24'] - df_2000['imerg_max_24']).abs().mean()
    mae_om = (df_2000['max_24'] - df_2000['om_max_24']).abs().mean()
    
    print(f"Error Absoluto Medio (IMERG): {mae_imerg:.2f} mm")
    print(f"Error Absoluto Medio (OpenMeteo): {mae_om:.2f} mm")
    
    if mae_om < mae_imerg:
        print("=> OPEN-METEO es más preciso que el satélite bruto en Ecuador.")
    else:
        print("=> IMERG es más preciso que el modelo matemático.")

    # Calcular factores de calibración para la fuente ganadora (Open-Meteo casi seguro)
    print("\n--- Factores Regionales Finales (Open-Meteo) ---")
    df_raw['om_ratio'] = df_raw['max_24'] / df_raw['om_max_24']
    df_raw.replace([np.inf, -np.inf], np.nan, inplace=True)
    
    factors = df_raw.dropna(subset=['om_ratio']).groupby('region')['om_ratio'].agg(['mean', 'std', 'count']).reset_index()
    for _, r in factors.iterrows():
        print(f"Region: {r['region']} | Factor: {r['mean']:.2f} | Std: {r['std']:.2f} | Count: {r['count']}")
        
    print("\n--- Regresión Logística Final ---")
    df_neg = df_raw[df_raw['max_24'] < 5.0].copy()
    
    pos_data = extract_features(positives, 1)
    
    neg_list = []
    for _, row in df_neg.iterrows():
        year = int(row['year'])
        month = int(row['month'])
        day = int(row['day'])
        start_date, end_date = format_date(year, month, day)
        neg_list.append({
            "name": f"{row['station_name']} {start_date}",
            "station_name": row['station_name'],
            "lat": row['lat'],
            "lon": row['lon'],
            "start": start_date,
            "end": end_date,
            "region": row['region']
        })
    
    if len(neg_list) > 100:
        import random
        random.shuffle(neg_list)
        neg_list = neg_list[:100]
        
    neg_data_om = extract_features(neg_list, 0, rain_source_col="om_max_24", df_ref=df_raw)
    
    df_ml = pd.DataFrame(pos_data + neg_data_om)
    df_ml = df_ml.replace([np.inf, -np.inf], np.nan).fillna(0)
    
    X = df_ml[["rain_norm", "twi_norm", "dist_norm", "imperv_norm"]]
    y = df_ml["is_flood"]
    
    clf = LogisticRegression(class_weight='balanced')
    clf.fit(X, y)
    
    print("Pesos Finales del Modelo Físico:")
    print(f"Lluvia (Calibrada OM): {clf.coef_[0][0]:.4f}")
    print(f"Topografía (TWI):      {clf.coef_[0][1]:.4f}")
    print(f"Dist. Cauce (Ríos):    {clf.coef_[0][2]:.4f}")
    print(f"Impermeabilidad (Uso): {clf.coef_[0][3]:.4f}")
    print(f"Precisión Global en dataset estricto: {accuracy_score(y, clf.predict(X))*100:.2f}%")
