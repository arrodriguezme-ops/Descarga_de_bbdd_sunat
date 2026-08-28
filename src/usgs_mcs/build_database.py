"""Orquesta: descarga -> extraccion de texto -> parsing -> base de datos final.

Genera, dentro de data/usgs_mcs/processed/:
  - salient_statistics.csv     (formato largo/tidy, la tabla principal)
  - world_production_reserves.csv (formato largo/tidy)
  - commodity_text.csv         (texto libre por commodity/anio)
  - commodities_index.csv      (que commodities se detectaron por anio)
  - usgs_mcs.sqlite            (las 4 tablas anteriores, para consultas SQL)
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from .download import MCS_PDF_URLS, RAW_PDF_DIR, download_all
from .extract_text import extract_pdf_text
from .parse_mcs import parse_report

PROCESSED_DIR = Path("data/usgs_mcs/processed")


def build_all(years: list[int] | None = None, force_download: bool = False, force_text: bool = False) -> None:
    years = years or sorted(MCS_PDF_URLS)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    downloaded = download_all(years=years, force=force_download)

    salient_all: list[dict] = []
    world_all: list[dict] = []
    text_all: list[dict] = []
    idx_all: list[dict] = []

    for year in years:
        pdf_path = downloaded.get(year) or (RAW_PDF_DIR / f"mcs{year}.pdf")
        if not pdf_path.exists():
            print(f"[{year}] PDF no disponible, se omite")
            continue
        try:
            full_text = extract_pdf_text(pdf_path, year, force=force_text)
            result = parse_report(full_text, year)
        except Exception as exc:  # noqa: BLE001
            print(f"[{year}] ERROR parseando: {exc}")
            continue

        salient_all.extend(result["salient_statistics"])
        world_all.extend(result["world_production_reserves"])
        text_all.extend(result["free_text"])
        idx_all.extend(result["commodities"])
        print(
            f"[{year}] commodities={len(result['commodities'])} "
            f"salient_rows={len(result['salient_statistics'])} "
            f"world_rows={len(result['world_production_reserves'])}"
        )

    salient_df = pd.DataFrame(salient_all)
    world_df = pd.DataFrame(world_all)
    text_df = pd.DataFrame(text_all)
    idx_df = pd.DataFrame(idx_all)

    col_order_salient = [
        "report_year", "commodity", "variable", "data_year", "estimado", "value_raw", "value_num",
    ]
    col_order_world = [
        "report_year", "commodity", "country", "col_header", "value_raw", "value_num",
    ]
    if not salient_df.empty:
        salient_df = salient_df[[c for c in col_order_salient if c in salient_df.columns]]
    if not world_df.empty:
        world_df = world_df[[c for c in col_order_world if c in world_df.columns]]

    salient_df.to_csv(PROCESSED_DIR / "salient_statistics.csv", index=False, encoding="utf-8-sig")
    world_df.to_csv(PROCESSED_DIR / "world_production_reserves.csv", index=False, encoding="utf-8-sig")
    text_df.to_csv(PROCESSED_DIR / "commodity_text.csv", index=False, encoding="utf-8-sig")
    idx_df.to_csv(PROCESSED_DIR / "commodities_index.csv", index=False, encoding="utf-8-sig")

    db_path = PROCESSED_DIR / "usgs_mcs.sqlite"
    with sqlite3.connect(db_path) as con:
        salient_df.to_sql("salient_statistics", con, if_exists="replace", index=False)
        world_df.to_sql("world_production_reserves", con, if_exists="replace", index=False)
        text_df.to_sql("commodity_text", con, if_exists="replace", index=False)
        idx_df.to_sql("commodities_index", con, if_exists="replace", index=False)

    print("\n=== RESUMEN ===")
    print(f"anios procesados: {sorted(set(idx_df.report_year))}" if not idx_df.empty else "sin datos")
    print(f"salient_statistics: {len(salient_df):,} filas")
    print(f"world_production_reserves: {len(world_df):,} filas")
    print(f"commodity_text: {len(text_df):,} filas")
    print(f"Archivos en {PROCESSED_DIR.resolve()}")
    print(f"SQLite: {db_path.resolve()}")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Construye la base de datos de USGS Mineral Commodity Summaries")
    ap.add_argument("--years", type=str, default=None, help="ej. 2015-2026 o lista 2020,2021,2022")
    ap.add_argument("--force-download", action="store_true")
    ap.add_argument("--force-text", action="store_true")
    args = ap.parse_args()

    years = None
    if args.years:
        if "-" in args.years:
            a, b = args.years.split("-")
            years = list(range(int(a), int(b) + 1))
        else:
            years = [int(y) for y in args.years.split(",")]

    build_all(years=years, force_download=args.force_download, force_text=args.force_text)
