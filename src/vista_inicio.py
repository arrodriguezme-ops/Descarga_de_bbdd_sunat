"""
vista_inicio.py

Pantalla de presentacion: elegir entre las fuentes de datos disponibles.
"""

import streamlit as st


def _tarjeta(col, titulo, texto, boton, pagina, key):
    with col:
        with st.container(border=True):
            st.subheader(titulo)
            st.write(texto)
            if st.button(boton, width="stretch", key=key, type="primary"):
                st.session_state.pagina = pagina
                st.rerun()


def render():
    st.title("Panel de descargas -- Peru")
    st.caption("Elige que fuente de datos quieres explorar.")

    fila1 = st.columns(3)
    _tarjeta(
        fila1[0], "📦 Importaciones / Exportaciones SUNAT",
        "Busca una subpartida arancelaria (por texto o codigo) y descarga el "
        "detalle de comercio exterior directamente del portal de Aduanas "
        "SUNAT, para el rango de anios que elijas.",
        "Ir a Importaciones SUNAT", "sunat", "ir_sunat",
    )
    _tarjeta(
        fila1[1], "🌦️ Clima NASA POWER (Perú)",
        "Temperatura maxima, minima y promedio, humedad relativa y "
        "precipitacion, a nivel diario, para los departamentos del Peru que "
        "elijas y el rango de anios que quieras.",
        "Ir a Clima NASA", "clima", "ir_clima",
    )
    _tarjeta(
        fila1[2], "⚖️ Concentración de mercado (IHH)",
        "Sube tu base (o tus 3 bases: oferta, demanda, transacciones), y "
        "obten participacion de mercado e IHH por año -- con simulacion de "
        "fusion opcional entre dos grupos economicos.",
        "Ir a Concentración (IHH)", "concentracion", "ir_ihh",
    )

    fila2 = st.columns(3)
    _tarjeta(
        fila2[0], "🥬 Precios mayoristas SISAP",
        "Precios y volumen diario de los mercados mayoristas de Lima "
        "(SISAP-MIDAGRI): filtra por mercado/producto/variable/periodo, "
        "descarga en CSV, DTA o Parquet, y arma series de tiempo.",
        "Ir a SISAP", "sisap", "ir_sisap",
    )
    _tarjeta(
        fila2[1], "⛏️ Minerales USGS",
        "Producción minera, de refinería y reservas por país y mineral "
        "(1996-2026): filtra por mineral/país/variable/año, descarga "
        "directa, serie de evolución y ranking de principales productores.",
        "Ir a Minerales USGS", "usgs", "ir_usgs",
    )
    _tarjeta(
        fila2[2], "🇵🇪 Cartera Minera MINEM",
        "Proyectos mineros en cartera del Perú (actualización a 2026): "
        "filtra por empresa, proyecto, estado, tipo de proyecto, mineral y "
        "año, con gráficos de cantidad de proyectos por año y por mineral.",
        "Ir a Cartera Minera", "minem", "ir_minem",
    )

    fila3 = st.columns(3)
    _tarjeta(
        fila3[0], "🗂️ Herramientas de PDF",
        "Convierte PDF a Markdown, agrega OCR a un PDF escaneado (texto "
        "buscable), y busca hasta 20 palabras clave en el buscador oficial "
        "de normas legales de gob.pe -- por autoridad y con enlace directo.",
        "Ir a Herramientas de PDF", "pdf", "ir_pdf",
    )
    _tarjeta(
        fila3[1], "🚗 Sector Automotor AAP",
        "Ventas mensuales de vehículos nuevos en Perú (2020-2026), "
        "descargadas de los informes de la AAP: filtra por tipo de "
        "vehículo y año, con gráficos y descarga de la base completa.",
        "Ir a Sector Automotor", "aap", "ir_aap",
    )

    fila4 = st.columns(3)
    _tarjeta(
        fila4[0], "🔧 Sector Automotor AAP — Detalle",
        "Todo lo demás que traen los informes de AAP: ventas anuales por "
        "segmento (SUV, pick-up, motos, trimotos...), ranking por marca, "
        "tablas por color/origen/combustible/lujo/electrificados/créditos, "
        "mapa por oficina registral y series de línea reconstruidas.",
        "Ir al Detalle AAP", "aap_detalle", "ir_aap_detalle",
    )
