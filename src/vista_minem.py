"""
vista_minem.py

Dashboard de la Cartera de Proyectos de Inversión Minera (CPIM) del MINEM:
filtros por empresa/operador, proyecto, estado (etapa de avance), tipo de
proyecto, mineral y año, más gráficos de cantidad de proyectos por año y
por mineral.

Lee data/minem_cpim/proyectos_mineros_wide.csv (y su version en formato
largo), generados por src/minem_construir_datos.py a partir de la Cartera
de Proyectos de Inversión Minera 2025 (MINEM, actualización octubre 2025).
"""

import io
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ / "src") not in sys.path:
    sys.path.insert(0, str(RAIZ / "src"))

CARPETA = RAIZ / "data" / "minem_cpim"
ARCHIVO_WIDE = CARPETA / "proyectos_mineros_wide.csv"
ARCHIVO_LONG = CARPETA / "proyectos_mineros_long.csv"


def _disponible() -> bool:
    return ARCHIVO_WIDE.exists() and ARCHIVO_LONG.exists()


@st.cache_data(show_spinner=False)
def _cargar_wide() -> pd.DataFrame:
    df = pd.read_csv(ARCHIVO_WIDE)
    for col in ["anio_inicio_ejecucion", "anio_fin_ejecucion", "anio_puesta_marcha"]:
        df[col] = df[col].astype("Int64")
    return df


@st.cache_data(show_spinner=False)
def _cargar_long() -> pd.DataFrame:
    return pd.read_csv(ARCHIVO_LONG)


@st.cache_data(show_spinner=False)
def _exportar_bytes(df: pd.DataFrame, formato: str) -> bytes:
    buffer = io.BytesIO()
    if formato == "csv":
        df.to_csv(buffer, index=False, encoding="utf-8")
    elif formato == "xlsx":
        df.to_excel(buffer, index=False)
    else:
        raise ValueError(formato)
    return buffer.getvalue()


def render():
    st.title("Cartera de Proyectos de Inversión Minera — MINEM")
    st.caption(
        "Proyectos mineros en cartera (actualización octubre 2025) + potenciales "
        "para la Cartera de Inversión Minera 2026 -- transcrito del informe oficial "
        "del Ministerio de Energía y Minas. Los campos sin información reportada "
        "quedan en blanco (NaN)."
    )

    if not _disponible():
        st.error(
            "No se encontraron los datos procesados. Corre:\n\n"
            "```\npython src/minem_construir_datos.py\n```"
        )
        return

    df = _cargar_wide()

    st.divider()
    st.subheader("1. Filtros")

    c1, c2, c3 = st.columns(3)
    with c1:
        empresas = st.multiselect("Empresa / operador", options=sorted(df["operador"].dropna().unique()))
    with c2:
        proyectos = st.multiselect("Proyecto", options=sorted(df["proyecto"].unique()))
    with c3:
        minerales = st.multiselect("Mineral", options=sorted(df["mineral_principal"].dropna().unique()))

    c4, c5, c6 = st.columns(3)
    with c4:
        estados = st.multiselect("Estado del proyecto (etapa de avance)", options=sorted(df["etapa_avance"].dropna().unique()))
    with c5:
        tipos = st.multiselect("Tipo de proyecto", options=sorted(df["tipo_proyecto"].dropna().unique()))
    with c6:
        departamentos = st.multiselect("Departamento", options=sorted(df["departamento"].dropna().unique()))

    anios_disponibles = sorted(
        set(df["anio_inicio_ejecucion"].dropna().tolist())
        | set(df["anio_fin_ejecucion"].dropna().tolist())
        | set(df["anio_puesta_marcha"].dropna().tolist())
    )
    if anios_disponibles:
        anio_min, anio_max = int(min(anios_disponibles)), int(max(anios_disponibles))
        rango_anios = st.slider(
            "Año (inicio ejecución, fin ejecución o puesta en marcha dentro del rango)",
            min_value=anio_min, max_value=anio_max, value=(anio_min, anio_max),
        )
    else:
        rango_anios = None

    mask = pd.Series(True, index=df.index)
    if empresas:
        mask &= df["operador"].isin(empresas)
    if proyectos:
        mask &= df["proyecto"].isin(proyectos)
    if minerales:
        mask &= df["mineral_principal"].isin(minerales)
    if estados:
        mask &= df["etapa_avance"].isin(estados)
    if tipos:
        mask &= df["tipo_proyecto"].isin(tipos)
    if departamentos:
        mask &= df["departamento"].isin(departamentos)
    # Solo se aplica el filtro de año si el usuario movió el slider de su
    # rango completo por defecto (que equivale a "sin filtro" -- incluye
    # tambien los proyectos sin ningun año definido, los "P.D.").
    if rango_anios and rango_anios != (anio_min, anio_max):
        en_rango = (
            df["anio_inicio_ejecucion"].between(*rango_anios)
            | df["anio_fin_ejecucion"].between(*rango_anios)
            | df["anio_puesta_marcha"].between(*rango_anios)
        )
        mask &= en_rango

    filtrado = df[mask]

    st.success(f"{len(filtrado)} proyectos encontrados -- CAPEX total: US$ {filtrado['capex_musd'].sum():,.0f} millones")
    st.dataframe(filtrado, width="stretch", hide_index=True)

    st.divider()
    st.subheader("2. Descargas")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.download_button(
            "⬇️ CSV (wide)", data=_exportar_bytes(filtrado, "csv"), file_name="proyectos_mineros_filtrado.csv",
            mime="text/csv", width="stretch",
        )
    with c2:
        st.download_button(
            "⬇️ Excel (wide)", data=_exportar_bytes(filtrado, "xlsx"), file_name="proyectos_mineros_filtrado.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch",
        )
    with c3:
        long_filtrado = _cargar_long()
        long_filtrado = long_filtrado[long_filtrado["proyecto"].isin(filtrado["proyecto"])]
        st.download_button(
            "⬇️ CSV (formato largo)", data=_exportar_bytes(long_filtrado, "csv"), file_name="proyectos_mineros_long.csv",
            mime="text/csv", width="stretch",
        )

    if filtrado.empty:
        return

    st.divider()
    st.subheader("3. Gráficos")

    g1, g2 = st.columns(2)
    with g1:
        st.markdown("**Cantidad de proyectos por año de puesta en marcha**")
        por_anio = filtrado["anio_puesta_marcha"].dropna().value_counts().sort_index()
        if por_anio.empty:
            st.caption("Ningún proyecto filtrado tiene año de puesta en marcha definido.")
        else:
            st.bar_chart(por_anio)

    with g2:
        st.markdown("**Cantidad de proyectos por mineral**")
        por_mineral = filtrado["mineral_principal"].value_counts()
        st.bar_chart(por_mineral)

    g3, g4 = st.columns(2)
    with g3:
        st.markdown("**Cantidad de proyectos por estado (etapa de avance)**")
        st.bar_chart(filtrado["etapa_avance"].value_counts())
    with g4:
        st.markdown("**CAPEX (US$ millones) por mineral**")
        st.bar_chart(filtrado.groupby("mineral_principal")["capex_musd"].sum().sort_values(ascending=False))

    st.markdown("**CAPEX (US$ millones) por departamento**")
    st.bar_chart(filtrado.groupby("departamento")["capex_musd"].sum().sort_values(ascending=False))
