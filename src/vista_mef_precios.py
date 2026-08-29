"""
vista_mef_precios.py

Dashboard de precios referenciales de vehículos del MEF (Ministerio de
Economía y Finanzas) -- tabla de valores referenciales publicada
anualmente (2008-2025), usada para valoración aduanera/tributaria de
vehículos. Filtros por grupo (categoría vehicular), marca, modelo y rango
de años; gráficos de evolución de precio (con varios modelos a la vez);
descarga de la base completa o filtrada en CSV/Excel/Parquet.

Lee data/mef_precios_vehiculos.parquet, generado por
src/mef_construir_precios.py a partir de data/BBDD_precios.csv.
"""

import io
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ / "src") not in sys.path:
    sys.path.insert(0, str(RAIZ / "src"))

ARCHIVO_PARQUET = RAIZ / "data" / "mef_precios_vehiculos.parquet"
ARCHIVO_CSV_ORIGEN = RAIZ / "data" / "BBDD_precios.csv"

MAX_MODELOS_GRAFICO = 12  # mas de esto, el grafico de lineas se vuelve ilegible


def _disponible() -> bool:
    return ARCHIVO_PARQUET.exists()


@st.cache_data(show_spinner=False)
def _cargar() -> pd.DataFrame:
    return pd.read_parquet(ARCHIVO_PARQUET)


@st.cache_data(show_spinner=False)
def _exportar_bytes(df: pd.DataFrame, formato: str) -> bytes:
    buffer = io.BytesIO()
    if formato == "csv":
        df.to_csv(buffer, index=False, encoding="utf-8")
    elif formato == "parquet":
        df.to_parquet(buffer, index=False, compression="zstd")
    elif formato == "xlsx":
        df.to_excel(buffer, index=False)
    else:
        raise ValueError(formato)
    return buffer.getvalue()


def _botones_descarga(df: pd.DataFrame, nombre_base: str, key_prefix: str):
    c1, c2, c3 = st.columns(3)
    with c1:
        st.download_button(
            "⬇️ CSV", data=_exportar_bytes(df, "csv"), file_name=f"{nombre_base}.csv",
            mime="text/csv", width="stretch", key=f"{key_prefix}_csv",
        )
    with c2:
        st.download_button(
            "⬇️ Excel", data=_exportar_bytes(df, "xlsx"), file_name=f"{nombre_base}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch", key=f"{key_prefix}_xlsx",
        )
    with c3:
        st.download_button(
            "⬇️ Parquet", data=_exportar_bytes(df, "parquet"), file_name=f"{nombre_base}.parquet",
            mime="application/octet-stream", width="stretch", key=f"{key_prefix}_parquet",
        )


def render():
    st.title("Precios de vehículos — MEF")
    st.caption(
        "Tabla de valores referenciales de vehículos que publica el MEF cada año "
        "(2008-2025), usada para valoración aduanera y tributaria. Un precio de "
        "referencia por grupo/marca/modelo/año -- no es precio de mercado real, "
        "es el valor que usa el fisco como referencia."
    )

    if not _disponible():
        st.error(
            "No se encontraron los datos procesados. Corre:\n\n"
            "`python src/mef_construir_precios.py`"
        )
        return

    df = _cargar()

    st.divider()
    st.subheader("1. Filtros")

    c1, c2 = st.columns(2)
    with c1:
        grupos = st.multiselect(
            "Grupo (categoría vehicular)", options=sorted(df["categoria_vehicular"].unique()),
            default=[], help="Vacío = todos los grupos.",
        )
    with c2:
        base_marca = df[df["categoria_vehicular"].isin(grupos)] if grupos else df
        marcas = st.multiselect(
            "Marca(s)", options=sorted(base_marca["marca"].unique()),
            default=[], help="Vacío = todas las marcas (dentro del grupo elegido, si hay uno).",
        )

    base_modelo = base_marca[base_marca["marca"].isin(marcas)] if marcas else base_marca
    modelos_disponibles = sorted(base_modelo["modelo"].unique())
    if not marcas and len(modelos_disponibles) > 500:
        st.caption(
            f"⚠️ {len(modelos_disponibles):,} modelos disponibles sin filtrar por marca -- "
            "elige una o más marcas arriba para acotar la lista de modelos."
        )
    modelos = st.multiselect(
        "Modelo(s)", options=modelos_disponibles, default=[],
        help="Vacío = todos los modelos (dentro de marca/grupo elegidos, si hay).",
    )

    anio_min, anio_max = int(df["anio"].min()), int(df["anio"].max())
    rango_anios = st.slider(
        "Rango de años", min_value=anio_min, max_value=anio_max, value=(anio_min, anio_max),
    )

    mask = df["anio"].between(rango_anios[0], rango_anios[1])
    if grupos:
        mask &= df["categoria_vehicular"].isin(grupos)
    if marcas:
        mask &= df["marca"].isin(marcas)
    if modelos:
        mask &= df["modelo"].isin(modelos)
    filtrado = df[mask].sort_values(["anio", "categoria_vehicular", "marca", "modelo"])

    st.success(f"{len(filtrado):,} filas encontradas.")
    st.dataframe(
        filtrado.rename(columns={
            "categoria_vehicular": "Grupo", "marca": "Marca", "modelo": "Modelo",
            "precio": "Precio (S/)", "anio": "Año",
        }).head(300),
        width="stretch", hide_index=True,
    )

    st.divider()
    st.subheader("2. Descargas")

    d1, d2 = st.columns(2)
    with d1:
        st.markdown("**Selección filtrada** (según los filtros de arriba)")
        nombre_filtrado = f"mef_precios_filtrado_{rango_anios[0]}_{rango_anios[1]}"
        _botones_descarga(filtrado, nombre_filtrado, "filtrado")
    with d2:
        st.markdown(f"**Base completa** ({len(df):,} filas, {anio_min}-{anio_max}, todos los grupos)")
        _botones_descarga(df, "mef_precios_vehiculos_completo", "completo")

    if filtrado.empty:
        return

    st.divider()
    st.subheader("3. Evolución de precios")
    st.caption("Puedes elegir varios modelos a la vez para compararlos en el mismo gráfico.")

    opciones_grafico = sorted(filtrado["modelo"].unique())
    default_grafico = opciones_grafico[: min(5, len(opciones_grafico))]
    modelos_grafico = st.multiselect(
        f"Modelo(s) a graficar (máximo {MAX_MODELOS_GRAFICO} para que se lea bien)",
        options=opciones_grafico, default=default_grafico, max_selections=MAX_MODELOS_GRAFICO,
        key="modelos_grafico",
    )

    if not modelos_grafico:
        st.info("Elige al menos un modelo para graficar su evolución de precio.")
    else:
        datos_grafico = filtrado[filtrado["modelo"].isin(modelos_grafico)]
        # un mismo (grupo, marca, modelo, año) puede repetirse (variantes sin
        # distinguir, ej. "OTROS MODELOS") -- promedio en vez de sumar
        pivot = datos_grafico.pivot_table(
            index="anio", columns="modelo", values="precio", aggfunc="mean"
        )
        st.line_chart(pivot)
        st.caption(f"Precio referencial promedio (S/) por año · {len(modelos_grafico)} modelo(s).")

        st.markdown("**Comparación del último año disponible en el rango**")
        anio_comparacion = int(datos_grafico["anio"].max())
        comparacion = (
            datos_grafico[datos_grafico["anio"] == anio_comparacion]
            .groupby("modelo")["precio"].mean().sort_values(ascending=False)
        )
        st.bar_chart(comparacion)
        st.caption(f"Precio referencial promedio (S/) en {anio_comparacion}.")
