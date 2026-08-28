"""
aap_construir_detalle_paralelo.py

Misma logica que aap_construir_detalle.py, pero paralelizada por informe
(cada PDF es independiente entre si -- no hay razon para procesarlos uno
por uno). Es puro trabajo local de CPU (pdfplumber leyendo el PDF), sin
red, asi que multiprocessing.Pool escala casi linealmente con el numero
de nucleos.

Uso (PowerShell o cualquier terminal):
    python src/aap_construir_detalle_paralelo.py
    python src/aap_construir_detalle_paralelo.py --procesos 8
    python src/aap_construir_detalle_paralelo.py --desde 2024-01 --hasta 2026-07

En una maquina de 8 nucleos, los ~79 informes (que en serie tardan unos
8-9 minutos) deberian bajar a 1-2 minutos.
"""

from __future__ import annotations

import argparse
import multiprocessing as mp
import sys
import time
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
CARPETA_RAW = RAIZ / "data" / "aap_informes" / "raw"
CARPETA_PROCESADO = RAIZ / "data" / "aap_informes" / "processed"

sys.path.insert(0, str(RAIZ / "src"))


def _procesar_uno(args: tuple[int, int, str]) -> tuple[str, dict[str, pd.DataFrame], list[pd.DataFrame]]:
    """Corre en un proceso hijo -- reimporta el modulo ahi (necesario en
    Windows, que usa 'spawn' en vez de 'fork': cada proceso hijo arranca
    limpio y no hereda los imports del padre)."""
    anio, mes, informe_fuente = args
    sys.path.insert(0, str(RAIZ / "src"))
    from aap_tablas_detalle import parsear_informe_detalle

    ruta = CARPETA_RAW / f"{anio}-{mes:02d}.pdf"
    if not ruta.exists():
        return informe_fuente, {}, []
    t0 = time.time()
    try:
        resultado = parsear_informe_detalle(ruta, anio, mes)
    except Exception as e:  # noqa: BLE001
        print(f"  [ERROR] {ruta.name}: {e}", flush=True)
        return informe_fuente, {}, []
    tablas_grilla = [t.assign(informe_fuente=informe_fuente) for t in resultado["tablas_grilla"]]
    resto = {
        k: v.assign(informe_fuente=informe_fuente)
        for k, v in resultado.items() if k != "tablas_grilla" and not v.empty
    }
    resumen = f"tablas_grilla={len(tablas_grilla)}, " + ", ".join(f"{k}={len(v)}" for k, v in resultado.items() if k != "tablas_grilla")
    print(f"  [{informe_fuente}] {resumen} ({time.time()-t0:.1f}s)", flush=True)
    return informe_fuente, resto, tablas_grilla


def main(desde: str | None = None, hasta: str | None = None, procesos: int | None = None):
    from aap_scraper import listar_informes
    from aap_tablas_detalle import consolidar_tablas_grilla

    df_informes = listar_informes().sort_values(["anio", "mes"]).reset_index(drop=True)
    if desde:
        a, m = desde.split("-")
        df_informes = df_informes[(df_informes.anio * 100 + df_informes.mes) >= (int(a) * 100 + int(m))]
    if hasta:
        a, m = hasta.split("-")
        df_informes = df_informes[(df_informes.anio * 100 + df_informes.mes) <= (int(a) * 100 + int(m))]

    tareas = [
        (int(f["anio"]), int(f["mes"]), f"{f['anio']}-{f['mes']:02d}")
        for _, f in df_informes.iterrows()
    ]
    n_procesos = procesos or max(1, (mp.cpu_count() or 4) - 1)
    print(f"Procesando {len(tareas)} informes con {n_procesos} procesos en paralelo...")

    t0 = time.time()
    acumulado: dict[str, list[pd.DataFrame]] = {}
    tablas_grilla_crudas: list[pd.DataFrame] = []
    with mp.Pool(n_procesos) as pool:
        for _, resto, tablas_grilla in pool.imap_unordered(_procesar_uno, tareas):
            for cat, df in resto.items():
                acumulado.setdefault(cat, []).append(df)
            tablas_grilla_crudas.extend(tablas_grilla)

    print(f"\nTotal: {time.time()-t0:.1f}s")

    CARPETA_PROCESADO.mkdir(parents=True, exist_ok=True)
    for cat, lst in acumulado.items():
        df_final = pd.concat(lst, ignore_index=True) if lst else pd.DataFrame()
        ruta_salida = CARPETA_PROCESADO / f"detalle_{cat}.csv"
        df_final.to_csv(ruta_salida, index=False, encoding="utf-8-sig")
        print(f"{len(df_final)} filas -> {ruta_salida}")

    familias = consolidar_tablas_grilla(tablas_grilla_crudas)
    for familia, df_final in familias.items():
        ruta_salida = CARPETA_PROCESADO / f"detalle_tabla_{familia}.csv"
        df_final.to_csv(ruta_salida, index=False, encoding="utf-8-sig")
        print(f"{len(df_final)} filas -> {ruta_salida}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--desde", help="Procesar desde este informe (AAAA-MM) en adelante")
    ap.add_argument("--hasta", help="Procesar hasta este informe (AAAA-MM) inclusive")
    ap.add_argument("--procesos", type=int, help="Numero de procesos en paralelo (default: nucleos-1)")
    args = ap.parse_args()
    main(desde=args.desde, hasta=args.hasta, procesos=args.procesos)
