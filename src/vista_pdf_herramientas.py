"""
vista_pdf_herramientas.py

Servicio de herramientas de PDF, con 3 pestañas:
1. PDF -> Markdown (pymupdf4llm)
2. OCR -> PDF (ocrmypdf + Tesseract) -- convierte un PDF escaneado (o
   imagen) en un PDF con capa de texto seleccionable/buscable.
3. Búsqueda de PDFs en reguladores -- busca hasta 20 palabras clave en el
   buscador oficial de gob.pe (normas legales de cualquier entidad/
   regulador peruano), exporta un Excel con enlace directo de descarga de
   cada PDF encontrado, y muestra estadísticos/gráficos por palabra clave
   y por autoridad.
"""

import io
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ / "src") not in sys.path:
    sys.path.insert(0, str(RAIZ / "src"))

from gobpe_buscador import MAX_KEYWORDS, buscar_multiples_keywords, verificar_pdf  # noqa: E402
from pdf_herramientas import idiomas_ocr_disponibles, ocr_a_pdf, pdf_a_markdown, ruta_temporal  # noqa: E402

CARPETA_SALIDA = RAIZ / "data" / "busqueda_normas"
CARPETA_SALIDA.mkdir(parents=True, exist_ok=True)


def _tab_pdf_a_markdown():
    st.subheader("Convertir PDF a Markdown")
    st.caption(
        "Usa pymupdf4llm -- rápido y sin descargar ningún modelo, funciona mejor con "
        "PDFs de texto nativo. Si tu PDF es escaneado, primero pásalo por la pestaña "
        "'OCR → PDF' de al lado."
    )
    archivo = st.file_uploader("Sube un PDF", type=["pdf"], key="archivo_pdf_md")
    if archivo is None:
        return

    ruta_tmp = ruta_temporal(".pdf")
    ruta_tmp.write_bytes(archivo.getvalue())
    try:
        with st.spinner("Convirtiendo..."):
            markdown = pdf_a_markdown(ruta_tmp)
    except Exception as e:  # noqa: BLE001
        st.error(f"No se pudo convertir: {e}")
        return
    finally:
        ruta_tmp.unlink(missing_ok=True)

    st.success(f"{len(markdown):,} caracteres de Markdown generados.")
    with st.expander("Vista previa"):
        st.text(markdown[:5000] + ("..." if len(markdown) > 5000 else ""))

    nombre_salida = Path(archivo.name).stem + ".md"
    st.download_button(
        "⬇️ Descargar Markdown", data=markdown.encode("utf-8"), file_name=nombre_salida,
        mime="text/markdown", width="stretch",
    )


def _tab_ocr_a_pdf():
    st.subheader("OCR → PDF (agregar capa de texto buscable)")
    st.caption(
        "Usa ocrmypdf + Tesseract -- toma un PDF escaneado (o una imagen) y devuelve "
        "un PDF con el mismo aspecto, pero con texto seleccionable y buscable."
    )
    archivo = st.file_uploader("Sube un PDF (o imagen JPG/PNG)", type=["pdf", "jpg", "jpeg", "png"], key="archivo_ocr")
    if archivo is None:
        return

    idiomas_disp = idiomas_ocr_disponibles()
    c1, c2 = st.columns(2)
    with c1:
        idiomas = st.multiselect(
            "Idioma(s)", options=idiomas_disp,
            default=[i for i in ("spa", "eng") if i in idiomas_disp] or idiomas_disp[:1],
        )
    with c2:
        deskew = st.checkbox("Enderezar páginas torcidas (deskew)", value=True)

    c3, c4 = st.columns(2)
    with c3:
        forzar_ocr = st.checkbox("Forzar OCR (rehacer aunque ya tenga texto)", value=False)
    with c4:
        invalidar_firma = st.checkbox(
            "Permitir invalidar firma digital",
            value=False,
            help="Muchos PDFs oficiales (ej. gob.pe) vienen firmados digitalmente -- "
            "el OCR los modifica, así que por defecto se rechaza tocarlos.",
        )

    if not st.button("Procesar OCR", type="primary", width="stretch"):
        return

    sufijo = Path(archivo.name).suffix or ".pdf"
    ruta_entrada = ruta_temporal(sufijo)
    ruta_entrada.write_bytes(archivo.getvalue())
    ruta_salida = ruta_temporal(".pdf")

    with st.spinner("Corriendo OCR... puede tardar uno o dos minutos según el tamaño del PDF."):
        ok, mensaje = ocr_a_pdf(
            ruta_entrada, ruta_salida, idiomas=idiomas or ["spa"],
            forzar_ocr=forzar_ocr, deskew=deskew, invalidar_firma_digital=invalidar_firma,
        )

    if ok:
        st.success(f"Listo -- {mensaje}")
        st.download_button(
            "⬇️ Descargar PDF con OCR", data=ruta_salida.read_bytes(),
            file_name=Path(archivo.name).stem + "_ocr.pdf", mime="application/pdf", width="stretch",
        )
    else:
        st.error(mensaje)

    ruta_entrada.unlink(missing_ok=True)
    ruta_salida.unlink(missing_ok=True)


@st.cache_data(show_spinner=False)
def _exportar_excel(df: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    df.to_excel(buffer, index=False, sheet_name="Resultados")
    return buffer.getvalue()


def _tab_busqueda_reguladores():
    st.subheader("Búsqueda de PDFs en reguladores (gob.pe)")
    st.caption(
        f"Busca hasta {MAX_KEYWORDS} palabras clave en el buscador oficial de normas "
        "legales de gob.pe (abarca todas las entidades/reguladores del Estado peruano: "
        "ministerios, OSINERGMIN, SBS, INDECOPI, municipalidades, etc.). El buscador de "
        "gob.pe ya indexa el texto completo de cada PDF, así que no hace falta "
        "descargarlos todos de antemano."
    )

    texto_keywords = st.text_area(
        f"Palabras clave (una por línea o separadas por coma, máximo {MAX_KEYWORDS})",
        placeholder="electromovilidad\nmovilidad eléctrica\nexoneración tributaria\n...",
        height=140,
    )
    keywords = [k.strip() for k in texto_keywords.replace(",", "\n").splitlines() if k.strip()][:MAX_KEYWORDS]
    if texto_keywords.strip():
        st.caption(f"{len(keywords)} palabra(s) clave detectada(s).")

    c1, c2 = st.columns(2)
    with c1:
        paginas_max = st.slider("Páginas de resultados por palabra clave (25 c/u)", 1, 10, 3)
    with c2:
        institucion = st.text_input("Filtrar por institución (opcional, ej. 'osinergmin')", value="")

    buscar = st.button("Buscar", type="primary", width="stretch")

    if not buscar and "resultados_normas" not in st.session_state:
        return

    if buscar:
        if not keywords:
            st.warning("Escribe al menos una palabra clave.")
            return

        placeholder_estado = st.empty()
        estado = {}

        def on_status(info):
            estado[info["keyword"]] = info
            filas = [
                {"Palabra clave": k, "Estado": v["estado"], "Detalle": v.get("mensaje", "")}
                for k, v in estado.items()
            ]
            placeholder_estado.dataframe(pd.DataFrame(filas), hide_index=True, width="stretch")

        with st.spinner("Buscando en gob.pe..."):
            df = buscar_multiples_keywords(
                keywords, paginas_max=paginas_max,
                institucion=institucion.strip() or None, on_status=on_status,
            )

        df = df.drop_duplicates(subset=["pdf_url", "keyword"]).reset_index(drop=True)
        st.session_state.resultados_normas = df

    df = st.session_state.get("resultados_normas")
    if df is None or df.empty:
        st.info("Sin resultados todavía." if df is not None else "")
        return

    st.divider()
    st.subheader(f"Resultados: {len(df)} coincidencias, {df['pdf_url'].nunique()} documentos únicos")
    st.dataframe(
        df[["keyword", "titulo", "autoridad", "tipo_documento", "fecha_publicacion", "pdf_url", "snippet"]],
        width="stretch", hide_index=True,
    )

    st.download_button(
        "📥 Descargar Excel (con enlace directo de descarga por fila)",
        data=_exportar_excel(df), file_name="busqueda_normas_gobpe.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch",
    )

    st.divider()
    st.subheader("Estadísticos y gráficos")

    g1, g2 = st.columns(2)
    with g1:
        st.markdown("**Documentos por palabra clave**")
        st.bar_chart(df["keyword"].value_counts())
    with g2:
        st.markdown("**Top 15 autoridades con más coincidencias**")
        st.bar_chart(df["autoridad"].value_counts().head(15))

    st.markdown("**Tabla cruzada: palabra clave × autoridad (top 10 autoridades)**")
    top_autoridades = df["autoridad"].value_counts().head(10).index
    cruzada = pd.crosstab(df[df["autoridad"].isin(top_autoridades)]["autoridad"], df[df["autoridad"].isin(top_autoridades)]["keyword"])
    st.dataframe(cruzada, width="stretch")

    st.divider()
    with st.expander("Verificación profunda (opcional, más lenta): descargar y confirmar dentro del PDF"):
        st.caption(
            "Descarga cada PDF a un archivo temporal, extrae el texto página por "
            "página, confirma la keyword adentro y da el número de página exacto -- "
            "nunca deja el PDF guardado en disco. Útil si el snippet de gob.pe no "
            "alcanza. Corre solo sobre los primeros N documentos únicos para no demorar horas."
        )
        n_verificar = st.slider("Cuántos documentos únicos verificar", 1, 30, 5, key="n_verificar")
        if st.button("Verificar", key="verificar_btn"):
            urls_unicas = df["pdf_url"].drop_duplicates().head(n_verificar).tolist()
            progreso = st.progress(0.0)
            filas_verif = []
            for i, url in enumerate(urls_unicas):
                kws_de_ese_doc = df.loc[df["pdf_url"] == url, "keyword"].unique().tolist()
                resultado = verificar_pdf(url, kws_de_ese_doc)
                if resultado.coincidencias is not None:
                    bloque = resultado.coincidencias.copy()
                    bloque["pdf_url"] = url
                    filas_verif.append(bloque)
                progreso.progress((i + 1) / len(urls_unicas))
            if filas_verif:
                st.dataframe(pd.concat(filas_verif, ignore_index=True), width="stretch", hide_index=True)
            else:
                st.info("No se encontraron coincidencias verificadas dentro del texto de esos PDFs.")


def render():
    st.title("Herramientas de PDF")
    st.caption(
        "Convertir PDF a Markdown, agregar OCR a un PDF escaneado, y buscar normas por "
        "palabra clave en reguladores peruanos -- todo corre localmente."
    )

    tab1, tab2, tab3 = st.tabs(["📄 PDF → Markdown", "🔎 OCR → PDF", "🏛️ Búsqueda en reguladores"])
    with tab1:
        _tab_pdf_a_markdown()
    with tab2:
        _tab_ocr_a_pdf()
    with tab3:
        _tab_busqueda_reguladores()
