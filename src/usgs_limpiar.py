"""
usgs_limpiar.py

Limpia y normaliza las tablas crudas de USGS Mineral Commodity Summaries
(data/usgs_mcs/processed/*.csv, generadas por descargar_usgs_minerales.py)
para que el dashboard pueda filtrar por año/país/mineral/variable sin
lidiar con el ruido propio de extraer texto de PDFs escaneados durante 30
años de reportes (encabezados de columna que cambian de formato de año en
año, paises con texto pegado, etc).

Genera:
- data/usgs_mcs/processed/world_clean.parquet
    (país x mineral x año x variable x valor -- produccion minera, de
    refineria, de fundicion, reservas, base de reservas)
- data/usgs_mcs/processed/salient_clean.parquet
    (indicadores de EE.UU. por mineral x año x variable -- precio,
    importaciones, exportaciones, consumo, empleo, etc.)

Correr:
    python src/usgs_limpiar.py
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz, process

RAIZ = Path(__file__).resolve().parent.parent
CARPETA = RAIZ / "data" / "usgs_mcs" / "processed"

# Encabezados de columna de la tabla "world_production_reserves" -- cambian
# de formato segun el año del reporte, hay que normalizarlos a
# (variable, año_del_dato). "e" al final = estimado (se descarta la letra,
# no se distingue de dato firme para simplificar).
PATRONES = [
    (re.compile(r"^Mine production\s*(\d{4})e?\.?$", re.I), "Producción minera"),
    (re.compile(r"^Refinery production\s*(\d{4})e?\.?$", re.I), "Producción de refinería"),
    (re.compile(r"^Smelter production\s*(\d{4})e?\.?$", re.I), "Producción de fundición"),
    (re.compile(r"^value\s*(\d{4})e?\.?$", re.I), "Producción (formato antiguo)"),
    (re.compile(r"^Reserves\s*(\d{4})e?\.?$", re.I), "Reservas"),
]
PATRON_RESERVE_BASE = re.compile(r"^Reserve base\.?$", re.I)
PATRON_RESERVES_SIN_ANIO = re.compile(r"^Reserves\.?$", re.I)

# Filas de "país" que en realidad son texto de PDF mal cortado (varios
# numeros pegados al nombre) -- se descartan.
PATRON_PAIS_BASURA = re.compile(r"\d")

AGREGADOS = {"World total", "World total (rounded)", "World total (may be rounded)", "Other countries"}


def _limpiar_nombre_pais_basico(nombre: str) -> str:
    """Primer paso: quita anotaciones de commodity/nota al pie que el PDF
    dejo pegadas al nombre del pais (parentesis, sufijo 'NA NA', comas con
    aclaraciones tipo 'Bolivia, ulexite', caracteres mal decodificados)."""
    n = str(nombre).strip()
    n = n.replace("�", "'")
    n = re.sub(r"\s*NA\s*NA\s*$", "", n)
    n = re.sub(r"\s*\([^)]*\)e?\s*$", "", n).strip()
    n = re.sub(r",\s*[a-z][^,]*$", "", n).strip()
    return n


def _colapsar_variantes(serie: pd.Series, umbral_frecuencia: int = 5, umbral_similitud: int = 90) -> pd.Series:
    """Colapsa variantes ruidosas de texto (sufijos de nota al pie, typos,
    pequeños cambios de redacción entre años) contra el conjunto de valores
    que SI aparecen limpios y frecuentes -- via fuzzy matching (rapidfuzz),
    sin depender de un listado fijo (para no quedar corto con nombres o
    términos legítimos pero poco comunes)."""
    conteo = serie.value_counts()
    confiables = set(conteo[conteo >= umbral_frecuencia].index)

    cache: dict[str, str] = {}

    def _resolver(valor: str) -> str:
        if valor in confiables:
            return valor
        if valor in cache:
            return cache[valor]
        candidato = valor
        # Sufijo 'e' (estimado) pegado sin espacio -- ej. 'Argentinae'
        if valor.endswith("e") and valor[:-1] in confiables:
            candidato = valor[:-1]
        elif confiables:
            mejor = process.extractOne(valor, confiables, scorer=fuzz.ratio)
            if mejor and mejor[1] >= umbral_similitud:
                candidato = mejor[0]
        cache[valor] = candidato
        return candidato

    return serie.map(_resolver)


def normalizar_paises(serie_paises: pd.Series) -> pd.Series:
    basico = serie_paises.map(_limpiar_nombre_pais_basico)
    return _colapsar_variantes(basico, umbral_frecuencia=5, umbral_similitud=90)


def _clasificar_columna(col_header: str, report_year: int) -> tuple[str, int] | tuple[None, None]:
    col_header = str(col_header).strip()
    for patron, nombre in PATRONES:
        m = patron.match(col_header)
        if m:
            return nombre, int(m.group(1))
    if PATRON_RESERVE_BASE.match(col_header):
        return "Base de reservas", report_year
    if PATRON_RESERVES_SIN_ANIO.match(col_header):
        return "Reservas", report_year
    return None, None


def limpiar_world_production() -> pd.DataFrame:
    df = pd.read_csv(CARPETA / "world_production_reserves.csv")
    df = df[df["value_num"].notna()]
    # Paises con digitos pegados = ruido de extraccion de PDF (texto de
    # varias columnas concatenado en una sola celda).
    df = df[~df["country"].astype(str).str.contains(PATRON_PAIS_BASURA, na=False)]

    variables, anios = [], []
    for col_header, report_year in zip(df["col_header"], df["report_year"]):
        var, anio = _clasificar_columna(col_header, report_year)
        variables.append(var)
        anios.append(anio)
    df = df.assign(variable=variables, anio=anios)
    df = df[df["variable"].notna()].copy()
    df["anio"] = df["anio"].astype(int)
    df["country"] = normalizar_paises(df["country"])
    df["es_agregado"] = df["country"].isin(AGREGADOS)

    limpio = df[["anio", "report_year", "commodity", "country", "variable", "value_num", "es_agregado"]].rename(
        columns={"commodity": "mineral", "country": "pais", "value_num": "valor"}
    )
    # Si un mismo (año,mineral,pais,variable) aparece en mas de un reporte
    # (años de reportes distintos citando el mismo año-dato), nos quedamos
    # con el dato del reporte MAS RECIENTE que lo menciona (las revisiones
    # posteriores de USGS suelen corregir cifras preliminares).
    limpio = limpio.sort_values("report_year").drop_duplicates(
        subset=["anio", "mineral", "pais", "variable"], keep="last"
    )
    return limpio.drop(columns="report_year").reset_index(drop=True)


def _limpiar_variable_texto(v: str) -> str:
    """Quita marcas de nota al pie de USGS (numeros pegados a palabras o
    sueltos entre espacios, parentesis con solo numeros) de la etiqueta de
    variable -- quedan bastantes casi-duplicados por diferencias de
    redaccion entre años que no vale la pena perseguir mas."""
    v = str(v).replace("�", "'")
    v = re.sub(r"\(\d+\)", "", v)
    v = re.sub(r"(?<=[a-zA-Z])\d{1,3}(?=[\s,:;]|$)", "", v)
    v = re.sub(r"(?<=\s)\d{1,3}(?=\s)", "", v)
    v = re.sub(r"[\'’]\s*$", "", v)
    v = re.sub(r"^[,:\s]+", "", v)
    v = re.sub(r"\s+", " ", v).strip()
    return v.rstrip(":,")


def limpiar_salient_statistics() -> pd.DataFrame:
    df = pd.read_csv(CARPETA / "salient_statistics.csv")
    df = df[df["value_num"].notna()].copy()
    df = df.rename(columns={"commodity": "mineral", "variable": "variable_raw", "data_year": "anio", "value_num": "valor"})
    df["variable"] = df["variable_raw"].map(_limpiar_variable_texto)
    df = df[df["variable"] != ""]
    # Colapsar casi-duplicados por commodity (la misma variable puede venir
    # redactada un poco distinto de un reporte a otro): threshold mas bajo
    # de frecuencia porque cada serie tiene ~30 años de datos, no cientos.
    df["variable"] = df.groupby("mineral")["variable"].transform(
        lambda s: _colapsar_variantes(s, umbral_frecuencia=3, umbral_similitud=88)
    )
    limpio = df[["anio", "report_year", "mineral", "variable", "valor", "estimado"]].sort_values("report_year")
    limpio = limpio.drop_duplicates(subset=["anio", "mineral", "variable"], keep="last")
    return limpio.drop(columns="report_year").reset_index(drop=True)


def main():
    print("Limpiando world_production_reserves.csv...")
    world = limpiar_world_production()
    ruta_world = CARPETA / "world_clean.parquet"
    world.to_parquet(ruta_world, index=False, compression="zstd")
    print(f"  -> {len(world):,} filas, {world['mineral'].nunique()} minerales, {world['pais'].nunique()} países -> {ruta_world}")

    print("Limpiando salient_statistics.csv...")
    salient = limpiar_salient_statistics()
    ruta_salient = CARPETA / "salient_clean.parquet"
    salient.to_parquet(ruta_salient, index=False, compression="zstd")
    print(f"  -> {len(salient):,} filas, {salient['mineral'].nunique()} minerales, {salient['variable'].nunique()} variables -> {ruta_salient}")


if __name__ == "__main__":
    main()
