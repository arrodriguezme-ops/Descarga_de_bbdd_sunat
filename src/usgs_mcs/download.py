"""Descarga los PDFs de Mineral Commodity Summaries (MCS) de la USGS, 1996-2026.

Las URLs fueron obtenidas directamente de la pagina oficial:
https://www.usgs.gov/centers/national-minerals-information-center/mineral-commodity-summaries
(el dominio de hosting de los PDFs ha cambiado varias veces a lo largo de los anios,
por eso cada anio apunta a un host distinto).
"""
from __future__ import annotations

import time
from pathlib import Path

import requests

# report_year -> URL directa del PDF principal (no incluye los "appendixes")
MCS_PDF_URLS: dict[int, str] = {
    1996: "https://d9-wret.s3.us-west-2.amazonaws.com/assets/palladium/production/atoms/files/mcs-1996ocr.pdf",
    1997: "https://d9-wret.s3.us-west-2.amazonaws.com/assets/palladium/production/atoms/files/mcs-1997ocr.pdf",
    1998: "https://d9-wret.s3.us-west-2.amazonaws.com/assets/palladium/production/atoms/files/mcs-1998ocr.pdf",
    1999: "https://d9-wret.s3.us-west-2.amazonaws.com/assets/palladium/production/atoms/files/mcs-1999ocr.pdf",
    2000: "https://d9-wret.s3.us-west-2.amazonaws.com/assets/palladium/production/mineral-pubs/mcs/mcs2000.pdf",
    2001: "https://d9-wret.s3.us-west-2.amazonaws.com/assets/palladium/production/mineral-pubs/mcs/mcs2001.pdf",
    2002: "https://d9-wret.s3.us-west-2.amazonaws.com/assets/palladium/production/mineral-pubs/mcs/mcs2002.pdf",
    2003: "https://d9-wret.s3.us-west-2.amazonaws.com/assets/palladium/production/mineral-pubs/mcs/mcs2003.pdf",
    2004: "https://d9-wret.s3.us-west-2.amazonaws.com/assets/palladium/production/mineral-pubs/mcs/mcs2004.pdf",
    2005: "https://d9-wret.s3.us-west-2.amazonaws.com/assets/palladium/production/mineral-pubs/mcs/mcs2005.pdf",
    2006: "https://d9-wret.s3.us-west-2.amazonaws.com/assets/palladium/production/mineral-pubs/mcs/mcs2006.pdf",
    2007: "https://d9-wret.s3.us-west-2.amazonaws.com/assets/palladium/production/mineral-pubs/mcs/mcs2007.pdf",
    2008: "https://d9-wret.s3.us-west-2.amazonaws.com/assets/palladium/production/mineral-pubs/mcs/mcs2008.pdf",
    2009: "https://d9-wret.s3.us-west-2.amazonaws.com/assets/palladium/production/mineral-pubs/mcs/mcs2009.pdf",
    2010: "https://d9-wret.s3.us-west-2.amazonaws.com/assets/palladium/production/mineral-pubs/mcs/mcs2010.pdf",
    2011: "https://d9-wret.s3.us-west-2.amazonaws.com/assets/palladium/production/mineral-pubs/mcs/mcs2011.pdf",
    2012: "https://d9-wret.s3.us-west-2.amazonaws.com/assets/palladium/production/mineral-pubs/mcs/mcs2012.pdf",
    2013: "https://apps.usgs.gov/minerals-information-archives/mcs/mcs2013.pdf",
    2014: "https://apps.usgs.gov/minerals-information-archives/mcs/mcs2014.pdf",
    2015: "https://apps.usgs.gov/minerals-information-archives/mcs/mcs2015.pdf",
    2016: "https://apps.usgs.gov/minerals-information-archives/mcs/mcs2016.pdf",
    2017: "https://apps.usgs.gov/minerals-information-archives/mcs/mcs2017.pdf",
    2018: "https://apps.usgs.gov/minerals-information-archives/mcs/mcs2018.pdf",
    2019: "https://apps.usgs.gov/minerals-information-archives/mcs/mcs2019.pdf",
    2020: "https://pubs.usgs.gov/periodicals/mcs2020/mcs2020.pdf",
    2021: "https://pubs.usgs.gov/periodicals/mcs2021/mcs2021.pdf",
    2022: "https://pubs.usgs.gov/periodicals/mcs2022/mcs2022.pdf",
    2023: "https://pubs.usgs.gov/periodicals/mcs2023/mcs2023.pdf",
    2024: "https://pubs.usgs.gov/periodicals/mcs2024/mcs2024.pdf",
    2025: "https://pubs.usgs.gov/periodicals/mcs2025/mcs2025.pdf",
    2026: "https://pubs.usgs.gov/periodicals/mcs2026/mcs2026.pdf",
}

RAW_PDF_DIR = Path("data/usgs_mcs/raw_pdf")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; usgs-mcs-downloader/1.0)"}


def download_all(years: list[int] | None = None, force: bool = False, pause: float = 1.0) -> dict[int, Path]:
    """Descarga los PDFs faltantes. Devuelve {anio: ruta_local}."""
    RAW_PDF_DIR.mkdir(parents=True, exist_ok=True)
    years = years or sorted(MCS_PDF_URLS)
    out: dict[int, Path] = {}
    for year in years:
        url = MCS_PDF_URLS.get(year)
        if not url:
            print(f"[{year}] sin URL conocida, saltando")
            continue
        dest = RAW_PDF_DIR / f"mcs{year}.pdf"
        if dest.exists() and dest.stat().st_size > 0 and not force:
            out[year] = dest
            continue
        print(f"[{year}] descargando {url}")
        try:
            resp = requests.get(url, headers=HEADERS, timeout=120)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
            size_mb = dest.stat().st_size / 1e6
            print(f"[{year}] OK ({size_mb:.1f} MB) -> {dest}")
            out[year] = dest
        except Exception as exc:  # noqa: BLE001
            print(f"[{year}] ERROR descargando: {exc}")
        time.sleep(pause)
    return out


if __name__ == "__main__":
    download_all()
