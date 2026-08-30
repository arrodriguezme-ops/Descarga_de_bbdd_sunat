"""
temas.py

Temas de color adicionales para el panel, seleccionables en vivo desde la
barra lateral (ademas del claro/oscuro nativo de Streamlit, que por
defecto ahora es oscuro -- ver .streamlit/config.toml -- y tambien se
puede cambiar desde el menu ⋮ > Settings del propio Streamlit).

Streamlit no tiene soporte nativo para mas de un tema personalizado
conmutable en tiempo real. La mayoria de los widgets se tematizan
inyectando un bloque <style> que sobreescribe las variables de color que
usa la interfaz (stApp, stSidebar, botones, etc.) -- pero ALGUNOS widgets
(st.dataframe/st.data_editor, que se dibujan sobre un <canvas> con
glide-data-grid) NO leen CSS en absoluto: sus colores salen del tema
NATIVO de Streamlit (theme.backgroundColor, theme.textColor, etc.) que el
frontend recibe una sola vez, al abrir la conexion. Para esos casos se usa
`st.config.set_option("theme.xxx", ...)` (ver `_sincronizar_tema_nativo`)
y se fuerza una recarga real de la pagina cuando el tema elegido cambia
-- un rerun comun de Streamlit no alcanza porque no vuelve a mandar el
tema al frontend, solo una conexion nueva lo hace.
"""

from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

TEMAS = {
    "Automático (claro/oscuro de Streamlit)": None,
    "ARRM": {
        "base": "dark",
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
        "base": "light",
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

# Tema nativo de Streamlit para "Automático" -- los valores por defecto
# reales de Streamlit en modo oscuro (los mismos que .streamlit/config.toml
# deja puestos con base="dark"). Sirve para poder "devolver" el tema nativo
# a su estado normal si alguien elige CE/ARRM y despues vuelve a Automático.
_NATIVO_AUTOMATICO = {
    "base": "dark",
    "backgroundColor": "#0e1117",
    "secondaryBackgroundColor": "#262730",
    "textColor": "#fafafa",
    "primaryColor": "#ff4b4b",
}


def _opciones_nativas(paleta: dict | None) -> dict:
    if paleta is None:
        return _NATIVO_AUTOMATICO
    return {
        "base": paleta.get("base", "dark"),
        "backgroundColor": paleta["fondo"],
        "secondaryBackgroundColor": paleta["fondo_secundario"],
        "textColor": paleta["texto"],
        "primaryColor": paleta["primario"],
    }


def _sincronizar_tema_nativo(nombre_tema: str, paleta: dict | None):
    """Widgets dibujados en canvas (tablas) no leen CSS -- solo el tema
    NATIVO de Streamlit, que el frontend recibe una vez al conectar. Si el
    tema nativo ya coincide con el elegido, no hace nada; si no coincide,
    lo actualiza server-side y fuerza una recarga real de la pagina (un
    rerun comun no alcanza para retematizar el canvas, hace falta una
    conexion nueva).

    OJO: la comparacion NO se hace leyendo el valor actual con
    `config.get_option()` -- varias opciones (ej. theme.backgroundColor)
    no tienen un default fijo en Python, viven en `None` hasta que algo
    las setea explicitamente y el frontend resuelve el color real solo
    del lado del cliente. Comparar contra eso siempre daba "distinto" y
    quedaba en un loop infinito de recargas (pantalla en blanco para
    siempre). En su lugar se guarda un marcador propio en la URL
    (?_tema_nativo=...) que indica que color ya quedo aplicado.
    """
    marcador = st.query_params.get("_tema_nativo")
    if marcador == nombre_tema:
        return

    for clave, valor in _opciones_nativas(paleta).items():
        try:
            st.config.set_option(f"theme.{clave}", valor)
        except Exception:  # noqa: BLE001
            pass

    st.query_params["_tema_nativo"] = nombre_tema
    # OJO: un <script> insertado con st.markdown(unsafe_allow_html=True)
    # NUNCA se ejecuta -- es una limitacion del propio navegador (el HTML
    # se inserta via innerHTML, y los <script> insertados asi no corren,
    # nada que ver con Streamlit). components.html() SI ejecuta JS de
    # verdad porque lo corre dentro de un iframe con su propio documento
    # (srcdoc), no via innerHTML -- por eso hace falta "window.parent"
    # para recargar la pagina de arriba y no el iframe mismo.
    components.html(
        "<script>window.parent.location.reload();</script>", height=0, width=0,
    )
    st.stop()


def selector_tema() -> str:
    """Dibuja el selector de tema en la barra lateral y devuelve el
    nombre elegido (persistido en la URL via query param, para que
    sobreviva a la recarga que hace falta al cambiar de tema)."""
    opciones = list(TEMAS.keys())
    tema_url = st.query_params.get("tema")
    if "tema" not in st.session_state:
        st.session_state.tema = tema_url if tema_url in opciones else opciones[0]
    tema = st.selectbox("🎨 Tema", options=opciones, key="tema")
    if st.query_params.get("tema") != tema:
        st.query_params["tema"] = tema
    return tema


def aplicar_tema(nombre_tema: str):
    paleta = TEMAS.get(nombre_tema)

    # Esto puede disparar un st.stop() + recarga si el tema nativo
    # (el que usan las tablas dibujadas en canvas) todavia no coincide
    # con el elegido -- en ese caso el resto de esta funcion ni se llega
    # a ejecutar en esta corrida, se retoma en la corrida de despues de
    # recargar.
    _sincronizar_tema_nativo(nombre_tema, paleta)

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
       -- por defecto Streamlit los pinta en un rojo que no combina con
       ningun tema, hay que fijarlos a mano para que el contraste alcance
       para leerlos.
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

    /* Menu desplegable de selectbox/multiselect (la lista de opciones que
       se abre al hacer click) -- Streamlit lo pinta con su fondo oscuro
       nativo fijo (rgb(14,17,23)) sin importar el tema, y el texto le
       queda encima del color de {paleta['texto']} de arriba -- con CE
       (texto oscuro) eso da texto oscuro sobre fondo oscuro, ilegible.
       El div con el fondo real es el padre directo de [role="listbox"]
       (su propio fondo es transparente), por eso :has(). */
    div:has(> [role="listbox"]) {{
        background-color: {seleccion_fondo} !important;
        border: 1px solid {paleta['borde']} !important;
    }}
    [role="option"] {{
        color: {seleccion_texto} !important;
        background-color: transparent !important;
    }}
    [role="option"]:hover, [role="option"][aria-selected="true"] {{
        background-color: {paleta['primario']} !important;
        color: {paleta['fondo']} !important;
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
        # "h1 *, h2 *, h3 *" es necesario ademas de "h1, h2, h3": Streamlit
        # envuelve el texto real en un <span> hijo sin clase, que la regla
        # generica de "span { color: texto }" de mas arriba pisa (un hijo
        # con su propio color explicito no hereda el del padre) -- sin
        # este bloque el titulo queda con el color de texto normal
        # encima de la banda de color, casi ilegible.
        st.markdown(
            f"""
            <style>
            h1, h2, h3, h1 *, h2 *, h3 * {{
                color: {titulo_texto} !important;
            }}
            h1, h2, h3 {{
                background-color: {titulo_fondo} !important;
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
