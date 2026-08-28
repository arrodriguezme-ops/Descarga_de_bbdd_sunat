"""Parsea el texto (ya extraido) de un informe MCS y devuelve tablas tidy.

Cada commodity mineral en el MCS ocupa normalmente 2 paginas consecutivas con
el mismo encabezado ("<numero de pagina>\n<NOMBRE COMMODITY>\n..."). Este
modulo:

  1. Detecta las secciones por commodity dentro del texto completo del anio.
  2. Dentro de cada seccion, extrae la tabla "Salient Statistics-United
     States" (produccion, importaciones, exportaciones, precios, etc.) en
     formato largo (tidy): una fila por (commodity, variable, anio_dato).
  3. Extrae la tabla mundial "World (Mine) Production ... and Reserves" en
     formato largo: una fila por (commodity, pais, variable, anio_dato).
  4. Guarda los bloques de texto libre (Domestic Production and Use, Events
     Trends and Issues, etc.) por si se quieren re-procesar despues.

El parsing es best-effort: los informes 1996-1999 vienen de escaneos OCR y el
alineamiento columna-valor a veces se degrada. Cuando una fila no calza con
el numero esperado de columnas, se guarda igual con sus valores crudos en
`value_raw` para no perder informacion, y se deja `value_num` en NaN si no se
pudo convertir a numero.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

PAGE_SEP = "\n\x0c\n"

HEADING_RE = re.compile(r"^[A-Z][A-Z0-9 ,\.\-\(\)&/']+$")

SECTION_MARKERS = [
    "Recycling:",
    "Import Sources",
    "Events, Trends, and Issues:",
    "Events, Trends and Issues:",
    "World Mine Production",
    "World Mine and Refinery Production",
    "World Refinery Production",
    "World Smelter Production",
    "World Production",
    "World Resources:",
    "Substitutes:",
    "Government Stockpile:",
    "Tariff:",
    "Depletion Allowance:",
    "Prepared by",
]

WORLD_TABLE_MARKER_RE = re.compile(
    r"World[^\n:]{0,90}?(?:Production|Reserves|Reserve Base)[^\n:]{0,40}:"
)

YEAR_TOKEN_RE = re.compile(r"^(19|20)\d{2}\S{0,2}$")
VALUE_TOKEN_RE = re.compile(
    r"^(?:e?-?\(?\d[\d,\.]*\)?e?|\(\d+\)|NA|N\.A\.|W|—|-|--|—)$"
)
END_SECTION_RE = re.compile("|".join(re.escape(m) for m in SECTION_MARKERS))


@dataclass
class CommoditySection:
    report_year: int
    commodity: str
    pages: list[int] = field(default_factory=list)
    text: str = ""


def _clean_heading(line: str) -> str | None:
    line = line.strip()
    if not line or len(line) < 3 or len(line) > 70:
        return None
    # Quita un digito de nota al pie pegado al final, p.ej. "ALUMINUM1" -> "ALUMINUM"
    m = re.match(r"^([A-Z][A-Z0-9 ,\.\-\(\)&/']*[A-Z\)])\d{1,2}$", line)
    if m:
        line = m.group(1)
    if not HEADING_RE.match(line):
        return None
    # Evita falsos positivos de titulos de secciones generales del reporte.
    if line in {"CONTENTS", "INSTANT INFORMATION", "KEY PUBLICATIONS", "FOREWORD"}:
        return None
    if line.startswith("U.S. GEOLOGICAL SURVEY"):
        return None
    return line


def split_commodity_sections(full_text: str, report_year: int) -> list[CommoditySection]:
    """Agrupa las paginas del reporte en secciones por commodity mineral."""
    pages = full_text.split(PAGE_SEP)
    sections: list[CommoditySection] = []
    current: CommoditySection | None = None

    for page_num, page_text in enumerate(pages):
        lines = page_text.splitlines()
        heading = None
        if len(lines) >= 2:
            page_num_candidate = lines[0].strip().replace(" ", "")
            if page_num_candidate.isdigit() and len(page_num_candidate) <= 4:
                heading = _clean_heading(lines[1])
        if heading:
            if current and current.commodity == heading:
                current.pages.append(page_num)
                current.text += "\n" + page_text
                continue
            current = CommoditySection(report_year=report_year, commodity=heading)
            current.pages.append(page_num)
            current.text = page_text
            sections.append(current)
        # Si no hay heading reconocible, la pagina se ignora para el split
        # (portada, indice, apendices, etc.) pero no se agrega a `current`
        # para no mezclar texto de secciones distintas.
    return sections


def _to_num(raw: str) -> float | None:
    raw = raw.strip()
    if raw in {"NA", "N.A.", "W", "—", "-", "--", "—", ""}:
        return None
    raw = raw.lstrip("e")
    raw = re.sub(r"^\((\d+)\)$", r"\1", raw)  # (2) -> nota al pie, no valor
    if re.fullmatch(r"\(\d+\)", raw):
        return None
    raw = raw.replace(",", "")
    try:
        return float(raw)
    except ValueError:
        return None


def _extract_year_headers(line: str) -> list[str]:
    tokens = line.strip().split()
    years = [t for t in tokens if YEAR_TOKEN_RE.match(t)]
    return years


def _cut_block(text: str) -> str:
    m = END_SECTION_RE.search(text)
    return text[: m.start()] if m else text


def parse_salient_statistics(section_text: str) -> list[dict]:
    """Devuelve filas tidy: variable, data_year, value_raw, value_num."""
    rows: list[dict] = []
    m = re.search(r"Sali\w*[\s\.,\-:]*Statist\w*[^\n]*:\s*\n?", section_text)
    if not m:
        return rows
    rest = section_text[m.end():]
    lines = rest.splitlines()
    if not lines:
        return rows

    years = _extract_year_headers(lines[0])
    header_consumed = 1
    if len(years) < 2:
        # A veces los anios estan pegados en la misma linea que "Salient Statistics:"
        years = _extract_year_headers(section_text[max(0, m.start() - 5):m.end()])
        header_consumed = 0
    if len(years) < 2:
        return rows
    n = len(years)
    data_years = [re.match(r"(\d{4})", y).group(1) for y in years]
    est_flags = ["e" in y[4:].lower() for y in years]

    block = "\n".join(lines[header_consumed:])
    block = _cut_block(block)

    tokens = block.split()
    label_buf: list[str] = []
    i = 0
    while i < len(tokens):
        # busca la corrida maxima de value-tokens desde i
        j = i
        while j < len(tokens) and VALUE_TOKEN_RE.match(tokens[j]):
            j += 1
        run_len = j - i
        if run_len >= n:
            values = tokens[j - n : j]
            label = " ".join(label_buf).strip(" :")
            label = re.sub(r"(?<=[A-Za-z\)])\d{1,2}$", "", label).strip()
            label_buf = []
            if label:
                for yr, est, val in zip(data_years, est_flags, values):
                    rows.append(
                        {
                            "variable": label,
                            "data_year": int(yr),
                            "estimado": est or val.lower().startswith("e"),
                            "value_raw": val,
                            "value_num": _to_num(val),
                        }
                    )
            i = j
        else:
            label_buf.append(tokens[i])
            i += 1
    return rows


COUNTRY_ROW_RE = re.compile(r"^[A-Z][A-Za-z\.\s,\(\)\-']*?\s+(?=[\d\(——NW\-])")


def parse_world_table(section_text: str) -> list[dict]:
    """Devuelve filas tidy del cuadro mundial: pais, col_index, col_header, valores."""
    rows: list[dict] = []
    m = WORLD_TABLE_MARKER_RE.search(section_text)
    if not m:
        return rows
    after = section_text[m.end():]
    us_m = re.search(r"^United States\s+", after, re.MULTILINE)
    if not us_m:
        return rows
    header_text = after[: us_m.start()]
    body = after[us_m.start():]
    body = _cut_block(body)
    body_lines = [ln for ln in body.splitlines() if ln.strip()]

    # Determina N (numero de columnas de valores) a partir de la fila "United States"
    us_tokens = body_lines[0].split()
    j = len(us_tokens)
    k = j
    while k > 0 and VALUE_TOKEN_RE.match(us_tokens[k - 1]):
        k -= 1
    n = j - k
    if n == 0:
        return rows

    # Nombres de columnas best-effort: solo mira las 1-2 lineas de cabecera
    # justo antes de la fila "United States" (evita contaminarse con la
    # frase de revisiones que suele preceder al cuadro, la cual tambien
    # contiene palabras como "Reserves").
    header_lines = header_text.strip("\n").splitlines()
    years_line_idx = None
    for idx in range(len(header_lines) - 1, -1, -1):
        if len(_extract_year_headers(header_lines[idx])) >= 2:
            years_line_idx = idx
            break
    years_seq: list[str] = []
    metric_words: list[str] = []
    if years_line_idx is not None:
        years_seq = _extract_year_headers(header_lines[years_line_idx])
        if years_line_idx > 0:
            metric_line = header_lines[years_line_idx - 1]
            metric_words = re.findall(
                r"Mine production|Refinery production|Smelter production|Reserve base|Reserves",
                metric_line,
            )
    col_names: list[str] = []
    extra = max(0, n - len(years_seq))
    tail_metrics = metric_words[len(metric_words) - extra :] if extra else []
    head_metrics = metric_words[: len(metric_words) - extra] if extra else metric_words
    if head_metrics and len(years_seq) and len(years_seq) % max(1, len(head_metrics)) == 0:
        per = len(years_seq) // len(head_metrics)
        idx = 0
        for metric in head_metrics:
            for _ in range(per):
                yr = years_seq[idx] if idx < len(years_seq) else ""
                yr = re.sub(r"[^0-9a-zA-Z]", "", yr)
                col_names.append(f"{metric} {yr}".strip())
                idx += 1
    else:
        for idx in range(len(years_seq)):
            col_names.append(f"value {years_seq[idx]}")
    for i, metric in enumerate(tail_metrics):
        col_names.append(metric)
    while len(col_names) < n:
        col_names.append(f"col_{len(col_names) + 1}")
    col_names = col_names[:n]

    for line in body_lines:
        tokens = line.split()
        if len(tokens) < n + 1 and not (len(tokens) == n and tokens[0][0].isupper()):
            # linea sin suficientes tokens para ser fila de pais valida
            if len(tokens) <= n:
                continue
        split_at = len(tokens) - n
        country = " ".join(tokens[:split_at]).strip(" :")
        values = tokens[split_at:]
        if not country or not country[0].isalpha():
            continue
        for col_name, val in zip(col_names, values):
            rows.append(
                {
                    "country": country,
                    "col_header": col_name,
                    "value_raw": val,
                    "value_num": _to_num(val),
                }
            )
    return rows


def extract_free_text(section_text: str) -> dict:
    out: dict[str, str] = {}
    patterns = {
        "domestic_production_and_use": r"Domestic Production and Use:\s*(.*?)(?=Salient Statistics|Recycling:|Import Sources|$)",
        "events_trends_issues": r"Events,? Trends,? and Issues:\s*(.*?)(?=World Mine|World Production|World Resources|Substitutes:|$)",
        "recycling": r"Recycling:\s*(.*?)(?=Import Sources|Salient Statistics|World Mine|$)",
        "import_sources": r"Import Sources[^\n:]*:\s*(.*?)(?=Tariff:|Recycling:|World Mine|$)",
        "substitutes": r"Substitutes:\s*(.*?)(?=eEstimated|>|World Mine|Prepared by|$)",
    }
    for key, pat in patterns.items():
        m = re.search(pat, section_text, re.DOTALL)
        if m:
            txt = re.sub(r"\s+", " ", m.group(1)).strip()
            if txt:
                out[key] = txt[:4000]
    return out


def parse_report(full_text: str, report_year: int) -> dict[str, list[dict]]:
    sections = split_commodity_sections(full_text, report_year)
    salient_rows: list[dict] = []
    world_rows: list[dict] = []
    text_rows: list[dict] = []

    for sec in sections:
        for row in parse_salient_statistics(sec.text):
            row["report_year"] = report_year
            row["commodity"] = sec.commodity
            salient_rows.append(row)
        for row in parse_world_table(sec.text):
            row["report_year"] = report_year
            row["commodity"] = sec.commodity
            world_rows.append(row)
        free = extract_free_text(sec.text)
        if free:
            free["report_year"] = report_year
            free["commodity"] = sec.commodity
            text_rows.append(free)

    return {
        "salient_statistics": salient_rows,
        "world_production_reserves": world_rows,
        "free_text": text_rows,
        "commodities": [{"report_year": report_year, "commodity": s.commodity, "n_pages": len(s.pages)} for s in sections],
    }
