"""
vista_sunat.py

Pantalla de busqueda de subpartida arancelaria + descarga de importaciones/
exportaciones en SUNAT.

Cambios clave respecto a la primera version:
- Las solicitudes de TODOS los anios elegidos se mandan de una sola vez (no
  una por una), y se sondean en conjunto -- mucho mas rapido cuando se pide
  mas de un anio (ver sunat_scraper.procesar_subpartida_anios).
- La descarga corre en un hilo en segundo plano (no bloquea la pagina), y su
  estado se guarda en un almacen compartido (st.cache_resource) + un archivo
  JSON en disco, asi que el progreso sigue visible aunque recargues la
  pagina o abras otra pestaña -- mientras el proceso de Streamlit siga vivo.
- Se pueden lanzar varias corridas en paralelo (distintas subpartidas, o la
  misma varias veces): todas quedan listadas en la misma tabla de estado.
"""

import json
import sys
import threading
import time
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from rapidfuzz import fuzz, process

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ / "src") not in sys.path:
    sys.path.insert(0, str(RAIZ / "src"))

from sunat_scraper import (  # noqa: E402
    ESTADO_COMPLETADO,
    ESTADO_ERROR,
    ESTADO_PARTIDA_INVALIDA,
    ESTADO_SIN_DATOS,
    nueva_sesion,
    procesar_subpartida_anios,
)

ARCHIVO_SUBPARTIDAS = RAIZ / "data" / "subpartidas_completo.csv"
CARPETA_RESULTADOS = RAIZ / "data" / "resultados_sunat"
CARPETA_DBF = RAIZ / "data" / "dbf_extraidos"
CARPETA_CONSOLIDADO = RAIZ / "data" / "consolidados"
ARCHIVO_ESTADO = RAIZ / "data" / "estado_descargas_sunat.json"
for carpeta in (CARPETA_RESULTADOS, CARPETA_DBF, CARPETA_CONSOLIDADO):
    carpeta.mkdir(parents=True, exist_ok=True)

MAX_SUGERENCIAS = 30

COLOR_POR_ESTADO = {
    "En cola": "#7a7a7a",
    "Enviando consulta": "#3b82f6",
    "Esperando a SUNAT": "#d97706",
    "Descargando": "#2563eb",
    "Leyendo datos": "#2563eb",
    ESTADO_COMPLETADO: "#16a34a",
    ESTADO_SIN_DATOS: "#6b7280",
    ESTADO_ERROR: "#dc2626",
    ESTADO_PARTIDA_INVALIDA: "#dc2626",
}


# ---------------------------------------------------------------------------
# Almacen compartido de estado (sobrevive a recargas de pagina y a otras
# pestañas, porque st.cache_resource es un singleton por proceso, no por
# sesion). Ademas se persiste a disco por si el proceso se reinicia.
# ---------------------------------------------------------------------------
@st.cache_resource
def _almacen():
    almacen = {"jobs": {}, "lock": threading.Lock()}
    if ARCHIVO_ESTADO.exists():
        try:
            almacen["jobs"] = json.loads(ARCHIVO_ESTADO.read_text(encoding="utf-8"))
            for job in almacen["jobs"].values():
                job.setdefault("resultados_disponibles", bool(job.get("archivo_consolidado")))
        except Exception:
            pass
    return almacen


def _guardar_estado(almacen):
    try:
        serializable = {
            job_id: {
                "subpartida": j["subpartida"],
                "descripcion": j.get("descripcion", ""),
                "regi": j["regi"],
                "anios": j["anios"],
                "creado": j["creado"],
                "estado_por_anio": j["estado_por_anio"],
                "terminado": j.get("terminado", False),
                "archivo_consolidado": j.get("archivo_consolidado"),
                "filas_consolidado": j.get("filas_consolidado", 0),
            }
            for job_id, j in almacen["jobs"].items()
        }
        ARCHIVO_ESTADO.write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _lanzar_job(subpartida: str, descripcion: str, regi: str, anios: list[int]):
    almacen = _almacen()
    job_id = f"{subpartida}_{regi}_{min(anios)}_{max(anios)}_{int(time.time())}"
    with almacen["lock"]:
        almacen["jobs"][job_id] = {
            "subpartida": subpartida,
            "descripcion": descripcion,
            "regi": regi,
            "anios": anios,
            "creado": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "estado_por_anio": {str(a): {"estado": "En cola", "mensaje": ""} for a in anios},
            "terminado": False,
        }
        _guardar_estado(almacen)

    def _worker():
        def on_status(info):
            with almacen["lock"]:
                job = almacen["jobs"].get(job_id)
                if job is None:
                    return
                job["estado_por_anio"][str(info["anio"])] = {
                    "estado": info["estado"], "mensaje": info.get("mensaje", ""),
                }
                _guardar_estado(almacen)

        try:
            sesion = nueva_sesion()
            resultados = procesar_subpartida_anios(
                subpartida, anios, sesion, CARPETA_RESULTADOS, CARPETA_DBF,
                regi=regi, on_status=on_status,
            )
            partes = [r.datos for r in resultados.values() if r.datos is not None]
            with almacen["lock"]:
                job = almacen["jobs"].get(job_id)
                if job is not None:
                    if partes:
                        consolidado = pd.concat(partes, ignore_index=True)
                        nombre = f"{subpartida}_{regi}_{min(anios)}_{max(anios)}.csv"
                        ruta = CARPETA_CONSOLIDADO / nombre
                        consolidado.to_csv(ruta, index=False, encoding="utf-8")
                        job["archivo_consolidado"] = str(ruta)
                        job["filas_consolidado"] = len(consolidado)
                    job["terminado"] = True
                    _guardar_estado(almacen)
        except Exception as e:
            with almacen["lock"]:
                job = almacen["jobs"].get(job_id)
                if job is not None:
                    for a in anios:
                        estado_actual = job["estado_por_anio"].get(str(a), {}).get("estado")
                        if estado_actual not in (ESTADO_COMPLETADO, ESTADO_SIN_DATOS):
                            job["estado_por_anio"][str(a)] = {"estado": ESTADO_ERROR, "mensaje": str(e)}
                    job["terminado"] = True
                    _guardar_estado(almacen)

    threading.Thread(target=_worker, daemon=True).start()
    return job_id


ARCHIVO_CAPITULOS = RAIZ / "data" / "sunat_capitulos_secciones.csv"


@st.cache_data
def _cargar_subpartidas():
    if not ARCHIVO_SUBPARTIDAS.exists():
        return None
    df = pd.read_csv(ARCHIVO_SUBPARTIDAS, dtype=str)
    df["codigo_subpartida"] = df["codigo_subpartida"].str.strip()
    df["descripcion"] = df["descripcion"].str.strip()
    df["etiqueta"] = df["codigo_subpartida"] + " -- " + df["descripcion"]
    # capitulo = 2 primeros digitos del codigo de 10 -- permite agrupar por
    # sector/mercado (ver _cargar_capitulos) sin tener que guardar la
    # columna en el CSV de subpartidas.
    df["capitulo"] = df["codigo_subpartida"].str[:2]
    return df.reset_index(drop=True)


@st.cache_data
def _cargar_capitulos():
    """Indice Seccion (sector) -> Capitulo (subsector) del Arancel de
    Aduanas, para la busqueda alternativa 'por sector/mercado'. Ver
    data/sunat_capitulos_secciones.csv (generado una vez a partir del
    Arancel de Aduanas 2022, no cambia salvo que la nomenclatura HS se
    revise -- no hace falta regenerarlo en cada corrida)."""
    if not ARCHIVO_CAPITULOS.exists():
        return None
    df = pd.read_csv(ARCHIVO_CAPITULOS, dtype={"capitulo": str}, encoding="utf-8-sig")
    return df.sort_values(["seccion_numero", "capitulo"]).reset_index(drop=True)


@st.fragment(run_every=4)
def _panel_estado():
    almacen = _almacen()
    with almacen["lock"]:
        jobs = {jid: dict(j) for jid, j in almacen["jobs"].items()}

    if not jobs:
        st.info("Aun no se ha lanzado ninguna descarga.")
        return

    filas = []
    for job in sorted(jobs.values(), key=lambda j: j["creado"], reverse=True):
        for anio in job["anios"]:
            info = job["estado_por_anio"].get(str(anio), {"estado": "En cola", "mensaje": ""})
            filas.append({
                "Lanzado": job["creado"],
                "Subpartida": job["subpartida"],
                "Tipo": "Importacion" if job["regi"] == "Impo" else "Exportacion",
                "Anio": anio,
                "Estado": info["estado"],
                "Detalle": info.get("mensaje", ""),
            })
    tabla = pd.DataFrame(filas)

    def color_fila(row):
        color = COLOR_POR_ESTADO.get(row["Estado"], "#7a7a7a")
        return [f"background-color: {color}; color: white"] * len(row)

    st.dataframe(tabla.style.apply(color_fila, axis=1), hide_index=True, width="stretch", height=min(72 + 35 * len(tabla), 500))
    st.caption("Se actualiza solo cada pocos segundos. Puedes recargar la pagina o cerrar la pestaña: el estado se conserva mientras el servidor de Streamlit siga corriendo.")

    st.divider()
    st.subheader("Resultados listos para descargar")
    jobs_listos = [j for j in jobs.values() if j.get("terminado") and j.get("archivo_consolidado")]
    if not jobs_listos:
        st.caption("Todavia no hay ningun resultado consolidado.")
        return

    for job in sorted(jobs_listos, key=lambda j: j["creado"], reverse=True):
        ruta = Path(job["archivo_consolidado"])
        if not ruta.exists():
            continue
        etiqueta = f"{job['subpartida']} ({min(job['anios'])}-{max(job['anios'])}, {job['regi']}) -- {job.get('filas_consolidado', 0):,} filas"
        with st.expander(etiqueta):
            st.download_button(
                "Descargar CSV consolidado",
                data=ruta.read_bytes(),
                file_name=ruta.name,
                mime="text/csv",
                width="stretch",
                key=f"descarga_{ruta.name}",
            )


def _selector_por_texto(df: pd.DataFrame) -> pd.DataFrame:
    """Modo 'por texto o codigo': busqueda difusa + multiselect. Devuelve
    el subconjunto de df elegido por el usuario (0 o mas filas)."""
    consulta = st.text_input(
        "Escribe el producto o el codigo (ej. 'cobre concentrado', 'vino tinto', '2603000000')",
        key="consulta_texto",
    )

    if consulta.strip():
        coincidencias = process.extract(
            consulta, df["etiqueta"].tolist(), scorer=fuzz.WRatio, limit=MAX_SUGERENCIAS
        )
        indices = [idx for _, score, idx in coincidencias]
        opciones_df = df.iloc[indices]
        ayuda = f"Mostrando las {len(opciones_df)} coincidencias mas parecidas a tu busqueda."
    else:
        opciones_df = df
        ayuda = f"Sin filtro: las {len(df):,} subpartidas del arancel. Escribe arriba para acotar."

    etiquetas_elegidas = st.multiselect(
        "Subpartida(s) (codigo -- descripcion) -- puedes elegir varias:",
        options=opciones_df["etiqueta"].tolist(),
        help=ayuda,
        key="selector_subpartida_texto",
    )
    return opciones_df[opciones_df["etiqueta"].isin(etiquetas_elegidas)]


def _selector_por_sector(df: pd.DataFrame) -> pd.DataFrame:
    """Modo 'por sector/mercado': Seccion (sector, ej. 'Productos
    Minerales') -> Capitulo (subsector, ej. 'Minerales metaliferos') ->
    multiselect de subpartidas dentro de ese capitulo. Usa la
    clasificacion oficial del Arancel de Aduanas (21 Secciones, 98
    Capitulos) en vez de una taxonomia inventada."""
    capitulos = _cargar_capitulos()
    if capitulos is None:
        st.warning(
            f"No se encontro '{ARCHIVO_CAPITULOS.relative_to(RAIZ)}' -- la busqueda por sector no esta "
            "disponible, pero la busqueda por texto/codigo si funciona."
        )
        return df.iloc[0:0]

    secciones = capitulos[["seccion_numero", "seccion_romano", "seccion_nombre"]].drop_duplicates().sort_values("seccion_numero")
    etiquetas_seccion = [f"{r.seccion_romano} -- {r.seccion_nombre}" for r in secciones.itertuples()]
    seccion_elegida = st.selectbox("Sector (Sección del Arancel):", options=etiquetas_seccion, key="selector_seccion")
    seccion_num = secciones.iloc[etiquetas_seccion.index(seccion_elegida)]["seccion_numero"]

    caps_de_la_seccion = capitulos[capitulos["seccion_numero"] == seccion_num]
    etiquetas_cap = [f"Cap. {r.capitulo} -- {r.capitulo_descripcion}" for r in caps_de_la_seccion.itertuples()]
    cap_elegido = st.selectbox(
        "Subsector (Capítulo) -- elige uno o más para tener detalle:",
        options=etiquetas_cap, key="selector_capitulo",
    )
    capitulo_num = caps_de_la_seccion.iloc[etiquetas_cap.index(cap_elegido)]["capitulo"]

    opciones_df = df[df["capitulo"] == capitulo_num]
    if opciones_df.empty:
        st.info("Este capítulo no tiene subpartidas en la base cargada.")
        return opciones_df

    etiquetas_elegidas = st.multiselect(
        f"Subpartida(s) dentro de este capítulo ({len(opciones_df)} disponibles) -- puedes elegir varias:",
        options=opciones_df["etiqueta"].tolist(),
        key="selector_subpartida_sector",
    )
    return opciones_df[opciones_df["etiqueta"].isin(etiquetas_elegidas)]


def render():
    st.title("Buscador y descarga de importaciones por subpartida -- SUNAT")

    df = _cargar_subpartidas()

    if df is None:
        st.error(
            f"No se encontro '{ARCHIVO_SUBPARTIDAS.relative_to(RAIZ)}'. Corre primero:\n\n"
            "`python src/descargar_arancel_completo.py`"
        )
        st.stop()

    col_izq, col_der = st.columns([2.2, 1])

    with col_izq:
        st.subheader("1. Elige la(s) subpartida(s)")
        modo = st.radio(
            "Modo de búsqueda", options=["Por texto o código", "Por sector / mercado"],
            horizontal=True, key="modo_busqueda_sunat",
        )
        if modo == "Por texto o código":
            elegidas = _selector_por_texto(df)
        else:
            elegidas = _selector_por_sector(df)

        if elegidas.empty:
            st.info("Elige al menos una subpartida arriba para continuar.")
        else:
            st.dataframe(
                elegidas[["codigo_subpartida", "descripcion"]].rename(
                    columns={"codigo_subpartida": "Código", "descripcion": "Descripción"}
                ),
                hide_index=True, width="stretch",
            )

        st.divider()
        st.subheader("2. Descarga de importaciones en SUNAT")

        anio_actual = date.today().year
        c1, c2, c3 = st.columns(3)
        with c1:
            anio_inicio = st.number_input("Anio inicio", min_value=2007, max_value=anio_actual, value=anio_actual - 3)
        with c2:
            anio_fin = st.number_input("Anio fin", min_value=2007, max_value=anio_actual, value=anio_actual)
        with c3:
            regi = st.selectbox(
                "Tipo", options=["Impo", "Expo"],
                format_func=lambda x: "Importaciones" if x == "Impo" else "Exportaciones",
            )

        st.caption(
            "Al lanzar, se manda una corrida por cada subpartida elegida (con las "
            "solicitudes de TODOS los anios del rango de una sola vez, sondeadas en "
            "conjunto) -- todas corren en segundo plano y en paralelo entre si, asi "
            "que puedes seguir usando la pagina (o cerrarla) mientras esperan a SUNAT."
        )

        lanzar = st.button(
            "Descargar de SUNAT", type="primary", width="stretch", disabled=elegidas.empty,
        )

        if lanzar:
            if anio_inicio > anio_fin:
                st.error("El anio de inicio no puede ser mayor que el anio de fin.")
            else:
                anios = list(range(int(anio_inicio), int(anio_fin) + 1))
                for _, fila in elegidas.iterrows():
                    _lanzar_job(fila["codigo_subpartida"], fila["descripcion"], regi, anios)
                st.success(
                    f"Descarga lanzada para {len(elegidas)} subpartida(s) x {len(anios)} año(s). "
                    "Revisa el estado a la derecha."
                )

    with col_der:
        st.subheader("Estado de las descargas")
        _panel_estado()
