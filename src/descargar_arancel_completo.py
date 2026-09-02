"""
descargar_arancel_completo.py

Descarga el Arancel de Aduanas 2022 completo publicado por SUNAT en formato
Excel (todas las subpartidas de todos los capitulos, no solo vehiculos) y lo
deja limpio en un CSV: codigo_subpartida, descripcion, arancel_advalorem.

Fuente oficial:
https://www.sunat.gob.pe/orientacionaduanera/aranceles/2022/naladisa2012-Arancel-2022.xlsx

Genera data/subpartidas_completo.csv, que usa el dashboard (dashboard.py).

Para correrlo (desde la raiz del repo):
    pip install -r requirements.txt
    python src/descargar_arancel_completo.py
"""

import re
from pathlib import Path

import pandas as pd
import requests

URL_ARANCEL = "https://www.sunat.gob.pe/orientacionaduanera/aranceles/2022/naladisa2012-Arancel-2022.xlsx"

RAIZ = Path(__file__).resolve().parent.parent
CARPETA_DATA = RAIZ / "data"
CARPETA_DATA.mkdir(exist_ok=True)

ARCHIVO_LOCAL = CARPETA_DATA / "arancel_2022_completo.xlsx"
ARCHIVO_SALIDA = CARPETA_DATA / "subpartidas_completo.csv"


def descargar_si_hace_falta():
    if not ARCHIVO_LOCAL.exists():
        print(f"Descargando {URL_ARANCEL} ...")
        resp = requests.get(URL_ARANCEL, headers={"User-Agent": "Mozilla/5.0"}, timeout=120)
        resp.raise_for_status()
        ARCHIVO_LOCAL.write_bytes(resp.content)
        print(f"Guardado en {ARCHIVO_LOCAL} ({len(resp.content) / 1024:.0f} KB)")
    else:
        print(f"Usando archivo local ya descargado: {ARCHIVO_LOCAL}")


def main():
    descargar_si_hace_falta()

    # -----------------------------------------------------------------
    # Leer todas las hojas del Excel (el arancel suele venir en una sola
    # hoja larga, pero por si acaso se recorren todas)
    # -----------------------------------------------------------------
    xls = pd.ExcelFile(ARCHIVO_LOCAL, engine="openpyxl")
    print(f"Hojas encontradas: {xls.sheet_names}")

    # Sin asumir fila de encabezado (header=None): estos archivos de
    # gobierno suelen tener titulos/notas antes de la tabla real -- se
    # detecta la fila/columna de inicio de datos automaticamente abajo.
    hojas = {
        nombre: pd.read_excel(xls, sheet_name=nombre, header=None, dtype=str)
        for nombre in xls.sheet_names
    }

    # -----------------------------------------------------------------
    # Detectar, en cada hoja, la columna que contiene el codigo de
    # subpartida (patron de 10 digitos, con o sin puntos: 8703.23.10.00
    # u 8703231000) y la columna de descripcion (texto junto al codigo)
    # -----------------------------------------------------------------
    patron_codigo = re.compile(r"^\d{2,4}(\.\d{2}){0,3}$|^\d{8,10}$")

    partes = []
    for nombre, df in hojas.items():
        print(f"\nHoja '{nombre}': {df.shape[0]} filas x {df.shape[1]} columnas")

        conteo_por_columna = {
            col: df[col].astype(str).str.strip().str.match(patron_codigo).sum()
            for col in df.columns
        }
        if not conteo_por_columna:
            continue
        col_codigo = max(conteo_por_columna, key=conteo_por_columna.get)
        n_match = conteo_por_columna[col_codigo]

        if n_match < 100:
            print(f"  -> Muy pocos codigos detectados ({n_match}), se omite esta hoja.")
            continue

        print(f"  -> Columna de codigo detectada: indice {col_codigo} ({n_match} coincidencias)")

        col_desc = col_codigo + 1 if (col_codigo + 1) in df.columns else None
        col_arancel = col_codigo + 2 if (col_codigo + 2) in df.columns else None

        sub = df[[c for c in [col_codigo, col_desc, col_arancel] if c is not None]].copy()
        nombres_cols = ["codigo_subpartida", "descripcion", "arancel_advalorem"][: sub.shape[1]]
        sub.columns = nombres_cols

        sub["codigo_subpartida"] = sub["codigo_subpartida"].astype(str).str.strip()
        sub = sub[sub["codigo_subpartida"].str.match(patron_codigo)]

        # Normalizar a 10 digitos sin puntos
        sub["codigo_subpartida"] = sub["codigo_subpartida"].str.replace(".", "", regex=False)

        # OJO -- bug real que hacia desaparecer TODOS los capitulos 01-09
        # (animales vivos, carnes, pescados, lacteos, plantas, hortalizas,
        # frutas, cafe/especias) de la base: Excel guarda "0101210000"
        # como el NUMERO 101210000, no como texto -- al pasar por
        # astype(str) el cero inicial se pierde y queda en 9 digitos. Como
        # ningun capitulo real empieza en "00" (no existe capitulo 00),
        # cualquier codigo de 9 digitos en este punto SIEMPRE es un
        # capitulo 01-09 que perdio su cero inicial -- se restaura antes
        # de filtrar por longitud, si no el filtro de abajo los descarta
        # a todos en silencio.
        sub.loc[sub["codigo_subpartida"].str.len() == 9, "codigo_subpartida"] = (
            sub.loc[sub["codigo_subpartida"].str.len() == 9, "codigo_subpartida"].str.zfill(10)
        )
        sub = sub[sub["codigo_subpartida"].str.len() == 10]

        partes.append(sub)

    if not partes:
        raise RuntimeError(
            "No se pudo detectar automaticamente la estructura del Excel. "
            f"Abre '{ARCHIVO_LOCAL}' manualmente, revisa en que fila empieza la "
            "tabla real y que columnas tienen el codigo/descripcion."
        )

    subpartidas_completo = (
        pd.concat(partes, ignore_index=True)
        .drop_duplicates(subset="codigo_subpartida")
        .sort_values("codigo_subpartida")
    )
    subpartidas_completo["descripcion"] = subpartidas_completo["descripcion"].astype(str).str.strip()
    subpartidas_completo = subpartidas_completo[subpartidas_completo["descripcion"].str.len() > 0]

    subpartidas_completo.to_csv(ARCHIVO_SALIDA, index=False, encoding="utf-8")

    print(f"\nListo: {len(subpartidas_completo)} subpartidas guardadas en '{ARCHIVO_SALIDA}'")
    print(subpartidas_completo.head(20))


if __name__ == "__main__":
    main()
