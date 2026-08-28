"""
aap_construir_bases_finales.py

Ultimo paso: toma los CSV "detalle_*" que ya produjo
aap_construir_detalle(_paralelo).py -- que son el volcado crudo por
pagina, con ruido y texto de titulo inconsistente entre ediciones -- y
arma las bases finales, LIMPIAS, en los niveles de agregacion que tiene
sentido usar:

- base_ventas_mensual_por_tipo.csv   (=serie_mensual.csv de aap_parser,
                                       ya esta limpia, se copia tal cual)
- base_ventas_anuales_por_segmento.csv  (categoria_padre, segmento,
                                       anio_dato, unidades -- "a <mes> de
                                       cada año" por Automoviles/SW,
                                       Camionetas, SUV, Pick-up, Camiones
                                       y tracto, Minibus/Omnibus, Motos,
                                       Trimotos, Segmento de lujo,
                                       Electrificados)
- base_ventas_por_marca.csv          (categoria_padre, marca, anio,
                                       unidades, rank, var_pct_acum,
                                       part_pct)

Reglas de limpieza (pedidas explicitamente): a nivel segmento/marca solo
deben quedar categorias RECONOCIBLES (con nombre real de segmento o
marca) -- cualquier fila cuyo "titulo" no calce con ningun segmento
conocido se DESCARTA (es resto de titulo de pagina mal detectado, no un
segmento real). Ademas se descartan outliers estadisticos dentro de cada
segmento/categoria (valores que se salen much del rango del resto de esa
misma serie -- normalmente numeros que se colaron de una tabla vecina).

Correr:
    python src/aap_construir_bases_finales.py
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
CARPETA_PROCESADO = RAIZ / "data" / "aap_informes" / "processed"


def _filtrar_outliers_mad(df: pd.DataFrame, columnas_grupo: list[str], columna_valor: str, umbral: float) -> pd.DataFrame:
    """Descarta, dentro de cada grupo (columnas_grupo), las filas cuyo
    valor se aleja demasiado de la mediana del propio grupo -- usa MAD
    (median absolute deviation), mas robusto que desviacion estandar
    frente a los outliers que justamente se quiere detectar. Vectorizado
    con transform() (no .apply() con funcion por grupo, que en pandas
    3.x a veces devuelve columnas de agrupacion inconsistentes)."""
    vals = df[columna_valor].astype(float)
    grp = df.groupby(columnas_grupo)[columna_valor]
    mediana = grp.transform("median")
    mad = (vals - mediana).abs().groupby([df[c] for c in columnas_grupo]).transform("median")
    z = (vals - mediana).abs() / (mad.replace(0, np.nan) * 1.4826)
    mantener = z.isna() | (z < umbral)
    return df[mantener]


def _normalizar(texto: str) -> str:
    """minusculas, sin tildes, solo letras -- para hacer match robusto
    contra variantes de un mismo titulo entre ediciones distintas."""
    texto = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z]", "", texto.lower())


# ---------------------------------------------------------------------
# Base 1: ventas anuales por segmento (a partir de detalle_barras_segmento_anual.csv)
# ---------------------------------------------------------------------

# orden IMPORTA: se evalua de arriba a abajo y se toma el primer match --
# "trimotos" tiene que ir antes que "motos" (si no, "trimotos" tambien
# calzaria con el patron de "motos").
_CANON_SEGMENTOS = [
    (r"^automovile?ssw$|^automoviless?w$", "Automóviles, SW"),
    (r"^camionetas$", "Camionetas"),
    (r"^pickupfurgonetas$", "Pick Up, Furgonetas"),
    (r"^suvtodoterrenos?$", "SUV, Todoterreno"),
    (r"^camionesytracto$", "Camiones y Tracto"),
    (r"^minib[us]smnibus$|^minibusomnibus$|^minibusmnibus$", "Minibús, Ómnibus"),
    (r"^trimotos$", "Trimotos"),
    (r"^motos$", "Motos"),
    (r"^segmentodelujo$|^segmentolujo$", "Segmento de Lujo"),
]

_CANON_CATEGORIA_PADRE = [
    (r"livianos", "Livianos"),
    (r"pesados", "Pesados"),
    (r"menores", "Menores"),
    (r"electrific|electric|hibrid", "Electrificados"),
    (r"lujo", "Lujo"),
]

# el segmento por si solo YA determina la categoria-padre sin ambiguedad
# (un "Camiones y Tracto" siempre es Pesados, nunca Livianos) -- el
# texto de "seccion" no es confiable para esto (paginas mal detectadas
# arrastran el titulo de OTRA seccion), asi que esta tabla tiene
# prioridad sobre _categoria_padre() cuando el segmento es de esta lista.
_SEGMENTO_A_CATEGORIA_FORZADA = {
    "Automóviles, SW": "Livianos", "Camionetas": "Livianos",
    "Pick Up, Furgonetas": "Livianos", "SUV, Todoterreno": "Livianos",
    "Camiones y Tracto": "Pesados", "Minibús, Ómnibus": "Pesados",
    "Motos": "Menores", "Trimotos": "Menores",
}

# rango absoluto plausible por segmento (unidades/año) -- generoso, pero
# pone un techo. Calibrado contra los valores 2017-2026 que verifique a
# mano contra la imagen del PDF (ver conversacion). El filtro MAD por si
# solo no basta: si varias filas "malas" de la misma pagina mal-leida
# caen juntas, quedan como su propio grupo consistente y el MAD no las
# marca -- este techo absoluto es la segunda linea de defensa.
_RANGO_PLAUSIBLE_SEGMENTO = {
    "Automóviles, SW": (2_000, 55_000),
    "Camionetas": (1_000, 26_000),
    "Pick Up, Furgonetas": (500, 32_000),
    "SUV, Todoterreno": (2_000, 90_000),
    "Camiones y Tracto": (500, 22_000),
    "Minibús, Ómnibus": (200, 6_000),
    "Motos": (15_000, 260_000),
    "Trimotos": (15_000, 140_000),
    "Segmento de Lujo": (200, 8_000),
}


def _categoria_padre(seccion: str) -> str:
    n = _normalizar(seccion)
    for patron, nombre in _CANON_CATEGORIA_PADRE:
        if re.search(patron, n):
            return nombre
    return "Sin clasificar"


def construir_ventas_por_segmento() -> pd.DataFrame:
    ruta = CARPETA_PROCESADO / "detalle_barras_segmento_anual.csv"
    if not ruta.exists():
        print(f"  (no existe {ruta.name}, se salta)")
        return pd.DataFrame()
    df = pd.read_csv(ruta, encoding="utf-8-sig", low_memory=False)

    df["_segmento_norm"] = df["subtitulo"].apply(_normalizar)
    segmento_canonico = pd.Series(pd.NA, index=df.index, dtype="object")
    for patron, nombre in _CANON_SEGMENTOS:
        mascara = segmento_canonico.isna() & df["_segmento_norm"].str.match(patron, na=False)
        segmento_canonico[mascara] = nombre
    df["segmento"] = segmento_canonico

    antes = len(df)
    df = df.dropna(subset=["segmento"]).copy()
    print(f"  segmento reconocido: {len(df)} de {antes} filas ({antes - len(df)} descartadas por titulo no reconocido)")

    df["categoria_padre"] = df["seccion"].apply(_categoria_padre)
    # el segmento manda cuando es inequivoco (ver comentario en la tabla)
    forzada = df["segmento"].map(_SEGMENTO_A_CATEGORIA_FORZADA)
    df["categoria_padre"] = forzada.combine_first(df["categoria_padre"])

    # con la categoria-padre ya forzada por segmento, "Camiones y Tracto"
    # / "Minibús, Ómnibus" / "Motos" / "Trimotos" nunca deberian
    # coexistir bajo mas de UNA categoria-padre -- si el segmento no esta
    # en la tabla forzada (los de Livianos "ambiguos": Automoviles/SW,
    # Camionetas, etc. YA estan forzados tambien arriba, asi que en la
    # practica todos los segmentos reconocidos quedan con una sola
    # categoria posible salvo "Segmento de Lujo", que si aplica a mas de
    # un tipo de vehiculo -- ese se deja tal cual venga de "seccion".

    # filtro de outliers: dentro de cada (categoria_padre, segmento), un
    # valor que se sale mucho de la mediana de esa MISMA serie casi
    # siempre es un numero que se colo de una etiqueta vecina (2 valores
    # de barra superpuestos, etc.) -- se usa MAD (median absolute
    # deviation), mas robusto que desviacion estandar para esto.
    antes2 = len(df)
    df = _filtrar_outliers_mad(df, ["categoria_padre", "segmento"], "valor", umbral=6)
    print(f"  filtro MAD: {len(df)} de {antes2} filas")

    # techo/piso absoluto por segmento (segunda linea de defensa, ver
    # comentario en _RANGO_PLAUSIBLE_SEGMENTO)
    antes3 = len(df)
    minimo = df["segmento"].map(lambda s: _RANGO_PLAUSIBLE_SEGMENTO.get(s, (0, float("inf")))[0])
    maximo = df["segmento"].map(lambda s: _RANGO_PLAUSIBLE_SEGMENTO.get(s, (0, float("inf")))[1])
    df = df[(df["valor"] >= minimo) & (df["valor"] <= maximo)]
    print(f"  rango plausible: {len(df)} de {antes3} filas ({antes3 - len(df)} descartadas por fuera de rango esperado)")

    # deduplicar: si varias ediciones reportan el mismo (categoria,
    # segmento, anio_dato), preferir la edicion MAS RECIENTE -- para años
    # pasados el numero deberia ser estable (revision), para el año en
    # curso del informe la edicion mas reciente es la que tiene mas meses
    # acumulados.
    df = df.sort_values("informe_fuente")
    df = df.drop_duplicates(subset=["categoria_padre", "segmento", "anio_dato"], keep="last")

    resultado = df[[
        "categoria_padre", "segmento", "anio_dato", "valor", "informe_fuente", "mes_informe",
    ]].rename(columns={"valor": "unidades", "mes_informe": "mes_corte_informe"})
    resultado = resultado.sort_values(["categoria_padre", "segmento", "anio_dato"]).reset_index(drop=True)
    return resultado


# ---------------------------------------------------------------------
# Base 2: ventas por marca (a partir de detalle_ranking_marca.csv)
# ---------------------------------------------------------------------

_CANON_CATEGORIA_MARCA = [
    (r"transferenci", "Transferencia de seminuevos"),
    (r"tractocamion", "Tractocamiones"),
    (r"camion", "Camiones"),
    (r"minibus|omnibus", "Minibús y Ómnibus"),
    (r"trimoto", "Trimotos"),
    (r"moto", "Motos"),
    (r"electrific|electric|hibrid", "Electrificados"),
    (r"lujo", "Livianos de lujo"),
    (r"pesad", "Pesados"),
    (r"liviano", "Livianos"),
]


def _categoria_marca(seccion: str, subtitulo: str) -> Optional[str]:
    n = _normalizar(f"{seccion} {subtitulo}")
    for patron, nombre in _CANON_CATEGORIA_MARCA:
        if re.search(patron, n):
            return nombre
    return None


def construir_ventas_por_marca() -> pd.DataFrame:
    ruta = CARPETA_PROCESADO / "detalle_ranking_marca.csv"
    if not ruta.exists():
        print(f"  (no existe {ruta.name}, se salta)")
        return pd.DataFrame()
    df = pd.read_csv(ruta, encoding="utf-8-sig", low_memory=False)

    df["categoria"] = df.apply(lambda f: _categoria_marca(f.get("seccion", ""), f.get("subtitulo", "")), axis=1)
    antes = len(df)
    df = df.dropna(subset=["categoria"]).copy()
    # nombre de marca real: al menos 2 letras, no solo simbolos/numeros
    df = df[df["marca"].astype(str).str.replace(r"[^A-Za-zÁÉÍÓÚÑáéíóúñ]", "", regex=True).str.len() >= 2]
    print(f"  categoria reconocida: {len(df)} de {antes} filas ({antes - len(df)} descartadas)")

    # reshape ancho (anio_2019, anio_2020, ...) -> largo (anio, unidades)
    cols_anio = [c for c in df.columns if re.fullmatch(r"anio_20\d{2}", c)]
    id_cols = ["categoria", "marca", "rank", "var_pct_acum", "part_pct", "informe_fuente"]
    largo = df.melt(id_vars=id_cols, value_vars=cols_anio, var_name="anio", value_name="unidades")
    largo["anio"] = largo["anio"].str.replace("anio_", "", regex=False).astype(int)
    largo = largo.dropna(subset=["unidades"])
    largo = largo[largo["unidades"] > 0]

    # marca real (no "col12" ni fragmentos de 1 letra que se colaron)
    largo["_marca_norm"] = largo["marca"].str.strip().str.upper()
    largo = largo[largo["_marca_norm"].str.len() >= 2]

    # outliers dentro de cada (categoria, marca): mismo criterio MAD que
    # en segmentos -- una marca que reporta 100x su propio historico es
    # casi siempre un numero mal leido, no una venta real. Umbral mas
    # laxo (8) que en segmentos: marcas chicas fluctuan mas de un mes a
    # otro y no hay que confundir eso con un error de lectura.
    antes2 = len(largo)
    largo = _filtrar_outliers_mad(largo, ["categoria", "_marca_norm"], "unidades", umbral=8)
    print(f"  filtro de outliers: {len(largo)} de {antes2} filas")

    largo = largo.sort_values("informe_fuente")
    largo = largo.drop_duplicates(subset=["categoria", "_marca_norm", "anio"], keep="last")
    largo = largo.drop(columns="_marca_norm")

    largo = largo.sort_values(["categoria", "anio", "unidades"], ascending=[True, True, False]).reset_index(drop=True)
    return largo


def main():
    print("Construyendo base_ventas_anuales_por_segmento.csv...")
    df_segmento = construir_ventas_por_segmento()
    ruta_segmento = CARPETA_PROCESADO / "base_ventas_anuales_por_segmento.csv"
    df_segmento.to_csv(ruta_segmento, index=False, encoding="utf-8-sig")
    print(f"  -> {len(df_segmento)} filas en {ruta_segmento}\n")

    print("Construyendo base_ventas_por_marca.csv...")
    df_marca = construir_ventas_por_marca()
    ruta_marca = CARPETA_PROCESADO / "base_ventas_por_marca.csv"
    df_marca.to_csv(ruta_marca, index=False, encoding="utf-8-sig")
    print(f"  -> {len(df_marca)} filas en {ruta_marca}\n")

    ruta_mensual_origen = CARPETA_PROCESADO / "serie_mensual.csv"
    if ruta_mensual_origen.exists():
        df_mensual = pd.read_csv(ruta_mensual_origen, encoding="utf-8-sig")
        ruta_mensual = CARPETA_PROCESADO / "base_ventas_mensual_por_tipo.csv"
        df_mensual.to_csv(ruta_mensual, index=False, encoding="utf-8-sig")
        print(f"base_ventas_mensual_por_tipo.csv -> {len(df_mensual)} filas (copiado de serie_mensual.csv)")


if __name__ == "__main__":
    main()
