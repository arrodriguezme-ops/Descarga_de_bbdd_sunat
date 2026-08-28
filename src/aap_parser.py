"""
aap_parser.py

Extrae datos estructurados de un informe mensual de la AAP (PDF nativo, no
escaneado). Dos fuentes, dentro del mismo documento:

1. Tabla mensual principal "Venta de vehículos livianos y pesados"
   (Año x Ene..Dic, con todo el histórico desde 2017 hasta el mes del
   informe) -- es la ÚNICA tabla del documento con bordes lo bastante
   limpios para parsear fila por fila de forma confiable (se probó con
   pdfplumber.extract_tables() y separa encabezado de datos porque las
   celdas no tienen bordes completos; el texto plano línea por línea SÍ
   sale limpio, así que se parsea así).
2. Los totales acumulados (enero-mes del informe) por tipo de vehículo
   (livianos / pesados / menores), que el resumen ejecutivo siempre repite
   como una frase con el número en unidades -- se extraen por regex.

Las tablas de ranking por marca/región/color/origen NO se parsean (tienen
layouts mucho más variables entre ediciones y con pdfplumber no salen
confiables) -- se pueden bajar los PDFs originales para revisarlas a mano.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import pandas as pd

MESES_ORDEN = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Set", "Oct", "Nov", "Dic"]

_RE_FILA_ANUAL = re.compile(r"^(\d{4})\s+(.+)$")
_RE_NUM = re.compile(r"-?[\d,]+(?:\.\d+)?|-")


def _texto_completo(ruta_pdf: Path) -> list[str]:
    import pdfplumber

    with pdfplumber.open(ruta_pdf) as pdf:
        return [p.extract_text() or "" for p in pdf.pages]


def _a_numero(token: str) -> Optional[float]:
    token = token.strip()
    if token in ("-", "", "—"):
        return None
    try:
        return float(token.replace(",", ""))
    except ValueError:
        return None


def extraer_serie_principal(paginas_texto: list[str]) -> pd.DataFrame:
    """Busca la tabla 'Año Ene Feb ... Dic Total Anual' (ventas de
    vehículos livianos y pesados combinados) y la devuelve en formato
    largo: anio, mes, unidades."""
    filas_salida = []
    for texto in paginas_texto:
        if "Ene Feb Mar" not in texto and "Ene\nFeb" not in texto.replace(" ", "\n"):
            if "Ene" not in texto or "Dic" not in texto:
                continue
        for linea in texto.splitlines():
            m = _RE_FILA_ANUAL.match(linea.strip())
            if not m:
                continue
            anio = int(m.group(1))
            if not (2000 <= anio <= 2100):
                continue
            tokens = _RE_NUM.findall(m.group(2))
            if len(tokens) < 12:
                continue
            for i, mes_nombre in enumerate(MESES_ORDEN):
                if i >= len(tokens):
                    break
                valor = _a_numero(tokens[i])
                if valor is not None:
                    filas_salida.append({"anio": anio, "mes": i + 1, "mes_nombre": mes_nombre, "unidades": valor})

    if not filas_salida:
        return pd.DataFrame(columns=["anio", "mes", "mes_nombre", "unidades"])

    df = pd.DataFrame(filas_salida).drop_duplicates(subset=["anio", "mes"], keep="last")
    return df.sort_values(["anio", "mes"]).reset_index(drop=True)


# Frases fijas que el resumen ejecutivo repite todos los meses -- el numero
# de unidades acumuladas (enero -> mes del informe) para cada tipo.
_PATRONES_RESUMEN = {
    "Livianos": re.compile(r"comercializaron\s+([\d,]+)\s+unidades de veh[ií]culos livianos", re.I),
    "Pesados": re.compile(r"se vendieron\s+([\d,]+)\s+unidades[,.]", re.I),
    "Menores": re.compile(r"comercializaron\s+([\d,]+)\s+unidades[,.]\s+n[uú]mero", re.I),
}


def extraer_resumen_por_tipo(paginas_texto: list[str], anio_informe: int, mes_informe: int) -> pd.DataFrame:
    """Extrae, del resumen ejecutivo, el total acumulado (enero -> mes del
    informe) por tipo de vehículo (Livianos/Pesados/Menores) -- best-effort
    via regex sobre frases que el informe repite cada edición; si la
    redacción cambió ese mes y no matchea, queda NaN (no se inventa)."""
    texto_junto = "\n".join(paginas_texto[:8])  # el resumen ejecutivo esta en las primeras paginas
    texto_junto = " ".join(texto_junto.split())  # colapsar saltos de linea para que el regex no se corte

    filas = []
    for tipo, patron in _PATRONES_RESUMEN.items():
        m = patron.search(texto_junto)
        unidades = _a_numero(m.group(1)) if m else None
        filas.append({
            "anio_informe": anio_informe, "mes_informe": mes_informe,
            "tipo_vehiculo": tipo, "unidades_acumuladas_enero_a_mes": unidades,
        })
    return pd.DataFrame(filas)


def parsear_informe(ruta_pdf: Path, anio_informe: int, mes_informe: int) -> dict:
    paginas_texto = _texto_completo(ruta_pdf)
    return {
        "serie_principal": extraer_serie_principal(paginas_texto),
        "resumen_por_tipo": extraer_resumen_por_tipo(paginas_texto, anio_informe, mes_informe),
    }
