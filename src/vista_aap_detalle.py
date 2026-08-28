"""
vista_aap_detalle.py

Dashboard de detalle exhaustivo del sector automotor AAP: todo lo que
aap_construir_detalle(_paralelo).py + aap_construir_bases_finales.py
extraen de los ~79 informes mensuales, mas alla de la serie mensual
principal que ya cubre vista_aap.py -- ventas anuales por segmento,
ventas por marca, tablas de detalle (color/origen/combustible/lujo/
electrificados/creditos/importaciones), mapa regional y series
reconstruidas de graficos sin etiquetar.

Lee data/aap_informes/processed/base_*.parquet y detalle_*.parquet
(almacenamiento en Parquet -- son las bases livianas que se versionan en
el repo; los botones de descarga igual ofrecen CSV/Excel).
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

ARCHIVO_SEGMENTO = CARPETA / "base_ventas_anuales_por_segmento.parquet"
ARCHIVO_MARCA = CARPETA / "base_ventas_por_marca.parquet"
ARCHIVO_MAPA = CARPETA / "detalle_mapa_regional.parquet"
ARCHIVO_LINEAS = CARPETA / "detalle_lineas_no_etiquetadas.parquet"

TABLAS_DETALLE = {
    "Por color": "detalle_tabla_por_color.parquet",
    "Por origen de fabricación": "detalle_tabla_por_origen_fabricacion.parquet",
    "Motos por combustible y cilindrada": "detalle_tabla_motos_combustible_cilindrada.parquet",
    "Segmento de lujo": "detalle_tabla_lujo_por_clase.parquet",
    "Electrificados por tipo de tecnología": "detalle_tabla_electrificados_tipo_tecnologia.parquet",
    "Saldo de créditos vehiculares": "detalle_tabla_saldo_creditos_vehiculares.parquet",
    "Importación de suministros": "detalle_tabla_importacion_suministros.parquet",
}


@st.cache_data(show_spinner=False)
def _cargar(ruta: Path) -> pd.DataFrame:
    if not ruta.exists():
        return pd.DataFrame()
    return pd.read_parquet(ruta)


@st.cache_data(show_spinner=False)
def _exportar_bytes(df: pd.DataFrame, formato: str) -> bytes:
    buffer = io.BytesIO()
    if formato == "csv":
        df.to_csv(buffer, index=False, encoding="utf-8-sig")
    else:
        df.to_excel(buffer, index=False)
    return buffer.getvalue()


def _boton_descarga(df: pd.DataFrame, nombre_base: str, key: str):
    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "⬇️ CSV", data=_exportar_bytes(df, "csv"), file_name=f"{nombre_base}.csv",
            mime="text/csv", width="stretch", key=f"{key}_csv",
        )
    with c2:
        st.download_button(
            "⬇️ Excel", data=_exportar_bytes(df, "xlsx"), file_name=f"{nombre_base}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch", key=f"{key}_xlsx",
        )


def render():
    st.title("Sector automotor AAP — Detalle exhaustivo")
    st.caption(
        "Todo lo demás que traen los informes mensuales de AAP además de la serie principal "
        "(ver 'Sector Automotor AAP'): ventas anuales por segmento, ranking por marca, tablas "
        "por color/origen/combustible/lujo/electrificados/créditos/importaciones, mapa "
        "regional y reconstrucción de gráficos de línea sin cada punto etiquetado. Solo los "
        "informes desde ~2022 en adelante (formato \"revista\" de 46-77 páginas) traen estas "
        "secciones -- 2020-2021 son documentos cortos sin esto."
    )

    if not ARCHIVO_SEGMENTO.exists():
        st.error(
            "No se encontraron las bases de detalle. Corre, en este orden:\n\n"
            "```\npython src/aap_construir_detalle_paralelo.py\n"
            "python src/aap_construir_bases_finales.py\n```"
        )
        return

    # ------------------------------------------------------------------
    st.divider()
    st.subheader("1. Ventas anuales por segmento")
    st.caption(
        "\"A [mes] de cada año\": para años completos es el total anual; para el año del "
        "informe (columna mes_corte_informe) es acumulado enero-a-ese-mes, no año completo."
    )

    df_seg = _cargar(ARCHIVO_SEGMENTO)
    if df_seg.empty:
        st.info("Sin datos.")
    else:
        c1, c2 = st.columns(2)
        with c1:
            categorias = sorted(df_seg["categoria_padre"].unique())
            cat_sel = st.multiselect("Categoría", options=categorias, default=categorias, key="seg_cat")
        with c2:
            segmentos_disp = sorted(df_seg[df_seg["categoria_padre"].isin(cat_sel)]["segmento"].unique())
            seg_sel = st.multiselect("Segmento", options=segmentos_disp, default=segmentos_disp, key="seg_seg")

        filt = df_seg[df_seg["categoria_padre"].isin(cat_sel) & df_seg["segmento"].isin(seg_sel)]
        if filt.empty:
            st.info("Sin datos para ese filtro.")
        else:
            pivot = filt.pivot_table(index="anio_dato", columns="segmento", values="unidades")
            st.line_chart(pivot)
            with st.expander("Ver tabla"):
                st.dataframe(filt.sort_values(["categoria_padre", "segmento", "anio_dato"]), width="stretch", hide_index=True)
            _boton_descarga(filt, "aap_ventas_por_segmento", "seg")

    # ------------------------------------------------------------------
    st.divider()
    st.subheader("2. Ventas por marca")

    df_marca = _cargar(ARCHIVO_MARCA)
    if df_marca.empty:
        st.info("Sin datos.")
    else:
        c1, c2, c3 = st.columns(3)
        with c1:
            cat_marca = st.selectbox("Categoría", options=sorted(df_marca["categoria"].unique()), key="marca_cat")
        anios_disp = sorted(df_marca[df_marca["categoria"] == cat_marca]["anio"].unique())
        with c2:
            anio_marca = st.selectbox("Año", options=anios_disp, index=len(anios_disp) - 1, key="marca_anio")
        with c3:
            top_n = st.slider("Top N marcas", min_value=5, max_value=30, value=10, key="marca_top")

        filt_marca = df_marca[(df_marca["categoria"] == cat_marca) & (df_marca["anio"] == anio_marca)]
        filt_marca = filt_marca.sort_values("unidades", ascending=False).head(top_n)

        if filt_marca.empty:
            st.info("Sin datos para ese filtro.")
        else:
            st.bar_chart(filt_marca.set_index("marca")["unidades"])
            with st.expander("Ver tabla"):
                st.dataframe(
                    filt_marca[["rank", "marca", "unidades", "var_pct_acum", "part_pct", "informe_fuente"]],
                    width="stretch", hide_index=True,
                )
        _boton_descarga(df_marca, "aap_ventas_por_marca_completo", "marca")

    # ------------------------------------------------------------------
    st.divider()
    st.subheader("3. Tablas de detalle")

    tabla_elegida = st.selectbox("Tabla", options=list(TABLAS_DETALLE.keys()), key="tabla_sel")
    df_tabla = _cargar(CARPETA / TABLAS_DETALLE[tabla_elegida])
    if df_tabla.empty:
        st.info("Sin datos para esta tabla (puede que ninguna edición del rango descargado la traiga).")
    else:
        informes_disp = sorted(df_tabla["informe_fuente"].unique()) if "informe_fuente" in df_tabla.columns else []
        if informes_disp:
            informe_sel = st.selectbox("Informe (edición)", options=["Todos"] + informes_disp[::-1], key="tabla_informe")
            if informe_sel != "Todos":
                df_tabla = df_tabla[df_tabla["informe_fuente"] == informe_sel]
        st.dataframe(df_tabla, width="stretch", hide_index=True)
        _boton_descarga(df_tabla, f"aap_{TABLAS_DETALLE[tabla_elegida].replace('.parquet', '')}", "tabla")
        st.caption(
            "Columnas c0, c1, c2... cuando no tienen nombre propio: se alinean por POSICIÓN "
            "entre ediciones (el texto exacto del encabezado varía levemente entre informes)."
        )

    # ------------------------------------------------------------------
    st.divider()
    st.subheader("4. Ventas por oficina registral (mapa regional)")
    st.caption("Best-effort: cobertura parcial -- no todas las oficinas se logran leer en todas las ediciones.")

    df_mapa = _cargar(ARCHIVO_MAPA)
    if df_mapa.empty:
        st.info("Sin datos.")
    else:
        informes_mapa = sorted(df_mapa["informe_fuente"].unique())
        informe_mapa_sel = st.selectbox("Informe (edición)", options=informes_mapa[::-1], key="mapa_informe")
        filt_mapa = df_mapa[df_mapa["informe_fuente"] == informe_mapa_sel]
        st.dataframe(
            filt_mapa[["oficina_registral", "unidades", "var_pct_anual", "participacion_pct", "seccion"]],
            width="stretch", hide_index=True,
        )
        _boton_descarga(df_mapa, "aap_mapa_regional_completo", "mapa")

    # ------------------------------------------------------------------
    st.divider()
    st.subheader("5. Series reconstruidas (gráficos de línea sin cada punto etiquetado)")
    st.caption(
        "Importaciones, financiamiento, etc. mes a mes -- reconstruidas desde las coordenadas "
        "del trazo del PDF (no hay texto real para esos puntos). **confianza='alta'** solo en "
        "los extremos (donde SÍ hay una etiqueta de texto real); **'baja'** en los meses "
        "intermedios, con error medido de hasta ~20% frente al dato real -- úsalas con cautela."
    )

    df_lineas = _cargar(ARCHIVO_LINEAS)
    if df_lineas.empty:
        st.info("Sin datos.")
    else:
        c1, c2 = st.columns(2)
        with c1:
            solo_alta = st.checkbox("Mostrar solo confianza alta", value=False, key="lineas_alta")
        with c2:
            secciones_disp = sorted(df_lineas["seccion"].unique())
            seccion_lineas = st.multiselect("Sección", options=secciones_disp, default=secciones_disp, key="lineas_seccion")

        filt_lineas = df_lineas[df_lineas["seccion"].isin(seccion_lineas)]
        if solo_alta:
            filt_lineas = filt_lineas[filt_lineas["confianza"] == "alta"]

        if filt_lineas.empty:
            st.info("Sin datos para ese filtro.")
        else:
            with st.expander("Ver tabla"):
                st.dataframe(filt_lineas, width="stretch", hide_index=True)
            _boton_descarga(df_lineas, "aap_lineas_reconstruidas_completo", "lineas")
