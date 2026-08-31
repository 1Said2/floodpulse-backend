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
- **NASA GPM IMERG** (satélite, vía Google Earth Engine): lluvia ya caída,
  calibrada con un factor de corrección distinto por región (Sierra: 1.14x,
  Costa: 5.11x — el satélite subestima mucho más en la costa por el tipo
  de nube).
- **Open-Meteo**: pronóstico futuro (para anticipar antes de que la
  inundación sea visible) y como respaldo histórico cuando IMERG no
  detecta nada (nubes "cálidas" que el satélite no ve bien).
El sistema toma el MÁXIMO entre ambas fuentes calibradas — si quieres
evitar depender de esto durante pruebas locales, usa el parámetro
`rainfall_mm` para forzar un valor manual (ver siguiente sección).

## ¿Necesito configurar Google Earth Engine?
Solo si quieres que el sistema traiga la lluvia automático (modo real/histórico).
Si solo estás probando el dashboard o la lógica de SMS, **usa siempre el
parámetro `rainfall_mm`** en tus pruebas — así el sistema nunca llama a
Earth Engine y no necesitas ninguna cuenta ni configuración. Si en algún
punto quieres probar el modo automático completo, avísame y lo vemos.

## Sectores de referencia validados (para pruebas o demo)
Tenemos 8 eventos reales documentados con lluvia real conocida — útiles
para pasar como `rainfall_mm` en tus pruebas:
- Ajaví, Ibarra: lat 0.35502, lon -78.12463 — 40.8mm (requiere
  `fallback_waterway_coords`, el colector está embovedado)
- Malacatos, Loja: lat -3.994537, lon -79.205415 — 40.0mm
- (el resto de sectores validados están en las notas del equipo — pregúntame
  si necesitas alguno específico)

## Pendiente
- [ ] Confirmar "control negativo" (zona sin riesgo) con coordenadas
      verificadas en OpenStreetMap
- [ ] Terminar de correr los 8 eventos de validación con el nuevo ensamble
      IMERG + Open-Meteo
- [ ] Definir el sector final para la demo del sábado
