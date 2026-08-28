"""Extrae el texto de cada PDF de MCS pagina por pagina, con cache en disco."""
from __future__ import annotations

from pathlib import Path

import pdfplumber

TEXT_DIR = Path("data/usgs_mcs/text")
PAGE_SEP = "\n\x0c\n"  # form-feed como separador de pagina


def extract_pdf_text(pdf_path: Path, year: int, force: bool = False) -> str:
    """Extrae el texto completo del PDF (todas las paginas unidas por PAGE_SEP).

    Cachea el resultado en data/usgs_mcs/text/mcs<year>.txt para no tener que
    re-leer PDFs de 200+ paginas en cada corrida.
    """
    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = TEXT_DIR / f"mcs{year}.txt"
    if cache_path.exists() and not force:
        return cache_path.read_text(encoding="utf-8")

    print(f"[{year}] extrayendo texto de {pdf_path.name} ...")
    pages_text: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            txt = page.extract_text() or ""
            pages_text.append(txt)
    full_text = PAGE_SEP.join(pages_text)
    cache_path.write_text(full_text, encoding="utf-8")
    print(f"[{year}] {len(pages_text)} paginas -> {cache_path}")
    return full_text
