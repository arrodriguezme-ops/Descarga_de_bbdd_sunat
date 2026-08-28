"""
descargar_sisap_completo.py

Descarga TODO el historico diario disponible del SISAP (Sistema de
Abastecimiento y Precios de MIDAGRI) para mercados mayoristas de Lima
Metropolitana:
http://sistemas.midagri.gob.pe/sisap/portal2/mayorista/resumenes/consultar/

Recorre cada producto (Aceite, Ajo, Papa, Cebolla, ...) x cada mercado
(los mercados individuales + el agregado "Lima Metropolitana") y pide la
serie diaria completa de precio maximo, precio promedio, precio minimo y
volumen. No hace falta saber de antemano desde que anio hay datos: se pide
un rango amplio (FECHA_INICIO -> hoy) y el propio scraper parte la consulta
en bloques mas chicos cuando el portal la rechaza por "demasiados
criterios" (ver src/sisap_scraper.py).

Es RESUMIBLE: cada combinacion producto+mercado ya descargada se anota en
data/sisap_mayorista_manifiesto.csv, asi que si se corta a la mitad (Ctrl+C,
caida de red, etc.) basta con volver a correr el script y sigue donde se
quedo, sin repetir combinaciones ya hechas.

Con ~70 productos x 8 "mercados" (7 individuales + agregado) son ~560
consultas; con la pausa por defecto entre requests, la corrida completa
puede tomar bastante mas de una hora la primera vez (las corridas
siguientes, para actualizar, son mucho mas rapidas si se recorta
FECHA_INICIO a una fecha reciente).

Para correrlo (desde la raiz del repo, en PowerShell):
    pip install -r requirements.txt
    python descargar_sisap_completo.py

Parametros opcionales por linea de comandos:
    python descargar_sisap_completo.py --desde 01/01/2015 --hasta 31/12/2024
    python descargar_sisap_completo.py --pausa 0.5
"""

from __future__ import annotations

import argparse
import csv
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from src.sisap_scraper import (
    MERCADO_TODOS,
    descargar_producto_mercado,
    descubrir_mercados,
    descubrir_productos,
    nueva_sesion,
)

RAIZ = Path(__file__).resolve().parent
CARPETA_DATA = RAIZ / "data"
CARPETA_DATA.mkdir(exist_ok=True)

ARCHIVO_SALIDA = CARPETA_DATA / "sisap_mayorista_precios.csv"
ARCHIVO_MANIFIESTO = CARPETA_DATA / "sisap_mayorista_manifiesto.csv"

COLUMNAS_SALIDA = [
    "fecha", "mercado_codigo", "mercado_nombre",
    "producto_codigo", "producto_nombre", "variedad", "variable", "valor",
]


def parsear_fecha_cli(txt: str) -> date:
    return datetime.strptime(txt, "%d/%m/%Y").date()


def cargar_manifiesto() -> set[tuple[str, str]]:
    if not ARCHIVO_MANIFIESTO.exists():
        return set()
    df = pd.read_csv(ARCHIVO_MANIFIESTO, dtype=str)
    return set(zip(df["producto_codigo"], df["mercado_codigo"]))


def anotar_manifiesto(producto_codigo: str, mercado_codigo: str, n_filas: int):
    nuevo = not ARCHIVO_MANIFIESTO.exists()
    with open(ARCHIVO_MANIFIESTO, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if nuevo:
            w.writerow(["producto_codigo", "mercado_codigo", "filas", "terminado_en"])
        w.writerow([producto_codigo, mercado_codigo, n_filas, datetime.now().isoformat(timespec="seconds")])


def guardar_bloque(df: pd.DataFrame):
    nuevo = not ARCHIVO_SALIDA.exists()
    df.to_csv(ARCHIVO_SALIDA, mode="a", index=False, header=nuevo, columns=COLUMNAS_SALIDA, encoding="utf-8-sig")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--desde", type=parsear_fecha_cli, default=date(2000, 1, 1),
                     help="Fecha de inicio dd/mm/aaaa (default: 01/01/2000, bastante antes de que exista el portal)")
    ap.add_argument("--hasta", type=parsear_fecha_cli, default=date.today(),
                     help="Fecha de fin dd/mm/aaaa (default: hoy)")
    ap.add_argument("--pausa", type=float, default=1.0, help="Segundos de pausa entre requests (default: 1.0)")
    ap.add_argument("--solo-agregado", action="store_true",
                     help="Solo consulta 'Lima Metropolitana' agregado (mercado=*), sin desglosar por mercado individual")
    args = ap.parse_args()

    print("Descubriendo productos y mercados desde el portal...")
    sesion = nueva_sesion()
    productos = descubrir_productos(sesion)
    mercados = descubrir_mercados(sesion)
    if args.solo_agregado:
        mercados = {MERCADO_TODOS: mercados[MERCADO_TODOS]}

    print(f"  {len(productos)} productos, {len(mercados)} mercados (incluye agregado)")
    print(f"  Rango de fechas: {args.desde:%d/%m/%Y} - {args.hasta:%d/%m/%Y}")

    combinaciones = [
        (cod_prod, cod_merc)
        for cod_prod in productos
        for cod_merc in mercados
    ]
    ya_hechas = cargar_manifiesto()
    pendientes = [c for c in combinaciones if c not in ya_hechas]
    print(f"  {len(combinaciones)} combinaciones producto x mercado totales, "
          f"{len(ya_hechas)} ya descargadas antes, {len(pendientes)} pendientes\n")

    total_filas_nuevas = 0
    for i, (cod_prod, cod_merc) in enumerate(pendientes, start=1):
        nombre_prod = productos[cod_prod]
        nombre_merc = mercados[cod_merc]
        print(f"[{i}/{len(pendientes)}] {nombre_prod} ({cod_prod}) @ {nombre_merc} ({cod_merc})...", end=" ", flush=True)

        try:
            df = descargar_producto_mercado(
                sesion, cod_prod, cod_merc, args.desde, args.hasta,
                pausa_entre_requests_seg=args.pausa,
                on_status=lambda msg: print(f"\n{msg}", end=""),
            )
        except KeyboardInterrupt:
            print("\n\nInterrumpido por el usuario. Lo ya descargado quedo guardado; "
                  "volve a correr el script para continuar donde quedaste.")
            return

        if not df.empty:
            df["mercado_codigo"] = cod_merc
            df["mercado_nombre"] = nombre_merc
            df["producto_codigo"] = cod_prod
            df["producto_nombre"] = nombre_prod
            guardar_bloque(df)
            total_filas_nuevas += len(df)

        anotar_manifiesto(cod_prod, cod_merc, len(df))
        print(f"{len(df)} filas")

    print(f"\nListo. {total_filas_nuevas} filas nuevas agregadas a '{ARCHIVO_SALIDA}'.")
    print(f"Manifiesto de combinaciones ya descargadas: '{ARCHIVO_MANIFIESTO}'.")
    print("Para volver a correr y bajar solo lo que falte (o actualizar con fechas nuevas), "
          "corre el script de nuevo -- las combinaciones ya hechas se saltan automaticamente.")
    print("Para forzar una descarga desde cero, borra data/sisap_mayorista_manifiesto.csv "
          "(y opcionalmente data/sisap_mayorista_precios.csv).")


if __name__ == "__main__":
    main()
