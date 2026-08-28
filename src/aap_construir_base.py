"""
aap_construir_base.py

Orquesta todo el pipeline de AAP: descarga los 79+ informes mensuales
(src/aap_scraper.py), parsea cada uno (src/aap_parser.py) y consolida
todo en data/aap_informes/:

- serie_mensual.parquet       (anio, mes, mes_nombre, unidades, informe_fuente)
- resumen_por_tipo.parquet    (anio_informe, mes_informe, tipo_vehiculo, unidades_acumuladas_enero_a_mes)
- totales_anuales.parquet     (anio, total_acumulado_a_mes_informe, total_anual) -- de la misma
                              tabla "Año x Ene..Dic" de serie_mensual, las 2 columnas finales
                              que esa no usa.
- variacion_interanual.parquet (anio_reciente, anio_anterior, concepto [Ene..Dic,
                              Total_acumulado, Total_anual], var_pct) -- filas "Var. %"
                              de la misma tabla.

Salida en Parquet (no CSV): son las bases que se versionan en el repo (livianas,
listas para el dashboard sin correr nada) -- Parquet las deja mucho mas chicas
y con los tipos de dato correctos (sin el warning de columnas mixtas que da
pandas al leer CSVs grandes).

Correr:
    python src/aap_construir_base.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
CARPETA_RAW = RAIZ / "data" / "aap_informes" / "raw"
CARPETA_PROCESADO = RAIZ / "data" / "aap_informes" / "processed"


def _a_parquet(df: pd.DataFrame, ruta: Path):
    """to_parquet() explota si el DataFrame no tiene NINGUNA columna (un
    pd.DataFrame() vacio a secas, sin schema) -- pasa si algun extractor no
    encontro nada en ningun informe. En ese caso se guarda un parquet con
    un unico string column vacio en vez de fallar todo el pipeline."""
    if df.columns.empty:
        df = pd.DataFrame({"_sin_datos": pd.Series(dtype="object")})
    df.to_parquet(ruta, index=False, compression="zstd")


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

    series, resumenes, totales_anuales_lst, variaciones_lst = [], [], [], []
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

        informe_fuente = f"{fila['anio']}-{fila['mes']:02d}"
        totales = resultado.get("totales_anuales")
        if totales is not None and not totales.empty:
            totales_anuales_lst.append(totales.assign(informe_fuente=informe_fuente))
        variacion = resultado.get("variacion_interanual")
        if variacion is not None and not variacion.empty:
            variaciones_lst.append(variacion.assign(informe_fuente=informe_fuente))

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

    ruta_serie = CARPETA_PROCESADO / "serie_mensual.parquet"
    ruta_resumen = CARPETA_PROCESADO / "resumen_por_tipo.parquet"
    _a_parquet(serie_final, ruta_serie)
    _a_parquet(resumen_final, ruta_resumen)

    totales_final = pd.concat(totales_anuales_lst, ignore_index=True) if totales_anuales_lst else pd.DataFrame()
    if not totales_final.empty:
        totales_final = totales_final.sort_values("informe_fuente").drop_duplicates(
            subset=["anio"], keep="last"
        ).sort_values("anio").reset_index(drop=True)
    ruta_totales = CARPETA_PROCESADO / "totales_anuales.parquet"
    _a_parquet(totales_final, ruta_totales)

    variacion_final = pd.concat(variaciones_lst, ignore_index=True) if variaciones_lst else pd.DataFrame()
    if not variacion_final.empty:
        variacion_final = variacion_final.sort_values("informe_fuente").drop_duplicates(
            subset=["anio_reciente", "anio_anterior", "concepto"], keep="last"
        ).sort_values(["anio_reciente", "concepto"]).reset_index(drop=True)
    ruta_variacion = CARPETA_PROCESADO / "variacion_interanual.parquet"
    _a_parquet(variacion_final, ruta_variacion)

    print(f"\n{len(serie_final)} filas -> {ruta_serie}")
    print(f"{len(resumen_final)} filas -> {ruta_resumen}")
    print(f"{len(totales_final)} filas -> {ruta_totales}")
    print(f"{len(variacion_final)} filas -> {ruta_variacion}")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--forzar-descarga", action="store_true", help="Re-descarga aunque el PDF ya exista localmente")
    args = ap.parse_args()
    main(forzar_descarga=args.forzar_descarga)
