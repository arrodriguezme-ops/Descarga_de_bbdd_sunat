"""
app.py

Punto de entrada del panel. Pantalla de inicio con dos opciones:
- Importaciones/Exportaciones SUNAT por subpartida (src/vista_sunat.py)
- Clima diario NASA POWER por departamento del Peru (src/vista_clima.py)

Para correrlo:
    pip install -r requirements.txt
    python src/descargar_arancel_completo.py   # una sola vez, para SUNAT
    streamlit run app.py
"""

import sys
from pathlib import Path

import streamlit as st

RAIZ = Path(__file__).resolve().parent
if str(RAIZ / "src") not in sys.path:
    sys.path.insert(0, str(RAIZ / "src"))

import temas  # noqa: E402
import vista_clima  # noqa: E402
import vista_concentracion  # noqa: E402
import vista_inicio  # noqa: E402
import vista_sisap  # noqa: E402
import vista_aap  # noqa: E402
import vista_minem  # noqa: E402
import vista_pdf_herramientas  # noqa: E402
import vista_sunat  # noqa: E402
import vista_usgs  # noqa: E402

st.set_page_config(page_title="Datos Perú -- Panel de descargas", layout="wide")

if "pagina" not in st.session_state:
    st.session_state.pagina = "inicio"

with st.sidebar:
    tema_elegido = temas.selector_tema()
    st.divider()
    st.markdown("### Navegación")
    if st.button("🏠 Inicio", width="stretch"):
        st.session_state.pagina = "inicio"
        st.rerun()
    if st.button("📦 Importaciones SUNAT", width="stretch"):
        st.session_state.pagina = "sunat"
        st.rerun()
    if st.button("🌦️ Clima NASA", width="stretch"):
        st.session_state.pagina = "clima"
        st.rerun()
    if st.button("⚖️ Concentración de mercado (IHH)", width="stretch"):
        st.session_state.pagina = "concentracion"
        st.rerun()
    if st.button("🥬 Precios mayoristas SISAP", width="stretch"):
        st.session_state.pagina = "sisap"
        st.rerun()
    if st.button("⛏️ Minerales USGS", width="stretch"):
        st.session_state.pagina = "usgs"
        st.rerun()
    if st.button("🇵🇪 Cartera Minera MINEM", width="stretch"):
        st.session_state.pagina = "minem"
        st.rerun()
    if st.button("🗂️ Herramientas de PDF", width="stretch"):
        st.session_state.pagina = "pdf"
        st.rerun()
    if st.button("🚗 Sector Automotor AAP", width="stretch"):
        st.session_state.pagina = "aap"
        st.rerun()

temas.aplicar_tema(tema_elegido)

if st.session_state.pagina == "inicio":
    vista_inicio.render()
elif st.session_state.pagina == "sunat":
    vista_sunat.render()
elif st.session_state.pagina == "clima":
    vista_clima.render()
elif st.session_state.pagina == "concentracion":
    vista_concentracion.render()
elif st.session_state.pagina == "sisap":
    vista_sisap.render()
elif st.session_state.pagina == "usgs":
    vista_usgs.render()
elif st.session_state.pagina == "minem":
    vista_minem.render()
elif st.session_state.pagina == "pdf":
    vista_pdf_herramientas.render()
elif st.session_state.pagina == "aap":
    vista_aap.render()
