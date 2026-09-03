# FloodPulse — Backend (Motor de Riesgo)

Sistema de índice de riesgo de inundación hiperlocal, calculado 100% con
datos públicos abiertos (sin sensores propios). Track 1 — HackTech El Niño 2026.

## Cómo correrlo
1. `python -m venv venv` y activar el entorno
2. `pip install -r requirements.txt`
3. `uvicorn src.main:app --reload`
4. Abrir http://localhost:8000/docs (Swagger) para probar

## Endpoints

### GET /risk
Calcula el riesgo de un sector dado por coordenadas. Parámetros:
- `lat`, `lon` (obligatorios)
- `bbox_offset_deg` (opcional, default 0.005 ≈ 500m)
- `rainfall_mm` (opcional — si se da, el sistema usa ese valor directo y
  NO llama a ninguna fuente externa de lluvia. Útil para probar sin
  necesitar configurar Google Earth Engine, ver abajo)
- `event_start`, `event_end` (opcional — pide lluvia histórica real de esas fechas)
- `fallback_waterway_coords` (opcional — string JSON `[[lon,lat],...]`, solo
  si el cauce está embovedado/no mapeado en OSM — necesario para Ajaví)

Devuelve: `{lat, lon, risk_score (0-100), timestamp, components: {rainfall_mm,
twi_max, distance_to_channel_m, imperviousness_pct}, grid_geojson}`

`grid_geojson` es un GeoJSON con el detalle celda por celda (para el mapa
de calor) — cada feature tiene `risk_score`, `twi_raw`, `dist_m`, `imperv_pct`.

### GET /validation
Compara el riesgo calculado contra un evento histórico real conocido.
Parámetros: `lat`, `lon`, `event_window_start`, `event_window_end`,
`ground_truth_flooded` (bool), `bbox_offset_deg`.

## Cómo funciona la lluvia (arquitectura híbrida, actualizada)
El sistema combina dos fuentes automáticas, no una sola:
- **NASA GPM IMERG / CHIRPS** (satélite, vía Google Earth Engine): lluvia ya caída e histórica.
- **Open-Meteo**: pronóstico futuro (para anticipar antes de que la
  inundación sea visible) y como respaldo histórico cuando el satélite no
  detecta nada (nubes "cálidas" que el satélite no ve bien).
El sistema toma el MÁXIMO entre ambas fuentes calibradas — si quieres
evitar depender de esto durante pruebas locales, usa el parámetro
`rainfall_mm` para forzar un valor manual (ver siguiente sección).

¿Y necesito configurar Google Earth Engine?
Solo si quieres que el sistema traiga la lluvia automático (modo real/histórico).
Si solo estás probando el dashboard o la lógica de SMS, **usa siempre el
parámetro `rainfall_mm`** en tus pruebas — así el sistema nunca llama a
Earth Engine y no necesitas ninguna cuenta ni configuración. Si en algún
punto quieres probar el modo automático completo, deberás configurar una Service Account de GEE y poner sus credenciales en `config.py`.

## 📊 Calibración y Rendimiento

El motor se calibra dinámicamente según la región y ha sido evaluado mediante curvas ROC (Receiver Operating Characteristic) contra datos históricos. 
La evaluación de susceptibilidad topográfica (`point_risk`) ha validado la capacidad de discriminación del modelo a nivel hiperlocal.

> [!NOTE]
> **Prueba de Concepto y Piso Implícito de Lluvia**
> Los resultados actuales (**AUC 0.810**) corresponden a una evaluación controlada de susceptibilidad topográfica sobre una muestra pequeña de 19 puntos (12 positivos y 7 negativos) provenientes de **un solo evento** en una sola ciudad (Guayaquil, abril de 2025). El AUC de 0.810 sirve como **prueba de concepto de la métrica topográfica** bajo lluvia fija (113.2 mm), pero no representa la exactitud (accuracy) final del sistema completo a nivel nacional.
>
> **Umbral de Alertas y Escala:** Para el cálculo local de alertas de sector, el sistema evalúa exclusivamente el puntaje puntual exacto (`point_risk`). El umbral analítico (`31.16`) establece un piso operativo implícito de **~21 mm de lluvia diaria** para que el modelo alerte sobre las zonas más vulnerables suscritas, un criterio congruente con los avisos meteorológicos del INAMHI.

> [!WARNING]
> **Limitación de los Datos Negativos (Espaciales)**
> La ausencia de un sector en un reporte de prensa no prueba definitivamente que no se inundó. Los sectores "negativos" del dataset son una aproximación generada mediante un doble filtro: documental (ausentes en los partes oficiales/noticias) y topográfico (elevación y distancia al cauce claramente superiores a la mediana de los inundados). El modelo asume que estas zonas altas y no reportadas no sufrieron inundación, lo cual debe tenerse en cuenta al interpretar la especificidad del modelo.

![Curva ROC](../floodpulse-validation/roc_curve.png)

## Pendiente (HackTech El Niño 2026)
- [x] Corregir `sys.excepthook` para el modelo WhiteboxTools en Windows.
- [x] Reemplazar usos de funciones obsoletas como `.unary_union`.
- [ ] Integrar el umbral óptimo en los repositorios Frontend y Alerts (`alert_threshold`).
- [ ] Definir el sector final para la demo del sábado (sugerido: Ajaví o Monte Sinaí).
