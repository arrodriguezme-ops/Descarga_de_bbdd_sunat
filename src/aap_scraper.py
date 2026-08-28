"""
aap_scraper.py

Descubre y descarga todos los informes mensuales del sector automotor
publicados por la AAP (Asociación Automotriz del Perú) en
https://aap.org.pe/estadisticas/informes-del-sector-automotor.

La pagina trae TODOS los enlaces a PDF ya en el HTML (no hace falta hacer
click año por año) -- para los años 2020-2025 la URL misma trae el año y
el mes (/estadisticas/{año}/{Mes}.pdf); para el año en curso (carpeta
"informes-mensuales", con nombres de archivo mas variados) se usa el texto
visible del enlace (el nombre del mes) + el año actual.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Callable, Optional

import pandas as pd
import requests
from bs4 import BeautifulSoup

URL_INFORMES = "https://aap.org.pe/estadisticas/informes-del-sector-automotor"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "setiembre": 9, "septiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}
NOMBRE_MES = {v: k.capitalize() for k, v in MESES.items() if k != "septiembre"}


def listar_informes() -> pd.DataFrame:
    """Devuelve un DataFrame [anio, mes, mes_nombre, url] con todos los
    informes mensuales encontrados en la pagina de AAP.

    La pagina organiza los informes en un panel por año
    (<div id="2026" class="tab-panel">...</div>, uno por cada año), asi que
    el año se saca del id de ese contenedor -- NO de la URL del PDF (los
    informes mas recientes viven todos bajo una misma carpeta
    "informes-mensuales" sin año en el nombre de archivo, incluyendo meses
    de más de un año calendario distinto)."""
    resp = requests.get(URL_INFORMES, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    filas = []
    for panel in soup.select("div.tab-panel[id]"):
        anio_id = panel.get("id", "")
        if not re.fullmatch(r"\d{4}", anio_id):
            continue
        anio = int(anio_id)

        for a in panel.select('a[href$=".pdf"]'):
            href = a.get("href", "")
            texto = a.get_text(strip=True)

            # El mes: primero se intenta sacar de la URL (año/Mes.pdf), y si
            # no matchea (carpeta "informes-mensuales", nombres de archivo
            # variados) se usa el texto visible del enlace.
            m = re.search(r"/([A-Za-zÀ-ÿ]+)\.pdf$", href, re.I)
            mes_nombre_raw = (m.group(1) if m else texto).lower()
            mes = MESES.get(mes_nombre_raw) or MESES.get(texto.lower())
            if mes is None:
                continue  # no es un informe mensual (ej. politicas, otros PDFs)

            url = href if href.startswith("http") else "https://aap.org.pe" + href
            filas.append({"anio": anio, "mes": mes, "mes_nombre": NOMBRE_MES[mes], "url": url})

    df = pd.DataFrame(filas).drop_duplicates(subset=["anio", "mes"], keep="first")
    return df.sort_values(["anio", "mes"]).reset_index(drop=True)


def nombre_archivo(anio: int, mes: int) -> str:
    return f"{anio}-{mes:02d}.pdf"


def descargar_informes(
    carpeta_destino: Path,
    forzar: bool = False,
    pausa_seg: float = 0.5,
    on_status: Optional[Callable[[dict], None]] = None,
) -> pd.DataFrame:
    """Descarga todos los informes encontrados por listar_informes() a
    carpeta_destino (nombre {año}-{mes:02d}.pdf). Si ya existe el archivo y
    forzar=False, no lo vuelve a descargar. Devuelve el DataFrame de
    listar_informes() con una columna adicional 'archivo_local'."""
    carpeta_destino.mkdir(parents=True, exist_ok=True)
    df = listar_informes()

    rutas = []
    for _, fila in df.iterrows():
        ruta = carpeta_destino / nombre_archivo(fila["anio"], fila["mes"])
        etiqueta = f"{fila['mes_nombre']} {fila['anio']}"

        if ruta.exists() and not forzar:
            if on_status:
                on_status({"informe": etiqueta, "estado": "Ya descargado"})
            rutas.append(str(ruta))
            continue

        if on_status:
            on_status({"informe": etiqueta, "estado": "Descargando"})
        try:
            resp = requests.get(fila["url"], headers=HEADERS, timeout=60)
            resp.raise_for_status()
            ruta.write_bytes(resp.content)
            rutas.append(str(ruta))
            if on_status:
                on_status({"informe": etiqueta, "estado": "Completado", "mensaje": f"{len(resp.content)/1024:.0f} KB"})
        except requests.RequestException as e:
            rutas.append(None)
            if on_status:
                on_status({"informe": etiqueta, "estado": "Error", "mensaje": str(e)})
        time.sleep(pausa_seg)

    df["archivo_local"] = rutas
    return df
