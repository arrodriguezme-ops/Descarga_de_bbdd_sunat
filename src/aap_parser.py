"""
aap_parser.py

Extrae datos estructurados de un informe mensual de la AAP (PDF nativo, no
escaneado). Tres fuentes, dentro del mismo documento:

1. Tabla mensual principal "Venta de vehículos livianos y pesados"
   (Año x Ene..Dic, con todo el histórico desde 2017 hasta el mes del
   informe) -- SOLO aparece en algunas ediciones (se confirmó que ediciones
   más recientes la incluyen como anexo; muchas ediciones 2020-2024 NO la
   traen). Cuando está, es la única tabla del documento con bordes lo
   bastante limpios para parsear fila por fila de forma confiable.
2. El titular del mes propio del informe ("en <mes> de <año> se vendieron
   X unidades...") para livianos/pesados/menores, dentro del resumen
   ejecutivo -- SIEMPRE está presente, pero la AAP cambió la redacción de
   esta frase varias veces a lo largo de los años (al menos 4 estilos
   distintos detectados entre 2020 y 2026: "Venta vehículos livianos: ...
   vendieron X unidades", "livianos nuevos se ubicó en X unidades", "se
   vendieron X vehículos livianos", "livianos nuevos llegó a X unidades").
   Se cubre con varios patrones/verbos alternativos (best-effort: si la
   redacción de un mes puntual no matchea ninguno, esa celda queda vacía,
   no se inventa). Esta es la fuente principal de la serie mensual cuando
   no hay tabla-anexo (1).
3. Los totales acumulados (enero-mes del informe) por tipo de vehículo,
   que el resumen ejecutivo también repite como frase aparte -- se
   extraen por regex (best-effort, igual que (2)).

Nota de layout: muchas páginas de estos informes tienen dos columnas (una
barra lateral angosta + el texto principal). pdfplumber.extract_text()
por defecto intercala el texto de ambas columnas por posición vertical,
lo que rompe oraciones a la mitad. Por eso el texto para (2) y (3) se
reconstruye columna por columna (ver _texto_columnas_adaptativo) en vez de
usar extract_text() directo -- éste último sólo se usa para (1), que sale
bien porque esa tabla ocupa el ancho completo de la página.

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


def _texto_columnas_adaptativo(pagina) -> str:
    """Reconstruye el texto de una página respetando columnas: si detecta
    un "hueco" (gutter) ancho sin palabras cerca del centro de la página,
    separa en dos columnas y reconstruye cada una top-a-bottom / izq-a-der
    por separado (evita que se intercalen oraciones de la barra lateral
    con las del texto principal). Si no hay hueco claro (texto a ancho
    completo, como en varios informes narrativos), no separa nada."""
    palabras = pagina.extract_words(use_text_flow=False, keep_blank_chars=False)
    if not palabras:
        return ""

    ancho = pagina.width
    centros = sorted((w["x0"] + w["x1"]) / 2 for w in palabras)
    mejor_hueco, corte = 0.0, None
    for a, b in zip(centros, centros[1:]):
        medio = (a + b) / 2
        if ancho * 0.3 < medio < ancho * 0.7 and (b - a) > mejor_hueco:
            mejor_hueco, corte = b - a, medio

    def _reconstruir(lista_palabras) -> str:
        bandas: dict[int, list] = {}
        for w in lista_palabras:
            bandas.setdefault(round(w["top"] / 3), []).append(w)
        lineas = []
        for fila in sorted(bandas):
            palabras_fila = sorted(bandas[fila], key=lambda w: w["x0"])
            lineas.append(" ".join(w["text"] for w in palabras_fila))
        return "\n".join(lineas)

    UMBRAL_HUECO_PT = 25
    if mejor_hueco >= UMBRAL_HUECO_PT:
        izquierda = [w for w in palabras if (w["x0"] + w["x1"]) / 2 < corte]
        derecha = [w for w in palabras if (w["x0"] + w["x1"]) / 2 >= corte]
        return _reconstruir(izquierda) + "\n" + _reconstruir(derecha)
    return _reconstruir(palabras)


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


def extraer_totales_anuales(paginas_texto: list[str]) -> pd.DataFrame:
    """Misma tabla que extraer_serie_principal ('Año Ene..Dic Total a
    <mes> Total Anual'), pero se queda con las 2 columnas finales de cada
    fila -- el acumulado al mes del informe y el total anual -- que
    extraer_serie_principal descarta (solo usa los primeros 12
    tokens)."""
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
            if len(tokens) < 14:
                continue  # sin las 2 columnas de total, no hay nada que sacar aca
            total_acumulado = _a_numero(tokens[12])
            total_anual = _a_numero(tokens[13])
            # filtro de plausibilidad: el total anual de vehiculos
            # livianos+pesados en Peru siempre ha estado en el orden de
            # decenas/cientos de miles -- un valor de pocos miles (ej. un
            # "2008"/"2022" que en realidad son OTRO año colandose desde
            # una tabla vecina mal alineada) no es un total real, se
            # descarta en vez de guardar basura.
            if total_anual is not None and total_anual < 10_000:
                continue
            if total_acumulado is None and total_anual is None:
                continue
            filas_salida.append({
                "anio": anio,
                "total_acumulado_a_mes_informe": total_acumulado,
                "total_anual": total_anual,
            })

    if not filas_salida:
        return pd.DataFrame(columns=["anio", "total_acumulado_a_mes_informe", "total_anual"])

    df = pd.DataFrame(filas_salida).drop_duplicates(subset=["anio"], keep="last")
    return df.sort_values("anio").reset_index(drop=True)


_RE_FILA_VAR = re.compile(r"^Var\.?\s*%\s*(\d{2})/(\d{2})\s+(.+)$")


def extraer_variacion_interanual(paginas_texto: list[str]) -> pd.DataFrame:
    """Filas 'Var. % <añoB>/<añoA>' de la misma tabla -- variación
    porcentual mes a mes (y del acumulado/total anual) respecto al año
    anterior. Formato largo: anio_reciente, anio_anterior, concepto
    (Ene..Dic, Total_acumulado, Total_anual), var_pct."""
    filas_salida = []
    for texto in paginas_texto:
        if "Var. %" not in texto and "Var.%" not in texto:
            continue
        for linea in texto.splitlines():
            m = _RE_FILA_VAR.match(linea.strip())
            if not m:
                continue
            anio_reciente = 2000 + int(m.group(1))
            anio_anterior = 2000 + int(m.group(2))
            tokens = _RE_NUM.findall(m.group(3))
            if len(tokens) < 12:
                continue
            for i, mes_nombre in enumerate(MESES_ORDEN):
                if i >= 12:
                    break
                valor = _a_numero(tokens[i])
                if valor is not None:
                    filas_salida.append({
                        "anio_reciente": anio_reciente, "anio_anterior": anio_anterior,
                        "concepto": mes_nombre, "var_pct": valor / 100,
                    })
            for idx_token, concepto in ((12, "Total_acumulado"), (13, "Total_anual")):
                if idx_token < len(tokens):
                    valor = _a_numero(tokens[idx_token])
                    if valor is not None:
                        filas_salida.append({
                            "anio_reciente": anio_reciente, "anio_anterior": anio_anterior,
                            "concepto": concepto, "var_pct": valor / 100,
                        })

    if not filas_salida:
        return pd.DataFrame(columns=["anio_reciente", "anio_anterior", "concepto", "var_pct"])

    df = pd.DataFrame(filas_salida).drop_duplicates(subset=["anio_reciente", "anio_anterior", "concepto"], keep="last")
    return df.sort_values(["anio_reciente", "concepto"]).reset_index(drop=True)


# Frases fijas que el resumen ejecutivo repite todos los meses -- el numero
# de unidades acumuladas (enero -> mes del informe) para cada tipo.
_PATRONES_RESUMEN = {
    "Livianos": re.compile(r"comercializaron\s+([\d,]+)\s+unidades de veh[ií]culos livianos", re.I),
    # OJO: sin ancla al tipo, este patron matcheaba el PRIMER "se vendieron
    # X unidades" del documento (que suele ser el de Livianos) y lo
    # etiquetaba como Pesados -- ahora exige que "pesados" o "tractocamiones"
    # aparezca cerca, en la misma oracion.
    "Pesados": re.compile(
        r"(?:veh[ií]culos?\s+pesados|tractocamiones)[^.]{0,200}?"
        r"(?:se\s+vendieron|vendieron|se\s+situ[óo]\s+en|se\s+ubic[óo]\s+en)\s+([\d,]+)\s+unidades",
        re.I,
    ),
    "Menores": re.compile(r"comercializaron\s+([\d,]+)\s+unidades[,.]\s+n[uú]mero", re.I),
}

# Verbos que la AAP ha usado, en distintas ediciones, para reportar la
# cifra del PROPIO mes del informe (no acumulada) por tipo de vehículo.
_RE_NUM_TITULAR = r"([\d,]+(?:\.\d+)?)"
_VERBOS_TITULAR = (
    r"(?:vendieron|se\s+vendieron|se\s+ubic[óo]\s+en|se\s+situ[óo]\s+en|registr[óo]"
    r"|lleg[óo]\s+a|avanz[óo]\s+a|retrocedi[óo]\s+a|cay[óo]\s+a|descendi[óo]\s+a|ascendi[óo]\s+a)"
)

_PATRONES_TITULAR_MENSUAL = {
    "Livianos": [
        re.compile(
            rf"veh[ií]culos?\s+livianos(?!\s+y\s+pesados)[^.]{{0,150}}?{_VERBOS_TITULAR}\s+{_RE_NUM_TITULAR}",
            re.I,
        ),
        re.compile(rf"{_VERBOS_TITULAR}\s+{_RE_NUM_TITULAR}\s+veh[ií]culos?\s+livianos", re.I),
    ],
    "Pesados": [
        re.compile(rf"veh[ií]culos?\s+pesados[^.]{{0,150}}?{_VERBOS_TITULAR}\s+{_RE_NUM_TITULAR}", re.I),
        re.compile(rf"tractocamiones[^.]{{0,80}}?{_VERBOS_TITULAR}\s+{_RE_NUM_TITULAR}", re.I),
    ],
    "Menores": [
        re.compile(
            rf"veh[ií]culos?\s+menores(?!\s*\()[^.]{{0,150}}?{_VERBOS_TITULAR}\s+{_RE_NUM_TITULAR}",
            re.I,
        ),
        re.compile(
            rf"veh[ií]culos?\s+menores\s*\(motos\s+y\s+trimotos\)[^.]{{0,80}}?{_VERBOS_TITULAR}\s+{_RE_NUM_TITULAR}",
            re.I,
        ),
    ],
}


# Rango plausible de unidades vendidas EN UN SOLO MES (Peru, 2017-2026) por
# tipo -- sirve para descartar automaticamente los casos en que el regex
# atrapa por error una cifra ACUMULADA (varios meses) en vez de la mensual
# (la redaccion de "acumulado" y "del mes" es demasiado parecida en varias
# ediciones para distinguirlas de forma 100% confiable solo con texto).
_RANGO_PLAUSIBLE = {
    "Livianos": (1_000, 40_000),
    "Pesados": (100, 5_000),
    "Menores": (5_000, 90_000),
}


def _primer_match_plausible(texto: str, patrones: list[re.Pattern], tipo: str) -> Optional[float]:
    minimo, maximo = _RANGO_PLAUSIBLE[tipo]
    for patron in patrones:
        for m in patron.finditer(texto):
            valor = _a_numero(m.group(1))
            if valor is not None and minimo <= valor <= maximo:
                return valor
    return None


# Meses de confinamiento total (abril/mayo 2020): las concesionarias
# estuvieron cerradas y la venta fue -100%/nula, pero el resumen ejecutivo
# no dice "se vendieron 0 unidades" en ningun lado -- dice explicitamente
# que no hubo venta. Sin este detector, los patrones de arriba terminan
# atrapando por error algun numero suelto de otra parte del texto.
_RE_VENTA_NULA = re.compile(
    r"cay[óo]\s+-?100\s*%|no\s+se\s+registr[óo]\s+la\s+venta|permanecieron\s+cerradas",
    re.I,
)


def extraer_titular_mensual(paginas_texto_columnas: list[str]) -> dict[str, Optional[float]]:
    """Extrae, del resumen ejecutivo, la cifra del PROPIO mes del informe
    (no acumulada) por tipo de vehículo -- best-effort via varios patrones
    (la AAP cambió la redacción de esta frase varias veces entre 2020 y
    2026); si ninguno matchea (o el numero que matchea cae fuera del rango
    plausible para un solo mes -- suele ser una cifra acumulada mal
    capturada), ese tipo queda None (no se inventa)."""
    texto = " ".join(" ".join(t.split()) for t in paginas_texto_columnas)
    if _RE_VENTA_NULA.search(texto[:600]):
        return {"Livianos": 0.0, "Pesados": 0.0, "Menores": 0.0}
    return {
        tipo: _primer_match_plausible(texto, patrones, tipo)
        for tipo, patrones in _PATRONES_TITULAR_MENSUAL.items()
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
    import pdfplumber

    with pdfplumber.open(ruta_pdf) as pdf:
        paginas_texto = [p.extract_text() or "" for p in pdf.pages]
        # el resumen ejecutivo (titulares mensuales) siempre esta en las
        # primeras paginas -- no hace falta reconstruir el documento entero
        # columna por columna (mas lento).
        paginas_texto_columnas = [_texto_columnas_adaptativo(p) for p in pdf.pages[:6]]

    serie = extraer_serie_principal(paginas_texto)

    # Si la tabla-anexo (Año x Ene..Dic) no trae el propio mes del informe
    # (o no existe en esta edicion, que es lo mas comun en 2020-2024),
    # completamos esa unica celda con el titular del resumen ejecutivo
    # (Livianos + Pesados = mismo total que reportaria la tabla-anexo).
    ya_tiene_mes_propio = not serie.empty and (
        (serie["anio"] == anio_informe) & (serie["mes"] == mes_informe)
    ).any()
    if not ya_tiene_mes_propio:
        titular = extraer_titular_mensual(paginas_texto_columnas)
        livianos, pesados = titular.get("Livianos"), titular.get("Pesados")
        if livianos is not None and pesados is not None:
            fila_propia = pd.DataFrame([{
                "anio": anio_informe, "mes": mes_informe,
                "mes_nombre": MESES_ORDEN[mes_informe - 1],
                "unidades": livianos + pesados,
            }])
            serie = pd.concat([serie, fila_propia], ignore_index=True).sort_values(
                ["anio", "mes"]
            ).reset_index(drop=True)

    return {
        "serie_principal": serie,
        "resumen_por_tipo": extraer_resumen_por_tipo(paginas_texto, anio_informe, mes_informe),
        "totales_anuales": extraer_totales_anuales(paginas_texto),
        "variacion_interanual": extraer_variacion_interanual(paginas_texto),
    }
