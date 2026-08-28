"""
aap_construir_base.py

Orquesta todo el pipeline de AAP: descarga los 79+ informes mensuales
(src/aap_scraper.py), parsea cada uno (src/aap_parser.py) y consolida
todo en data/aap_informes/:

- serie_mensual.csv       (anio, mes, mes_nombre, unidades, informe_fuente)
- resumen_por_tipo.csv    (anio_informe, mes_informe, tipo_vehiculo, unidades_acumuladas_enero_a_mes)

Correr:
    python src/aap_construir_base.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
CARPETA_RAW = RAIZ / "data" / "aap_informes" / "raw"
CARPETA_PROCESADO = RAIZ / "data" / "aap_informes" / "processed"


def main(forzar_descarga: bool = False):
    import sys

    sys.path.insert(0, str(RAIZ / "src"))
    from aap_parser import parsear_informe
    from aap_scraper import descargar_informes

    CARPETA_RAW.mkdir(parents=True, exist_ok=True)
    CARPETA_PROCESADO.mkdir(parents=True, exist_ok=True)

    print("Descargando informes de AAP...")
    df_informes = descargar_informes(
        CARPETA_RAW, forzar=forzar_descarga,
        on_status=lambda info: print(f"  [{info['informe']}] {info['estado']} {info.get('mensaje', '')}"),
    )
    print(f"\n{df_informes['archivo_local'].notna().sum()} de {len(df_informes)} informes disponibles localmente.")

    series, resumenes = [], []
    for _, fila in df_informes.iterrows():
        # OJO: "not fila['archivo_local']" NO detecta NaN (bool(float('nan'))
        # es True en Python) -- hay que usar pd.isna() explicitamente, si no
        # una sola descarga fallida (archivo_local = NaN) tumba todo el loop.
        if pd.isna(fila["archivo_local"]):
            continue
        ruta = Path(fila["archivo_local"])
        try:
            resultado = parsear_informe(ruta, int(fila["anio"]), int(fila["mes"]))
        except Exception as e:  # noqa: BLE001
            print(f"  [ERROR] {ruta.name}: {e}")
            continue

        serie = resultado["serie_principal"]
        if not serie.empty:
            serie = serie.assign(informe_fuente=f"{fila['anio']}-{fila['mes']:02d}")
            series.append(serie)

        resumenes.append(resultado["resumen_por_tipo"])
        print(f"  [{fila['anio']}-{fila['mes']:02d}] {len(serie)} filas de serie, resumen extraido")

    serie_final = pd.concat(series, ignore_index=True) if series else pd.DataFrame()
    if not serie_final.empty:
        # Si el mismo (año,mes) aparece en varios informes (se repite el
        # historico en cada edicion), nos quedamos con el dato del informe
        # MAS RECIENTE que lo reporta (revisiones posteriores corrigen cifras).
        serie_final["orden_informe"] = serie_final["informe_fuente"]
        serie_final = serie_final.sort_values("orden_informe").drop_duplicates(
            subset=["anio", "mes"], keep="last"
        ).drop(columns="orden_informe").sort_values(["anio", "mes"]).reset_index(drop=True)

    resumen_final = pd.concat(resumenes, ignore_index=True) if resumenes else pd.DataFrame()

    ruta_serie = CARPETA_PROCESADO / "serie_mensual.csv"
    ruta_resumen = CARPETA_PROCESADO / "resumen_por_tipo.csv"
    serie_final.to_csv(ruta_serie, index=False, encoding="utf-8-sig")
    resumen_final.to_csv(ruta_resumen, index=False, encoding="utf-8-sig")

    print(f"\n{len(serie_final)} filas -> {ruta_serie}")
    print(f"{len(resumen_final)} filas -> {ruta_resumen}")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--forzar-descarga", action="store_true", help="Re-descarga aunque el PDF ya exista localmente")
    args = ap.parse_args()
    main(forzar_descarga=args.forzar_descarga)
