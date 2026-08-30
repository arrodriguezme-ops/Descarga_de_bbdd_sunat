"""
temas.py

Temas de color adicionales para el panel, seleccionables en vivo desde la
barra lateral (ademas del claro/oscuro nativo de Streamlit, que por
defecto ahora es oscuro -- ver .streamlit/config.toml -- y tambien se
puede cambiar desde el menu ⋮ > Settings del propio Streamlit).

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
        "fondo": "#000000",
        "fondo_secundario": "#1A1A1A",
        "texto": "#F5F5F0",
        "primario": "#FFD400",          # amarillo
        "borde": "#4A4A4A",             # gris
        "acento": "#FFD400",            # amarillo (antes azul -- pagina mas amarilla)
        "fondo_input": "#1F1F1F",
        "seleccion_fondo": "#3A3A3A",   # chips de multiselect: gris oscuro
        "seleccion_texto": "#FFFFFF",   # ...con texto blanco, legible
        "encabezado_color": "#FFD400",  # titulos/subtitulos en amarillo
    },
    "CE": {
        "fondo": "#FFFFFF",
        "fondo_secundario": "#FBEAEC",  # gris claro con tinte rojo
        "texto": "#2B2D42",
        "primario": "#C81E3A",          # rojo, mas intenso que antes
        "borde": "#B98A90",             # gris rojizo
        "acento": "#006F96",            # azul petroleo (links)
        "fondo_input": "#FBEAEC",
        "seleccion_fondo": "#8C0F26",   # chips de multiselect: rojo oscuro intenso
        "seleccion_texto": "#FFFFFF",   # ...con texto blanco (rojo oscuro -> letra blanca)
        "titulo_fondo": "#8C0F26",      # banda de fondo en titulos: rojo oscuro intenso
        "titulo_texto": "#FFFFFF",      # ...con letra blanca
        "fuente": "Arial, Helvetica, sans-serif",
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

    color_encabezado = paleta.get("encabezado_color", paleta["texto"])
    titulo_fondo = paleta.get("titulo_fondo")
    titulo_texto = paleta.get("titulo_texto", paleta["texto"])
    seleccion_fondo = paleta.get("seleccion_fondo", paleta["fondo_secundario"])
    seleccion_texto = paleta.get("seleccion_texto", paleta["texto"])
    fuente = paleta.get("fuente")

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
    p, label, span, div, li {{
        color: {paleta['texto']} !important;
    }}
    h1, h2, h3, h4, h5, h6 {{
        color: {color_encabezado} !important;
    }}

    /* Divisores (st.divider) y separadores, con el color primario del tema */
    hr {{
        border-color: {paleta['primario']} !important;
        opacity: 0.7;
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
    [data-testid="stDateInputField"],
    [data-testid="stDateInputField"] input,
    [data-baseweb="select"] > div,
    [data-testid="stFileUploaderDropzone"],
    textarea {{
        background-color: {paleta['fondo_input']} !important;
        color: {paleta['texto']} !important;
        border-color: {paleta['borde']} !important;
    }}

    /* Chips de multiselect (mercado/producto/mineral/subpartida elegidos, etc.)
       y opcion resaltada dentro del menu desplegable -- por defecto Streamlit
       los pinta en un rojo que no combina con ningun tema, hay que fijarlos
       a mano para que el contraste alcance para leerlos.
       [data-tag] es el selector real (Streamlit >= 1.50, componentes
       react-aria); [data-baseweb="tag"] se deja como respaldo por si corre
       con una version mas vieja (BaseWeb). */
    [data-testid="stMultiSelectTagsContainer"] [data-tag],
    [data-baseweb="tag"] {{
        background-color: {seleccion_fondo} !important;
        color: {seleccion_texto} !important;
    }}
    [data-testid="stMultiSelectTagsContainer"] [data-tag] span,
    [data-baseweb="tag"] span {{
        color: {seleccion_texto} !important;
    }}
    [data-testid="stMultiSelectTagsContainer"] [data-tag] button svg,
    [data-baseweb="tag"] svg {{
        fill: {seleccion_texto} !important;
    }}
    [data-baseweb="menu"] li[aria-selected="true"] {{
        background-color: {seleccion_fondo} !important;
        color: {seleccion_texto} !important;
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

    if titulo_fondo:
        # Banda de color de fondo en titulos (st.title) y subtitulos
        # (st.subheader) -- va aparte porque pisa la regla generica de
        # h1-h6 de arriba (misma especificidad, pero se define despues).
        st.markdown(
            f"""
            <style>
            h1, h2, h3 {{
                background-color: {titulo_fondo} !important;
                color: {titulo_texto} !important;
                padding: 0.35em 0.6em !important;
                border-radius: 6px;
            }}
            </style>
            """,
            unsafe_allow_html=True,
        )

    if fuente:
        st.markdown(
            f"""
            <style>
            /* :not([data-testid="stIconMaterial"]) -- los iconos de Streamlit
               (flechas, tijeras, etc.) se dibujan con una fuente de iconos
               por ligadura de texto (ej. el span dice literalmente
               "keyboard_double_arrow_left"); forzar Arial ahi rompe el icono
               y se ve el texto crudo en vez del dibujo. */
            .stApp, .stApp *:not([data-testid="stIconMaterial"]) {{
                font-family: {fuente} !important;
            }}
            </style>
            """,
            unsafe_allow_html=True,
        )
