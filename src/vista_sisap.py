"""
vista_sisap.py

Dashboard de precios y volúmenes mayoristas SISAP (MIDAGRI): filtros por
mercado, producto, variable y periodo, descarga en CSV/DTA/Parquet (de la
base completa o de la base ya filtrada), y series de tiempo personalizadas.

Lee de data/sisap_parquet/ (dataset Parquet particionado por producto,
generado por src/sisap_convertir_parquet.py a partir del CSV de
descargar_sisap_completo.py) -- mucho más rápido que releer el CSV de ~1 GB
cada vez.
"""

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pyarrow.dataset as ds
import streamlit as st

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ / "src") not in sys.path:
    sys.path.insert(0, str(RAIZ / "src"))

CSV_ORIGEN = RAIZ / "data" / "sisap_mayorista_precios.csv"
CARPETA_PARQUET = RAIZ / "data" / "sisap_parquet"
PARQUET_COMPLETO = RAIZ / "data" / "sisap_parquet_completo.parquet"
CARPETA_EXPORTS = RAIZ / "data" / "sisap_exports"
CARPETA_EXPORTS.mkdir(parents=True, exist_ok=True)

ETIQUETAS_VARIABLE = {
    "precio_max": "Precio máximo",
    "precio_min": "Precio mínimo",
    "precio_prom": "Precio promedio",
    "volumen": "Volumen",
}


def _dataset_disponible() -> bool:
    return CARPETA_PARQUET.exists() and any(CARPETA_PARQUET.iterdir())


@st.cache_resource(show_spinner=False)
def _abrir_dataset():
    return ds.dataset(CARPETA_PARQUET, format="parquet", partitioning="hive")


@st.cache_data(show_spinner=False)
def _metadatos():
    """Lee solo las columnas de catálogo (mercado/producto/fecha), livianas
    de por sí gracias al formato columnar, para armar los filtros."""
    dataset = _abrir_dataset()
    tabla = dataset.to_table(columns=["mercado_codigo", "mercado_nombre", "producto_codigo", "producto_nombre", "fecha"])
    df = tabla.to_pandas()

    mercados = df[["mercado_codigo", "mercado_nombre"]].drop_duplicates().sort_values("mercado_nombre")
    productos = df[["producto_codigo", "producto_nombre"]].drop_duplicates().sort_values("producto_nombre")
    fecha_min = pd.to_datetime(df["fecha"]).min().date()
    fecha_max = pd.to_datetime(df["fecha"]).max().date()
    return mercados, productos, fecha_min, fecha_max


def _to_stata_seguro(df: pd.DataFrame) -> pd.DataFrame:
    """Prepara un dataframe para exportar a .dta: fecha como datetime real,
    nombres de columna validos, sin tipos que Stata no entienda."""
    df = df.copy()
    if "fecha" in df.columns:
        df["fecha"] = pd.to_datetime(df["fecha"])
    df.columns = [str(c)[:32] for c in df.columns]
    return df


@st.cache_data(show_spinner=False)
def _exportar_bytes(df: pd.DataFrame, formato: str) -> bytes:
    import io

    buffer = io.BytesIO()
    if formato == "csv":
        df.to_csv(buffer, index=False, encoding="utf-8")
    elif formato == "parquet":
        df.to_parquet(buffer, index=False, compression="zstd")
    elif formato == "dta":
        df_stata = _to_stata_seguro(df)
        df_stata.to_stata(buffer, write_index=False, version=118)
    else:
        raise ValueError(formato)
    return buffer.getvalue()


def render():
    st.title("Dashboard de precios mayoristas — SISAP (MIDAGRI)")
    st.caption(
        "Precios (máximo, promedio, mínimo) y volumen diario de los mercados "
        "mayoristas de Lima Metropolitana, publicado por MIDAGRI."
    )

    if not _dataset_disponible():
        if CSV_ORIGEN.exists():
            st.warning(
                "Falta convertir el CSV a Parquet (mucho más rápido de leer). Corre:\n\n"
                "`python src/sisap_convertir_parquet.py`"
            )
        else:
            st.error(
                "No se encontró la base de SISAP. Corre primero:\n\n"
                "`python descargar_sisap_completo.py`\n\n"
                "y luego:\n\n`python src/sisap_convertir_parquet.py`"
            )
        return

    mercados, productos, fecha_min, fecha_max = _metadatos()

    st.divider()
    st.subheader("1. Filtros")

    c1, c2 = st.columns(2)
    with c1:
        mercados_elegidos = st.multiselect(
            "Mercado(s)",
            options=mercados["mercado_nombre"].tolist(),
            default=mercados["mercado_nombre"].tolist()[:1],
        )
    with c2:
        productos_elegidos = st.multiselect(
            "Producto(s)",
            options=productos["producto_nombre"].tolist(),
            default=productos["producto_nombre"].tolist()[:1],
        )

    c3, c4 = st.columns(2)
    with c3:
        variables_elegidas = st.multiselect(
            "Variable(s)",
            options=list(ETIQUETAS_VARIABLE.keys()),
            default=list(ETIQUETAS_VARIABLE.keys()),
            format_func=lambda k: ETIQUETAS_VARIABLE[k],
        )
    with c4:
        rango_fechas = st.date_input(
            "Periodo",
            value=(max(fecha_min, date(fecha_max.year - 1, 1, 1)), fecha_max),
            min_value=fecha_min,
            max_value=fecha_max,
        )

    if not (mercados_elegidos and productos_elegidos and variables_elegidas):
        st.info("Elige al menos un mercado, un producto y una variable.")
        return
    if not isinstance(rango_fechas, tuple) or len(rango_fechas) != 2:
        st.info("Elige un rango de fechas (inicio y fin).")
        return

    codigos_mercado = mercados.loc[mercados["mercado_nombre"].isin(mercados_elegidos), "mercado_codigo"].tolist()
    codigos_producto = productos.loc[productos["producto_nombre"].isin(productos_elegidos), "producto_codigo"].tolist()
    fecha_inicio, fecha_fin = rango_fechas

    aplicar = st.button("Aplicar filtro", type="primary", width="stretch")

    if aplicar or "sisap_df_filtrado" in st.session_state:
        if aplicar:
            dataset = _abrir_dataset()
            filtro = (
                ds.field("mercado_codigo").isin(codigos_mercado)
                & ds.field("producto_codigo").isin(codigos_producto)
                & ds.field("variable").isin(variables_elegidas)
                & (ds.field("fecha") >= fecha_inicio.isoformat())
                & (ds.field("fecha") <= fecha_fin.isoformat())
            )
            with st.spinner("Filtrando..."):
                df_filtrado = dataset.to_table(filter=filtro).to_pandas()
            df_filtrado["fecha"] = pd.to_datetime(df_filtrado["fecha"])
            df_filtrado = df_filtrado.sort_values("fecha")
            st.session_state.sisap_df_filtrado = df_filtrado

        df_filtrado = st.session_state.sisap_df_filtrado
        st.success(f"{len(df_filtrado):,} filas encontradas.")
        st.dataframe(df_filtrado.head(200), width="stretch")

        st.divider()
        st.subheader("2. Descargas")

        dc1, dc2 = st.columns(2)
        with dc1:
            st.markdown("**Base filtrada** (según los filtros de arriba)")
            nombre_base = f"sisap_filtrado_{fecha_inicio}_{fecha_fin}"
            for formato, mime, ext in [
                ("csv", "text/csv", "csv"),
                ("parquet", "application/octet-stream", "parquet"),
                ("dta", "application/octet-stream", "dta"),
            ]:
                st.download_button(
                    f"⬇️ {ext.upper()} filtrado",
                    data=_exportar_bytes(df_filtrado, formato),
                    file_name=f"{nombre_base}.{ext}",
                    mime=mime,
                    width="stretch",
                    key=f"descarga_filtrado_{formato}",
                )

        with dc2:
            st.markdown("**Base completa** (~11 millones de filas, todos los mercados/productos/años)")
            st.download_button(
                "⬇️ Parquet completo (rápido, ~20 MB)",
                data=PARQUET_COMPLETO.read_bytes(),
                file_name="sisap_mayorista_completo.parquet",
                mime="application/octet-stream",
                width="stretch",
            )
            st.download_button(
                "⬇️ CSV completo (~1 GB, puede tardar)",
                data=CSV_ORIGEN.read_bytes(),
                file_name="sisap_mayorista_completo.csv",
                mime="text/csv",
                width="stretch",
            )
            ruta_dta_completo = CARPETA_EXPORTS / "sisap_mayorista_completo.dta"
            if ruta_dta_completo.exists():
                st.download_button(
                    "⬇️ DTA completo",
                    data=ruta_dta_completo.read_bytes(),
                    file_name="sisap_mayorista_completo.dta",
                    mime="application/octet-stream",
                    width="stretch",
                )
            else:
                if st.button("Generar DTA completo (puede tardar varios minutos)", width="stretch"):
                    with st.spinner("Generando .dta completo -- esto puede tardar..."):
                        dataset = _abrir_dataset()
                        df_todo = dataset.to_table().to_pandas()
                        df_todo_stata = _to_stata_seguro(df_todo)
                        df_todo_stata.to_stata(ruta_dta_completo, write_index=False, version=118)
                    st.rerun()

        st.divider()
        st.subheader("3. Serie de tiempo personalizada")

        sc1, sc2, sc3 = st.columns(3)
        with sc1:
            variable_serie = st.selectbox(
                "Variable a graficar",
                options=variables_elegidas,
                format_func=lambda k: ETIQUETAS_VARIABLE.get(k, k),
            )
        with sc2:
            agrupar_por = st.selectbox(
                "Separar líneas por", options=["Mercado", "Producto", "Ninguno (una sola línea)"]
            )
        with sc3:
            frecuencia = st.selectbox("Frecuencia", options=["Diaria", "Semanal", "Mensual", "Anual"], index=2)

        agregacion = st.selectbox("Función de agregación", options=["promedio", "máximo", "mínimo", "suma"])
        func_agg = {"promedio": "mean", "máximo": "max", "mínimo": "min", "suma": "sum"}[agregacion]

        datos_serie = df_filtrado[df_filtrado["variable"] == variable_serie].copy()
        if datos_serie.empty:
            st.info("No hay datos para esa variable con los filtros actuales.")
            return

        regla = {"Diaria": "D", "Semanal": "W", "Mensual": "MS", "Anual": "YS"}[frecuencia]
        columna_grupo = {
            "Mercado": "mercado_nombre",
            "Producto": "producto_nombre",
            "Ninguno (una sola línea)": None,
        }[agrupar_por]

        if columna_grupo:
            pivot = (
                datos_serie.set_index("fecha")
                .groupby(columna_grupo)["valor"]
                .resample(regla)
                .agg(func_agg)
                .unstack(level=0)
            )
        else:
            pivot = datos_serie.set_index("fecha")["valor"].resample(regla).agg(func_agg).to_frame("valor")

        st.line_chart(pivot)
        st.caption(f"{ETIQUETAS_VARIABLE.get(variable_serie, variable_serie)} · {agregacion} · frecuencia {frecuencia.lower()}")
