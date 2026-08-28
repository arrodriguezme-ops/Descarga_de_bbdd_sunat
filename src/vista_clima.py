"""
vista_clima.py

Pantalla para descargar clima diario (temperatura maxima/minima/promedio,
humedad relativa, precipitacion) de NASA POWER para departamentos de Peru.
"""

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ / "src") not in sys.path:
    sys.path.insert(0, str(RAIZ / "src"))

from nasa_power import (  # noqa: E402
    DEPARTAMENTOS_PERU,
    PARAMETROS_DISPONIBLES,
    PRIMER_ANIO_DISPONIBLE,
    descargar_clima_departamento,
)

CARPETA_CLIMA = RAIZ / "data" / "clima_nasa"
CARPETA_CLIMA.mkdir(parents=True, exist_ok=True)

COLOR_POR_ESTADO = {
    "En cola": "#7a7a7a",
    "Descargando": "#2563eb",
    "Completado": "#16a34a",
    "Error": "#dc2626",
}


@st.cache_data(show_spinner=False, ttl=60 * 60 * 24)
def _descargar_cacheado(departamento: str, anio_inicio: int, anio_fin: int, parametros: tuple[str, ...]):
    return descargar_clima_departamento(departamento, anio_inicio, anio_fin, list(parametros))


def render():
    st.title("Clima diario NASA POWER -- Departamentos del Perú")
    st.caption(
        "Fuente: NASA POWER (power.larc.nasa.gov) -- el mismo servicio que usa el "
        "paquete de R 'nasapower', consultado aca directo via su API REST publica "
        "(no requiere API key). Serie diaria por punto (capital de cada departamento)."
    )

    col_a, col_b = st.columns([2, 1])
    with col_a:
        departamentos = st.multiselect(
            "Departamento(s)",
            options=sorted(DEPARTAMENTOS_PERU.keys()),
            default=["Lima"],
        )
    with col_b:
        anio_actual = date.today().year
        anio_inicio, anio_fin = st.slider(
            "Rango de anios",
            min_value=PRIMER_ANIO_DISPONIBLE,
            max_value=anio_actual,
            value=(anio_actual - 5, anio_actual),
        )

    parametros_elegidos = st.multiselect(
        "Variables",
        options=list(PARAMETROS_DISPONIBLES.keys()),
        default=list(PARAMETROS_DISPONIBLES.keys()),
        format_func=lambda k: PARAMETROS_DISPONIBLES[k],
    )

    lanzar = st.button("Descargar datos climaticos", type="primary", width="stretch")

    if "clima_estado" not in st.session_state:
        st.session_state.clima_estado = {}
    if "clima_datos" not in st.session_state:
        st.session_state.clima_datos = None

    placeholder_estado = st.empty()

    def pintar_estado():
        if not st.session_state.clima_estado:
            placeholder_estado.empty()
            return
        filas = [
            {"Departamento": d, "Estado": e["estado"], "Detalle": e.get("mensaje", "")}
            for d, e in st.session_state.clima_estado.items()
        ]
        tabla = pd.DataFrame(filas)

        def color_fila(row):
            color = COLOR_POR_ESTADO.get(row["Estado"], "#7a7a7a")
            return [f"background-color: {color}; color: white"] * len(row)

        placeholder_estado.dataframe(tabla.style.apply(color_fila, axis=1), hide_index=True, width="stretch")

    if lanzar:
        if not departamentos:
            st.error("Elige al menos un departamento.")
            st.stop()
        if not parametros_elegidos:
            st.error("Elige al menos una variable.")
            st.stop()

        st.session_state.clima_estado = {d: {"estado": "En cola"} for d in departamentos}
        pintar_estado()

        partes = []
        for d in departamentos:
            st.session_state.clima_estado[d] = {"estado": "Descargando"}
            pintar_estado()
            try:
                df = _descargar_cacheado(d, int(anio_inicio), int(anio_fin), tuple(parametros_elegidos))
                partes.append(df)
                st.session_state.clima_estado[d] = {"estado": "Completado", "mensaje": f"{len(df)} dias"}
            except Exception as e:
                st.session_state.clima_estado[d] = {"estado": "Error", "mensaje": str(e)}
            pintar_estado()

        if partes:
            consolidado = pd.concat(partes, ignore_index=True)
            st.session_state.clima_datos = consolidado
            st.session_state.clima_parametros = parametros_elegidos
            nombre = f"clima_{'_'.join(departamentos)}_{anio_inicio}_{anio_fin}.csv"
            # OJO: usar to_csv(ruta) directo, no write_text(to_csv(...)) --
            # write_text abre el archivo en modo texto y traduce \n a \r\n en
            # Windows, pero to_csv() ya puede venir con \r\n, y el resultado
            # queda con \r\r\n (fila en blanco intercalada al abrir en Excel).
            consolidado.to_csv(CARPETA_CLIMA / nombre, index=False, encoding="utf-8")
    else:
        pintar_estado()

    datos = st.session_state.clima_datos
    if datos is not None and not datos.empty:
        st.divider()
        st.subheader("Resultado")
        st.dataframe(datos.head(300), width="stretch")

        parametros_para_grafico = st.session_state.get("clima_parametros", list(PARAMETROS_DISPONIBLES.keys()))
        variable_grafico = st.selectbox(
            "Variable a graficar",
            options=[p for p in parametros_para_grafico if p in datos.columns],
            format_func=lambda k: PARAMETROS_DISPONIBLES.get(k, k),
        )
        if variable_grafico:
            pivot = datos.pivot_table(index="fecha", columns="departamento", values=variable_grafico)
            st.line_chart(pivot)

        st.download_button(
            "Descargar CSV",
            data=datos.to_csv(index=False).encode("utf-8"),
            file_name=f"clima_nasa_{anio_inicio}_{anio_fin}.csv",
            mime="text/csv",
            width="stretch",
        )
