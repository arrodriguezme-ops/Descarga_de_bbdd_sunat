"""Descarga y procesa los informes USGS Mineral Commodity Summaries (1996-2026)
y arma una base de datos tidy con estadisticas por mineral y por anio.

Uso:
    python descargar_usgs_minerales.py                # todos los anios 1996-2026
    python descargar_usgs_minerales.py --years 2015-2026
    python descargar_usgs_minerales.py --years 2026
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from usgs_mcs.build_database import build_all  # noqa: E402

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
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
