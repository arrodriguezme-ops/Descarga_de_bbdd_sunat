"""
aap_construir_detalle.py

Corre aap_tablas_detalle.py sobre TODOS los informes ya descargados
(data/aap_informes/raw/) y consolida el resultado en varias bases,
separadas por nivel de agregacion (tal como se pidio: no una sola tabla
plana, sino una por nivel natural de los datos):

- detalle_tablas_grilla.csv       -- por color / origen / combustible /
                                      cilindrada, con lo que cada informe
                                      trae a nivel de detalle no-marca.
- detalle_ranking_marca.csv       -- ventas por marca, por categoria de
                                      vehiculo (livianos/camiones/motos/
                                      trimotos/electricos/transferencias),
                                      dos anios de referencia por edicion.
- detalle_barras_segmento_anual.csv -- ventas anuales "a <mes> de cada
                                      año" por segmento (Automovil/SW,
                                      Camionetas, SUV, Pick-up, Camiones,
                                      Minibus, Motos, Trimotos, lujo,
                                      electricos...).
- detalle_mapa_regional.csv       -- ventas por oficina registral
                                      (best-effort, cobertura parcial).
- detalle_lineas_no_etiquetadas.csv -- importaciones/financiamiento mes
                                      a mes, con columna confianza
                                      ('alta' solo en los extremos con
                                      etiqueta de texto real, 'baja' en
                                      los meses reconstruidos por
                                      geometria del trazo bezier).

Solo los informes ~2022 en adelante (documentos "revista" de 46-77
paginas) tienen estas secciones -- 2020-2021 (14-15 paginas) simplemente
no aportan filas aqui, no es un error.

Correr:
    python src/aap_construir_detalle.py [--informe 2026-07] [--limite N]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
CARPETA_RAW = RAIZ / "data" / "aap_informes" / "raw"
CARPETA_PROCESADO = RAIZ / "data" / "aap_informes" / "processed"

sys.path.insert(0, str(RAIZ / "src"))


def main(solo_informe: str | None = None, limite: int | None = None,
         desde: str | None = None, hasta: str | None = None, append: bool = False):
    from aap_scraper import listar_informes
    from aap_tablas_detalle import parsear_informe_detalle

    df_informes = listar_informes()
    df_informes = df_informes.sort_values(["anio", "mes"]).reset_index(drop=True)
    if solo_informe:
        anio_f, mes_f = solo_informe.split("-")
        df_informes = df_informes[(df_informes.anio == int(anio_f)) & (df_informes.mes == int(mes_f))]
    if limite:
        df_informes = df_informes.tail(limite)
    if desde:
        a, m = desde.split("-")
        df_informes = df_informes[
            (df_informes.anio * 100 + df_informes.mes) >= (int(a) * 100 + int(m))
        ]
    if hasta:
        a, m = hasta.split("-")
        df_informes = df_informes[
            (df_informes.anio * 100 + df_informes.mes) <= (int(a) * 100 + int(m))
        ]

    acumulado: dict[str, list[pd.DataFrame]] = {
        "ranking_marca": [], "barras_segmento_anual": [],
        "mapa_regional": [], "lineas_no_etiquetadas": [],
    }
    tablas_grilla_crudas: list[pd.DataFrame] = []

    for _, fila in df_informes.iterrows():
        ruta = CARPETA_RAW / f"{fila['anio']}-{fila['mes']:02d}.pdf"
        if not ruta.exists():
            continue
        t0 = time.time()
        try:
            resultado = parsear_informe_detalle(ruta, int(fila["anio"]), int(fila["mes"]))
        except Exception as e:  # noqa: BLE001
            print(f"  [ERROR] {ruta.name}: {e}")
            continue
        informe_fuente = f"{fila['anio']}-{fila['mes']:02d}"
        resumen = []
        for tabla in resultado["tablas_grilla"]:
            tablas_grilla_crudas.append(tabla.assign(informe_fuente=informe_fuente))
        resumen.append(f"tablas_grilla={len(resultado['tablas_grilla'])}")
        for cat, df in resultado.items():
            if cat == "tablas_grilla":
                continue
            if not df.empty:
                df = df.assign(informe_fuente=informe_fuente)
                acumulado[cat].append(df)
            resumen.append(f"{cat}={len(df)}")
        print(f"  [{informe_fuente}] {', '.join(resumen)} ({time.time()-t0:.1f}s)")

    _escribir_resultados(acumulado, tablas_grilla_crudas, append)


def _escribir_resultados(acumulado: dict[str, list[pd.DataFrame]], tablas_grilla_crudas: list[pd.DataFrame], append: bool):
    from aap_tablas_detalle import consolidar_tablas_grilla

    CARPETA_PROCESADO.mkdir(parents=True, exist_ok=True)

    for cat, lst in acumulado.items():
        df_final = pd.concat(lst, ignore_index=True) if lst else pd.DataFrame()
        ruta_salida = CARPETA_PROCESADO / f"detalle_{cat}.csv"
        if append and ruta_salida.exists():
            previo = pd.read_csv(ruta_salida, encoding="utf-8-sig")
            df_final = pd.concat([previo, df_final], ignore_index=True)
            if "informe_fuente" in df_final.columns:
                df_final = df_final.drop_duplicates()
        df_final.to_csv(ruta_salida, index=False, encoding="utf-8-sig")
        print(f"{len(df_final)} filas -> {ruta_salida}")

    # tablas_grilla se agrupa por familia (por_color, por_origen_...) y se
    # alinea por posicion en vez de por el texto exacto del encabezado
    # (que varia entre ediciones) -- cada familia sale en su propio CSV.
    familias = consolidar_tablas_grilla(tablas_grilla_crudas)
    for familia, df_final in familias.items():
        ruta_salida = CARPETA_PROCESADO / f"detalle_tabla_{familia}.csv"
        if append and ruta_salida.exists():
            previo = pd.read_csv(ruta_salida, encoding="utf-8-sig")
            df_final = pd.concat([previo, df_final], ignore_index=True)
            if "informe_fuente" in df_final.columns:
                df_final = df_final.drop_duplicates()
        df_final.to_csv(ruta_salida, index=False, encoding="utf-8-sig")
        print(f"{len(df_final)} filas -> {ruta_salida}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--informe", help="Procesar solo un informe puntual, formato AAAA-MM (ej. 2026-07)")
    ap.add_argument("--limite", type=int, help="Procesar solo los ultimos N informes (por fecha)")
    ap.add_argument("--desde", help="Procesar desde este informe (AAAA-MM) en adelante")
    ap.add_argument("--hasta", help="Procesar hasta este informe (AAAA-MM) inclusive")
    ap.add_argument("--append", action="store_true", help="Agregar al CSV existente en vez de sobreescribir (para correr en lotes)")
    args = ap.parse_args()
    main(solo_informe=args.informe, limite=args.limite, desde=args.desde, hasta=args.hasta, append=args.append)
