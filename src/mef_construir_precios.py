"""
mef_construir_precios.py

Limpia data/BBDD_precios.csv -- la tabla de valores referenciales de
vehículos que publica el MEF (Ministerio de Economía y Finanzas) cada año
(2008-2025), usada para la valoración aduanera/tributaria de vehículos
nuevos y usados -- y la deja lista en Parquet para el dashboard.

Limpieza:
- El CSV viene separado por ";", con BOM UTF-8 y nombres de columna con
  tildes (se normalizan a snake_case sin tildes).
- Trae 4 filas de "nota al pie" coladas como si fueran datos (la
  Categoría Vehicular de esas filas es el texto completo de la nota, ej.
  "1/ Marca y modelos eliminados por la Resolución...") -- se descartan.
- "CAMIONES " (con espacio al final) y "CAMIONES" son la misma categoría
  en años distintos -- se recorta espacio en blanco de todas las
  columnas de texto.
- ~1700 filas no traen Modelo_generación (dato real, solo que el modelo
  no se registró en el año en cuestión) -- se etiquetan como
  "(Sin especificar)" en vez de dejarlas en NaN, para que no rompan los
  filtros multiselect del dashboard.

Genera:
    data/mef_precios_vehiculos.parquet

Correr:
    python src/mef_construir_precios.py
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
ARCHIVO_ORIGEN = RAIZ / "data" / "BBDD_precios.csv"
ARCHIVO_SALIDA = RAIZ / "data" / "mef_precios_vehiculos.parquet"

RENOMBRE_COLUMNAS = {
    "Categoría Vehicular": "categoria_vehicular",
    "Marca": "marca",
    "Modelo_generación": "modelo",
    "precio": "precio",
    "Año": "anio",
}


def main():
    if not ARCHIVO_ORIGEN.exists():
        raise FileNotFoundError(f"No se encontro {ARCHIVO_ORIGEN}")

    df = pd.read_csv(ARCHIVO_ORIGEN, sep=";", encoding="utf-8-sig", dtype=str)
    df.columns = [c.strip() for c in df.columns]
    df = df.rename(columns=RENOMBRE_COLUMNAS)

    for col in ("categoria_vehicular", "marca", "modelo"):
        df[col] = df[col].str.strip()

    # filas de "nota al pie" coladas como datos: la categoria vehicular de
    # esas filas empieza con "N/ " (nota numerada)
    antes = len(df)
    df = df[~df["categoria_vehicular"].str.match(r"^\d/", na=False)].copy()
    print(f"Descartadas {antes - len(df)} filas de nota al pie.")

    df["precio"] = pd.to_numeric(df["precio"], errors="coerce")
    df["anio"] = pd.to_numeric(df["anio"], errors="coerce").astype("Int64")
    df["modelo"] = df["modelo"].fillna("(Sin especificar)")

    antes = len(df)
    df = df.dropna(subset=["precio", "anio", "categoria_vehicular", "marca"])
    if antes != len(df):
        print(f"Descartadas {antes - len(df)} filas con precio/anio/categoria/marca vacios.")

    df = df.sort_values(["anio", "categoria_vehicular", "marca", "modelo"]).reset_index(drop=True)

    ARCHIVO_SALIDA.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(ARCHIVO_SALIDA, index=False, compression="zstd")

    print(f"\n{len(df):,} filas -> {ARCHIVO_SALIDA}")
    print(f"Años: {df['anio'].min()}-{df['anio'].max()}")
    print(f"Categorías: {sorted(df['categoria_vehicular'].unique())}")
    print(f"Marcas: {df['marca'].nunique()}, Modelos: {df['modelo'].nunique()}")


if __name__ == "__main__":
    main()
