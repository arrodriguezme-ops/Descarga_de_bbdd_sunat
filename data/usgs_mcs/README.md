# Base de datos USGS Mineral Commodity Summaries (1996–2026)

Datos extraidos de los 31 informes anuales "Mineral Commodity Summaries" (MCS)
del U.S. Geological Survey (National Minerals Information Center):
https://www.usgs.gov/centers/national-minerals-information-center/mineral-commodity-summaries

## Como regenerar

```bash
python descargar_usgs_minerales.py                 # los 31 anios (1996-2026)
python descargar_usgs_minerales.py --years 2015-2026
python descargar_usgs_minerales.py --years 2026 --force-download --force-text
```

El script descarga los PDFs (`data/usgs_mcs/raw_pdf/`), cachea el texto
extraido pagina por pagina (`data/usgs_mcs/text/`) y escribe las tablas
finales en `data/usgs_mcs/processed/`.

## Archivos de salida (`data/usgs_mcs/processed/`)

Formato **largo/tidy** (una fila = una observacion), pensado para filtrar y
pivotear en pandas/Excel/Power BI en vez de una tabla ancha fija, porque cada
mineral reporta variables distintas (no todos tienen "precio" o "empleo",
por ejemplo).

### `salient_statistics.csv` — la tabla principal (~124,000 filas)
Estadisticas domesticas de EE.UU. por mineral, tal como aparecen en el cuadro
"Salient Statistics—United States" de cada commodity (produccion, importacion,
exportacion, consumo, precio, existencias, empleo, dependencia neta de
importaciones, etc.).

| columna | descripcion |
|---|---|
| `report_year` | anio de edicion del informe MCS (1996-2026) |
| `commodity` | nombre del mineral, tal como aparece en el reporte (ALUMINUM, COPPER, ...) |
| `variable` | nombre de la fila/variable (ej. "Production: Mine, recoverable") |
| `data_year` | anio real al que corresponde el dato (los reportes muestran series de ~5 anios) |
| `estimado` | True si el dato viene marcado como estimado (sufijo "e") |
| `value_raw` | valor tal cual aparece en el PDF (texto, conserva comas, "W", "NA", "—") |
| `value_num` | valor numerico (float) cuando fue posible convertirlo; NaN si es "W" (withheld), "NA", "—", etc. |

### `world_production_reserves.csv` — cuadro mundial por pais (~70,000 filas)
Produccion minera/de refineria y reservas por pais, del cuadro "World (Mine)
Production ... and Reserves" de cada commodity.

| columna | descripcion |
|---|---|
| `report_year`, `commodity` | igual que arriba |
| `country` | pais (incluye la fila "World total (rounded)") |
| `col_header` | nombre de columna reconstruido, ej. "Mine production 2025e", "Reserves" |
| `value_raw`, `value_num` | igual que arriba |

### `commodity_text.csv`
Texto libre por mineral y anio: "Domestic Production and Use", "Events, Trends,
and Issues", "Recycling", "Import Sources", "Substitutes" (util para NLP o
para leer contexto cualitativo).

### `commodities_index.csv`
Que minerales se detectaron en cada edicion del informe y cuantas paginas
ocupo cada uno (util para ver que commodities entraron/salieron del reporte
a lo largo de los anios).

### `usgs_mcs.sqlite`
Las 4 tablas de arriba en una base SQLite (`salient_statistics`,
`world_production_reserves`, `commodity_text`, `commodities_index`) para
consultas SQL directas.

## Ejemplo: pasar a formato ancho (una columna por variable) para un mineral

```python
import pandas as pd
sal = pd.read_csv("data/usgs_mcs/processed/salient_statistics.csv")
cobre = sal[sal.commodity == "COPPER"]
ancho = cobre.pivot_table(index=["report_year", "data_year"], columns="variable", values="value_num")
```

## Limitaciones conocidas

- **1996-1999**: los PDFs originales de la USGS son escaneos con OCR de
  calidad variable. La mayoria de los anios se parsea bien, pero el informe
  **1997** tiene OCR notablemente mas ruidoso (numeros y encabezados de anio
  corrompidos: "19.92" en vez de "1992", etc.), por lo que tiene bastantes
  menos filas que el resto (814 vs ~4,000+ en anios vecinos). Los datos que
  si se extrajeron son confiables; lo que falta es lo que el OCR corrompio.
- El nombre de columna (`col_header`) del cuadro mundial es best-effort: en
  anios donde el encabezado de la tabla no se pudo interpretar queda como
  "value_2024", "col_1", etc. en vez de un nombre descriptivo — el valor en
  si sigue siendo correcto.
- `value_num` queda vacio (NaN) cuando el reporte no publico un numero real:
  "W" = dato retenido por confidencialidad, "NA" = no disponible, "—" = cero
  o no aplica. `value_raw` conserva el texto original en esos casos.
- El PDF de 2006 tuvo que descargarse aparte (el host de USGS cortaba la
  conexion en la corrida automatica); si vuelves a correr todo el pipeline
  y falla de nuevo, corre `python descargar_usgs_minerales.py --years 2006`.
- El split por commodity asume el patron "2 paginas por mineral" que usa la
  USGS en (casi) todos los anios; commodities muy grandes (ej. "Iron and
  Steel") pueden ocupar mas paginas y se agrupan igual porque el encabezado
  se repite en cada pagina.
