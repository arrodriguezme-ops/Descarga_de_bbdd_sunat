"""
gobpe_buscador.py

Busca normas legales (resoluciones, decretos, directivas, etc.) publicadas
por entidades/reguladores peruanos en el buscador oficial de gob.pe, por
palabra clave -- hasta 20 keywords por corrida.

Traducido y generalizado a partir de un script en R que asumia una tabla
pre-armada de normas (resultado de un "paso 1" que buscaba en gob.pe) y
solo hacia el "paso 2" (descargar cada PDF a un temporal, extraer texto y
buscar las keywords adentro). Acá se hacen los dos pasos en uno: el
buscador de gob.pe (www.gob.pe/busquedas.json) YA hace busqueda de texto
completo dentro de los documentos e indica coincidencias -- por lo que ese
es el "paso 1" natural, sin necesitar una tabla previa. Opcionalmente
(paso 2, apagado por defecto porque es mucho mas lento) se puede verificar
cada PDF descargandolo a un archivo temporal y buscando la keyword dentro
del texto extraido pagina por pagina, igual que hacia el script en R --
util cuando el snippet de gob.pe no alcanza o se quiere el numero de
pagina exacto de la coincidencia.
"""

from __future__ import annotations

import re
import tempfile
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import pandas as pd
import requests

URL_BUSQUEDA = "https://www.gob.pe/busquedas.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

MAX_KEYWORDS = 20
RESULTADOS_POR_PAGINA = 25

_RE_TAG = re.compile(r"<[^>]+>")


def _quitar_html(texto: Optional[str]) -> str:
    if not texto:
        return ""
    return _RE_TAG.sub("", texto).strip()


def _normalizar(texto: str) -> str:
    """Quita tildes y pasa a minusculas (para comparar sin depender de acentos)."""
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return texto.lower()


def _extraer_href(campo_url_html: str) -> Optional[str]:
    m = re.search(r'href="([^"]+)"', campo_url_html or "")
    if not m:
        return None
    href = m.group(1)
    if href.startswith("/"):
        return "https://www.gob.pe" + href
    return href


def _extraer_autoridad(content_sub_title_card: Optional[str]) -> str:
    """content_sub_title_card viene como 'SIGLA - Nombre completo de la entidad'."""
    if not content_sub_title_card:
        return "(no especificada)"
    partes = content_sub_title_card.split(" - ", 1)
    return partes[1].strip() if len(partes) == 2 else content_sub_title_card.strip()


def buscar_keyword(
    keyword: str,
    contenido: str = "normas",
    institucion: Optional[str] = None,
    paginas_max: int = 3,
    pausa_seg: float = 0.3,
    sesion: Optional[requests.Session] = None,
) -> pd.DataFrame:
    """Busca UNA keyword en el buscador de gob.pe, paginando hasta
    paginas_max paginas (25 resultados c/u). Devuelve un DataFrame con una
    fila por documento encontrado."""
    sesion = sesion or requests.Session()
    filas = []

    for pagina in range(1, paginas_max + 1):
        params = {"contenido[]": contenido, "term": keyword, "sort_by": "relevance", "page": pagina}
        if institucion:
            params["institucion"] = institucion
        try:
            resp = sesion.get(URL_BUSQUEDA, params=params, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError):
            break

        resultados = data.get("data", {}).get("attributes", {}).get("results", [])
        if not resultados:
            break

        for r in resultados:
            pdf_url = r.get("action_url")
            if not pdf_url or not str(pdf_url).lower().endswith(".pdf"):
                continue  # solo nos interesan documentos con PDF descargable
            filas.append({
                "keyword": keyword,
                "id_gobpe": r.get("id"),
                "titulo": r.get("name_with_parent") or _quitar_html(r.get("url", "")),
                "autoridad": _extraer_autoridad(r.get("content_sub_title_card")),
                "tipo_documento": r.get("group_type") or r.get("official_document_type") or "",
                "fecha_publicacion": (r.get("publication") or "").strip(),
                "pdf_url": pdf_url,
                "pagina_gobpe": _extraer_href(r.get("url", "")),
                "snippet": _quitar_html(r.get("content")),
                "score": r.get("score"),
            })

        if len(resultados) < RESULTADOS_POR_PAGINA:
            break  # ya no hay mas paginas
        time.sleep(pausa_seg)

    return pd.DataFrame(filas)


def buscar_multiples_keywords(
    keywords: list[str],
    contenido: str = "normas",
    institucion: Optional[str] = None,
    paginas_max: int = 3,
    pausa_seg: float = 0.3,
    on_status: Optional[Callable[[dict], None]] = None,
) -> pd.DataFrame:
    """Busca varias keywords (hasta MAX_KEYWORDS) y consolida todo en un
    solo DataFrame. Un mismo documento puede aparecer varias veces si
    calza con mas de una keyword (una fila por combinacion documento x
    keyword, para poder sacar estadisticos por palabra clave)."""
    keywords = [k.strip() for k in keywords if k and k.strip()][:MAX_KEYWORDS]
    if not keywords:
        return pd.DataFrame()

    sesion = requests.Session()
    partes = []
    for i, kw in enumerate(keywords, start=1):
        if on_status:
            on_status({"keyword": kw, "indice": i, "total": len(keywords), "estado": "Buscando"})
        try:
            df_kw = buscar_keyword(
                kw, contenido=contenido, institucion=institucion,
                paginas_max=paginas_max, pausa_seg=pausa_seg, sesion=sesion,
            )
        except Exception as e:  # noqa: BLE001
            if on_status:
                on_status({"keyword": kw, "indice": i, "total": len(keywords), "estado": "Error", "mensaje": str(e)})
            continue
        partes.append(df_kw)
        if on_status:
            on_status({
                "keyword": kw, "indice": i, "total": len(keywords),
                "estado": "Completado", "mensaje": f"{len(df_kw)} documentos",
            })

    if not partes:
        return pd.DataFrame()
    return pd.concat(partes, ignore_index=True)


# ---------------------------------------------------------------------------
# Verificacion profunda opcional (equivalente al "paso 2" del script en R):
# descarga cada PDF a un temporal, extrae texto pagina por pagina, confirma
# la keyword en el propio texto (sin depender del snippet de gob.pe) y
# devuelve el numero de pagina + contexto exacto. Mas lento -- pensado para
# correr solo sobre el subconjunto de resultados que interesan de verdad.
# ---------------------------------------------------------------------------
@dataclass
class ResultadoVerificacion:
    estado: str
    paginas_totales: Optional[int] = None
    paginas_con_texto: Optional[int] = None
    parece_escaneado: Optional[bool] = None
    coincidencias: Optional[pd.DataFrame] = None
    error_detalle: Optional[str] = None


def _extraer_contexto(texto_pagina: str, keyword_norm: str, radio: int = 100) -> Optional[str]:
    texto_norm = _normalizar(texto_pagina)
    pos = texto_norm.find(keyword_norm)
    if pos == -1:
        return None
    ini = max(0, pos - radio)
    fin = min(len(texto_pagina), pos + len(keyword_norm) + radio)
    return " ".join(texto_pagina[ini:fin].split())


def verificar_pdf(
    pdf_url: str,
    keywords: list[str],
    umbral_caracteres: int = 20,
    timeout_seg: int = 60,
) -> ResultadoVerificacion:
    """Descarga pdf_url a un archivo TEMPORAL, extrae el texto (pdfplumber),
    busca las keywords pagina por pagina, y borra el temporal al terminar
    -- nunca deja el PDF en disco (igual que el script en R original)."""
    if not pdf_url:
        return ResultadoVerificacion(estado="SIN_URL")

    import pdfplumber

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        ruta_tmp = Path(tmp.name)

    try:
        try:
            resp = requests.get(pdf_url, headers=HEADERS, timeout=timeout_seg)
            resp.raise_for_status()
        except requests.RequestException as e:
            return ResultadoVerificacion(estado="ERROR_DESCARGA", error_detalle=str(e))

        if len(resp.content) < 100:
            return ResultadoVerificacion(estado="ARCHIVO_VACIO_O_INVALIDO")

        ruta_tmp.write_bytes(resp.content)

        try:
            with pdfplumber.open(ruta_tmp) as pdf:
                paginas_texto = [(p.extract_text() or "") for p in pdf.pages]
        except Exception as e:  # noqa: BLE001
            return ResultadoVerificacion(estado="ERROR_LECTURA_PDF", error_detalle=str(e))

        if not paginas_texto:
            return ResultadoVerificacion(estado="ERROR_LECTURA_PDF", error_detalle="PDF sin paginas")

        n_total = len(paginas_texto)
        n_con_texto = sum(1 for t in paginas_texto if len(t.strip()) >= umbral_caracteres)
        parece_escaneado = (n_total - n_con_texto) / n_total > 0.5

        filas = []
        for num_pagina, texto_pagina in enumerate(paginas_texto, start=1):
            if len(texto_pagina.strip()) < umbral_caracteres:
                continue
            texto_norm = _normalizar(texto_pagina)
            for kw in keywords:
                kw_norm = _normalizar(kw)
                if kw_norm in texto_norm:
                    filas.append({
                        "pagina": num_pagina, "keyword": kw,
                        "contexto": _extraer_contexto(texto_pagina, kw_norm),
                    })

        coincidencias = pd.DataFrame(filas) if filas else None
        if parece_escaneado:
            estado = "PROBABLE_ESCANEADO"
        elif coincidencias is not None:
            estado = "OK_CON_COINCIDENCIAS"
        else:
            estado = "OK_SIN_COINCIDENCIAS"

        return ResultadoVerificacion(
            estado=estado, paginas_totales=n_total, paginas_con_texto=n_con_texto,
            parece_escaneado=parece_escaneado, coincidencias=coincidencias,
        )
    finally:
        ruta_tmp.unlink(missing_ok=True)
