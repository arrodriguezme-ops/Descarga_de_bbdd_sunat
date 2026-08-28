"""
nasa_power.py

Cliente para la API publica de NASA POWER (power.larc.nasa.gov), que entrega
series diarias de clima por punto geografico (temperatura, humedad,
precipitacion, etc.) sin necesidad de API key ni cuenta.

Es el mismo servicio que usa por debajo el paquete de R 'nasapower' -- aca se
llama directo via requests, sin depender de ningun paquete de Python externo
(no hace falta 'nasapower' para Python, la API REST es publica y simple).

Documentacion: https://power.larc.nasa.gov/docs/services/api/temporal/daily/
"""

from __future__ import annotations

import time
from typing import Optional

import pandas as pd
import requests

URL_POWER_DIARIO = "https://power.larc.nasa.gov/api/temporal/daily/point"

# Parametros de clima mas usados -> etiqueta legible en español
PARAMETROS_DISPONIBLES = {
    "T2M_MAX": "Temperatura maxima (°C)",
    "T2M_MIN": "Temperatura minima (°C)",
    "T2M": "Temperatura promedio (°C)",
    "RH2M": "Humedad relativa (%)",
    "PRECTOTCORR": "Precipitacion (mm/dia)",
}

# Coordenadas (capital de cada departamento/region del Peru) -- da una serie
# climatica puntual representativa; NO es un promedio del area completa del
# departamento (para eso harian falta poligonos y multiples puntos por zona).
DEPARTAMENTOS_PERU: dict[str, tuple[float, float]] = {
    "Amazonas": (-6.2298, -77.8683),
    "Áncash": (-9.5277, -77.5278),
    "Apurímac": (-13.6339, -72.8814),
    "Arequipa": (-16.4090, -71.5375),
    "Ayacucho": (-13.1588, -74.2232),
    "Cajamarca": (-7.1638, -78.5003),
    "Callao": (-12.0566, -77.1181),
    "Cusco": (-13.5319, -71.9675),
    "Huancavelica": (-12.7863, -74.9757),
    "Huánuco": (-9.9306, -76.2422),
    "Ica": (-14.0678, -75.7286),
    "Junín": (-12.0653, -75.2049),
    "La Libertad": (-8.1116, -79.0287),
    "Lambayeque": (-6.7714, -79.8409),
    "Lima": (-12.0464, -77.0428),
    "Loreto": (-3.7491, -73.2538),
    "Madre de Dios": (-12.5933, -69.1891),
    "Moquegua": (-17.1938, -70.9350),
    "Pasco": (-10.6866, -76.2560),
    "Piura": (-5.1945, -80.6328),
    "Puno": (-15.8402, -70.0219),
    "San Martín": (-6.0339, -76.9714),
    "Tacna": (-18.0146, -70.2536),
    "Tumbes": (-3.5669, -80.4515),
    "Ucayali": (-8.3791, -74.5539),
}

PRIMER_ANIO_DISPONIBLE = 1981


def descargar_clima_departamento(
    departamento: str,
    anio_inicio: int,
    anio_fin: int,
    parametros: Optional[list[str]] = None,
    reintentos: int = 3,
    timeout: int = 60,
) -> pd.DataFrame:
    """Descarga la serie diaria de clima de NASA POWER para el punto
    (lat, lon) de la capital del departamento indicado, entre anio_inicio y
    anio_fin (inclusive). Devuelve un DataFrame con columnas:
    fecha, departamento, <una columna por parametro pedido>.
    """
    if departamento not in DEPARTAMENTOS_PERU:
        raise ValueError(
            f"Departamento desconocido: '{departamento}'. "
            f"Opciones validas: {', '.join(sorted(DEPARTAMENTOS_PERU))}"
        )
    lat, lon = DEPARTAMENTOS_PERU[departamento]
    parametros = parametros or list(PARAMETROS_DISPONIBLES.keys())

    params = {
        "parameters": ",".join(parametros),
        "community": "AG",
        "longitude": lon,
        "latitude": lat,
        "start": f"{anio_inicio}0101",
        "end": f"{anio_fin}1231",
        "format": "JSON",
    }

    ultimo_error: Optional[Exception] = None
    data = None
    for intento in range(1, reintentos + 1):
        try:
            resp = requests.get(URL_POWER_DIARIO, params=params, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            break
        except requests.RequestException as e:
            ultimo_error = e
            time.sleep(2 * intento)
    if data is None:
        raise RuntimeError(f"No se pudo consultar NASA POWER para {departamento}: {ultimo_error}")

    parametros_data = data.get("properties", {}).get("parameter", {})
    if not parametros_data:
        detalle = data.get("messages") or data.get("header") or data
        raise RuntimeError(f"NASA POWER no devolvio datos para {departamento}: {detalle}")

    series = {}
    for param, valores in parametros_data.items():
        s = pd.Series(valores, name=param, dtype="float64")
        s.index = pd.to_datetime(s.index, format="%Y%m%d")
        series[param] = s

    df = pd.DataFrame(series).sort_index()
    # NASA POWER marca los datos faltantes con -999
    df = df.mask(df <= -990)
    df.index.name = "fecha"
    df = df.reset_index()
    df.insert(1, "departamento", departamento)
    return df
