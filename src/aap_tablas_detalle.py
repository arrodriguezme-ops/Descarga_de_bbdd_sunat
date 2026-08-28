"""
aap_tablas_detalle.py

Extractor "de máximo esfuerzo" para TODA la información de los informes
mensuales de AAP (no solo la serie mensual principal, que ya cubre
aap_parser.py). Los informes desde ~2022 son documentos de 46-77 páginas
con muchas secciones (venta livianos/pesados/menores/lujo/eléctricos,
importaciones, transferencias de seminuevos, financiamiento), cada una
con varios tipos de contenido:

1. TABLAS DE GRILLA genuinas (ej. "Por color", "Por origen de
   fabricación", "Motos por combustible y cilindrada" con columnas
   mensuales Ene-Jul por marca) -- se detectan buscando
   pdfplumber.extract_tables(strategy="text") con >=3 columnas y >=4
   filas de datos numéricos. Esta es la fuente MÁS confiable (texto
   real, sin geometría que adivinar) y la que más variedad de
   desagregación aporta (por color/origen/combustible/marca/mes).

2. RANKINGS "Por marca" (tarjetas numeradas con logo + cifras) -- se
   detectan por el patrón de rango "1 2 3 ... N" seguido de nombres de
   marca y cifras "2025: X" / "2026: Y". Se parsean por regex sobre el
   texto (no requieren geometría porque cada tarjeta es autocontenida).

3. GRÁFICOS DE BARRA anuales por segmento ("a [mes] de cada año", con
   TODAS las barras etiquetadas) -- las etiquetas de valor y de
   variación % quedan como texto flotante sobre cada barra, sin marcador
   de a qué año corresponden. Se asume orden ordinal: el valor más a la
   izquierda es el año más antiguo del rango (siempre 10 años, terminan
   en el año del informe). Ocasionalmente dos etiquetas se superponen
   visualmente y sus caracteres quedan intercalados por pdfplumber -- en
   esos casos la fila queda incompleta en vez de inventar un valor.

4. MAPAS "Por oficina registral" -- cada oficina es una caja de texto
   flotante (nombre, unidades, var%, part%) posicionada sobre un mapa.
   Se agrupan las palabras por proximidad (mismo bloque = misma caja) en
   vez de leerlas en orden de texto plano.

5. LÍNEAS DE TIEMPO SIN etiquetar cada punto (ej. importaciones o
   financiamiento mes a mes 2020-2026, donde solo el primer y el último
   punto tienen texto) -- se reconstruyen las demás desde las
   coordenadas del trazo vectorial (bezier) del PDF, calibradas contra
   los ejes. Validado contra valores conocidos: el error puede ser de
   hasta ~20% porque el suavizado de la curva no pasa exactamente por
   el dato real -- por eso estas filas se exportan con
   confianza="baja" en vez de mezclarse con las demás (más confiables).

No todos los informes tienen todas estas secciones (solo desde ~2022 en
adelante; 2020-2021 son documentos de 14-15 páginas sin nada de esto).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

MESES_ABREV = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Set", "Oct", "Nov", "Dic"]
_RE_MES_COL = re.compile(r"^(Ene|Feb|Mar|Abr|May|Jun|Jul|Ago|Set|Sep|Oct|Nov|Dic)-?(\d{2})$", re.I)
_RE_NUM = re.compile(r"^-?[\d,]+(?:\.\d+)?%?$")


def _a_numero(token: str) -> Optional[float]:
    token = (token or "").strip().replace('"', "")
    if token in ("-", "", "—", "n/a", "N/A"):
        return None
    es_pct = token.endswith("%")
    token = token.rstrip("%")
    try:
        val = float(token.replace(",", ""))
    except ValueError:
        return None
    return val / 100.0 if es_pct else val


def _titulo_pagina(texto: str) -> tuple[str, str]:
    """(seccion, subtitulo) a partir de las primeras 1-3 lineas de texto
    de la pagina -- la seccion es el encabezado grande (ej. "Venta de
    vehiculos livianos") y el subtitulo la linea siguiente relevante
    (ej. "Por origen de fabricacion")."""
    # "Volver al indice" suele venir pegado a la MISMA linea que el
    # titulo (comparten renglon en el PDF) -- hay que recortarlo del
    # final de la linea, no descartar la linea entera, o se pierde el
    # titulo real de la seccion.
    lineas = []
    for l in texto.splitlines():
        l = re.sub(r"Volver al.*$", "", l, flags=re.I).strip()
        if l:
            lineas.append(l)
    seccion = lineas[0] if lineas else ""
    subtitulo = ""
    for l in lineas[1:4]:
        if l.lower().startswith(("fuente", "elaborac")):
            continue
        subtitulo = l
        break
    return seccion, subtitulo


# ---------------------------------------------------------------------
# 1. Tablas de grilla genuinas
# ---------------------------------------------------------------------

def extraer_tablas_grilla(pagina, anio_informe: int, mes_informe: int) -> list[pd.DataFrame]:
    """Busca tablas con encabezado + filas de datos numericos usando
    extract_tables(strategy='text') (mas confiable que el default
    'lines' para estos informes, que no siempre dibujan bordes
    completos). Devuelve una lista de DataFrames (una tabla puede venir
    partida en varias por pdfplumber; se intenta unir por columnas)."""
    try:
        tablas_crudas = pagina.extract_tables({"vertical_strategy": "text", "horizontal_strategy": "text"})
    except Exception:
        return []

    resultados = []
    texto = pagina.extract_text() or ""
    seccion, subtitulo = _titulo_pagina(texto)

    def _es_fila_numerica(f) -> bool:
        celdas = [c.strip() for c in f if c and c.strip()]
        return len(celdas) >= 3 and sum(1 for c in celdas if _RE_NUM.match(c)) >= max(2, len(celdas) // 2)

    for tabla in tablas_crudas:
        filas = [f for f in tabla if any((c or "").strip() for c in f)]
        if len(filas) < 5:
            continue
        # localizar la fila de encabezado: una fila mayormente NO
        # numerica cuya fila siguiente (con contenido) SI sea mayormente
        # numerica -- evita que el titulo de la pagina (tambien texto no
        # numerico) se confunda con el encabezado real de la tabla.
        idx_header = None
        for i, f in enumerate(filas[:-1]):
            celdas = [c.strip() for c in f if c and c.strip()]
            if len(celdas) < 3 or sum(1 for c in celdas if _RE_NUM.match(c)) > len(celdas) // 2:
                continue
            siguientes = [g for g in filas[i + 1: i + 3] if any((c or "").strip() for c in g)]
            if siguientes and _es_fila_numerica(siguientes[0]):
                idx_header = i
                break
        if idx_header is None:
            continue

        fila_header = filas[idx_header]
        columnas = [(" ".join(c.split()) if c else f"col{i}") for i, c in enumerate(fila_header)]
        # columnas duplicadas (headers partidos en 2 lineas que colapsan
        # al mismo texto) rompen el constructor de DataFrame -- desambiguar
        vistos: dict[str, int] = {}
        columnas_unicas = []
        for c in columnas:
            vistos[c] = vistos.get(c, 0) + 1
            columnas_unicas.append(c if vistos[c] == 1 else f"{c}_{vistos[c]}")
        columnas = columnas_unicas
        n_col = len(columnas)

        filas_datos = []
        for f in filas[idx_header + 1:]:
            if sum(1 for c in f if c and c.strip()) < 3:
                continue
            fila = list(f)[:n_col]
            fila += [None] * (n_col - len(fila))
            filas_datos.append(fila)
        if len(filas_datos) < 3:
            continue

        df = pd.DataFrame(filas_datos, columns=columnas)
        # normalizar: quitar columnas totalmente vacias
        df = df.loc[:, [c for c in df.columns if df[c].notna().any() and (df[c].astype(str).str.strip() != "").any()]]
        if df.shape[1] < 3 or df.shape[0] < 3:
            continue

        # filtro de calidad: paginas con mapas, graficos o tablas de
        # credito a veces generan "tablas" falsas via extract_tables
        # (texto disperso que por casualidad cae en columnas). Una tabla
        # de grilla real tiene encabezados que son PALABRAS (no
        # fragmentos de 1-2 caracteres) y datos mayormente numericos.
        frags_cortos = sum(1 for c in columnas if len(c.strip()) <= 2 and not c.strip().isdigit())
        if frags_cortos > len(columnas) / 3:
            continue
        cols_numericas = [c for c in df.columns[1:] if df[c].astype(str).str.strip().apply(
            lambda v: bool(_RE_NUM.match(v)) or v in ("", "nan", "None")
        ).mean() > 0.6]
        if len(cols_numericas) < 2:
            continue

        df.insert(0, "anio_informe", anio_informe)
        df.insert(1, "mes_informe", mes_informe)
        df.insert(2, "seccion", seccion)
        df.insert(3, "subtitulo", subtitulo)
        df.insert(4, "pagina", pagina.page_number)
        resultados.append(df)

    return resultados


# Familias de tabla-grilla conocidas -- el texto exacto del subtitulo
# cambia levemente entre ediciones ("Por origen de fabricación" vs "a
# julio 2026" vs con tildes distintas), asi que se clasifica por
# palabras clave, no por texto exacto.
_FAMILIAS_TABLA = [
    ("por_color", r"por\s+color"),
    ("por_origen_fabricacion", r"origen\s+de\s+fabricaci"),
    ("motos_combustible_cilindrada", r"combustible\s+y\s+cilindrada|por\s+combustible"),
    ("saldo_creditos_vehiculares", r"cr[eé]dito.{0,20}vehicular|entidad\s+financiera"),
    ("importacion_suministros", r"importaci[oó]n\s+de\s+suministros"),
    ("electrificados_tipo_tecnologia", r"tipo\s+de\s+tecnolog"),
    ("lujo_por_clase", r"segmento\s+de\s+lujo|segmento\s+lujo"),
]


def _familia_tabla(seccion: str, subtitulo: str) -> Optional[str]:
    texto = f"{seccion} {subtitulo}".lower()
    for nombre, patron in _FAMILIAS_TABLA:
        if re.search(patron, texto, re.I):
            return nombre
    return None


def consolidar_tablas_grilla(tablas: list[pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Agrupa las tablas-grilla de MUCHAS ediciones distintas en una base
    por familia (por_color, por_origen_fabricacion, ...). No se puede
    concatenar por el nombre de columna tal cual: el texto exacto del
    encabezado varia (espacios, tildes, un "2026" chico que se cuela)
    entre ediciones, lo que generaria una columna nueva por variante en
    vez de alinear los datos. Se alinea por POSICION dentro de cada
    familia en su lugar -- las columnas quedan como c0, c1, c2... más
    los metadatos (anio_informe, mes_informe, informe_fuente, pagina).
    Las tablas que no calzan con ninguna familia conocida van a
    'otras_tablas' (sin alinear, se guardan tal cual para revision
    manual, no se descartan)."""
    metadatos = {"anio_informe", "mes_informe", "seccion", "subtitulo", "pagina", "informe_fuente"}
    por_familia: dict[str, list[pd.DataFrame]] = {}
    otras: list[pd.DataFrame] = []

    for df in tablas:
        if df.empty:
            continue
        seccion = str(df["seccion"].iloc[0]) if "seccion" in df.columns else ""
        subtitulo = str(df["subtitulo"].iloc[0]) if "subtitulo" in df.columns else ""
        familia = _familia_tabla(seccion, subtitulo)
        cols_dato = [c for c in df.columns if c not in metadatos]
        if familia is None:
            otras.append(df)
            continue
        df_pos = df[list(metadatos & set(df.columns)) + cols_dato].copy()
        nombres_originales = cols_dato
        df_pos = df_pos.rename(columns={c: f"c{i}" for i, c in enumerate(cols_dato)})
        # guardar los nombres de columna de ESTA edicion como una fila
        # aparte ayuda a auditar que la alineacion posicional tenga
        # sentido -- se antepone como comentario en el nombre de familia
        # mas abajo, no se pierde la info, solo no se usa para alinear.
        df_pos.attrs["encabezados_originales"] = nombres_originales
        por_familia.setdefault(familia, []).append(df_pos)

    resultado = {}
    for familia, lst in por_familia.items():
        max_cols = max(len(df.attrs.get("encabezados_originales", [])) for df in lst)
        # completar con columnas faltantes (None) para que todas las
        # ediciones de esta familia tengan el mismo numero de c_i antes
        # de concatenar -- si no, pandas igual las alinea por nombre,
        # pero asi queda explicito y no se arrastran huecos silenciosos.
        normalizadas = []
        for df in lst:
            faltantes = [f"c{i}" for i in range(max_cols) if f"c{i}" not in df.columns]
            for f in faltantes:
                df[f] = None
            normalizadas.append(df)
        df_familia = pd.concat(normalizadas, ignore_index=True)
        if familia in _COLUMNAS_SEMANTICAS:
            df_familia = df_familia.rename(columns=_COLUMNAS_SEMANTICAS[familia])
        resultado[familia] = df_familia

    if otras:
        # "otras" son tablas que no calzaron con ninguna familia conocida
        # -- cada una trae su propio texto de encabezado (garbled, unico
        # por edicion), asi que con cientos de ellas pd.concat(sort=False)
        # termina alineando miles de columnas casi todas distintas, lo
        # que en la practica se vuelve carisimo (memoria y tiempo) sin
        # aportar nada usable (son ruido, no datos limpios). Se guardan
        # solo los metadatos (que tabla era, de que informe, cuantas
        # filas/columnas tenia) para poder revisar manualmente cuales
        # merecerian una familia nueva -- no el contenido completo.
        resumen_otras = pd.DataFrame([
            {
                "informe_fuente": df["informe_fuente"].iloc[0] if "informe_fuente" in df.columns else None,
                "seccion": df["seccion"].iloc[0] if "seccion" in df.columns else None,
                "subtitulo": df["subtitulo"].iloc[0] if "subtitulo" in df.columns else None,
                "pagina": df["pagina"].iloc[0] if "pagina" in df.columns else None,
                "n_filas": len(df),
                "n_columnas": len(df.attrs.get("encabezados_originales", [])),
            }
            for df in otras
        ])
        resultado["otras_tablas"] = resumen_otras

    return resultado


# nombres de columna reales para las familias ya validadas a mano contra
# el PDF (ver docstring de consolidar_tablas_grilla) -- las que no estan
# aca quedan como c0, c1, c2... (todavia utilizables por posicion, solo
# sin el nombre bonito).
_COLUMNAS_SEMANTICAS = {
    "por_color": {
        "c0": "categoria", "c1": "automovil", "c2": "suv", "c3": "camionetas",
        "c4": "pickup_furgonetas", "c5": "acumulado_periodo_actual",
        "c6": "acumulado_periodo_anterior", "c7": "participacion_pct", "c8": "var_pct",
    },
    "por_origen_fabricacion": {
        "c0": "categoria", "c1": "automovil", "c2": "suv", "c3": "camionetas",
        "c4": "pickup_furgonetas", "c5": "acumulado_periodo_actual",
        "c6": "acumulado_periodo_anterior", "c7": "participacion_pct", "c8": "var_pct",
    },
}


# ---------------------------------------------------------------------
# 2. Rankings "Por marca" (tarjetas numeradas)
# ---------------------------------------------------------------------

_RE_MARCA_NOMBRE = re.compile(r"^[A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑ&.\-]*$")
_RE_ANIO_CIFRA = re.compile(r"^(20\d{2}):$")
_RE_PCT_SOLO = re.compile(r"^-?[\d.]+%$")


def extraer_ranking_marca(pagina, anio_informe: int, mes_informe: int) -> pd.DataFrame:
    """Parsea las tarjetas "Por marca" (rank + nombre + 2 años + var% +
    part%). Estas tarjetas vienen en una grilla de 2 o 3 columnas -- el
    texto plano de pdfplumber las intercala de forma ilegible (una fila
    visual mezcla las 2-3 tarjetas de esa fila), así que en vez de leer
    texto en orden se agrupan las PALABRAS por proximidad geométrica al
    numero de rank (1, 2, 3...), que siempre es el primer elemento de
    cada tarjeta."""
    texto_pag = pagina.extract_text() or ""
    if "por marca" not in texto_pag.lower():
        return pd.DataFrame()
    seccion, subtitulo = _titulo_pagina(texto_pag)

    palabras = pagina.extract_words()
    # anclas de rank: numero suelto (1-2 digitos) seguido, en la misma
    # banda vertical y un poco a la derecha, de un nombre de marca
    # (palabra que empieza en mayuscula).
    anclas = []
    for w in palabras:
        # el numero de rank a veces viene con punto pegado ("1.") y a
        # veces junto con el nombre en la MISMA palabra ("1.TOYOTA" no
        # se ha visto, pero "1." solo si)
        m_rank = re.fullmatch(r"(\d{1,2})\.?", w["text"])
        if not m_rank:
            continue
        candidatos_marca = [
            m for m in palabras
            if abs(m["top"] - w["top"]) < 14 and 0 < m["x0"] - w["x0"] < 150
            and _RE_MARCA_NOMBRE.match(m["text"]) and m["text"] not in ("Var", "Acum", "Part")
        ]
        if candidatos_marca:
            anclas.append({"rank": int(m_rank.group(1)), "x0": w["x0"], "top": w["top"]})
    if len(anclas) < 2:
        return pd.DataFrame()

    xs_col = sorted({a["x0"] for a in anclas})
    tops_fila = sorted({a["top"] for a in anclas})
    ancho_pag, alto_pag = float(pagina.width), float(pagina.height)

    filas = []
    for ancla in anclas:
        # limite derecho: la siguiente columna de anclas a la derecha
        col_idx = xs_col.index(ancla["x0"])
        x_fin = next((x for x in xs_col if x > ancla["x0"] + 20), ancho_pag)
        # limite inferior: la siguiente fila de anclas hacia abajo
        fila_idx = tops_fila.index(ancla["top"])
        top_fin = next((t for t in tops_fila if t > ancla["top"] + 20), alto_pag)

        palabras_tarjeta = [
            w for w in palabras
            if ancla["x0"] - 3 <= w["x0"] < x_fin - 2 and ancla["top"] - 3 <= w["top"] < top_fin - 2
        ]
        palabras_tarjeta.sort(key=lambda w: (round(w["top"] / 4), w["x0"]))
        texto_tarjeta = " ".join(w["text"] for w in palabras_tarjeta)

        m_marca = re.search(
            r"^\d{1,2}\.?\s+([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑ&.\- ]{1,25}?)\s+(?:Var|20\d{2}\s*:)",
            texto_tarjeta,
        )
        anios_vals = re.findall(r"(20\d{2}):\s*([\d,]+)", texto_tarjeta)
        if not m_marca or len(anios_vals) < 2:
            continue

        # el circulo de Var.% y el de Part.% son siempre los DOS UNICOS
        # porcentajes sueltos de la tarjeta -- en unas ediciones la
        # etiqueta "Var.%"/"Part.%" aparece ANTES del numero, en otras
        # DESPUES (como pie de cada circulo), asi que anclar por texto es
        # fragil; tomar los primeros 2 porcentajes en orden de lectura
        # (izq/arriba primero) es robusto en ambos formatos: el de Var.%
        # siempre esta a la izquierda del de Part.%.
        # ojo: "Var.%" tiene un "." suelto pegado al "%" -- exigir que
        # arranque con un digito evita que ese punto se cuele como un
        # "porcentaje" fantasma (0.0%) y desfase var/part.
        pcts = re.findall(r"(-?\d[\d.]*)%", texto_tarjeta)
        var_num = _a_numero(pcts[0] + "%") if len(pcts) >= 1 else None
        part_num = _a_numero(pcts[1] + "%") if len(pcts) >= 2 else None

        fila = {
            "anio_informe": anio_informe, "mes_informe": mes_informe,
            "seccion": seccion, "subtitulo": subtitulo,
            "rank": ancla["rank"], "marca": m_marca.group(1).strip(),
        }
        for anio_txt, val_txt in anios_vals[:2]:
            fila[f"anio_{anio_txt}"] = _a_numero(val_txt)
        fila["var_pct_acum"] = var_num
        fila["part_pct"] = part_num
        filas.append(fila)

    return pd.DataFrame(filas)


# ---------------------------------------------------------------------
# 3. Graficos de barra anuales por segmento (best-effort, orden ordinal)
# ---------------------------------------------------------------------

_RE_VALOR_BARRA = re.compile(r"^-?[\d]{1,3}(?:,\d{3})+$")
_RE_PCT_BARRA = re.compile(r"^-?[\d]{1,3}(?:\.\d+)?%$")
_RE_ANIO_EJE = re.compile(r"^20[0-3]\d$")


def extraer_barras_segmento_anual(pagina, anio_informe: int, mes_informe: int) -> pd.DataFrame:
    """Grafico de barras 'X a [mes] de cada año' con leyenda 'Ventas' /
    'Var. % Anual'. Detecta el eje de años real (fila de textos '2017'..
    '2026' repetida) y asigna los valores en orden ordinal de izquierda
    a derecha dentro de cada sub-grafico (columna). No intenta separar
    sub-graficos por titulo -- usa clusters de X para eso."""
    texto_pag = pagina.extract_text() or ""
    if "a julio de cada" not in texto_pag.lower() and " de cada a" not in texto_pag.lower():
        # intenta variantes "a <mes> de cada año"
        if not re.search(r"a\s+\w+\s+de\s+cada\s+a", texto_pag, re.I):
            return pd.DataFrame()

    palabras = pagina.extract_words(extra_attrs=["size"])
    etiquetas_anio = [
        (w["x0"], w["top"], int(w["text"])) for w in palabras if _RE_ANIO_EJE.match(w["text"])
    ]
    # titulos de cada sub-grafico: texto en fuente grande (>12pt, los
    # datos van a 8pt) por encima de su eje -- ej. "Automóviles, SW" /
    # "Camionetas" cuando la pagina trae varios sub-graficos.
    titulos_grandes = [w for w in palabras if w.get("size", 0) > 12]
    if len(etiquetas_anio) < 4:
        return pd.DataFrame()

    # una pagina puede traer varios sub-graficos en grilla (2x1, 2x2...)
    # -- cada eje de anios es una fila HORIZONTAL de 10 etiquetas con el
    # mismo 'top' (tolerancia +-3pt); agrupar primero por top (fila) y
    # luego, dentro de esa fila, por gaps grandes en X (columna) separa
    # sub-graficos que comparten la misma banda vertical.
    etiquetas_anio.sort(key=lambda t: t[1])
    filas_eje: list[list[tuple]] = [[etiquetas_anio[0]]]
    for et in etiquetas_anio[1:]:
        if et[1] - filas_eje[-1][-1][1] > 4:
            filas_eje.append([et])
        else:
            filas_eje[-1].append(et)

    subgraficos = []  # (x_min, x_max, top_eje, anios_ordenados)
    for fila in filas_eje:
        fila.sort(key=lambda t: t[0])
        bloque = [fila[0]]
        for et in fila[1:]:
            if et[0] - bloque[-1][0] > 60:
                subgraficos.append((bloque[0][0] - 15, bloque[-1][0] + 15, bloque[0][1], bloque))
                bloque = [et]
            else:
                bloque.append(et)
        subgraficos.append((bloque[0][0] - 15, bloque[-1][0] + 15, bloque[0][1], bloque))

    # redondear antes de deduplicar: dos sub-graficos de la MISMA fila
    # pueden tener tops casi identicos pero no exactamente iguales
    # (ej. 250.9164 vs 250.9175), lo que haria que uno se calculara como
    # "anterior" al otro y colapsara su propio rango de busqueda a casi
    # cero en vez de tratarlos como la misma fila.
    tops_eje_unicos = sorted({round(t) for _, _, t, _ in subgraficos})
    seccion, subtitulo_pagina = _titulo_pagina(texto_pag)
    filas = []
    for x_min, x_max, top_eje, bloque_anios in subgraficos:
        if len(bloque_anios) < 4:
            continue

        # titulo propio de este sub-grafico (si la pagina trae varios) --
        # el texto grande mas cercano por encima, dentro del rango de X.
        candidatos_titulo = [
            w for w in titulos_grandes if x_min - 30 <= w["x0"] <= x_max + 30 and w["top"] < top_eje
        ]
        if candidatos_titulo:
            top_mas_cercano = max(w["top"] for w in candidatos_titulo)
            partes = sorted(
                (w for w in candidatos_titulo if abs(w["top"] - top_mas_cercano) < 5),
                key=lambda w: w["x0"],
            )
            subtitulo = " ".join(w["text"] for w in partes)
        else:
            subtitulo = subtitulo_pagina
        # las etiquetas de valor de barra estan SIEMPRE arriba de su
        # propio eje de anios (top menor) y antes del proximo eje hacia
        # arriba -- acotar en Y evita mezclar el sub-grafico de al lado
        # (misma columna X, pero otra fila) cuando la pagina tiene 2x2.
        anteriores = [t for t in tops_eje_unicos if t < round(top_eje) - 4]
        top_min = anteriores[-1] if anteriores else 0
        valores = [
            (w["x0"], w["text"]) for w in palabras
            if x_min <= w["x0"] <= x_max and top_min <= w["top"] < top_eje
            and _RE_VALOR_BARRA.match(w["text"])
        ]
        # asignar cada valor al anio de x mas cercana (tolerancia 20pt) en
        # vez de exigir que el conteo calce exacto -- una etiqueta perdida
        # o solapada (ver docstring del modulo) ya no tumba TODO el
        # sub-grafico, solo esa celda puntual queda vacia.
        for x_anio, _top, anio in bloque_anios:
            candidatos = [(abs(x_anio - x), txt) for x, txt in valores if abs(x_anio - x) < 20]
            if not candidatos:
                continue
            _, val_txt = min(candidatos, key=lambda c: c[0])
            filas.append({
                "anio_informe": anio_informe, "mes_informe": mes_informe,
                "seccion": seccion, "subtitulo": subtitulo,
                "anio_dato": anio, "valor": _a_numero(val_txt),
                "pagina": pagina.page_number,
            })

    return pd.DataFrame(filas)


# ---------------------------------------------------------------------
# 4. Mapas "Por oficina registral" (agrupacion por proximidad)
# ---------------------------------------------------------------------

def extraer_mapa_regional(pagina, anio_informe: int, mes_informe: int) -> pd.DataFrame:
    texto_pag = pagina.extract_text() or ""
    if "oficina registral" not in texto_pag.lower():
        return pd.DataFrame()

    seccion, subtitulo = _titulo_pagina(texto_pag)
    palabras = pagina.extract_words()
    # cada caja: nombre de ciudad (mayus/minus normal) seguido, muy cerca
    # en Y, de un numero grande (unidades) y luego 2 lineas con
    # "var%" y "part%" -- se agrupan por clusters (x0 cercano, top
    # ascendente dentro de ~60pt)
    candidatos = [w for w in palabras if w["top"] > 150]  # saltar titulo/leyenda
    candidatos.sort(key=lambda w: (w["top"], w["x0"]))

    cajas: list[list[dict]] = []
    for w in candidatos:
        asignado = False
        for caja in cajas:
            ultimo = caja[-1]
            if abs(w["x0"] - ultimo["x0"]) < 70 and 0 <= w["top"] - ultimo["top"] < 20:
                caja.append(w)
                asignado = True
                break
        if not asignado:
            cajas.append([w])

    filas = []
    for caja in cajas:
        texto_caja = [w["text"] for w in caja]
        # primer token no numerico = nombre de la oficina; puede venir en
        # varias palabras (ej. "La Merced")
        nombre_partes = []
        i = 0
        while i < len(texto_caja) and not re.match(r"^[\d,.\-%]+$", texto_caja[i]):
            nombre_partes.append(texto_caja[i])
            i += 1
        resto = texto_caja[i:]
        if not nombre_partes or len(resto) < 1:
            continue
        numeros = [t for t in resto if re.match(r"^-?[\d,]+(?:\.\d+)?%?$", t)]
        if len(numeros) < 1:
            continue
        unidades = _a_numero(numeros[0]) if numeros else None
        var_pct = _a_numero(numeros[1]) / 100 if len(numeros) > 1 and numeros[1].endswith("%") else None
        part_pct = _a_numero(numeros[2]) / 100 if len(numeros) > 2 and numeros[2].endswith("%") else None
        filas.append({
            "anio_informe": anio_informe, "mes_informe": mes_informe,
            "seccion": seccion, "subtitulo": subtitulo,
            "oficina_registral": " ".join(nombre_partes), "unidades": unidades,
            "var_pct_anual": var_pct, "participacion_pct": part_pct,
            "pagina": pagina.page_number,
        })
    return pd.DataFrame(filas)


# ---------------------------------------------------------------------
# 5. Lineas de tiempo sin etiquetar cada punto (best-effort, baja confianza)
# ---------------------------------------------------------------------

def _decodificar_eje_x_rotado(palabras: list[dict], banda_top: tuple[float, float]) -> list[tuple[float, str]]:
    frag_por_x: dict[int, list[dict]] = {}
    for w in palabras:
        if banda_top[0] < w["top"] < banda_top[1]:
            frag_por_x.setdefault(round(w["x0"]), []).append(w)
    etiquetas = []
    for x0, frags in sorted(frag_por_x.items()):
        frags.sort(key=lambda w: -w["top"])
        texto = "".join(f["text"][::-1] for f in frags)
        etiquetas.append((x0, texto))
    return etiquetas


def extraer_lineas_no_etiquetadas(pagina, anio_informe: int, mes_informe: int) -> pd.DataFrame:
    """Reconstruye series mensuales de graficos de linea que solo tienen
    el primer y ultimo punto con texto (ej. importaciones, financiamiento
    mes a mes). Usa las coordenadas del trazo vectorial (curvas bezier)
    calibradas contra los ejes -- IMPORTANTE: el suavizado de la curva no
    pasa exactamente por el dato real, el error medido contra un valor
    conocido fue de hasta ~20%. Por eso estas filas van con
    confianza='baja', a diferencia del resto del pipeline."""
    palabras = pagina.extract_words()
    altura = float(pagina.height)

    # eje Y: numeros puros cerca del margen izquierdo
    eje_y = []
    for w in palabras:
        if w["x0"] < 95 and re.fullmatch(r"[\d,]+|-", w["text"]):
            val = 0.0 if w["text"] == "-" else float(w["text"].replace(",", ""))
            eje_y.append(((w["top"] + w["bottom"]) / 2, val))
    if len(eje_y) < 3:
        return pd.DataFrame()
    eje_y.sort()
    tops = np.array([t for t, v in eje_y])
    vals = np.array([v for t, v in eje_y])
    pendiente, intercepto = np.polyfit(tops, vals, 1)

    # eje X: etiquetas rotadas tipo "Ene-20".."Jul-26" -- probar varias
    # bandas de altura porque la posicion vertical del eje varia por
    # informe/seccion.
    etiquetas_x = []
    for banda in [(395, 450), (415, 470), (440, 495)]:
        etiquetas_x = _decodificar_eje_x_rotado(palabras, banda)
        etiquetas_x = [(x, t) for x, t in etiquetas_x if _RE_MES_COL.match(t.replace(" ", ""))]
        if len(etiquetas_x) >= 6:
            break
    if len(etiquetas_x) < 6:
        return pd.DataFrame()

    curvas = [c for c in pagina.curves if len(c.get("pts") or []) > 80]
    if not curvas:
        return pd.DataFrame()

    # generar TODOS los meses entre la primera y ultima etiqueta (aunque
    # el eje solo etiquete 1 de cada 2 meses, la serie real es mensual)
    primera_x, primer_txt = etiquetas_x[0]
    ultima_x, ultimo_txt = etiquetas_x[-1]
    m1 = _RE_MES_COL.match(primer_txt.replace(" ", ""))
    m2 = _RE_MES_COL.match(ultimo_txt.replace(" ", ""))
    mes1 = [m.lower()[:3] for m in MESES_ABREV].index(m1.group(1).lower()[:3]) + 1
    anio1 = 2000 + int(m1.group(2))
    mes2 = [m.lower()[:3] for m in MESES_ABREV].index(m2.group(1).lower()[:3]) + 1
    anio2 = 2000 + int(m2.group(2))
    n_meses = (anio2 - anio1) * 12 + (mes2 - mes1) + 1
    if n_meses < 2 or n_meses > 200:
        return pd.DataFrame()

    seccion, subtitulo = _titulo_pagina(pagina.extract_text() or "")

    # etiquetas de texto reales (numeros con coma) que pdfplumber SI capta
    # -- normalmente solo el primer y ultimo punto de cada linea las
    # tienen. Donde exista una, se usa el valor exacto (confianza "alta")
    # en vez del estimado geometrico, que es solo para los meses de en medio.
    etiquetas_numericas = [
        (w["x0"], (w["top"] + w["bottom"]) / 2, w["text"])
        for w in palabras
        if re.fullmatch(r"[\d,]{4,}", w["text"]) and w["x0"] > 95
    ]

    filas = []
    for idx_curva, curva in enumerate(curvas):
        vertices = []
        for seg in curva["path"]:
            if seg[0] in ("m", "l", "c", "y", "v"):
                x, y = seg[-1]
                vertices.append((x, altura - y))
        if len(vertices) < 10:
            continue
        xs_v = np.array([v[0] for v in vertices])
        ts_v = np.array([v[1] for v in vertices])

        for i in range(n_meses):
            mes_total = (mes1 - 1) + i
            anio = anio1 + mes_total // 12
            mes = mes_total % 12 + 1
            x_obj = primera_x + (ultima_x - primera_x) * i / (n_meses - 1)
            # tomar el punto de la curva mas cercano en X (no interpolar
            # entre puntos bezier lejanos, que amplifica el error)
            idx_cercano = int(np.argmin(np.abs(xs_v - x_obj)))
            top_cercano = ts_v[idx_cercano]
            valor = pendiente * top_cercano + intercepto
            confianza = "baja"
            # solo en los extremos (primer/ultimo mes) puede haber una
            # etiqueta de texto real cerca de donde termina esta curva
            # especifica -- ahi si conviene buscar el valor exacto.
            if i == 0 or i == n_meses - 1:
                # OJO: muchos de estos trazos son en realidad un area
                # rellena (linea + cierre hacia la base para el fill), asi
                # que el path vuelve casi al punto de partida al final --
                # el ULTIMO vertice del path casi nunca es el extremo
                # derecho real. Hay que tomar el vertice de x minimo/maximo,
                # no el primero/ultimo en orden de dibujo.
                idx_extremo = int(np.argmin(xs_v)) if i == 0 else int(np.argmax(xs_v))
                x_curva_extremo = xs_v[idx_extremo]
                top_curva_extremo = ts_v[idx_extremo]
                # la etiqueta de texto suele flotar arriba/al costado del
                # punto real (no exactamente encima) -- se prioriza la
                # cercania en X (el eje que identifica el mes) y se
                # tolera bastante mas holgura en Y.
                cercanas = [
                    (abs(ex - x_curva_extremo), etxt)
                    for ex, et, etxt in etiquetas_numericas
                    if abs(ex - x_curva_extremo) < 15 and abs(et - top_curva_extremo) < 60
                ]
                if cercanas:
                    _, etxt = min(cercanas, key=lambda c: c[0])
                    valor = float(etxt.replace(",", ""))
                    confianza = "alta"
            filas.append({
                "anio_informe": anio_informe, "mes_informe": mes_informe,
                "seccion": seccion, "subtitulo": subtitulo,
                "serie_idx": idx_curva, "anio": anio, "mes": mes,
                "valor_estimado": round(valor, 0),
                "confianza": confianza,
                "pagina": pagina.page_number,
            })
    return pd.DataFrame(filas)


# ---------------------------------------------------------------------
# Orquestador: recorre TODAS las paginas de un informe y aplica los 5
# extractores a cada una (una pagina puede no calzar con ninguno, o en
# principio con mas de uno -- cada extractor valida su propio patron de
# encabezado antes de intentar nada, asi que probarlos todos es barato).
# ---------------------------------------------------------------------

def parsear_informe_detalle(ruta_pdf: Path, anio_informe: int, mes_informe: int) -> dict[str, pd.DataFrame]:
    """Aplica los 5 extractores de este modulo a cada pagina del PDF y
    devuelve un dict {categoria: DataFrame consolidado}. Los informes
    2020-2021 (14-15 paginas, sin estas secciones) simplemente devuelven
    DataFrames vacios en todas las categorias -- no es un error."""
    import pdfplumber

    categorias: dict[str, list[pd.DataFrame]] = {
        "tablas_grilla": [], "ranking_marca": [], "barras_segmento_anual": [],
        "mapa_regional": [], "lineas_no_etiquetadas": [],
    }

    with pdfplumber.open(ruta_pdf) as pdf:
        for pagina in pdf.pages:
            try:
                categorias["tablas_grilla"].extend(extraer_tablas_grilla(pagina, anio_informe, mes_informe))
            except Exception:
                pass
            try:
                df = extraer_ranking_marca(pagina, anio_informe, mes_informe)
                if not df.empty:
                    categorias["ranking_marca"].append(df)
            except Exception:
                pass
            try:
                df = extraer_barras_segmento_anual(pagina, anio_informe, mes_informe)
                if not df.empty:
                    categorias["barras_segmento_anual"].append(df)
            except Exception:
                pass
            try:
                df = extraer_mapa_regional(pagina, anio_informe, mes_informe)
                if not df.empty:
                    categorias["mapa_regional"].append(df)
            except Exception:
                pass
            try:
                df = extraer_lineas_no_etiquetadas(pagina, anio_informe, mes_informe)
                if not df.empty:
                    categorias["lineas_no_etiquetadas"].append(df)
            except Exception:
                pass

    # "tablas_grilla" NO se concatena aca: cada tabla individual conserva
    # su propio seccion/subtitulo/columnas, porque hace falta esa
    # granularidad para clasificarlas por familia (por_color, por_origen,
    # etc.) y alinearlas por posicion en consolidar_tablas_grilla() --
    # concatenar de una vez mezclaria columnas de tablas de tipos
    # distintos que aparecen en el mismo informe.
    return {
        "tablas_grilla": categorias["tablas_grilla"],
        **{
            cat: (pd.concat(lst, ignore_index=True) if lst else pd.DataFrame())
            for cat, lst in categorias.items() if cat != "tablas_grilla"
        },
    }
