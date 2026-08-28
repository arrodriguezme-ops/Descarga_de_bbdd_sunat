"""
temas.py

Temas de color adicionales para el panel, seleccionables en vivo desde la
barra lateral (ademas del claro/oscuro nativo de Streamlit, que se elige
desde el menu ⋮ > Settings del propio Streamlit).

Streamlit no tiene soporte nativo para mas de un tema personalizado
conmutable en tiempo real -- esto se logra inyectando un bloque <style> que
sobreescribe las variables de color que usa la interfaz, apuntando a los
contenedores estables de Streamlit (stApp, stSidebar, botones, etc.).
"""

from __future__ import annotations

import streamlit as st

TEMAS = {
    "Automático (claro/oscuro de Streamlit)": None,
    "ARRM": {
        "fondo": "#141414",
        "fondo_secundario": "#232323",
        "texto": "#F5F5F0",
        "primario": "#F4C300",  # amarillo
        "borde": "#4A4A4A",     # gris
        "acento": "#2D6CDF",    # azul
        "fondo_input": "#2B2B2B",
    },
    "CE": {
        "fondo": "#FFFFFF",
        "fondo_secundario": "#EEF1F5",
        "texto": "#2B2D42",
        "primario": "#EF233C",  # rojo
        "borde": "#7D8BA3",     # gris azulado claro
        "acento": "#006F96",    # azul petroleo
        "fondo_input": "#F7F8FA",
    },
}


def selector_tema() -> str:
    """Dibuja el selector de tema en la barra lateral y devuelve el
    nombre elegido (persistido en session_state)."""
    opciones = list(TEMAS.keys())
    if "tema" not in st.session_state:
        st.session_state.tema = opciones[0]
    tema = st.selectbox("🎨 Tema", options=opciones, key="tema")
    return tema


def aplicar_tema(nombre_tema: str):
    paleta = TEMAS.get(nombre_tema)
    if paleta is None:
        return

    css = f"""
    <style>
    :root {{
        --arrm-ce-primario: {paleta['primario']};
    }}

    .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {{
        background-color: {paleta['fondo']} !important;
        color: {paleta['texto']} !important;
    }}
    [data-testid="stHeader"] {{
        background-color: {paleta['fondo']} !important;
    }}
    [data-testid="stSidebar"] {{
        background-color: {paleta['fondo_secundario']} !important;
        border-right: 1px solid {paleta['borde']};
    }}
    h1, h2, h3, h4, h5, h6, p, label, span, div, li {{
        color: {paleta['texto']} !important;
    }}

    /* Botones */
    .stButton > button, .stDownloadButton > button {{
        background-color: {paleta['fondo_secundario']} !important;
        color: {paleta['texto']} !important;
        border: 1px solid {paleta['borde']} !important;
    }}
    .stButton > button:hover, .stDownloadButton > button:hover {{
        border-color: {paleta['primario']} !important;
        color: {paleta['primario']} !important;
    }}
    .stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] {{
        background-color: {paleta['primario']} !important;
        color: {paleta['fondo']} !important;
        border: none !important;
    }}

    /* Inputs, selects, uploaders */
    [data-testid="stTextInput"] input,
    [data-testid="stNumberInput"] input,
    [data-baseweb="select"] > div,
    [data-testid="stFileUploaderDropzone"],
    textarea {{
        background-color: {paleta['fondo_input']} !important;
        color: {paleta['texto']} !important;
        border-color: {paleta['borde']} !important;
    }}

    /* Tarjetas / contenedores con borde */
    [data-testid="stContainer"], div[data-testid="stVerticalBlockBorderWrapper"] {{
        border-color: {paleta['borde']} !important;
    }}

    /* Links y elementos activos */
    a, .stTabs [aria-selected="true"] {{
        color: {paleta['acento']} !important;
    }}

    /* Barra de progreso, sliders */
    .stProgress > div > div > div {{
        background-color: {paleta['primario']} !important;
    }}
    </style>
    """
    st.markdown(css, unsafe_allow_html=True)
