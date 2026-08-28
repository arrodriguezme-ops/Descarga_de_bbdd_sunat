"""
dashboard.py

Este archivo quedo reemplazado por app.py (que ahora incluye una pantalla de
inicio para elegir entre SUNAT y Clima NASA). Corre:

    streamlit run app.py

en vez de este archivo. Lo dejamos como redireccion para que el comando
antiguo ('streamlit run dashboard.py') no rompa.
"""

import streamlit as st

st.set_page_config(page_title="Datos Perú -- Panel de descargas", layout="centered")
st.warning(
    "Este dashboard se movió. Corre en su lugar:\n\n"
    "```\nstreamlit run app.py\n```"
)
st.stop()
