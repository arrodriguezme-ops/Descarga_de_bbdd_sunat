"""
sisap_convertir_parquet.py

Convierte data/sisap_mayorista_precios.csv (CSV largo, ~11 millones de
filas / ~1 GB) a un dataset Parquet particionado por producto, para que el
dashboard (src/vista_sisap.py) pueda filtrar y leer mucho mas rapido de lo
que tomaria re-leer el CSV completo cada vez.

Genera:
- data/sisap_parquet/producto_codigo=<codigo>/part.parquet   (dataset particionado, para filtros rapidos)
- data/sisap_parquet_completo.parquet                        (un solo archivo, para el boton de "descargar todo en Parquet")

Usa pyarrow directamente (no pandas) para poder leer el CSV en streaming sin
cargar el gigabyte completo en memoria de una sola vez.

Correr (una vez, o cuando se vuelva a descargar el SISAP completo):
    python src/sisap_convertir_parquet.py
"""

from pathlib import Path

import pyarrow as pa
import pyarrow.csv as pv
import pyarrow.dataset as ds
import pyarrow.parquet as pq

RAIZ = Path(__file__).resolve().parent.parent
CSV_ORIGEN = RAIZ / "data" / "sisap_mayorista_precios.csv"
CARPETA_PARQUET = RAIZ / "data" / "sisap_parquet"
ARCHIVO_PARQUET_COMPLETO = RAIZ / "data" / "sisap_parquet_completo.parquet"

ESQUEMA = pa.schema([
    ("fecha", pa.string()),
    ("mercado_codigo", pa.string()),
    ("mercado_nombre", pa.string()),
    ("producto_codigo", pa.int64()),
    ("producto_nombre", pa.string()),
    ("variedad", pa.string()),
    ("variable", pa.string()),
    ("valor", pa.float64()),
])


def main():
    if not CSV_ORIGEN.exists():
        raise SystemExit(
            f"No se encontro '{CSV_ORIGEN}'. Corre primero 'python descargar_sisap_completo.py'."
        )

    print(f"Leyendo {CSV_ORIGEN} ({CSV_ORIGEN.stat().st_size / 1e6:.0f} MB) en streaming...")

    lector = pv.open_csv(
        CSV_ORIGEN,
        read_options=pv.ReadOptions(block_size=64 * 1024 * 1024),
        convert_options=pv.ConvertOptions(column_types=ESQUEMA),
    )

    CARPETA_PARQUET.mkdir(parents=True, exist_ok=True)

    # --- 1. Dataset particionado por producto (para filtros rapidos en el dashboard) ---
    print("Escribiendo dataset particionado por producto_codigo...")
    tablas_para_completo = []
    total_filas = 0
    lotes = []
    TAMANO_LOTE_ESCRITURA = 2_000_000  # filas acumuladas antes de flushear a disco

    def flush(lotes_pendientes):
        if not lotes_pendientes:
            return
        tabla = pa.concat_tables(lotes_pendientes)
        ds.write_dataset(
            tabla,
            base_dir=CARPETA_PARQUET,
            format="parquet",
            partitioning=ds.partitioning(pa.schema([("producto_codigo", pa.int64())]), flavor="hive"),
            existing_data_behavior="overwrite_or_ignore",
        )
        tablas_para_completo.append(tabla)

    filas_acumuladas = 0
    for lote in lector:
        tabla_lote = pa.Table.from_batches([lote])
        lotes.append(tabla_lote)
        filas_acumuladas += tabla_lote.num_rows
        total_filas += tabla_lote.num_rows
        if filas_acumuladas >= TAMANO_LOTE_ESCRITURA:
            flush(lotes)
            lotes = []
            filas_acumuladas = 0
            print(f"  ... {total_filas:,} filas procesadas")
    flush(lotes)

    print(f"Listo: {total_filas:,} filas -> '{CARPETA_PARQUET}' (particionado por producto_codigo)")

    # --- 2. Un solo archivo Parquet combinado, para el boton de descarga "todo en Parquet" ---
    print("Armando el Parquet combinado (un solo archivo, para descarga directa)...")
    dataset = ds.dataset(CARPETA_PARQUET, format="parquet", partitioning="hive")
    tabla_completa = dataset.to_table()
    pq.write_table(tabla_completa, ARCHIVO_PARQUET_COMPLETO, compression="zstd")
    print(
        f"Listo: '{ARCHIVO_PARQUET_COMPLETO}' "
        f"({ARCHIVO_PARQUET_COMPLETO.stat().st_size / 1e6:.0f} MB, vs "
        f"{CSV_ORIGEN.stat().st_size / 1e6:.0f} MB el CSV original)"
    )


if __name__ == "__main__":
    main()
