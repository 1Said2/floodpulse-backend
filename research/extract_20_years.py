import pdfplumber
import fitz
import os
import pandas as pd
import re
import sys

STATIONS = {
    'M0143': ('Malacatos', 'Sierra', -3.994537, -79.205415),
    'M1208': ('La Teodomira', 'Costa', -1.162778, -80.395833),
    'M1240': ('Ibarra', 'Sierra', 0.35502, -78.12463),
    'M0008': ('Puyo', 'Amazonia', -1.483, -77.983),
    'M1040': ('Macas', 'Amazonia', -2.316, -78.116),
    'M1203': ('Lumbaqui', 'Amazonia', 0.050, -77.316),
    'M0007': ('Nuevo Rocafuerte', 'Amazonia', -0.916, -75.400),
    'M0176': ('Naranjal', 'Costa', -2.666, -79.616),
    'M0037': ('Milagro', 'Costa', -2.133, -79.583),
    'M0185': ('Machala', 'Costa', -3.266, -79.950),
    'M0619': ('Manglaralto', 'Costa', -1.833, -80.733),
    'M0024': ('Quito', 'Sierra', -0.166, -78.483),
    'M1036': ('Riobamba', 'Sierra', -1.650, -78.683),
    'M0105': ('Otavalo', 'Sierra', 0.233, -78.266)
}

pdf_dir = r"C:\Users\micha\Pictures\met"
years = range(1994, 2014)

def parse_station_page(text):
    months = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]
    data = []
    lines = text.split('\n')
    
    for line in lines:
        for i, month in enumerate(months):
            if line.startswith(month):
                parts = line.split()
                try:
                    num_dias = parts[-1]
                    dia = parts[-2]
                    max_24 = parts[-3]
                    suma_mensual = parts[-4]
                    
                    if max_24.replace('.','',1).isdigit() and dia.isdigit():
                        data.append({
                            "month": i + 1,
                            "day": int(dia),
                            "max_24": float(max_24),
                            "suma_mensual": float(suma_mensual) if suma_mensual.replace('.','',1).isdigit() else 0.0
                        })
                except Exception:
                    pass
    return data

if __name__ == "__main__":
    all_records = []
    
    for y in years:
        path = os.path.join(pdf_dir, f"Meteorologico_{y}.pdf")
        if not os.path.exists(path):
            print(f"Skipping {y}, file not found.")
            sys.stdout.flush()
            continue
            
        print(f"--- Processing Year {y} ---")
        sys.stdout.flush()
        try:
            # 1. Búsqueda rápida con Fitz (PyMuPDF)
            doc = fitz.open(path)
            tena_code = None
            
            # Buscar Tena en las primeras 30 páginas
            for p_num in range(min(30, len(doc))):
                text = doc[p_num].get_text().upper()
                if "TENA" in text:
                    lines = text.split('\n')
                    for line in lines:
                        if "TENA" in line:
                            match = re.search(r'M\d{4}', line)
                            if match:
                                tena_code = match.group(0)
                                break
                    if tena_code: break
            
            if tena_code:
                print(f"Found Tena code for {y}: {tena_code}")
            else:
                print(f"Warning: Could not find Tena code for {y}")
            sys.stdout.flush()
            
            active_codes = list(STATIONS.keys())
            if tena_code: active_codes.append(tena_code)
            
            tena_info = ('Tena', 'Amazonia', -0.983, -77.816)
            
            # Buscar en qué páginas están las estaciones usando Fitz (Rapidísimo)
            pages_to_parse = {}
            for p_num in range(len(doc)):
                text = doc[p_num].get_text().upper()
                if not text: continue
                for code in active_codes:
                    info = STATIONS.get(code, tena_info)
                    name = info[0].upper()
                    
                    # El código antiguo quita el primer cero después de la M, ej. M0024 -> M024
                    old_code = code
                    if code.startswith("M0") and len(code) == 5:
                        old_code = "M" + code[2:]
                        
                    # Si el nombre, el código moderno o el antiguo están en la página, intentamos extraer
                    if name in text or code in text or old_code in text:
                        if p_num not in pages_to_parse:
                            pages_to_parse[p_num] = []
                        pages_to_parse[p_num].append(code)
            
            doc.close()
            
            # 2. Extracción profunda solo de las páginas encontradas usando pdfplumber
            if pages_to_parse:
                with pdfplumber.open(path) as pdf:
                    for p_num, codes_found in pages_to_parse.items():
                        page = pdf.pages[p_num]
                        page_text = page.extract_text()
                        for code in codes_found:
                            extracted = parse_station_page(page_text)
                            if extracted:
                                print(f"Successfully extracted {code} from {y} (Page {p_num+1})")
                                sys.stdout.flush()
                                info = STATIONS.get(code, tena_info)
                                for rec in extracted:
                                    all_records.append({
                                        "year": y,
                                        "station_code": code,
                                        "station_name": info[0],
                                        "region": info[1],
                                        "lat": info[2],
                                        "lon": info[3],
                                        "month": rec["month"],
                                        "day": rec["day"],
                                        "max_24": rec["max_24"],
                                        "suma_mensual": rec["suma_mensual"]
                                    })
                            
        except Exception as e:
            print(f"Error processing {y}: {e}")
            sys.stdout.flush()
            
    df = pd.DataFrame(all_records)
    out_path = r"C:\Users\micha\.gemini\antigravity-ide\brain\91d1d6a8-6e87-4801-8f0f-75b091b84d10\scratch\inamhi_1994_2013.csv"
    df.to_csv(out_path, index=False)
    print(f"Done! Saved {len(df)} records to {out_path}")
    sys.stdout.flush()
