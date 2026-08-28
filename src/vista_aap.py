"""
vista_aap.py

Dashboard de estadísticas del sector automotor peruano (AAP -- Asociación
Automotriz del Perú): descarga completa de los informes mensuales, filtros
por tipo de vehículo y año, descarga de la base completa o filtrada, y
gráficos.

Lee data/aap_informes/processed/serie_mensual.csv y resumen_por_tipo.csv,
generados por src/aap_construir_base.py.
"""

import io
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ / "src") not in sys.path:
    sys.path.insert(0, str(RAIZ / "src"))

CARPETA = RAIZ / "data" / "aap_informes" / "processed"
ARCHIVO_SERIE = CARPETA / "serie_mensual.csv"
ARCHIVO_RESUMEN = CARPETA / "resumen_por_tipo.csv"
CARPETA_RAW = RAIZ / "data" / "aap_informes" / "raw"


def _disponible() -> bool:
    return ARCHIVO_SERIE.exists()


@st.cache_data(show_spinner=False)
def _cargar_serie() -> pd.DataFrame:
    return pd.read_csv(ARCHIVO_SERIE)


@st.cache_data(show_spinner=False)
def _cargar_resumen() -> pd.DataFrame:
    if not ARCHIVO_RESUMEN.exists():
        return pd.DataFrame()
    return pd.read_csv(ARCHIVO_RESUMEN)


@st.cache_data(show_spinner=False)
def _exportar_bytes(df: pd.DataFrame, formato: str) -> bytes:
    buffer = io.BytesIO()
    if formato == "csv":
        df.to_csv(buffer, index=False, encoding="utf-8")
    else:
        df.to_excel(buffer, index=False)
    return buffer.getvalue()


def render():
    st.title("Sector automotor peruano — AAP")
    st.caption(
        "Ventas mensuales de vehículos nuevos en Perú (livianos + pesados), reportadas "
        "por la Asociación Automotriz del Perú (AAP) en base a SUNARP. Incluye también "
        "los totales acumulados por tipo de vehículo (livianos/pesados/menores) de cada "
        "informe. Fuente: informes mensuales de AAP (aap.org.pe)."
    )

    if not _disponible():
        st.error(
            "No se encontró la base procesada. Corre:\n\n"
            "```\npython src/aap_construir_base.py\n```\n\n"
            "(descarga ~80 PDFs de AAP y los parsea -- tarda unos minutos la primera vez)"
        )
        return

    serie = _cargar_serie()
    resumen = _cargar_resumen()

    st.divider()
    st.subheader("1. Serie mensual — vehículos livianos + pesados")

    anio_min, anio_max = int(serie["anio"].min()), int(serie["anio"].max())
    rango_anios = st.slider("Rango de años", min_value=anio_min, max_value=anio_max, value=(anio_min, anio_max))

    filtrado = serie[serie["anio"].between(*rango_anios)]
    st.success(f"{len(filtrado)} meses -- {filtrado['unidades'].sum():,.0f} unidades vendidas en el rango elegido")

    filtrado_orden = filtrado.assign(periodo=filtrado["anio"].astype(str) + "-" + filtrado["mes"].astype(str).str.zfill(2))
    st.line_chart(filtrado_orden.set_index("periodo")["unidades"])

    st.markdown("**Total anual**")
    st.bar_chart(filtrado.groupby("anio")["unidades"].sum())

    with st.expander("Ver tabla"):
        st.dataframe(filtrado, width="stretch", hide_index=True)

    st.divider()
    st.subheader("2. Totales acumulados por tipo de vehículo (por informe)")

    if resumen.empty:
        st.info("No hay datos de resumen por tipo disponibles.")
    else:
        c1, c2 = st.columns(2)
        with c1:
            tipos = st.multiselect(
                "Tipo de vehículo", options=sorted(resumen["tipo_vehiculo"].unique()),
                default=sorted(resumen["tipo_vehiculo"].unique()),
            )
        with c2:
            anios_resumen = sorted(resumen["anio_informe"].unique())
            anios_filtro = st.multiselect("Año del informe", options=anios_resumen, default=anios_resumen)

        resumen_filtrado = resumen[resumen["tipo_vehiculo"].isin(tipos) & resumen["anio_informe"].isin(anios_filtro)]
        resumen_filtrado = resumen_filtrado.dropna(subset=["unidades_acumuladas_enero_a_mes"])

        if resumen_filtrado.empty:
            st.info("Sin datos para ese filtro.")
        else:
            resumen_filtrado = resumen_filtrado.assign(
                periodo=resumen_filtrado["anio_informe"].astype(str) + "-" + resumen_filtrado["mes_informe"].astype(str).str.zfill(2)
            )
            pivot = resumen_filtrado.pivot_table(index="periodo", columns="tipo_vehiculo", values="unidades_acumuladas_enero_a_mes")
            st.line_chart(pivot)
            st.caption("Unidades acumuladas de enero al mes del informe (no es venta mensual aislada, es acumulado del año).")
            with st.expander("Ver tabla"):
                st.dataframe(resumen_filtrado, width="stretch", hide_index=True)

    st.divider()
    st.subheader("3. Descargas")

    d1, d2 = st.columns(2)
    with d1:
        st.markdown("**Serie filtrada (según el rango de años de arriba)**")
        st.download_button(
            "⬇️ CSV", data=_exportar_bytes(filtrado, "csv"), file_name="aap_serie_mensual_filtrada.csv",
            mime="text/csv", width="stretch",
        )
        st.download_button(
            "⬇️ Excel", data=_exportar_bytes(filtrado, "xlsx"), file_name="aap_serie_mensual_filtrada.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch",
        )
    with d2:
        st.markdown(f"**Base completa** (serie {len(serie)} filas + resumen {len(resumen)} filas)")
        st.download_button(
            "⬇️ CSV serie completa", data=_exportar_bytes(serie, "csv"), file_name="aap_serie_mensual_completa.csv",
            mime="text/csv", width="stretch",
        )
        if not resumen.empty:
            st.download_button(
                "⬇️ CSV resumen por tipo completo", data=_exportar_bytes(resumen, "csv"),
                file_name="aap_resumen_por_tipo_completo.csv", mime="text/csv", width="stretch",
            )

    if CARPETA_RAW.exists() and any(CARPETA_RAW.glob("*.pdf")):
        n_pdfs = len(list(CARPETA_RAW.glob("*.pdf")))
        st.caption(
            f"Los {n_pdfs} PDF originales descargados están en `data/aap_informes/raw/` "
            "(no se suben por Excel/CSV por su tamaño, pero quedan en tu disco para revisar "
            "las tablas de ranking por marca/región/color/origen a mano si las necesitas)."
        )
