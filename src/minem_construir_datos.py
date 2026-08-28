"""
minem_construir_datos.py

Arma la base de datos de proyectos mineros de la Cartera de Proyectos de
Inversión Minera (CPIM) del MINEM, a nivel de proyecto, a partir de la
Tabla 01 (actualización octubre 2025, 65 proyectos) y del Capítulo IV
(2 proyectos potenciales para la edición 2026) del informe en PDF/Markdown
que el usuario compartió. Transcrita a mano desde el documento -- la tabla
fuente viene con bastante ruido de OCR (celdas con varias filas pegadas,
columnas fuera de orden) para parsear de forma confiable con regex.

Genera, en data/minem_cpim/:
- proyectos_mineros_wide.csv  (una fila por proyecto, todas las columnas)
- proyectos_mineros_long.csv  (formato largo: proyecto, variable, valor)

Fuente: "Cartera de Proyectos de Inversión Minera 2025", Ministerio de
Energía y Minas del Perú, actualización a octubre de 2025.

Correr:
    python src/minem_construir_datos.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
CARPETA_SALIDA = RAIZ / "data" / "minem_cpim"

FUENTE = "CPIM MINEM, actualización octubre 2025"

# (inicio_ejecucion, fin_ejecucion, anio_puesta_marcha, proyecto, operador,
#  departamento, mineral_principal, etapa_avance, capex_musd)
# P.D. = "Por definir" en el original -> None (NaN)
PROYECTOS_CPIM = [
    (2022, 2025, 2025, "San Gabriel", "Compañía de Minas Buenaventura S.A.A.", "Moquegua", "Oro", "EJECUCIÓN", 650),
    (2023, 2042, 2024, "Reposición Inmaculada", "Compañía Minera Ares S.A.C.", "Ayacucho", "Oro", "EJECUCIÓN", 1319),
    (2024, 2029, 2024, "Reposición Antamina", "Compañía Minera Antamina S.A.", "Áncash", "Cobre", "EJECUCIÓN", 1604),
    (2024, 2026, 2026, "Romina", "Compañía Minera Chungar S.A.C.", "Lima", "Zinc", "EJECUCIÓN", 130),
    (2025, 2028, 2025, "Reposición San Rafael", "Minsur S.A.", "Puno", "Estaño", "FACTIBILIDAD", 294),
    (2025, 2036, 2025, "Reposición Colquijirca", "Sociedad Minera El Brocal SAA", "Pasco", "Cobre", "FACTIBILIDAD", 502),
    (2025, 2028, 2026, "Reposición Raura", "Compañía Minera Raura S.A.", "Huánuco", "Zinc", "EJECUCIÓN", 76),
    (2025, 2027, 2027, "Tía María", "Southern Perú Copper Corporation", "Arequipa", "Cobre", "EJECUCIÓN", 1802),
    (2025, 2028, 2028, "Corani", "Bear Creek Mining S.A.C.", "Puno", "Plata", "INGENIERÍA DE DETALLE", 579),
    (2025, 2033, 2028, "Pampa de Pongo", "Jinzhao Mining Perú S.A.", "Arequipa", "Hierro", "FACTIBILIDAD", 1781),
    (2025, 2028, 2029, "Zafranal", "Compañía Minera Zafranal S.A.C.", "Arequipa", "Cobre", "INGENIERÍA DE DETALLE", 1900),
    (2025, 2029, 2029, "Ampliación Huancapetí", "Compañía Minera Lincuna S.A.", "Áncash", "Zinc", "INGENIERÍA DE DETALLE", 345),
    (2026, 2032, 2026, "Ampliación Huarón", "Pan American Silver Huarón S.A.C.", "Pasco", "Plata", "FACTIBILIDAD", 118),
    (2026, 2053, 2026, "Optimización Cerro Verde", "Sociedad Minera Cerro Verde S.A.A.", "Arequipa", "Cobre", "FACTIBILIDAD", 2100),
    (2026, None, 2027, "Reposición Ferrobamba", "Minera Las Bambas S.A.", "Apurímac", "Cobre", "EJECUCIÓN", 1753),
    (2027, 2028, 2027, "Integración Coroccohuayco", "Compañía Minera Antapaccay S.A.", "Cusco", "Cobre", "FACTIBILIDAD", 1500),
    (2027, 2029, 2029, "Los Calatos", "Minera Hampton Perú S.A.C.", "Moquegua", "Cobre", "PRE-FACTIBILIDAD", 655),
    (2027, 2031, 2031, "Trapiche", "El Molle Verde S.A.C.", "Apurímac", "Cobre", "FACTIBILIDAD", 1038),
    (2029, 2034, 2032, "Coimolache Sulfuros", "Compañía Minera Coimolache S.A.", "Cajamarca", "Cobre", "CONCEPTUAL", 598),
    (2029, None, None, "La Arena Sulfuros", "La Arena S.A.", "La Libertad", "Cobre", "CONCEPTUAL", 1650),
    (None, None, 2027, "Mina Justa Subterránea", "Marcobre S.A.C.", "Ica", "Cobre", "CONCEPTUAL", 500),
    (None, None, 2029, "Ampliación Ilo", "Southern Perú Copper Corporation", "Moquegua", "Cobre", "CONCEPTUAL", 1354),
    (None, None, 2031, "Los Chancas", "Southern Perú Copper Corporation", "Apurímac", "Cobre", "PRE-FACTIBILIDAD", 2600),
    (None, None, 2032, "Michiquillay", "Southern Perú Copper Corporation", "Cajamarca", "Cobre", "CONCEPTUAL", 2500),
    (None, None, None, "Ampliación Bayóvar", "Compañía Minera Miski Mayo S.R.L.", "Piura", "Fosfatos", "FACTIBILIDAD", 450),
    (None, None, None, "Ampliación Cobriza", "Operadores Concentrados Peruanos S.A.C.", "Huancavelica", "Cobre", "PRE-FACTIBILIDAD", 93),
    (None, None, None, "Ampliación Contonga", "Norcobre S.A.C.", "Áncash", "Cobre", "CONCEPTUAL", 362),
    (None, None, None, "Ampliación Cuajone", "Southern Perú Copper Corporation", "Moquegua", "Cobre", "CONCEPTUAL", 605),
    (None, None, None, "Ampliación Esperanza", "Compañía Minera Caraveli S.A.C.", "Arequipa", "Oro", "PRE-FACTIBILIDAD", 300),
    (None, None, None, "Ampliación Huachocolpa", "Compañía Minera Kolpa S.A.", "Huancavelica", "Plata", "FACTIBILIDAD", 167),
    (None, None, None, "Ampliación Pachapaqui", "ICM Pachapaqui S.A.C.", "Áncash", "Zinc", "FACTIBILIDAD", 117),
    (None, None, None, "Ampliación Quellaveco", "Anglo American Quellaveco S.A.", "Moquegua", "Cobre", "PRE-FACTIBILIDAD", 850),
    (None, None, None, "Ampliación Recuperada", "Recuperada S.A.C.", "Huancavelica", "Plata", "PRE-FACTIBILIDAD", 138),
    (None, None, None, "Ampliación Shougang", "Shougang Hierro Peru S.A.A.", "Ica", "Hierro", "PRE-FACTIBILIDAD", 900),
    (None, None, None, "Ampliación Yauricocha", "Sociedad Minera Corona S.A.", "Lima", "Cobre", "PRE-FACTIBILIDAD", 235),
    (None, None, None, "Antilla", "Antilla Copper S.A.", "Apurímac", "Cobre", "PRE-FACTIBILIDAD", 250),
    (None, None, None, "Ariana", "Ariana Operaciones Mineras S.A.C.", "Junín", "Cobre", "EJECUCIÓN (SUSPENDIDA)", 140),
    (None, None, None, "Ayawilca", "Tinka Resources S.A.C.", "Pasco", "Zinc", "CONCEPTUAL", 382),
    (None, None, None, "Cañariaco", "Cañariaco Copper Perú S.A.", "Lambayeque", "Cobre", "PRE-FACTIBILIDAD", 2160),
    (None, None, None, "Cañón Florida", "Nexa Resources Perú S.A.A.", "Amazonas", "Zinc", "CONCEPTUAL", 214),
    (None, None, None, "Conga", "Minera Yanacocha S.R.L.", "Cajamarca", "Oro", "FACTIBILIDAD", 4800),
    (None, None, None, "Cotabambas", "Panoro Apurímac S.A.", "Apurímac", "Cobre", "PRE-FACTIBILIDAD", 1486),
    (None, None, None, "Don Javier", "Junefield Group S.A.", "Arequipa", "Cobre", "CONCEPTUAL", 600),
    (None, None, None, "El Galeno", "Lumina Copper S.A.C.", "Cajamarca", "Cobre", "PRE-FACTIBILIDAD", 3500),
    (None, None, None, "Haquira", "Minera Antares Perú S.A.C.", "Apurímac", "Cobre", "PRE-FACTIBILIDAD", 1860),
    (None, None, None, "Hierro Apurímac", "Apurímac Ferrum S.A.C.", "Apurímac", "Hierro", "PRE-FACTIBILIDAD", 2900),
    (None, None, None, "Hilarión", "Nexa Resources Perú S.A.A.", "Áncash", "Zinc", "PRE-FACTIBILIDAD", 585),
    (None, None, None, "Katy", "Cultinor S.A.C.", "Moquegua", "Cobre", "PRE-FACTIBILIDAD", 250),
    (None, None, None, "La Granja", "Minera La Granja S.A.C.", "Cajamarca", "Cobre", "CONCEPTUAL", 2400),
    (None, None, None, "Magistral", "Nexa Resources Perú S.A.A.", "Áncash", "Cobre", "FACTIBILIDAD", 493),
    (None, None, None, "Ollachea", "Minera Kuri Kullu S.A.", "Puno", "Oro", "PRE-FACTIBILIDAD", 126),
    (None, None, None, "Optimización Cajamarquilla", "Nexa Resources Cajamarquilla S.A.", "Lima", "Zinc", "FACTIBILIDAD", 96),
    (None, None, None, "Optimización Constancia", "Hudbay Perú S.A.C.", "Cusco", "Cobre", "PRE-FACTIBILIDAD", 500),
    (None, None, None, "Optimización Julcani", "Compañía de Minas Buenaventura S.A.A.", "Huancavelica", "Plata", "PRE-FACTIBILIDAD", 101),
    (None, None, None, "Optimización Pallancata", "Compañía Minera Ares S.A.C.", "Ayacucho", "Plata", "PRE-FACTIBILIDAD", 100),
    (None, None, None, "Optimización Pucamarca", "Minsur S.A.", "Tacna", "Oro", "INGENIERÍA DE DETALLE", 106),
    (None, None, None, "Planta de Cobre Río Seco", "Procesadora Industrial Río Seco S.A.", "Lima", "Cobre", "FACTIBILIDAD", 410),
    (None, None, None, "Pukaqaqa", "Olympic Precious Metals Ltd.", "Huancavelica", "Cobre", "PRE-FACTIBILIDAD", 655),
    (None, None, None, "Quechua", "Compañía Minera Quechua S.A.", "Cusco", "Cobre", "PRE-FACTIBILIDAD", 1290),
    (None, None, None, "Reaprovechamiento Quiruvilca", "Atom Enviromental II S.A.C.", "La Libertad", "Oro", "PRE-FACTIBILIDAD", 235),
    (None, None, None, "Reposición Cerro de Pasco", "Empresa Administradora Cerro S.A.C.", "Pasco", "Zinc", "PRE-FACTIBILIDAD", 129),
    (None, None, None, "Reposición Shahuindo", "Shahuindo S.A.C.", "Cajamarca", "Oro", "FACTIBILIDAD", 289),
    (None, None, None, "Río Blanco", "Rio Blanco Copper S.A.", "Piura", "Cobre", "FACTIBILIDAD", 2792),
    (None, None, None, "San Luis", "Reliant Ventures S.A.C.", "Áncash", "Plata", "FACTIBILIDAD", 90),
    (None, None, None, "Yanacocha Sulfuros", "Minera Yanacocha S.R.L.", "Cajamarca", "Cobre", "INGENIERÍA DE DETALLE", 2500),
]

# Proyectos potenciales para la Cartera de Inversión Minera 2026 (Cap. IV) --
# fuera de las 65 de la tabla 01, con datos parciales de sus fichas técnicas.
PROYECTOS_POTENCIALES_2026 = [
    {
        "proyecto": "Integración Atacocha - El Porvenir",
        "operador": np.nan,
        "departamento": np.nan,
        "mineral_principal": np.nan,
        "etapa_avance": "POTENCIAL CPIM 2026",
        "capex_musd": np.nan,
        "anio_inicio_ejecucion": np.nan,
        "anio_fin_ejecucion": np.nan,
        "anio_puesta_marcha": np.nan,
    },
    {
        "proyecto": "Optimización Carahuacra - San Cristobal",
        "operador": "Volcan Compañía Minera S.A.A.",
        "departamento": "Junín",
        "mineral_principal": "Zinc",
        "etapa_avance": "POTENCIAL CPIM 2026",
        "capex_musd": 242,
        "anio_inicio_ejecucion": np.nan,
        "anio_fin_ejecucion": np.nan,
        "anio_puesta_marcha": np.nan,
    },
]

# Campos bonus extraidos de las fichas tecnicas (solo disponibles para los
# proyectos que SI tienen ficha en el documento -- el resto queda en NaN).
TIPO_PROYECTO_FICHAS = {
    "Optimización Cerro Verde": "Brownfield",
    "Pampa de Pongo": "Greenfield",
    "Reposición Colquijirca": "Brownfield",
    "Tía María": "Greenfield",
    "Zafranal": "Greenfield",
    "Optimización Carahuacra - San Cristobal": "Brownfield",
}
SUBTIPO_PROYECTO_FICHAS = {
    "Optimización Cerro Verde": "Optimización",
    "Optimización Carahuacra - San Cristobal": "Integración",
}

# Ley del mineral / tonelaje de recursos o reservas, tal como los reporta la
# ficha tecnica de cada proyecto (formato libre: cada proyecto reporta esto
# de forma distinta -- unidades, si es recursos o reservas, por tajo, etc.).
LEY_RECURSOS_FICHAS = {
    "Optimización Cerro Verde": "4.58 Mt @ 0.35% Cu, 0.01% Mo, 1.52 g/t Ag",
    "Pampa de Pongo": "Mineral masivo: 3430.3 Mt @ 39.2% Fe, 0.1 ppm Au, 0.1% Cu (M&I); Mineral brechado: 193.6 Mt @ 17.2% Fe, 0.1% Cu (M&I)",
    "Reposición Colquijirca": "Tajo Sur: 4.53 Mt @ 2.05% Zn, 1% Pb, 2.85 oz/t Ag - 29.37 Mt @ 1.47% Cu, 0.66 oz/t Ag; Marcapunta UG: 30.5 Mt @ 1.29% Cu, 1.04 oz/t Ag, 0.67 oz/t Au; Tajo Norte: 6.32 Mt @ 2.26% Zn y Pb, 2.26 oz/t Ag - 1.77 Mt @ 1.51% Cu, 3.02 oz/t Ag",
    "Tía María": "Tajo La Tapada: 487.6 Mt @ 0.41% Cu",
    "Zafranal": "440.7 Mt @ 0.38% Cu, 0.07 g/t Au (P&P)",
}

# Capacidad de planta / producción anual estimada, tal como la reporta la
# ficha tecnica (formato libre).
CAPACIDAD_PLANTA_FICHAS = {
    "Optimización Cerro Verde": "Ampliación de concentradoras a 420 000 t/día",
    "Pampa de Pongo": "Fase I: 10 Mt/año; Fase II: 20 Mt/año; Fase III: 30 Mt/año",
    "Reposición Colquijirca": "Ampliación de 21 600 a 25 000 t/día",
    "Tía María": "100 000 t/día",
    "Zafranal": "80 000 t/día",
}


def construir_wide() -> pd.DataFrame:
    filas = []
    for inicio, fin, puesta, proyecto, operador, depto, mineral, etapa, capex in PROYECTOS_CPIM:
        filas.append({
            "proyecto": proyecto,
            "operador": operador,
            "departamento": depto,
            "mineral_principal": mineral,
            "etapa_avance": etapa,
            "capex_musd": capex,
            "anio_inicio_ejecucion": inicio,
            "anio_fin_ejecucion": fin,
            "anio_puesta_marcha": puesta,
        })
    filas.extend(PROYECTOS_POTENCIALES_2026)

    df = pd.DataFrame(filas)
    df["tipo_proyecto"] = df["proyecto"].map(TIPO_PROYECTO_FICHAS)
    df["subtipo_proyecto"] = df["proyecto"].map(SUBTIPO_PROYECTO_FICHAS)
    df["ley_mineral_recursos"] = df["proyecto"].map(LEY_RECURSOS_FICHAS)
    df["capacidad_planta"] = df["proyecto"].map(CAPACIDAD_PLANTA_FICHAS)
    df["tiene_fecha_definida"] = df["anio_inicio_ejecucion"].notna() | df["anio_fin_ejecucion"].notna()
    df["fuente"] = FUENTE

    for col in ["anio_inicio_ejecucion", "anio_fin_ejecucion", "anio_puesta_marcha"]:
        df[col] = df[col].astype("Int64")

    columnas = [
        "proyecto", "operador", "departamento", "mineral_principal",
        "etapa_avance", "tipo_proyecto", "subtipo_proyecto",
        "ley_mineral_recursos", "capacidad_planta",
        "anio_inicio_ejecucion", "anio_fin_ejecucion", "anio_puesta_marcha",
        "tiene_fecha_definida", "capex_musd", "fuente",
    ]
    return df[columnas].sort_values("proyecto").reset_index(drop=True)


def construir_long(wide: pd.DataFrame) -> pd.DataFrame:
    columnas_variables = [c for c in wide.columns if c not in ("proyecto", "fuente")]
    largo = wide.melt(id_vars=["proyecto", "fuente"], value_vars=columnas_variables, var_name="variable", value_name="valor")
    largo["valor"] = largo["valor"].astype(str).replace({"nan": np.nan, "<NA>": np.nan, "None": np.nan})
    return largo.sort_values(["proyecto", "variable"]).reset_index(drop=True)


def main():
    CARPETA_SALIDA.mkdir(parents=True, exist_ok=True)
    wide = construir_wide()
    long = construir_long(wide)

    ruta_wide = CARPETA_SALIDA / "proyectos_mineros_wide.csv"
    ruta_long = CARPETA_SALIDA / "proyectos_mineros_long.csv"
    wide.to_csv(ruta_wide, index=False, encoding="utf-8-sig")
    long.to_csv(ruta_long, index=False, encoding="utf-8-sig")

    print(f"{len(wide)} proyectos -> {ruta_wide}")
    print(f"{len(long)} filas (formato largo) -> {ruta_long}")
    print(f"\nCapex total: US$ {wide['capex_musd'].sum():,.0f} millones")
    print(f"Por mineral principal:\n{wide['mineral_principal'].value_counts()}")
    print(f"\nPor etapa de avance:\n{wide['etapa_avance'].value_counts()}")


if __name__ == "__main__":
    main()
