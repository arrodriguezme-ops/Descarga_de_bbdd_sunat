"""
ihh_concentracion.py

Motor de calculo de concentracion de mercado (IHH -- Indice de
Herfindahl-Hirschman) y participacion de mercado, generalizado a partir de
un script en R hecho para un caso puntual (Proyecto Manhattan, mercado
electrico) para que funcione con CUALQUIER base de datos: el usuario elige
en la UI que columna es la empresa, cual el grupo economico, cual el
periodo (año) y cuales son las variables de valor (cantidad/produccion,
facturacion, etc.).

Formulas (identicas a las del script original en R):
- Participacion de un grupo en un año = valor_grupo / valor_total_del_mercado_ese_año
- IHH de un año = suma(participacion_i^2) sobre TODOS los grupos de ese año.
  Se reporta en dos escalas: 'ihh' en fraccion (0-1, igual que el R
  original) y 'ihh_x10000' en la escala estandar de competencia (0-10,000,
  multiplicando por 10,000 -- la que usan las agencias de competencia para
  los umbrales de mercado no concentrado / moderado / concentrado).

Fusion (igual que 'metricas_oferta' del R): dado un grupo Adquiriente y un
grupo Objetivo, colapsa todo lo demas en 'Otros' y compara el IHH antes y
despues de fusionar Adquiriente+Objetivo en un solo agente, en el ultimo
año disponible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd


UMBRAL_NO_CONCENTRADO = 1500
UMBRAL_CONCENTRADO = 2500


def interpretar_ihh(ihh_x10000: float) -> str:
    """Clasificacion estandar (umbrales tipicos de agencias de competencia,
    escala 0-10,000)."""
    if ihh_x10000 is None or pd.isna(ihh_x10000):
        return ""
    if ihh_x10000 < UMBRAL_NO_CONCENTRADO:
        return "No concentrado"
    if ihh_x10000 < UMBRAL_CONCENTRADO:
        return "Moderadamente concentrado"
    return "Altamente concentrado"


@dataclass
class ResultadoVista:
    """Resultado de una combinacion (vista de mercado x variable), p.ej.
    'Oferta' x 'Facturacion'."""

    nombre_vista: str
    nombre_variable: str
    tabla_larga: pd.DataFrame  # grupo, anio, valor, participacion
    tabla_ancha: pd.DataFrame  # filas=grupo/Total/IHH, columnas=años
    ihh_por_anio: pd.DataFrame  # anio, ihh, ihh_x10000, interpretacion
    metricas_fusion: Optional[pd.DataFrame] = None
    grupo_adquiriente: Optional[str] = None
    grupo_objetivo: Optional[str] = None


def calcular_participacion(
    df: pd.DataFrame, col_grupo: str, col_anio: str, col_valor: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Agrupa por (año, grupo), calcula participacion de cada grupo dentro
    de cada año, y el IHH de cada año. Devuelve (tabla_larga, ihh_por_anio)."""
    if col_anio == col_grupo:
        raise ValueError(
            f"col_anio y col_grupo no pueden ser la misma columna ('{col_anio}')."
        )
    agrupado = (
        df.groupby([col_anio, col_grupo], as_index=False)[col_valor]
        .sum()
        .rename(columns={col_anio: "anio", col_grupo: "grupo", col_valor: "valor"})
    )
    agrupado["total_anual"] = agrupado.groupby("anio")["valor"].transform("sum")
    agrupado["participacion"] = agrupado["valor"] / agrupado["total_anual"]

    ihh_por_anio = (
        agrupado.groupby("anio")["participacion"]
        .apply(lambda s: (s**2).sum())
        .rename("ihh")
        .reset_index()
    )
    ihh_por_anio["ihh_x10000"] = ihh_por_anio["ihh"] * 10000
    ihh_por_anio["interpretacion"] = ihh_por_anio["ihh_x10000"].apply(interpretar_ihh)

    return agrupado, ihh_por_anio


def tabla_ancha_participacion(tabla_larga: pd.DataFrame, ihh_por_anio: pd.DataFrame) -> pd.DataFrame:
    """Pivotea a formato ancho (una fila por grupo, una columna por año),
    agregando filas de Total e IHH al final -- igual que 'oferta_final' en
    el R original, pero sin colapsar a un solo 'Otros'."""
    participacion_ancha = tabla_larga.pivot_table(
        index="grupo", columns="anio", values="participacion", aggfunc="first"
    )
    valor_ancho = tabla_larga.pivot_table(index="grupo", columns="anio", values="valor", aggfunc="first")

    # Ordenar grupos por participacion promedio descendente (los mas grandes primero)
    orden = participacion_ancha.mean(axis=1).sort_values(ascending=False).index
    participacion_ancha = participacion_ancha.loc[orden]

    total_por_anio = tabla_larga.groupby("anio")["valor"].sum()
    ihh_indexado = ihh_por_anio.set_index("anio")["ihh"]

    fila_total = pd.DataFrame([total_por_anio], index=["Total (valor)"])
    fila_ihh = pd.DataFrame([ihh_indexado], index=["IHH"])

    tabla = pd.concat([participacion_ancha, fila_total, fila_ihh])
    tabla.index.name = "Grupo económico"
    return tabla


def calcular_metricas_fusion(
    tabla_larga: pd.DataFrame,
    grupo_adquiriente: str,
    grupo_objetivo: str,
) -> pd.DataFrame:
    """Replica 'metricas_oferta' del R: colapsa todo lo que no sea
    Adquiriente/Objetivo en 'Otros', y compara el IHH antes/despues de
    fusionar Adquiriente+Objetivo, en el ultimo año disponible."""
    ultimo_anio = tabla_larga["anio"].max()
    datos_ultimo = tabla_larga[tabla_larga["anio"] == ultimo_anio].copy()

    def _agente(g):
        if g == grupo_adquiriente:
            return grupo_adquiriente
        if g == grupo_objetivo:
            return grupo_objetivo
        return "Otros"

    datos_ultimo["agente"] = datos_ultimo["grupo"].apply(_agente)
    colapsado = datos_ultimo.groupby("agente", as_index=False)["valor"].sum()
    colapsado["participacion"] = colapsado["valor"] / colapsado["valor"].sum()
    ihh_pre = (colapsado["participacion"] ** 2).sum()

    colapsado["agente_fusion"] = colapsado["agente"].apply(
        lambda a: "Fusionado" if a in (grupo_adquiriente, grupo_objetivo) else a
    )
    post = colapsado.groupby("agente_fusion", as_index=False)["valor"].sum()
    post["ms"] = post["valor"] / post["valor"].sum()
    ihh_post = (post["ms"] ** 2).sum()

    # IHH promedio en TODOS los años (mismo esquema Adquiriente/Objetivo/Otros)
    tabla_larga_agente = tabla_larga.copy()
    tabla_larga_agente["agente"] = tabla_larga_agente["grupo"].apply(_agente)
    por_anio = tabla_larga_agente.groupby(["anio", "agente"], as_index=False)["valor"].sum()
    por_anio["participacion"] = por_anio["valor"] / por_anio.groupby("anio")["valor"].transform("sum")
    ihh_promedio = por_anio.groupby("anio")["participacion"].apply(lambda s: (s**2).sum()).mean()

    ms_adquiriente_prom = por_anio[por_anio["agente"] == grupo_adquiriente]["participacion"].mean()
    ms_objetivo_prom = por_anio[por_anio["agente"] == grupo_objetivo]["participacion"].mean()
    ms_conjunto_ultimo = colapsado[colapsado["agente"].isin([grupo_adquiriente, grupo_objetivo])][
        "participacion"
    ].sum()

    filas = [
        ("IHH Pre-Fusión (último año)", ihh_pre, ihh_pre * 10000),
        ("IHH Post-Fusión (último año)", ihh_post, ihh_post * 10000),
        ("Variación IHH (último año)", ihh_post - ihh_pre, (ihh_post - ihh_pre) * 10000),
        ("IHH Promedio (todos los años)", ihh_promedio, ihh_promedio * 10000),
        (f"MS {grupo_adquiriente} promedio", ms_adquiriente_prom, None),
        (f"MS {grupo_objetivo} promedio", ms_objetivo_prom, None),
        ("MS Conjunto (último año)", ms_conjunto_ultimo, None),
    ]
    metricas = pd.DataFrame(filas, columns=["Métrica", "Valor (fracción)", "Valor (x10,000)"])
    metricas["Último año"] = ultimo_anio
    return metricas


def calcular_vista(
    df: pd.DataFrame,
    col_grupo: str,
    col_anio: str,
    col_valor: str,
    nombre_vista: str,
    nombre_variable: str,
    grupo_adquiriente: Optional[str] = None,
    grupo_objetivo: Optional[str] = None,
) -> ResultadoVista:
    tabla_larga, ihh_por_anio = calcular_participacion(df, col_grupo, col_anio, col_valor)
    tabla_ancha = tabla_ancha_participacion(tabla_larga, ihh_por_anio)

    metricas_fusion = None
    if grupo_adquiriente and grupo_objetivo:
        metricas_fusion = calcular_metricas_fusion(tabla_larga, grupo_adquiriente, grupo_objetivo)

    return ResultadoVista(
        nombre_vista=nombre_vista,
        nombre_variable=nombre_variable,
        tabla_larga=tabla_larga,
        tabla_ancha=tabla_ancha,
        ihh_por_anio=ihh_por_anio,
        metricas_fusion=metricas_fusion,
        grupo_adquiriente=grupo_adquiriente,
        grupo_objetivo=grupo_objetivo,
    )


# ---------------------------------------------------------------------------
# Modo "3 bases": Base 1 (oferta: empresa/grupo/ID), Base 2 (demanda:
# empresa/grupo/ID) y Base 3 (transacciones: ID oferente x ID demandante x
# producción/ventas x año[/mes]). Replica la estructura del script original
# en R (base_oferta / base_demanda / base, unidas por left_join), pero con
# columnas configurables en vez de hardcodeadas.
# ---------------------------------------------------------------------------
def unir_tres_bases(
    base_oferta_map: pd.DataFrame,
    col_id_oferta: str,
    col_empresa_oferta: str,
    col_grupo_oferta: str,
    base_demanda_map: pd.DataFrame,
    col_id_demanda: str,
    col_empresa_demanda: str,
    col_grupo_demanda: str,
    base_transacciones: pd.DataFrame,
    col_id_oferente_trans: str,
    col_id_demandante_trans: str,
    col_anio_trans: str,
    col_mes_trans: Optional[str] = None,
) -> pd.DataFrame:
    """Une las 3 bases (igual que los left_join del R original) y arma una
    columna 'periodo' (= año si no hay mes, o 'AAAA-MM' si es mensual).
    Devuelve la base de transacciones enriquecida con
    grupo_oferente/grupo_demandante/periodo, lista para agrupar."""

    oferta = base_oferta_map[[col_id_oferta, col_empresa_oferta, col_grupo_oferta]].rename(
        columns={
            col_id_oferta: "_id_oferente",
            col_empresa_oferta: "empresa_oferente",
            col_grupo_oferta: "grupo_oferente",
        }
    )
    demanda = base_demanda_map[[col_id_demanda, col_empresa_demanda, col_grupo_demanda]].rename(
        columns={
            col_id_demanda: "_id_demandante",
            col_empresa_demanda: "empresa_demandante",
            col_grupo_demanda: "grupo_demandante",
        }
    )

    trans = base_transacciones.rename(
        columns={col_id_oferente_trans: "_id_oferente", col_id_demandante_trans: "_id_demandante"}
    )

    unido = trans.merge(oferta, on="_id_oferente", how="left").merge(demanda, on="_id_demandante", how="left")

    if col_mes_trans:
        unido["periodo"] = (
            unido[col_anio_trans].astype(int).astype(str)
            + "-"
            + unido[col_mes_trans].astype(int).astype(str).str.zfill(2)
        )
    else:
        unido["periodo"] = unido[col_anio_trans].astype(int)

    sin_grupo_oferente = unido["grupo_oferente"].isna().sum()
    sin_grupo_demandante = unido["grupo_demandante"].isna().sum()
    if sin_grupo_oferente or sin_grupo_demandante:
        unido.attrs["filas_sin_match"] = {
            "oferente": int(sin_grupo_oferente),
            "demandante": int(sin_grupo_demandante),
        }

    return unido


# ---------------------------------------------------------------------------
# Datos para el grafico de "quiebre": la evolucion historica del IHH, mas un
# punto extra al final donde la linea "con fusion" se separa de la real,
# mostrando el salto hacia el IHH post-fusion simulado.
# ---------------------------------------------------------------------------
def datos_grafico_fork(ihh_por_anio: pd.DataFrame, metricas_fusion: pd.DataFrame) -> pd.DataFrame:
    ihh_por_anio = ihh_por_anio.sort_values("anio")
    ultimo_anio = ihh_por_anio["anio"].max()
    ihh_ultimo_real = ihh_por_anio.loc[ihh_por_anio["anio"] == ultimo_anio, "ihh_x10000"].iloc[0]

    fila_post = metricas_fusion[metricas_fusion["Métrica"].str.contains("Post-Fusión")]
    ihh_post = float(fila_post["Valor (x10,000)"].iloc[0]) if not fila_post.empty else None

    filas = [
        {"periodo": str(a), "escenario": "Histórico (sin fusión)", "ihh_x10000": v}
        for a, v in zip(ihh_por_anio["anio"], ihh_por_anio["ihh_x10000"])
    ]
    if ihh_post is not None:
        etiqueta_fork = f"{ultimo_anio} + fusión"
        # Dos puntos que arrancan del mismo valor real del ultimo año (para
        # que la linea "con fusion" nazca pegada a la real) y saltan al
        # valor simulado post-fusion -- ahi se ve el quiebre entre ambas.
        filas.append({"periodo": str(ultimo_anio), "escenario": "Con fusión (simulado)", "ihh_x10000": ihh_ultimo_real})
        filas.append({"periodo": etiqueta_fork, "escenario": "Con fusión (simulado)", "ihh_x10000": ihh_post})

    return pd.DataFrame(filas)
