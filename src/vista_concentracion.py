"""
vista_concentracion.py

Servicio de concentracion de mercado (IHH) y participacion, para analisis de
fusiones. Generalizado a partir de un script en R hecho para un caso
puntual: aca el usuario sube su propia base y configura en la UI que
columna es la empresa, el grupo economico, el año/periodo y las variables
de valor (cantidad/produccion, facturacion, etc.) -- nada hardcodeado.

Dos modos de carga:
- "Tabla única": una sola base ya armada (empresa/grupo/año/valor por fila).
- "3 bases": Base 1 (oferta: empresa/grupo/ID), Base 2 (demanda:
  empresa/grupo/ID) y Base 3 (transacciones: ID oferente x ID demandante x
  producción/ventas x año[/mes]) -- se unen igual que los left_join del R
  original, y arma automáticamente las vistas de Oferta y Demanda.

Flujo (en ambos modos):
1. Cargar y mapear columnas.
2. Botón "Simular fusión" (apagado por defecto):
   - Apagado: solo IHH + participación de mercado por grupo económico.
   - Prendido: además pide Grupo Adquiriente / Grupo Objetivo y calcula el
     IHH pre/post fusión (colapsando todo lo demás en "Otros"), igual que
     el script original en R -- con un gráfico de "quiebre" mostrando cómo
     se separa la línea de IHH histórica de la simulada con fusión en el
     último año.
3. Resultados en pantalla (tablas + gráficos) y en un Excel formateado
   descargable.
"""

import sys
from pathlib import Path
from typing import Optional

import altair as alt
import pandas as pd
import streamlit as st

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ / "src") not in sys.path:
    sys.path.insert(0, str(RAIZ / "src"))

from ihh_concentracion import calcular_vista, datos_grafico_fork, interpretar_ihh, unir_tres_bases  # noqa: E402
from ihh_excel_export import exportar_excel_ihh  # noqa: E402

CARPETA_SALIDA = RAIZ / "data" / "concentracion_ihh"
CARPETA_SALIDA.mkdir(parents=True, exist_ok=True)

VARIABLES_TIPO = ["Cantidad (producción)", "Facturación (valor)", "Otra"]


@st.cache_data(show_spinner=False)
def _leer_archivo(nombre: str, contenido: bytes) -> pd.DataFrame:
    if nombre.lower().endswith(".csv"):
        return pd.read_csv(pd.io.common.BytesIO(contenido))
    return pd.read_excel(pd.io.common.BytesIO(contenido))


def _indice_por_defecto(columnas: list, claves: list[str], excluir: Optional[str] = None, respaldo: int = 0) -> int:
    """Adivina que columna usar por defecto buscando palabras clave en el
    nombre, para que selectores distintos no apunten los 3 a la misma
    columna por defecto."""
    for i, c in enumerate(columnas):
        if excluir is not None and c == excluir:
            continue
        if any(clave in str(c).lower() for clave in claves):
            return i
    return min(respaldo, len(columnas) - 1)


def _elegir_variables_y_etiquetas(df: pd.DataFrame, excluir: list, key_prefix: str) -> tuple[list, dict]:
    """UI reutilizable: elegir columnas numéricas de valor y taggear cada
    una como Cantidad/Facturación/Otra."""
    columnas_numericas = [
        c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and c not in excluir
    ]
    if not columnas_numericas:
        st.error("No se detectó ninguna columna numérica para usar como variable de valor.")
        return [], {}

    variables_elegidas = st.multiselect(
        "Columnas de valor a analizar",
        options=columnas_numericas,
        default=columnas_numericas[:2],
        key=f"{key_prefix}_variables",
    )
    etiquetas_variable = {}
    if variables_elegidas:
        cols_tipo = st.columns(min(len(variables_elegidas), 3) or 1)
        for i, col in enumerate(variables_elegidas):
            with cols_tipo[i % len(cols_tipo)]:
                etiquetas_variable[col] = st.selectbox(
                    f"'{col}' es...", options=VARIABLES_TIPO, key=f"{key_prefix}_tipo_{col}"
                )
    return variables_elegidas, etiquetas_variable


def _elegir_fusion_grupos(grupos_disponibles: list, key_prefix: str) -> tuple[Optional[str], Optional[str]]:
    grupos_disponibles = sorted(grupos_disponibles, key=str)
    if not grupos_disponibles:
        st.warning("No hay grupos económicos disponibles para elegir.")
        return None, None
    fc1, fc2 = st.columns(2)
    with fc1:
        adquiriente = st.selectbox(
            "Grupo económico Adquiriente", options=grupos_disponibles, key=f"{key_prefix}_grupo_a"
        )
    with fc2:
        opciones_objetivo = [g for g in grupos_disponibles if g != adquiriente]
        objetivo = st.selectbox("Grupo económico Objetivo", options=opciones_objetivo, key=f"{key_prefix}_grupo_b")
    return adquiriente, objetivo


def _procesar_y_guardar(resultados: list, prefijo_excel: str):
    st.session_state.resultados_ihh = resultados
    nombre_excel = f"{prefijo_excel}_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    ruta_excel = exportar_excel_ihh(resultados, CARPETA_SALIDA / nombre_excel)
    st.session_state.ruta_excel_ihh = str(ruta_excel)


# ---------------------------------------------------------------------------
# Modo 1: tabla única
# ---------------------------------------------------------------------------
def _modo_tabla_unica():
    archivo = st.file_uploader("Base de datos (Excel o CSV)", type=["xlsx", "xls", "csv"])
    if archivo is None:
        st.info(
            "Sube un archivo para empezar. Si no tienes uno a mano para probar, "
            "pide el mockup de ejemplo (`data/mockup_ihh.xlsx` en este repo)."
        )
        return

    df = _leer_archivo(archivo.name, archivo.getvalue())
    st.success(f"Base cargada: {len(df):,} filas, {len(df.columns)} columnas.")
    with st.expander("Vista previa de la base"):
        st.dataframe(df.head(50), width="stretch")

    columnas = list(df.columns)

    st.divider()
    st.subheader("1. Mapeo de columnas")

    c1, c2, c3 = st.columns(3)
    with c1:
        idx_anio = _indice_por_defecto(columnas, ["año", "anio", "year", "periodo", "fano"], respaldo=0)
        col_anio = st.selectbox("Columna de Año / Periodo", options=columnas, index=idx_anio, key="col_anio")
    with c2:
        idx_empresa = _indice_por_defecto(columnas, ["empresa", "company", "razon", "razón"], excluir=col_anio, respaldo=1)
        col_empresa = st.selectbox("Columna de Empresa", options=columnas, index=idx_empresa, key="col_empresa")
    with c3:
        opciones_grupo = ["(usar Empresa como grupo)"] + columnas
        idx_grupo = _indice_por_defecto(columnas, ["grupo", "group", "holding", "conglomerado"], excluir=col_anio)
        idx_grupo_sel = idx_grupo + 1 if columnas[idx_grupo] != col_anio and columnas[idx_grupo] != col_empresa else 0
        col_grupo_sel = st.selectbox(
            "Columna de Grupo Económico", options=opciones_grupo, index=idx_grupo_sel, key="col_grupo"
        )
        col_grupo = col_empresa if col_grupo_sel == "(usar Empresa como grupo)" else col_grupo_sel

    if len({col_anio, col_empresa, col_grupo}) < 2:
        st.error("La columna de Año y la de Empresa/Grupo no pueden ser la misma. Revisa el mapeo arriba.")
        return

    st.markdown("**Variables de valor** -- elige una o más columnas numéricas y di qué representa cada una:")
    variables_elegidas, etiquetas_variable = _elegir_variables_y_etiquetas(df, excluir=[col_anio], key_prefix="unica")
    if not variables_elegidas:
        return

    with st.expander("Opcional: perspectiva de mercado (oferta / demanda / etc.) y filtro adicional"):
        oc1, oc2 = st.columns(2)
        with oc1:
            opciones_lado = ["(una sola vista)"] + columnas
            col_lado_sel = st.selectbox(
                "Columna que distingue perspectivas (ej. 'Oferta'/'Demanda')", options=opciones_lado
            )
            col_lado = None if col_lado_sel == "(una sola vista)" else col_lado_sel
        with oc2:
            opciones_filtro = ["(sin filtro)"] + columnas
            col_filtro_sel = st.selectbox("Columna de filtro adicional (opcional)", options=opciones_filtro)
            col_filtro = None if col_filtro_sel == "(sin filtro)" else col_filtro_sel

        valor_filtro = None
        if col_filtro:
            valores_unicos = sorted(df[col_filtro].dropna().unique().tolist(), key=str)
            valor_filtro = st.multiselect(f"Valores de '{col_filtro}' a incluir", options=valores_unicos)

    st.divider()
    st.subheader("2. Fusión")
    simular_fusion = st.toggle(
        "🔀 Simular fusión (pedir grupos económicos a fusionar)",
        value=False,
        help="Apagado: solo IHH y participación de mercado. Prendido: además pide "
        "Grupo Adquiriente / Grupo Objetivo y calcula el IHH pre/post fusión.",
    )

    grupo_adquiriente = grupo_objetivo = None
    if simular_fusion:
        grupo_adquiriente, grupo_objetivo = _elegir_fusion_grupos(df[col_grupo].dropna().unique().tolist(), "unica")

    st.divider()
    procesar = st.button("Procesar", type="primary", width="stretch", key="procesar_unica")

    if not procesar and "resultados_ihh" not in st.session_state:
        return

    if procesar:
        df_filtrado = df
        if col_filtro and valor_filtro:
            df_filtrado = df_filtrado[df_filtrado[col_filtro].isin(valor_filtro)]

        if df_filtrado.empty:
            st.error("No quedaron filas después de aplicar el filtro.")
            return

        vistas = {"Mercado": df_filtrado}
        if col_lado:
            vistas = {str(valor): grupo for valor, grupo in df_filtrado.groupby(col_lado)}

        resultados = []
        for nombre_vista, datos_vista in vistas.items():
            for col_valor in variables_elegidas:
                resultado = calcular_vista(
                    datos_vista,
                    col_grupo=col_grupo,
                    col_anio=col_anio,
                    col_valor=col_valor,
                    nombre_vista=nombre_vista,
                    nombre_variable=f"{etiquetas_variable[col_valor]} ({col_valor})",
                    grupo_adquiriente=grupo_adquiriente if simular_fusion else None,
                    grupo_objetivo=grupo_objetivo if simular_fusion else None,
                )
                resultados.append(resultado)

        _procesar_y_guardar(resultados, "IHH_fusion" if simular_fusion else "IHH")


# ---------------------------------------------------------------------------
# Modo 2: 3 bases (Oferta + Demanda + Transacciones) -- asistente de 3 pasos
# ---------------------------------------------------------------------------
def _paso1_base_oferta():
    st.subheader("Base 1 — Oferta")
    st.caption("Empresas oferentes: Empresa / Grupo económico / ID.")

    archivo1 = st.file_uploader("Sube la Base 1", type=["xlsx", "xls", "csv"], key="archivo1")
    if archivo1 is None:
        base1_previo = st.session_state.get("base1_datos")
        if base1_previo is not None:
            st.info("Ya tienes una Base 1 cargada de antes. Sube otro archivo para reemplazarla, o avanza.")
        else:
            st.info("Sube la Base 1 para continuar.")
            return

    if archivo1 is not None:
        base1 = _leer_archivo(archivo1.name, archivo1.getvalue())
        st.session_state.base1_datos = base1
    else:
        base1 = st.session_state.base1_datos

    st.success(f"{len(base1):,} filas, {len(base1.columns)} columnas.")
    with st.expander("Vista previa"):
        st.dataframe(base1.head(20), width="stretch")

    cols1 = list(base1.columns)
    c1, c2, c3 = st.columns(3)
    with c1:
        col_id1 = st.selectbox("Columna ID", options=cols1, index=_indice_por_defecto(cols1, ["id"]), key="col_id1")
    with c2:
        col_empresa1 = st.selectbox(
            "Columna Empresa", options=cols1,
            index=_indice_por_defecto(cols1, ["empresa"], excluir=col_id1, respaldo=1), key="col_empresa1",
        )
    with c3:
        col_grupo1 = st.selectbox(
            "Columna Grupo económico", options=cols1,
            index=_indice_por_defecto(cols1, ["grupo"], excluir=col_id1, respaldo=min(2, len(cols1) - 1)),
            key="col_grupo1",
        )

    if len({col_id1, col_empresa1, col_grupo1}) < 3:
        st.error("Las 3 columnas (ID, Empresa, Grupo) deben ser distintas entre sí.")
        return

    st.session_state.base1_mapa = (col_id1, col_empresa1, col_grupo1)

    if st.button("Siguiente → Base 2 (Demanda)", type="primary", width="stretch"):
        st.session_state.paso_tres_bases = 2
        st.rerun()


def _paso2_base_demanda():
    if st.button("← Atrás (Base 1: Oferta)"):
        st.session_state.paso_tres_bases = 1
        st.rerun()

    st.subheader("Base 2 — Demanda")
    st.caption("Empresas o clientes demandantes: Empresa / Grupo económico / ID.")

    archivo2 = st.file_uploader("Sube la Base 2", type=["xlsx", "xls", "csv"], key="archivo2")
    if archivo2 is None:
        base2_previo = st.session_state.get("base2_datos")
        if base2_previo is not None:
            st.info("Ya tienes una Base 2 cargada de antes. Sube otro archivo para reemplazarla, o avanza.")
        else:
            st.info("Sube la Base 2 para continuar.")
            return

    if archivo2 is not None:
        base2 = _leer_archivo(archivo2.name, archivo2.getvalue())
        st.session_state.base2_datos = base2
    else:
        base2 = st.session_state.base2_datos

    st.success(f"{len(base2):,} filas, {len(base2.columns)} columnas.")
    with st.expander("Vista previa"):
        st.dataframe(base2.head(20), width="stretch")

    cols2 = list(base2.columns)
    c1, c2, c3 = st.columns(3)
    with c1:
        col_id2 = st.selectbox("Columna ID", options=cols2, index=_indice_por_defecto(cols2, ["id"]), key="col_id2")
    with c2:
        col_empresa2 = st.selectbox(
            "Columna Empresa", options=cols2,
            index=_indice_por_defecto(cols2, ["empresa"], excluir=col_id2, respaldo=1), key="col_empresa2",
        )
    with c3:
        col_grupo2 = st.selectbox(
            "Columna Grupo económico", options=cols2,
            index=_indice_por_defecto(cols2, ["grupo"], excluir=col_id2, respaldo=min(2, len(cols2) - 1)),
            key="col_grupo2",
        )

    if len({col_id2, col_empresa2, col_grupo2}) < 3:
        st.error("Las 3 columnas (ID, Empresa, Grupo) deben ser distintas entre sí.")
        return

    st.session_state.base2_mapa = (col_id2, col_empresa2, col_grupo2)

    if st.button("Siguiente → Base 3 (Transacciones)", type="primary", width="stretch"):
        st.session_state.paso_tres_bases = 3
        st.rerun()


def _modo_tres_bases():
    st.caption(
        "Sube por separado: **Base 1** (empresas oferentes: empresa / grupo económico "
        "/ ID), **Base 2** (empresas o clientes demandantes: empresa / grupo económico "
        "/ ID), y **Base 3** (transacciones: ID oferente x ID demandante x "
        "producción/ventas x año[/mes]). Se unen igual que en el script original "
        "y se arman automáticamente las vistas de Oferta y Demanda."
    )

    if "paso_tres_bases" not in st.session_state:
        st.session_state.paso_tres_bases = 1
    paso = st.session_state.paso_tres_bases

    etiquetas_paso = ["Base 1 · Oferta", "Base 2 · Demanda", "Base 3 · Transacciones y fusión"]
    st.progress(paso / 3, text=f"Paso {paso} de 3 — {etiquetas_paso[paso - 1]}")
    nav = " → ".join(
        f"**{i}. {etq}**" if i == paso else f"{i}. {etq}" for i, etq in enumerate(etiquetas_paso, start=1)
    )
    st.caption(nav)
    st.divider()

    if paso == 1:
        _paso1_base_oferta()
        return
    elif paso == 2:
        _paso2_base_demanda()
        return
    elif paso != 3:
        return

    # --- Paso 3: Base de transacciones + variables + fusión + procesar ---
    base1 = st.session_state.get("base1_datos")
    base2 = st.session_state.get("base2_datos")
    col_id1, col_empresa1, col_grupo1 = st.session_state.get("base1_mapa", (None, None, None))
    col_id2, col_empresa2, col_grupo2 = st.session_state.get("base2_mapa", (None, None, None))
    if base1 is None or base2 is None:
        st.warning("Falta completar los pasos 1 y 2 primero.")
        st.session_state.paso_tres_bases = 1
        st.rerun()

    if st.button("← Atrás (Base 2: Demanda)"):
        st.session_state.paso_tres_bases = 2
        st.rerun()

    st.subheader("Base 3 — Transacciones")
    archivo3 = st.file_uploader(
        "ID oferente x ID demandante x producción/ventas x año[/mes]", type=["xlsx", "xls", "csv"], key="archivo3"
    )
    if archivo3 is None:
        st.info("Sube la Base 3 para continuar.")
        return

    base3 = _leer_archivo(archivo3.name, archivo3.getvalue())
    st.success(f"{len(base3):,} filas, {len(base3.columns)} columnas.")
    with st.expander("Vista previa"):
        st.dataframe(base3.head(20), width="stretch")

    cols3 = list(base3.columns)
    b3c1, b3c2, b3c3 = st.columns(3)
    with b3c1:
        col_id_of3 = st.selectbox(
            "ID Empresa oferente", options=cols3, index=_indice_por_defecto(cols3, ["oferente", "generad"]), key="col_id_of3"
        )
    with b3c2:
        col_id_dem3 = st.selectbox(
            "ID Empresa/consumidor demandante", options=cols3,
            index=_indice_por_defecto(cols3, ["demand", "consum", "cliente"], excluir=col_id_of3, respaldo=1),
            key="col_id_dem3",
        )
    with b3c3:
        col_anio3 = st.selectbox(
            "Año", options=cols3, index=_indice_por_defecto(cols3, ["año", "anio", "year"], respaldo=2), key="col_anio3"
        )

    es_mensual = st.checkbox("La Base 3 es mensual (tiene columna de mes además del año)", value=False)
    col_mes3 = None
    if es_mensual:
        col_mes3 = st.selectbox(
            "Mes", options=[c for c in cols3 if c != col_anio3],
            index=_indice_por_defecto([c for c in cols3 if c != col_anio3], ["mes", "month"]),
            key="col_mes3",
        )

    if len({col_id_of3, col_id_dem3, col_anio3, col_mes3} - {None}) < (3 if not es_mensual else 4):
        st.error("Las columnas de ID oferente, ID demandante, año y mes (si aplica) deben ser distintas entre sí.")
        return

    st.markdown("**Variables de valor** (ej. producción, ventas) -- di qué representa cada una:")
    excluir3 = [col_anio3, col_id_of3, col_id_dem3] + ([col_mes3] if col_mes3 else [])
    variables_elegidas, etiquetas_variable = _elegir_variables_y_etiquetas(base3, excluir=excluir3, key_prefix="tres")
    if not variables_elegidas:
        return

    st.divider()
    st.subheader("Fusión")
    simular_fusion = st.toggle(
        "🔀 Simular fusión (pedir grupos económicos a fusionar)", value=False, key="fusion_tres"
    )

    vista_fusion = grupo_adquiriente = grupo_objetivo = None
    if simular_fusion:
        vista_fusion = st.selectbox("¿La fusión aplica a la vista de...", options=["Oferta", "Demanda"], key="vista_fusion_tres")
        grupos_fuente = base1[col_grupo1] if vista_fusion == "Oferta" else base2[col_grupo2]
        grupo_adquiriente, grupo_objetivo = _elegir_fusion_grupos(grupos_fuente.dropna().unique().tolist(), "tres")

    st.divider()
    procesar = st.button("Procesar", type="primary", width="stretch", key="procesar_tres")

    if not procesar and "resultados_ihh" not in st.session_state:
        return

    if procesar:
        unido = unir_tres_bases(
            base1, col_id1, col_empresa1, col_grupo1,
            base2, col_id2, col_empresa2, col_grupo2,
            base3, col_id_of3, col_id_dem3, col_anio3, col_mes3,
        )

        faltantes = unido.attrs.get("filas_sin_match")
        if faltantes:
            st.warning(
                f"⚠️ {faltantes['oferente']:,} filas de la Base 3 no encontraron el ID oferente en la "
                f"Base 1, y {faltantes['demandante']:,} no encontraron el ID demandante en la Base 2 -- "
                "esas filas quedan fuera del cálculo de esa vista (revisa que los IDs coincidan)."
            )

        vistas_datos = {
            "Oferta": unido.dropna(subset=["grupo_oferente"]),
            "Demanda": unido.dropna(subset=["grupo_demandante"]),
        }
        col_grupo_por_vista = {"Oferta": "grupo_oferente", "Demanda": "grupo_demandante"}

        resultados = []
        for nombre_vista, datos_vista in vistas_datos.items():
            if datos_vista.empty:
                continue
            for col_valor in variables_elegidas:
                aplica_fusion = simular_fusion and vista_fusion == nombre_vista
                resultado = calcular_vista(
                    datos_vista,
                    col_grupo=col_grupo_por_vista[nombre_vista],
                    col_anio="periodo",
                    col_valor=col_valor,
                    nombre_vista=nombre_vista,
                    nombre_variable=f"{etiquetas_variable[col_valor]} ({col_valor})",
                    grupo_adquiriente=grupo_adquiriente if aplica_fusion else None,
                    grupo_objetivo=grupo_objetivo if aplica_fusion else None,
                )
                resultados.append(resultado)

        _procesar_y_guardar(resultados, "IHH_3bases_fusion" if simular_fusion else "IHH_3bases")


# ---------------------------------------------------------------------------
# Resultados (compartido por ambos modos)
# ---------------------------------------------------------------------------
def _mostrar_resultados():
    resultados = st.session_state.get("resultados_ihh")
    if not resultados:
        return

    st.divider()
    st.subheader("3. Resultados")

    ruta_excel = st.session_state.get("ruta_excel_ihh")
    if ruta_excel and Path(ruta_excel).exists():
        st.download_button(
            "📥 Descargar Excel con insights (IHH + participación)",
            data=Path(ruta_excel).read_bytes(),
            file_name=Path(ruta_excel).name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
        )

    for resultado in resultados:
        st.markdown(f"### {resultado.nombre_vista} — {resultado.nombre_variable}")

        tab_participacion, tab_ihh, tab_fusion = st.tabs(
            ["Participación de mercado", "Evolución del IHH", "Fusión"]
        )

        with tab_participacion:
            tabla_mostrar = resultado.tabla_ancha.copy()
            formato = {c: "{:.2%}" for c in tabla_mostrar.columns}
            st.dataframe(
                tabla_mostrar.style.format(formato, na_rep="—").format(
                    {c: "{:,.2f}" for c in tabla_mostrar.columns}, subset=pd.IndexSlice[["Total (valor)"], :]
                ).format({c: "{:.4f}" for c in tabla_mostrar.columns}, subset=pd.IndexSlice[["IHH"], :]),
                width="stretch",
            )
            grafico_datos = resultado.tabla_larga.pivot_table(index="anio", columns="grupo", values="participacion")
            st.bar_chart(grafico_datos)

        with tab_ihh:
            ihh_mostrar = resultado.ihh_por_anio.set_index("anio")[["ihh", "ihh_x10000", "interpretacion"]]
            ihh_mostrar.columns = ["IHH (fracción)", "IHH (x10,000)", "Interpretación"]
            st.dataframe(ihh_mostrar, width="stretch")

            if resultado.metricas_fusion is not None:
                fork_datos = datos_grafico_fork(resultado.ihh_por_anio, resultado.metricas_fusion)
                orden_x = list(dict.fromkeys(fork_datos["periodo"].tolist()))
                chart = (
                    alt.Chart(fork_datos)
                    .mark_line(point=True)
                    .encode(
                        x=alt.X("periodo:N", sort=orden_x, title="Año"),
                        y=alt.Y("ihh_x10000:Q", title="IHH (x10,000)"),
                        color=alt.Color("escenario:N", title=""),
                        strokeDash=alt.StrokeDash("escenario:N", legend=None),
                        tooltip=["periodo", "escenario", alt.Tooltip("ihh_x10000:Q", format=",.0f")],
                    )
                    .properties(height=320)
                )
                st.altair_chart(chart, use_container_width=True)
                st.caption(
                    "La línea 'Con fusión' nace del mismo punto real del último año y se separa "
                    "(quiebre) hacia el IHH post-fusión simulado."
                )
            else:
                st.line_chart(resultado.ihh_por_anio.set_index("anio")[["ihh_x10000"]])

            st.caption(
                "Umbrales estándar (escala x10,000): < 1,500 no concentrado · "
                "1,500–2,500 moderadamente concentrado · > 2,500 altamente concentrado."
            )

        with tab_fusion:
            if resultado.metricas_fusion is None:
                st.caption("Simulación de fusión apagada para esta vista -- prende el interruptor y vuelve a procesar.")
            else:
                metricas = resultado.metricas_fusion.copy()
                st.dataframe(
                    metricas.style.format({"Valor (fracción)": "{:.4f}", "Valor (x10,000)": "{:,.2f}"}, na_rep="—"),
                    width="stretch",
                    hide_index=True,
                )
                fila_pre = metricas[metricas["Métrica"].str.contains("Pre-Fusión")]
                fila_post = metricas[metricas["Métrica"].str.contains("Post-Fusión")]
                if not fila_pre.empty and not fila_post.empty:
                    ihh_pre_x10000 = fila_pre["Valor (x10,000)"].iloc[0]
                    ihh_post_x10000 = fila_post["Valor (x10,000)"].iloc[0]
                    mc1, mc2, mc3 = st.columns(3)
                    mc1.metric("IHH Pre-Fusión (x10,000)", f"{ihh_pre_x10000:,.0f}")
                    mc2.metric(
                        "IHH Post-Fusión (x10,000)",
                        f"{ihh_post_x10000:,.0f}",
                        delta=f"{(ihh_post_x10000 - ihh_pre_x10000):,.0f}",
                        delta_color="inverse",
                    )
                    mc3.metric("Interpretación post-fusión", interpretar_ihh(ihh_post_x10000))


def render():
    st.title("Concentración de mercado (IHH) y análisis de fusión")
    st.caption(
        "Obtén participación de mercado e Índice de Herfindahl-Hirschman (IHH) por "
        "año -- con simulación de fusión opcional entre dos grupos económicos."
    )

    modo = st.radio(
        "Modo de carga",
        options=["Tabla única", "3 bases (Oferta + Demanda + Transacciones)"],
        horizontal=True,
        key="modo_ihh",
    )

    st.divider()

    if modo == "Tabla única":
        _modo_tabla_unica()
    else:
        _modo_tres_bases()

    _mostrar_resultados()
