"""
generar_mockup_ihh.py

Genera un Excel de prueba (data/mockup_ihh.xlsx) con la forma que espera el
servicio de Concentración (IHH): una fila por empresa/grupo/año/lado, con
una columna de cantidad (producción) y otra de facturación -- para poder
probar el servicio sin tener que armar tu propia base primero.

Simula un mercado electrico ficticio (parecido al caso Manhattan que
inspiro el script original), con dos lados (Oferta / Demanda), 3 años y
grupos economicos con distinta participacion -- incluyendo un caso donde
fusionar dos de ellos sube el IHH de forma notoria.

Correr:
    python src/generar_mockup_ihh.py
"""

import numpy as np
import pandas as pd

np.random.seed(7)

RUTA_SALIDA = "data/mockup_ihh.xlsx"

ANIOS = [2023, 2024, 2025]

# (empresa, grupo_economico, participacion_base_oferta)
EMPRESAS_OFERTA = [
    ("Generadora Andina",     "Grupo Cordillera",  0.28),
    ("Hidroeléctrica del Sur","Grupo Cordillera",  0.10),
    ("Energía Pacífico",      "Grupo Pacífico",    0.22),
    ("Termoeléctrica Costa",  "Grupo Pacífico",    0.06),
    ("Solar Amazonas",        "Grupo Amazonas",    0.14),
    ("Eólica Altiplano",      "Grupo Altiplano",   0.11),
    ("Generadora Independiente 1", "Independiente 1", 0.05),
    ("Generadora Independiente 2", "Independiente 2", 0.04),
]

EMPRESAS_DEMANDA = [
    ("Distribuidora Norte",   "Grupo Cordillera",  0.20),
    ("Comercializadora Sur",  "Grupo Pacífico",    0.18),
    ("Industrial Andes",      "Grupo Amazonas",    0.15),
    ("Retail Energético",     "Grupo Altiplano",   0.12),
    ("Cliente Libre 1",       "Independiente 1",   0.10),
    ("Cliente Libre 2",       "Independiente 2",   0.09),
    ("Cliente Libre 3",       "Independiente 3",   0.08),
    ("Cliente Libre 4",       "Independiente 4",   0.08),
]

MERCADOS = ["L", "R"]  # 'L' = Libre, 'R' = Regulado (para probar el filtro opcional)


def _generar_bloque(empresas, lado, unidad_base):
    filas = []
    for anio in ANIOS:
        crecimiento = 1 + 0.05 * (anio - ANIOS[0])
        for empresa, grupo, participacion_base in empresas:
            ruido = np.random.normal(1, 0.08)
            cantidad = round(unidad_base * participacion_base * crecimiento * ruido, 2)
            precio_unitario = round(np.random.normal(180, 15), 2)
            facturacion = round(cantidad * precio_unitario, 2)
            mercado = np.random.choice(MERCADOS, p=[0.8, 0.2])
            filas.append({
                "anio": anio,
                "empresa": empresa,
                "grupo_economico": grupo,
                "lado": lado,
                "mercado": mercado,
                "cantidad_produccion_gwh": cantidad,
                "facturacion_miles_usd": facturacion,
            })
    return filas


def main():
    filas = _generar_bloque(EMPRESAS_OFERTA, "Oferta", unidad_base=1000)
    filas += _generar_bloque(EMPRESAS_DEMANDA, "Demanda", unidad_base=900)

    df = pd.DataFrame(filas)
    df.to_excel(RUTA_SALIDA, index=False, sheet_name="Datos")
    print(f"Mockup generado: {RUTA_SALIDA} ({len(df)} filas)")
    print(df.head(10))


if __name__ == "__main__":
    main()
