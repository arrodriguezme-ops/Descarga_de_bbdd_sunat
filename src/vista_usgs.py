"""
vista_usgs.py

Dashboard de minerales USGS (Mineral Commodity Summaries, 1996-2026):
filtros por mineral / país / variable / año, descarga directa en
CSV/Excel/Parquet de la selección filtrada, serie de tiempo de la
evolución de la variable, y ranking de principales productores.

Lee data/usgs_mcs/processed/world_clean.parquet y salient_clean.parquet,
generados por src/usgs_limpiar.py a partir de lo que baja
descargar_usgs_minerales.py.
"""

import io
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ / "src") not in sys.path:
    sys.path.insert(0, str(RAIZ / "src"))

CARPETA = RAIZ / "data" / "usgs_mcs" / "processed"
ARCHIVO_WORLD = CARPETA / "world_clean.parquet"
ARCHIVO_SALIENT = CARPETA / "salient_clean.parquet"


def _disponible() -> bool:
    return ARCHIVO_WORLD.exists() and ARCHIVO_SALIENT.exists()


@st.cache_data(show_spinner=False)
def _cargar_world() -> pd.DataFrame:
    return pd.read_parquet(ARCHIVO_WORLD)


@st.cache_data(show_spinner=False)
def _cargar_salient() -> pd.DataFrame:
    return pd.read_parquet(ARCHIVO_SALIENT)


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
    st.title("Minerales — USGS Mineral Commodity Summaries")
    st.caption(
        "Producción minera, de refinería y de fundición, reservas y ranking de "
        "productores por país y mineral (1996-2026), más indicadores de EE.UU. "
        "(precio, importaciones, exportaciones, empleo, etc.) — fuente: USGS."
    )

    if not _disponible():
        st.error(
            "No se encontraron los datos procesados. Corre en orden:\n\n"
            "```\npython descargar_usgs_minerales.py\npython src/usgs_limpiar.py\n```"
        )
        return

    world = _cargar_world()

    st.divider()
    st.subheader("1. Filtros — producción mundial y reservas")

    c1, c2 = st.columns(2)
    with c1:
        minerales = st.multiselect(
            "Mineral(es)", options=sorted(world["mineral"].unique()), default=["COPPER"] if "COPPER" in world["mineral"].values else sorted(world["mineral"].unique())[:1],
        )
    with c2:
        incluir_agregados = st.checkbox("Incluir agregados (Mundo total, Otros países)", value=False)
        paises_disponibles = sorted(world.loc[~world["es_agregado"] | incluir_agregados, "pais"].unique())
        paises = st.multiselect("País(es) -- vacío = todos", options=paises_disponibles, default=[])

    c3, c4 = st.columns(2)
    with c3:
        variables = st.multiselect(
            "Variable(s)", options=sorted(world["variable"].unique()), default=["Producción minera"],
        )
    with c4:
        anio_min, anio_max = int(world["anio"].min()), int(world["anio"].max())
        rango_anios = st.slider("Rango de años", min_value=anio_min, max_value=anio_max, value=(max(anio_min, anio_max - 15), anio_max))

    if not minerales or not variables:
        st.info("Elige al menos un mineral y una variable.")
        return

    mask = (
        world["mineral"].isin(minerales)
        & world["variable"].isin(variables)
        & world["anio"].between(rango_anios[0], rango_anios[1])
    )
    if paises:
        mask &= world["pais"].isin(paises)
    elif not incluir_agregados:
        mask &= ~world["es_agregado"]
    filtrado = world[mask]

    st.success(f"{len(filtrado):,} filas encontradas.")
    st.dataframe(filtrado.head(300).sort_values(["mineral", "variable", "anio"]), width="stretch")

    st.divider()
    st.subheader("2. Descargas")
    nombre_base = f"usgs_{'_'.join(m.lower() for m in minerales[:3])}_{rango_anios[0]}_{rango_anios[1]}"
    _botones_descarga(filtrado, nombre_base, "world")

    if filtrado.empty:
        return

    st.divider()
    st.subheader("3. Evolución de la variable")

    variable_grafico = st.selectbox("Variable a graficar", options=variables, key="var_grafico")
    mineral_grafico = st.selectbox("Mineral", options=minerales, key="mineral_grafico") if len(minerales) > 1 else minerales[0]

    datos_serie = filtrado[(filtrado["variable"] == variable_grafico) & (filtrado["mineral"] == mineral_grafico)]
    if datos_serie.empty:
        st.info("No hay datos para esa combinación de mineral/variable en el rango elegido.")
    else:
        top_paises_serie = (
            datos_serie.groupby("pais")["valor"].sum().sort_values(ascending=False).head(10).index.tolist()
        )
        pivot = datos_serie[datos_serie["pais"].isin(top_paises_serie)].pivot_table(
            index="anio", columns="pais", values="valor", aggfunc="sum"
        )
        st.line_chart(pivot)
        st.caption(f"{mineral_grafico.title()} · {variable_grafico} · top 10 países por volumen acumulado en el rango elegido.")

    st.divider()
    st.subheader("4. Principales productores")

    pc1, pc2 = st.columns(2)
    with pc1:
        mineral_rank = st.selectbox("Mineral", options=minerales, key="mineral_rank")
    with pc2:
        variable_rank = st.selectbox("Variable", options=variables, key="variable_rank")

    datos_rank_base = world[(world["mineral"] == mineral_rank) & (world["variable"] == variable_rank) & (~world["es_agregado"])]
    if datos_rank_base.empty:
        st.info("No hay datos de países (sin agregados) para esa combinación.")
    else:
        anio_rank = st.select_slider(
            "Año", options=sorted(datos_rank_base["anio"].unique()), value=int(datos_rank_base["anio"].max())
        )
        datos_rank = datos_rank_base[datos_rank_base["anio"] == anio_rank].sort_values("valor", ascending=False).head(15)
        total_anio = datos_rank_base[datos_rank_base["anio"] == anio_rank]["valor"].sum()
        datos_rank = datos_rank.assign(participacion=datos_rank["valor"] / total_anio) if total_anio else datos_rank

        st.bar_chart(datos_rank.set_index("pais")["valor"])
        tabla_rank = datos_rank[["pais", "valor", "participacion"]].rename(
            columns={"pais": "País", "valor": "Valor", "participacion": "Participación"}
        )
        st.dataframe(
            tabla_rank.style.format({"Valor": "{:,.0f}", "Participación": "{:.1%}"}, na_rep="—"),
            width="stretch", hide_index=True,
        )
        st.caption(f"Top 15 países · {mineral_rank.title()} · {variable_rank} · {anio_rank}")

    st.divider()
    with st.expander("5. Otras variables (indicadores de EE.UU.: precio, comercio exterior, empleo, etc.)"):
        salient = _cargar_salient()
        sc1, sc2 = st.columns(2)
        with sc1:
            mineral_us = st.selectbox("Mineral", options=sorted(salient["mineral"].unique()), key="mineral_us")
        with sc2:
            opciones_var_us = sorted(salient.loc[salient["mineral"] == mineral_us, "variable"].unique())
            variables_us = st.multiselect("Variable(s)", options=opciones_var_us, default=opciones_var_us[:1], key="variables_us")

        if variables_us:
            datos_us = salient[(salient["mineral"] == mineral_us) & (salient["variable"].isin(variables_us))]
            pivot_us = datos_us.pivot_table(index="anio", columns="variable", values="valor", aggfunc="mean")
            st.line_chart(pivot_us)
            st.dataframe(datos_us.sort_values("anio", ascending=False), width="stretch")
            _botones_descarga(datos_us, f"usgs_us_{mineral_us.lower()}", "us")
