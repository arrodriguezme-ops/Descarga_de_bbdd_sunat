# Descarga_de_bbdd_sunat

Panel en Streamlit con 10 servicios de datos públicos del Perú: importaciones/
exportaciones por subpartida (SUNAT, con búsqueda por texto o por sector/
mercado), clima diario (NASA POWER), concentración de mercado e IHH para
análisis de fusiones, precios mayoristas (SISAP-MIDAGRI), minerales y
producción mundial (USGS), la Cartera de Proyectos de Inversión Minera
(MINEM), herramientas de PDF (conversión a Markdown, OCR, y búsqueda de
normas por palabra clave en reguladores peruanos), estadísticas del sector
automotor (AAP) -- en dos servicios: la serie mensual principal, y un detalle
exhaustivo (por segmento, marca, color, origen, combustible, crédito, mapa
regional) --, y precios referenciales de vehículos (MEF). Además, dos temas
de color propios (ARRM/CE) seleccionables desde la barra lateral.

## Inicio rápido

Requiere Python 3.10+.

```bash
git clone <url-de-este-repo>
cd Descarga_de_bbdd_sunat
pip install -r requirements.txt
streamlit run app.py
```

Con eso ya abre el panel (`http://localhost:8501`) con la pantalla de inicio
y los 10 servicios navegables desde la barra lateral. **Las bases ya
procesadas y livianas SÍ vienen incluidas en el repo** (en Parquet, ~46 MB
en total) -- Sector Automotor AAP, Minerales USGS, Precios SISAP, Cartera
Minera MINEM y Precios de Vehículos MEF abren con datos reales sin correr
nada. Lo que **no** viene
incluido son los datos crudos/intermedios de cada fuente (PDFs originales,
CSVs de ~1 GB, DBF descargados) -- esos son pesados o fáciles de
regenerar, y quedan en `.gitignore`. Si igual quieres regenerar la base de
algún servicio desde cero (por ejemplo, para traer los informes más
recientes de AAP), cada servicio te muestra en pantalla el comando exacto
si no encuentra su archivo. Resumen de qué correr por servicio (todos
opcionales, corre solo los que te interesen):

| Servicio | ¿Trae datos? | Setup para regenerar/actualizar | Tiempo aprox. |
|---|---|---|---|
| 📦 Importaciones SUNAT | No (subpartida a elegir) | `python src/descargar_arancel_completo.py` | ~1 min |
| 🌦️ Clima NASA | No, se descarga al vuelo | *(ninguno)* | -- |
| ⚖️ Concentración (IHH) | No, subes tu propia base | *(ninguno)* | -- |
| 🥬 Precios SISAP | **Sí** (Parquet incluido) | `python descargar_sisap_completo.py`<br>`python src/sisap_convertir_parquet.py` | horas la 1ª vez |
| ⛏️ Minerales USGS | **Sí** (Parquet incluido) | `python descargar_usgs_minerales.py`<br>`python src/usgs_limpiar.py` | ~10 min |
| 🇵🇪 Cartera Minera MINEM | **Sí** (CSV incluido) | `python src/minem_construir_datos.py` | segundos |
| 🗂️ Herramientas de PDF | No aplica | *(ninguno -- pero necesita Tesseract OCR, ver más abajo)* | -- |
| 🚗 Sector Automotor AAP | **Sí** (Parquet incluido) | `python src/aap_construir_base.py` | ~10-15 min (descarga + parseo de ~80 PDF) |
| 🔧 Sector Automotor AAP -- Detalle | **Sí** (Parquet incluido) | `python src/aap_construir_detalle_paralelo.py`<br>`python src/aap_construir_bases_finales.py` | ~5-25 min según núcleos *(requiere haber corrido el de arriba primero)* |
| 🚙 Precios de Vehículos MEF | **Sí** (Parquet incluido) | `python src/mef_construir_precios.py` | segundos *(solo si `data/BBDD_precios.csv` cambia -- no hay scraper, es un archivo fuente fijo)* |

El resto de este documento detalla cada servicio.

### ⚠️ Requisito adicional para "Herramientas de PDF"

La pestaña OCR → PDF necesita el motor **Tesseract OCR** instalado en el
sistema (no es un paquete de Python, es un programa aparte), con el
idioma español agregado.

**Vía automática (Windows, recomendada):**

```powershell
powershell -ExecutionPolicy Bypass -File .\instalar_tesseract_ocr.ps1
```

Instala Tesseract con winget si hace falta, descarga el idioma español,
y configura todo sin necesitar permisos de administrador. Al terminar
**cerrá y volvé a abrir la terminal** (las variables de entorno nuevas
solo las ve una terminal abierta después de correr el script) y ya
podés usar la pestaña.

**Vía manual (o si el script no aplica a tu caso):**

```bash
winget install --id UB-Mannheim.TesseractOCR -e
```

Por defecto Tesseract solo trae el idioma inglés -- para español, bajá
[`spa.traineddata`](https://github.com/tesseract-ocr/tessdata/raw/main/spa.traineddata)
y ponelo en la carpeta `tessdata` de la instalación (normalmente
`C:\Program Files\Tesseract-OCR\tessdata\`, o si no tenés permisos de
administrador para escribir ahí, en cualquier carpeta propia y seteando la
variable de entorno `TESSDATA_PREFIX` a esa carpeta -- copiando también las
subcarpetas `configs/` y `tessconfigs/` de la instalación original).

## Estructura

```
app.py                             # punto de entrada del panel (pantalla de inicio + navegación)
src/
  vista_inicio.py                 # pantalla de inicio (elegir servicio)
  vista_sunat.py                  # servicio 1: importaciones/exportaciones SUNAT (busqueda por texto o por sector)
  vista_clima.py                  # servicio 2: clima diario NASA POWER
  vista_concentracion.py          # servicio 3: concentración de mercado (IHH) / fusiones
  descargar_arancel_completo.py   # descarga el Arancel de Aduanas 2022 completo (todas las subpartidas)
  sunat_scraper.py                # lógica de scraping reutilizable (sesión, consulta, polling, descarga, DBF)
  sisap_scraper.py                # lógica de scraping reutilizable del SISAP (precios mayoristas MIDAGRI)
  nasa_power.py                   # cliente de la API de NASA POWER (clima)
  ihh_concentracion.py            # motor de cálculo de IHH / participación / fusión
  ihh_excel_export.py             # exportador a Excel formateado de los resultados de IHH
  generar_mockup_ihh.py           # genera data/mockup_ihh.xlsx para probar el servicio de IHH
  vista_sisap.py                  # servicio 4: precios mayoristas SISAP (MIDAGRI)
  sisap_convertir_parquet.py      # convierte el CSV de SISAP (~1 GB) a Parquet particionado
  vista_usgs.py                   # servicio 5: minerales USGS (producción/reservas por país)
  usgs_limpiar.py                 # limpia/normaliza los CSV crudos de USGS (paises, variables)
  usgs_mcs/                       # descarga + parseo de los PDF de USGS Mineral Commodity Summaries
  vista_minem.py                  # servicio 6: Cartera de Proyectos de Inversión Minera (MINEM)
  minem_construir_datos.py        # arma la base de proyectos mineros (wide + long) a partir del informe MINEM
  vista_pdf_herramientas.py       # servicio 7: PDF -> Markdown, OCR -> PDF, búsqueda de normas en gob.pe
  pdf_herramientas.py             # conversores PDF->MD (pymupdf4llm) y OCR->PDF (ocrmypdf)
  gobpe_buscador.py                # busca palabras clave en el buscador oficial de normas de gob.pe
  vista_aap.py                    # servicio 8: serie mensual + totales anuales + var.% del sector automotor (AAP)
  aap_scraper.py                  # descubre y descarga los informes mensuales de aap.org.pe
  aap_parser.py                   # extrae serie mensual, resumen por tipo, totales anuales y var.% interanual
  aap_construir_base.py           # orquesta descarga + parseo de todos los informes de AAP (servicio 8)
  vista_aap_detalle.py            # servicio 9: detalle exhaustivo (segmento, marca, color, origen, mapa...)
  aap_tablas_detalle.py           # extractores de "máximo esfuerzo": tablas de grilla, ranking por marca,
                                   #   barras por segmento, mapa regional, líneas sin etiquetar (best-effort)
  aap_construir_detalle.py        # orquesta aap_tablas_detalle.py sobre los ~80 informes (versión secuencial)
  aap_construir_detalle_paralelo.py # misma orquestación, en paralelo (multiprocessing.Pool) -- más rápida
  aap_construir_bases_finales.py  # arma las bases finales limpias del servicio 9 a partir del detalle crudo
  vista_mef_precios.py            # servicio 10: precios referenciales de vehiculos (MEF, 2008-2025)
  mef_construir_precios.py        # limpia data/BBDD_precios.csv y lo deja en Parquet
  temas.py                        # temas de color ARRM / CE seleccionables desde la barra lateral
descargar_sisap_completo.py       # descarga masiva de precios/volúmenes mayoristas del SISAP (MIDAGRI)
descargar_usgs_minerales.py       # descarga y parsea los reportes USGS Mineral Commodity Summaries (1996-2026)
notebooks/
  sunat_importaciones_scraper.ipynb  # descarga masiva (muchas subpartidas x muchos años)
data/                              # se genera solo (CSV, ZIP, DBF descargados, mockup)
```

## 1. Descargar el listado completo de subpartidas

Una sola vez (o cuando SUNAT actualice el arancel):

```bash
python src/descargar_arancel_completo.py
```

Genera `data/subpartidas_completo.csv` con **todas** las subpartidas del
Arancel de Aduanas 2022 (no solo un capítulo), con columnas
`codigo_subpartida`, `descripcion` y `arancel_advalorem`.

## 2. Panel (dashboard): SUNAT, clima y concentración de mercado

```bash
streamlit run app.py
```

Abre una pantalla de inicio con tres servicios:

### 📦 Importaciones / Exportaciones SUNAT

Dos modos para elegir subpartida(s), con **selección múltiple** en ambos
(se lanza una descarga por subpartida, todas corren en paralelo):

- **Por texto o código**: escribe texto libre (ej. `cobre concentrado`) y
  el selector se acota automáticamente a las subpartidas más parecidas por
  similitud de texto; también puedes escribir el código directamente.
- **Por sector / mercado**: elige un Sector (una de las 21 Secciones
  oficiales del Arancel de Aduanas, ej. "Productos Minerales", "Material
  de Transporte") y despues un Subsector (uno de los 98 Capítulos, ej.
  dentro de "Material de Transporte" -> Capítulo 87 "Vehículos
  automóviles..."), y elige varias subpartidas de ese capítulo sin tener
  que saber el código de memoria. La clasificación viene de
  `data/sunat_capitulos_secciones.csv` (extraída del Arancel de Aduanas
  oficial, no es una taxonomía inventada).
- Elige el rango de años y si quieres importaciones o exportaciones, y
  presiona **"Descargar de SUNAT"** -- por cada subpartida elegida, se
  mandan TODAS las solicitudes del rango de años de una sola vez y se
  sondean en conjunto (no una por una), y cada subpartida corre en su
  propio hilo en segundo plano: puedes recargar la página o cerrarla, el
  progreso queda guardado mientras el servidor de Streamlit siga corriendo.
- El panel de la derecha muestra, con colores, el estado de cada
  subpartida x año (en cola, enviando consulta, esperando a SUNAT,
  descargando, completado, sin datos, error) -- SUNAT procesa cada
  requerimiento de forma asíncrona y puede demorar varios minutos.
- Al terminar cada subpartida, se arma su propio CSV consolidado
  descargable.

### 🌦️ Clima diario NASA POWER (departamentos del Perú)

- Elige uno o varios departamentos, el rango de años (desde 1981) y las
  variables (temperatura máx/mín/promedio, humedad relativa,
  precipitación), y descarga la serie diaria directo de la API pública de
  NASA POWER (el mismo servicio que usa el paquete de R `nasapower`, sin
  necesitar ningún paquete extra ni API key).
- Resultado en tabla + gráfico de línea + CSV descargable.

### ⚖️ Concentración de mercado (IHH) / análisis de fusión

Dos modos de carga:

- **Tabla única**: sube una base ya armada (Excel o CSV) y mapea las
  columnas: Año, Empresa, Grupo económico, y una o más variables de valor
  (marcando cada una como Cantidad/Producción o Facturación). Si tu base
  mezcla varias perspectivas (p.ej. oferta y demanda), señala la columna
  que las distingue y se procesan por separado.
- **3 bases (Oferta + Demanda + Transacciones)**: para cuando tienes las
  bases por separado, igual que el script original en R -- Base 1
  (empresas oferentes: empresa / grupo económico / ID), Base 2 (empresas
  o clientes demandantes: empresa / grupo económico / ID) y Base 3
  (transacciones: ID oferente x ID demandante x producción/ventas x
  año[/mes, opcional para datos mensuales]). Se unen automáticamente
  (igual que los `left_join` del R) y arma las vistas de Oferta y Demanda.

En ambos modos, el botón **"🔀 Simular fusión"** viene apagado por defecto:
así solo obtienes participación de mercado e IHH por año (con gráfico de
barras de participación). Si lo prendes, pide el Grupo económico
Adquiriente y el Objetivo (en modo "3 bases", también a qué vista aplica:
Oferta o Demanda), y calcula el IHH pre/post fusión (colapsando todo lo
demás en "Otros"), variación, promedios y participación conjunta -- con un
**gráfico de quiebre**: la evolución histórica del IHH y, en el último año,
una segunda línea que se separa mostrando el salto hacia el IHH simulado
con fusión.

Resultados en pantalla (tablas + gráficos) y en un Excel formateado
descargable (`src/ihh_excel_export.py`). Para probar el servicio sin armar
tu propia base, corre `python src/generar_mockup_ihh.py` (genera
`data/mockup_ihh.xlsx`, un mercado eléctrico ficticio con oferta/demanda,
3 años y 8 grupos económicos, para el modo "Tabla única").

### 🥬 Precios mayoristas SISAP (MIDAGRI)

- Filtra por mercado, producto, variable (precio máx/mín/promedio,
  volumen) y periodo, sobre un dataset Parquet particionado por producto
  (`data/sisap_parquet/`, generado a partir del CSV de
  `descargar_sisap_completo.py` -- ver más abajo) que responde en
  milisegundos aunque la base tenga ~11 millones de filas.
- Descarga en **CSV, DTA (Stata) o Parquet**, tanto de la base filtrada
  como de la base completa.
- Series de tiempo personalizadas: elige la variable, cómo separar las
  líneas (por mercado o producto), la frecuencia (diaria/semanal/mensual/
  anual) y la función de agregación (promedio/máx/mín/suma).

Para generar el dataset Parquet (una vez, o cuando se vuelva a descargar
el SISAP completo):

```bash
python src/sisap_convertir_parquet.py
```

### ⛏️ Minerales USGS (producción mundial, reservas y estadísticas de EE.UU.)

- Filtra por **mineral(es), país(es), variable(s) y rango de años**, sobre
  producción minera/de refinería/de fundición y reservas de 74 minerales en
  ~190 países (1996-2026). Descarga directa en **CSV, Excel o Parquet** de
  la selección filtrada.
- **Evolución de la variable**: gráfico de línea de los top 10 países por
  volumen, para el mineral/variable elegidos.
- **Principales productores**: ranking (gráfico de barras + tabla con
  participación de mercado) de los 15 mayores países productores, para el
  año que elijas.
- Sección aparte con **otras variables** (indicadores de EE.UU. de USGS:
  precio, importaciones, exportaciones, consumo, empleo, etc. por mineral).

Setup (una sola vez):

```bash
python descargar_usgs_minerales.py   # descarga y parsea los PDF de USGS (puede tardar)
python src/usgs_limpiar.py           # normaliza paises/variables ruidosas del parseo de PDF
```

### 🇵🇪 Cartera Minera MINEM (Cartera de Proyectos de Inversión Minera)

- Base de proyectos mineros del Perú a nivel de proyecto (67: los 65 de la
  actualización octubre 2025 + 2 potenciales para la Cartera 2026),
  transcrita del informe oficial del MINEM. Campos: proyecto, operador,
  departamento, mineral principal, etapa de avance (estado), tipo/subtipo
  de proyecto (cuando el informe lo reporta), años de inicio/fin de
  ejecución y de puesta en marcha, y CAPEX (US$ millones) -- **NaN** donde
  el informe no reporta el dato.
- Filtros por **empresa/operador, proyecto, mineral, estado, tipo de
  proyecto, departamento y año**, con descarga en CSV/Excel (formato ancho)
  o CSV en **formato largo** (proyecto, variable, valor).
- Gráficos de cantidad de proyectos por año de puesta en marcha, por
  mineral, por etapa de avance, y de CAPEX por mineral/departamento.

Para regenerar la base (los datos ya están transcritos a mano dentro del
script, a partir del informe "Cartera de Proyectos de Inversión Minera
2025", MINEM, actualización octubre de 2025):

```bash
python src/minem_construir_datos.py
```

### 🗂️ Herramientas de PDF

Tres pestañas:

- **PDF → Markdown**: sube un PDF, lo convierte con `pymupdf4llm` (rápido,
  sin descargar modelos, funciona mejor con PDFs de texto nativo).
- **OCR → PDF**: sube un PDF escaneado (o imagen), le agrega una capa de
  texto seleccionable/buscable con `ocrmypdf` + Tesseract. Detecta PDFs con
  firma digital y por defecto no los toca (hay un check para permitirlo
  igual, si aceptás que la firma quede invalidada).
- **Búsqueda de PDFs en reguladores**: escribe hasta 20 palabras clave y
  busca en el buscador oficial de gob.pe (`gob.pe/busquedas.json`), que
  indexa el texto completo de las normas legales de **cualquier entidad**
  del Estado peruano (ministerios, OSINERGMIN, SBS, INDECOPI,
  municipalidades, etc.) -- no hace falta pre-armar una lista de PDFs.
  Exporta un Excel con el enlace directo de descarga de cada documento, más
  gráficos de coincidencias por palabra clave y por autoridad. Incluye
  también una verificación profunda opcional (descarga cada PDF a un
  temporal, confirma la keyword en el texto con el número de página exacto,
  y borra el temporal -- nunca deja el PDF guardado en disco).

### 🚗 Sector Automotor AAP

Descarga los ~80 informes mensuales de la Asociación Automotriz del Perú
(aap.org.pe) desde 2020 hasta el mes más reciente, y extrae, de la tabla
"Año x Ene..Dic" (la única con formato lo bastante consistente para
parsear de forma confiable en las ~80 ediciones):

- La **serie mensual histórica** (venta de vehículos livianos + pesados,
  por año/mes).
- El **total anual** y el **acumulado al mes del informe** (las 2
  columnas finales de esa misma tabla).
- La **variación % interanual** mes a mes (las filas "Var. %" de la
  misma tabla).
- Los **totales acumulados por tipo de vehículo** (livianos/pesados/
  menores) que cada informe reporta en su resumen ejecutivo.

Filtros por año y tipo de vehículo, gráficos, y descarga de la base
completa o filtrada (CSV/Excel).

```bash
python src/aap_construir_base.py
```

### 🔧 Sector Automotor AAP — Detalle

Segundo servicio, sobre los mismos ~80 PDF: extracción de "máximo esfuerzo"
de todo lo demás que traen los informes desde ~2022 en adelante (formato
"revista" de 46-77 páginas -- 2020-2021 son documentos cortos sin estas
secciones). Cinco tipos de contenido, cada uno con su propia estrategia de
extracción porque el layout de cada uno es distinto:

- **Ventas anuales por segmento** (Automóviles/SW, Camionetas, Pick-up,
  SUV, Camiones y tracto, Minibús/Ómnibus, Motos, Trimotos, Segmento de
  lujo) -- gráficos de barra totalmente etiquetados, se leen por posición
  ordinal contra el eje de años.
- **Ranking por marca**, por categoría (livianos, camiones, tractocamiones,
  minibús/ómnibus, motos, trimotos, electrificados, transferencias de
  seminuevos) -- tarjetas numeradas, se agrupan por proximidad geométrica
  al número de rank.
- **Tablas de detalle** (por color, por origen de fabricación, motos por
  combustible y cilindrada, segmento de lujo, electrificados, saldo de
  créditos vehiculares, importación de suministros) -- tablas de grilla
  reales, alineadas por posición de columna entre ediciones (el texto del
  encabezado varía levemente entre informes).
- **Mapa por oficina registral** -- best-effort, cobertura parcial (cada
  oficina es una caja de texto flotante sobre un mapa).
- **Series de línea reconstruidas** (importaciones, financiamiento mes a
  mes) -- estos gráficos solo traen el primer y último punto con texto
  real; los meses intermedios se reconstruyen desde las coordenadas del
  trazo vectorial del PDF, con columna `confianza` ('alta' solo en los
  extremos, 'baja' -- error medido de hasta ~20% -- en el resto).

Todas las tablas pasan por un filtro de outliers (MAD + rango plausible
por segmento) antes de llegar al panel, para no mostrar números que se
colaron de una etiqueta vecina mal leída.

```bash
python src/aap_construir_detalle_paralelo.py   # o aap_construir_detalle.py (mas lento, sin paralelizar)
python src/aap_construir_bases_finales.py
```

### 🚙 Precios de Vehículos MEF

Tabla de valores referenciales de vehículos que publica el MEF (Ministerio
de Economía y Finanzas) cada año desde 2008 hasta 2025 -- usada para
valoración aduanera y tributaria (no es precio de mercado real, es el
valor de referencia que usa el fisco). A diferencia de los demás
servicios, esta base **no tiene scraper propio**: viene de
`data/BBDD_precios.csv`, un archivo fuente que se agregó directo al repo.

- Filtros por **grupo** (categoría vehicular: A1-A4, camiones, camionetas,
  buses/ómnibus, remolcadores), **marca**, **modelo** y **rango de años**
  -- cada filtro acota las opciones del siguiente (elegir una marca reduce
  la lista de modelos a elegir).
- Gráfico de evolución de precio: se pueden elegir **varios modelos a la
  vez** (hasta 12) para compararlos en la misma línea de tiempo, más un
  gráfico de barras comparando el último año del rango elegido.
- Descarga en CSV, Excel o Parquet, tanto de la base completa (220 mil
  filas) como de la selección filtrada.

```bash
python src/mef_construir_precios.py   # solo si data/BBDD_precios.csv cambia
```

## 3. Descarga masiva (notebook)

Para bajar muchas subpartidas y muchos años de una sola corrida (por
ejemplo, para armar una base histórica), usa
`notebooks/sunat_importaciones_scraper.ipynb`. Reutiliza la misma lógica de
`src/sunat_scraper.py`; la lista de subpartidas de ejemplo es la de
vehículos (capítulos 87.03/87.04/87.11), pero se puede reemplazar por
cualquier lista de códigos de 10 dígitos (por ejemplo, filtrando
`data/subpartidas_completo.csv`).

## 4. Descarga masiva de precios mayoristas (SISAP - MIDAGRI)

Descarga el historial diario completo de precios (máximo, promedio, mínimo)
y volumen de los mercados mayoristas de Lima Metropolitana, publicado en
[SISAP](http://sistemas.midagri.gob.pe/sisap/portal2/mayorista/resumenes/consultar/),
para todos los productos (~70) y todos los mercados (los 7 individuales +
el agregado "Lima Metropolitana"):

```bash
python descargar_sisap_completo.py
```

Genera `data/sisap_mayorista_precios.csv` en formato largo (una fila por
fecha/mercado/producto/variedad/variable). Es **resumible**: cada
combinación producto+mercado ya bajada queda anotada en
`data/sisap_mayorista_manifiesto.csv`, así que si se corta a la mitad basta
con volver a correr el mismo comando.

Opciones útiles:

```bash
# Solo un rango de fechas (por defecto: 01/01/2000 hasta hoy)
python descargar_sisap_completo.py --desde 01/01/2015 --hasta 31/12/2024

# Solo el agregado "Lima Metropolitana", sin desglosar por mercado individual
# (mucho mas rapido -- 1 consulta por producto en vez de 8)
python descargar_sisap_completo.py --solo-agregado

# Reducir la pausa entre requests (por defecto 1 segundo)
python descargar_sisap_completo.py --pausa 0.5
```

La corrida completa (todos los productos x todos los mercados x todo el
histórico) hace varios cientos de consultas y puede demorar más de una
hora la primera vez; las corridas siguientes son casi instantáneas si no
hay combinaciones nuevas por bajar.

## Temas de color

Además del claro/oscuro nativo de Streamlit (menú ⋮ > Settings), la barra
lateral tiene un selector **🎨 Tema** con dos paletas propias del panel:

- **ARRM**: amarillo / negro / gris / gris claro / azul.
- **CE**: rojo (#EF233C) / azul marino (#2B2D42) / grises azulados / azul
  petróleo (#006F96) / turquesa (#30CEBB).

Se implementa inyectando CSS (`src/temas.py`) porque Streamlit no trae
soporte nativo para más de un tema personalizado conmutable en vivo.

## Notas sobre el portal de SUNAT

- El período de consulta debe estar dentro de un mismo año calendario.
- Los parámetros reales de descarga (`fregistro`/`hregistro`) no son la
  fecha/hora visible en la tabla de resultados: se extraen del atributo
  `onclick` de cada enlace de descarga.
- El servidor procesa cada requerimiento de forma asíncrona (puede tardar
  varios minutos), por eso el scraper hace *polling* hasta que el reporte
  queda listo.
- SUNAT usa el estado `Sin Registros` para decir "ya terminé y no hay
  datos" -- es un estado FINAL, el scraper corta el sondeo apenas lo ve
  (antes esperaba los 30 minutos completos del timeout para nada).
- Las conexiones a `aduanet.gob.pe` reintentan automáticamente (con
  backoff) ante hipos pasajeros de red/DNS, vía un adaptador de `requests`
  montado en `nueva_sesion()`.

## Notas sobre el portal SISAP (MIDAGRI)

- El formulario no navega a ninguna parte: el botón "Consultar" dispara un
  POST por AJAX a `resumenes/filtrar` que devuelve un fragmento de HTML (una
  tabla), y eso es lo que replica `sisap_scraper.py` directamente con
  `requests` en vez de manejar un navegador.
- El modo `periodicidad=intervalo` (pestaña "Intervalo de Tiempo") entrega
  una fila por día con datos entre `desde` y `hasta`, sin importar cuántos
  años de por medio, así que no hace falta ir año por año.
- El portal limita el tamaño de la consulta: si el rango de fechas es muy
  amplio responde "Demasiados criterios..."; el scraper lo detecta y parte
  el rango a la mitad recursivamente hasta que cada pedazo entra, así que no
  hace falta adivinar de antemano desde qué año hay datos para cada
  producto.
- `volumen` sólo trae valores reales si se pide un mercado específico -- con
  el agregado `mercado=*` ("Lima Metropolitana") esa columna siempre viene
  vacía.
- La respuesta viene codificada en `ISO-8859-1` (igual que el portal de
  SUNAT), aunque puede mostrarse con tildes rotas en una terminal de Windows
  con otro *code page*; el CSV generado (`utf-8-sig`) queda correcto.

* Actualización 29/07/2026: Encontré BBDD de TV en Perú y páginas con ratings y shares. Serán incluidas próximamente, así como los trims de vehículos.

