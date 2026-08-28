"""
sisap_scraper.py

Modulo reutilizable con la logica de consulta al SISAP (Sistema de
Abastecimiento y Precios) de MIDAGRI -- resumenes de precios/volumenes de
mercados mayoristas de Lima Metropolitana:
http://sistemas.midagri.gob.pe/sisap/portal2/mayorista/resumenes/consultar/

Descubierto por prueba y error (inspeccionando las llamadas AJAX del propio
portal):

- El formulario visible no navega a ninguna parte: al presionar "Consultar"
  dispara un POST por XHR a `resumenes/filtrar` y reemplaza un `<div>` con el
  HTML de respuesta (una tabla). Ese POST es el que replicamos aqui.
- El modo de periodicidad util para bajar series historicas es
  `periodicidad=intervalo` (pestania "Intervalo de Tiempo"): con `desde` y
  `hasta` (dd/mm/aaaa) devuelve UNA fila por dia con datos, sin importar
  cuantos anios de por medio -- no hace falta ir anio por anio.
- El servidor limita el "tamanio" de la consulta (fechas x variedades):
  si el rango es muy amplio responde
  `<p class=mensajeDeError>Demasiados criterios...`. La solucion es partir el
  rango de fechas a la mitad y reintentar recursivamente (ver
  `descargar_producto_mercado`).
- Si no hay datos para la combinacion pedida, responde
  `<p class=mensajeDeError>No existen resultados para los criterios
  elegidos.</p>` -- se interpreta como "sin datos", no como error.
- El precio_max/precio_prom/precio_min SI se pueden pedir agregados para
  todos los mercados de Lima Metropolitana a la vez (`mercado=*`), pero
  `volumen` SOLO trae valores reales si se pide un mercado especifico (con
  `mercado=*` la columna vuelve "..." -- no hay agregado de volumen).
- La respuesta HTML viene codificada en ISO-8859-1 (`Content-Type: text/html;
  charset=iso-8859-1`), igual que el portal de SUNAT.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable, Optional

import pandas as pd
import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# URLs del portal
# ---------------------------------------------------------------------------
URL_BASE = "http://sistemas.midagri.gob.pe/sisap/portal2/mayorista"
URL_CONSULTAR = f"{URL_BASE}/resumenes/consultar/"
URL_FILTRAR = f"{URL_BASE}/resumenes/filtrar"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}

VARIABLES = ["precio_max", "precio_prom", "precio_min", "volumen"]
MERCADO_TODOS = "*"  # "Lima Metropolitana" agregado (todos los mercados)

MENSAJE_SIN_DATOS = "no existen resultados"
MENSAJE_DEMASIADOS_CRITERIOS = "demasiados criterios"


@dataclass
class ResultadoConsulta:
    producto_codigo: str
    mercado_codigo: str
    desde: date
    hasta: date
    datos: pd.DataFrame
    n_requests: int = 1


# ---------------------------------------------------------------------------
# Sesion
# ---------------------------------------------------------------------------
def nueva_sesion() -> requests.Session:
    """Crea una sesion nueva. El portal entrega una cookie de sesion
    (`autentificator`) al cargar la pagina del formulario; sin ella el POST a
    `resumenes/filtrar` igual responde, pero conviene replicar la navegacion
    real."""
    s = requests.Session()
    s.headers.update({"User-Agent": HEADERS["User-Agent"]})
    s.get(URL_CONSULTAR, timeout=30)
    return s


# ---------------------------------------------------------------------------
# Descubrimiento de productos y mercados (se lee directo del HTML del
# formulario, para no tener que mantener las listas a mano si el portal
# agrega/quita productos)
# ---------------------------------------------------------------------------
def descubrir_productos(sesion: Optional[requests.Session] = None) -> dict[str, str]:
    """Devuelve {codigo_producto: nombre}, ej. {'1001': 'Aceite', ...}."""
    sesion = sesion or nueva_sesion()
    resp = sesion.get(URL_CONSULTAR, timeout=30)
    html = resp.content.decode("ISO-8859-1", errors="replace")
    soup = BeautifulSoup(html, "html.parser")

    productos: dict[str, str] = {}
    for chk in soup.select("input[name='productos[]']"):
        codigo = (chk.get("value") or "").strip()
        if not codigo or codigo == "NA":
            continue
        label = chk.find_parent("label")
        nombre = label.get_text(strip=True) if label else codigo
        productos[codigo] = nombre
    return productos


def descubrir_mercados(sesion: Optional[requests.Session] = None) -> dict[str, str]:
    """Devuelve {codigo_mercado: nombre}, incluyendo '*' -> 'Lima
    Metropolitana (todos los mercados)'."""
    sesion = sesion or nueva_sesion()
    resp = sesion.get(URL_CONSULTAR, timeout=30)
    html = resp.content.decode("ISO-8859-1", errors="replace")
    soup = BeautifulSoup(html, "html.parser")

    mercados: dict[str, str] = {MERCADO_TODOS: "Lima Metropolitana (todos los mercados)"}
    select = soup.find("select", attrs={"name": "mercado"})
    if select:
        for opt in select.find_all("option"):
            codigo = (opt.get("value") or "").strip()
            if not codigo or codigo == MERCADO_TODOS:
                continue
            mercados[codigo] = opt.get_text(strip=True)
    return mercados


# ---------------------------------------------------------------------------
# Consulta al endpoint AJAX
# ---------------------------------------------------------------------------
def _fmt(f: date) -> str:
    return f.strftime("%d/%m/%Y")


def consultar_intervalo(
    sesion: requests.Session,
    producto_codigo: str,
    mercado_codigo: str,
    desde: date,
    hasta: date,
    variables: list[str] = VARIABLES,
    timeout: int = 60,
) -> str:
    """Hace el POST a `resumenes/filtrar` en modo 'intervalo' (serie diaria
    entre `desde` y `hasta`) y devuelve el HTML de respuesta ya decodificado."""
    partes = [
        f"mercado={mercado_codigo}",
        "",
    ] + [f"variables[]={v}" for v in variables] + [
        "",
        f"fecha={_fmt(hasta)}",
        f"desde={_fmt(desde)}",
        f"hasta={_fmt(hasta)}",
        "",
        f"anios[]={hasta.year}",
        "",
        f"meses[]={hasta.month:02d}",
        "",
        f"semanas[]={hasta.isocalendar()[1]}",
        "",
        f"productos[]={producto_codigo}",
        "",
        "periodicidad=intervalo",
        "&&&&&&&&&&",
        "__ajax_carga_final=consulta",
        "ajax=true",
    ]
    body = "&".join(partes)
    resp = sesion.post(URL_FILTRAR, data=body.encode("ascii", errors="ignore"), headers=HEADERS, timeout=timeout)
    return resp.content.decode("ISO-8859-1", errors="replace")


# ---------------------------------------------------------------------------
# Parseo de la tabla de respuesta
# ---------------------------------------------------------------------------
_MAPA_VARIABLE = {
    "precio máximo": "precio_max",
    "precio maximo": "precio_max",
    "precio promedio": "precio_prom",
    "precio mínimo": "precio_min",
    "precio minimo": "precio_min",
    "volumen": "volumen",
}


def _clave_variable(texto: str) -> str:
    texto = re.sub(r"\s+", " ", texto).strip().lower()
    for clave, valor in _MAPA_VARIABLE.items():
        if texto.startswith(clave):
            return valor
    return texto


def parsear_tabla_intervalo(html: str) -> Optional[pd.DataFrame]:
    """Convierte el HTML de un reporte 'intervalo' en un DataFrame largo con
    columnas: fecha, variedad, variable, valor.

    Devuelve None si la respuesta es "sin datos". Lanza ValueError si la
    respuesta es "demasiados criterios" (quien llama debe partir el rango de
    fechas y reintentar) o si el HTML no tiene la forma esperada.
    """
    texto_plano = re.sub(r"<[^>]+>", " ", html).strip().lower()
    if MENSAJE_SIN_DATOS in texto_plano:
        return None
    if MENSAJE_DEMASIADOS_CRITERIOS in texto_plano:
        raise ValueError("demasiados_criterios")

    soup = BeautifulSoup(html, "html.parser")
    tabla = soup.find("table")
    if tabla is None:
        raise ValueError(f"Respuesta inesperada (sin tabla): {html[:200]!r}")

    filas = tabla.find_all("tr")
    filas_encabezado = [f for f in filas if "encabezado" in (f.get("class") or [])]
    filas_datos = [f for f in filas if "contenido" in (f.get("class") or [])]
    if len(filas_encabezado) < 2:
        raise ValueError(f"Encabezado inesperado: {html[:200]!r}")

    # Fila 1 de encabezado: nombre de variedad, repetido segun colspan
    # (ignora la primera celda "Fecha", que trae rowspan=2)
    variedades: list[str] = []
    celdas_fila1 = filas_encabezado[0].find_all("td")[1:]
    for celda in celdas_fila1:
        colspan = int(celda.get("colspan", 1))
        nombre = celda.get_text(strip=True)
        variedades.extend([nombre] * colspan)

    # Fila 2 de encabezado: variable (Precio Maximo/Promedio/Minimo/Volumen),
    # una celda por columna de datos
    variables_cols = [_clave_variable(c.get_text(" ", strip=True)) for c in filas_encabezado[1].find_all("td")]

    n_cols = min(len(variedades), len(variables_cols))
    columnas = list(zip(variedades[:n_cols], variables_cols[:n_cols]))

    registros = []
    for fila in filas_datos:
        celdas = fila.find_all("td")
        if not celdas:
            continue
        fecha_txt = celdas[0].get_text(strip=True)
        for (variedad, variable), celda in zip(columnas, celdas[1:]):
            valor_txt = celda.get_text(strip=True)
            if valor_txt in ("", "...", "-", "N/A"):
                continue
            valor = valor_txt.replace(",", "")
            try:
                valor = float(valor)
            except ValueError:
                continue
            registros.append({"fecha": fecha_txt, "variedad": variedad, "variable": variable, "valor": valor})

    if not registros:
        return None

    df = pd.DataFrame(registros)
    df["fecha"] = pd.to_datetime(df["fecha"], format="%d/%m/%Y", errors="coerce")
    df = df.dropna(subset=["fecha"])
    return df


# ---------------------------------------------------------------------------
# Descarga con particion adaptativa de fechas (para esquivar "Demasiados
# criterios" sin tener que adivinar de antemano un tamanio de bloque que
# sirva para todos los productos/mercados)
# ---------------------------------------------------------------------------
def descargar_producto_mercado(
    sesion: requests.Session,
    producto_codigo: str,
    mercado_codigo: str,
    desde: date,
    hasta: date,
    variables: list[str] = VARIABLES,
    pausa_entre_requests_seg: float = 1.0,
    reintentos_por_error_red: int = 3,
    on_status: Optional[Callable[[str], None]] = None,
    _profundidad: int = 0,
) -> pd.DataFrame:
    """Descarga la serie diaria completa de un producto en un mercado, para
    todo el rango [desde, hasta]. Si el portal rechaza el rango por
    'Demasiados criterios', lo parte a la mitad y reintenta recursivamente en
    cada mitad -- asi no hace falta saber de antemano cuanto historial
    real existe (las fechas sin datos simplemente no aparecen en la tabla)."""
    avisar = on_status or (lambda _msg: None)

    if desde > hasta:
        return pd.DataFrame(columns=["fecha", "variedad", "variable", "valor"])

    ultimo_error = None
    for intento in range(reintentos_por_error_red):
        try:
            html = consultar_intervalo(sesion, producto_codigo, mercado_codigo, desde, hasta, variables)
            break
        except requests.RequestException as e:
            ultimo_error = e
            time.sleep(2 * (intento + 1))
    else:
        avisar(f"  ! error de red tras {reintentos_por_error_red} intentos: {ultimo_error}")
        return pd.DataFrame(columns=["fecha", "variedad", "variable", "valor"])

    time.sleep(pausa_entre_requests_seg)

    try:
        df = parsear_tabla_intervalo(html)
    except ValueError as e:
        if "demasiados_criterios" in str(e) and desde < hasta:
            medio = desde + (hasta - desde) // 2
            avisar(f"{'  ' * _profundidad}-> rango {_fmt(desde)}-{_fmt(hasta)} muy grande, partiendo en dos")
            izquierda = descargar_producto_mercado(
                sesion, producto_codigo, mercado_codigo, desde, medio, variables,
                pausa_entre_requests_seg, reintentos_por_error_red, on_status, _profundidad + 1,
            )
            derecha = descargar_producto_mercado(
                sesion, producto_codigo, mercado_codigo, medio + timedelta(days=1), hasta, variables,
                pausa_entre_requests_seg, reintentos_por_error_red, on_status, _profundidad + 1,
            )
            return pd.concat([izquierda, derecha], ignore_index=True)
        avisar(f"  ! no se pudo interpretar la respuesta ({_fmt(desde)}-{_fmt(hasta)}): {e}")
        return pd.DataFrame(columns=["fecha", "variedad", "variable", "valor"])

    if df is None:
        return pd.DataFrame(columns=["fecha", "variedad", "variable", "valor"])
    return df
