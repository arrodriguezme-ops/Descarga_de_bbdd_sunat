"""
sunat_scraper.py

Modulo reutilizable con la logica de consulta y descarga de importaciones /
exportaciones por subpartida nacional en el portal de Aduanas SUNAT
(aduanet.gob.pe). Traducido y generalizado a partir del script original en R
(pensado solo para vehiculos, subpartidas 8703/8704/8711) para que funcione
con CUALQUIER subpartida de 10 digitos.

Lo usan tanto el dashboard (dashboard.py) como el notebook de descarga masiva
(notebooks/sunat_importaciones_scraper.ipynb), para no duplicar la logica.

Notas de funcionamiento del portal (descubiertas por prueba y error):
- El periodo de consulta (fini/ffin) debe estar DENTRO del mismo anio. No se
  puede pedir un rango que cruce de un anio a otro en una sola consulta.
- Los parametros de descarga (fregistro/hregistro) NO son la fecha/hora
  visible en la tabla de resultados -- son la hora real de registro del
  requerimiento, embebida en el atributo onclick de cada enlace
  (javascript:jsDescargarArchivo('archivo.ZIP','yyyymmdd','hhmmss')). Hay
  que extraerlos del HTML, no reconstruirlos de las columnas visibles.
- SUNAT procesa el requerimiento de forma asincrona: el reporte no queda
  listo al toque, hay que consultar la tabla de resultados varias veces
  (polling) hasta que el estado de la fila cambie a "Reporte".
"""

from __future__ import annotations

import io
import re
import time
import zipfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable, Optional

import pandas as pd
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    from dbfread import DBF
except ImportError:  # dbfread es opcional hasta que se necesite leer un .dbf
    DBF = None

# ---------------------------------------------------------------------------
# URLs del portal y configuracion general
# ---------------------------------------------------------------------------
URL_FORMULARIO = "http://www.aduanet.gob.pe/cl-ad-itestdesp/FrmConsultaSumin.jsp?tcon=E"
URL_ENVIO = "http://www.aduanet.gob.pe/cl-ad-itestdesp/SEGrabaReq"
URL_RESULTADOS = "http://www.aduanet.gob.pe/cl-ad-itsuministro/descargaS01Alias?accion=cargarFrmDescargarResultado"
URL_DESCARGA = "http://www.aduanet.gob.pe/cl-ad-itsuministro/descargaS01Alias"

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

DIAS_FIN_MES = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

# Estados posibles que se reportan via el callback on_status (para pintar
# la tabla lateral de progreso con colores en el dashboard).
ESTADO_PENDIENTE = "Pendiente"
ESTADO_ENVIANDO = "Enviando consulta"
ESTADO_ESPERANDO = "Esperando a SUNAT"
ESTADO_DESCARGANDO = "Descargando"
ESTADO_LEYENDO = "Leyendo datos"
ESTADO_COMPLETADO = "Completado"
ESTADO_SIN_DATOS = "Sin datos"
ESTADO_ERROR = "Error"
ESTADO_PARTIDA_INVALIDA = "Partida invalida"

# Palabras clave que SUNAT usa en la columna "Estado" de la tabla de
# resultados para decir "ya terminé de procesar, y no hay nada" -- son
# estados FINALES, no hay que seguir sondeando hasta que aparezcan como
# "Reporte" (nunca va a pasar). Antes el codigo los trataba como "sigue
# pendiente" y esperaba los 30 minutos completos para recien ahi fallar
# con timeout, cuando en realidad el resultado (sin datos) ya se sabia
# desde el primer chequeo.
_PALABRAS_SIN_DATOS = ("sin registro", "sin datos", "no existe informacion", "no existe información")


def _interpretar_estado_sunat(estado_resultado: str) -> str:
    """Clasifica el string de estado que devuelve SUNAT en:
    'listo' (el reporte esta listo para descargar), 'sin_datos' (SUNAT ya
    termino de procesar y no encontro registros -- estado final, no seguir
    esperando), o 'pendiente' (sigue en cola/procesando)."""
    e = estado_resultado.strip().lower()
    if e == "reporte":
        return "listo"
    if any(palabra in e for palabra in _PALABRAS_SIN_DATOS):
        return "sin_datos"
    return "pendiente"


@dataclass
class ResultadoAnio:
    subpartida: str
    anio: int
    estado: str
    mensaje: str = ""
    registros: int = 0
    archivo_local: Optional[str] = None
    datos: Optional[pd.DataFrame] = None


# ---------------------------------------------------------------------------
# Sesion / validacion
# ---------------------------------------------------------------------------
def nueva_sesion() -> requests.Session:
    """Crea una sesion nueva replicando la navegacion real (necesario para
    que el servidor entregue las cookies correctas).

    Monta un adaptador con reintentos automaticos (con backoff) para que un
    hipo pasajero de red/DNS -- que ya vimos que pasa contra aduanet.gob.pe
    de vez en cuando -- no tumbe toda la consulta de una: reintenta un par
    de veces antes de darse por vencido."""
    s = requests.Session()
    s.headers.update(HEADERS)
    reintentos = Retry(
        total=4,
        connect=4,
        read=2,
        backoff_factor=2,  # 2s, 4s, 8s, 16s...
        status_forcelist=[502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    adaptador = HTTPAdapter(max_retries=reintentos)
    s.mount("http://", adaptador)
    s.mount("https://", adaptador)
    s.get(URL_FORMULARIO, timeout=30)
    s.get(URL_RESULTADOS, headers={"Referer": URL_FORMULARIO}, timeout=30)
    return s


def validar_subpartida(subpartida: str, sesion: requests.Session) -> dict:
    """Verifica contra el propio servidor si una subpartida de 10 digitos
    existe / esta vigente, sin llegar a generar un requerimiento real."""
    fecha_prueba = date.today().strftime("%d/%m/%Y")
    data = {
        "lcnan": subpartida, "fini": fecha_prueba, "ffin": fecha_prueba,
        "ltotaduana": "T", "ltotpais": "T", "tipo": "DBF", "tcon": "E", "regi": "Impo",
    }
    try:
        resp = sesion.post(URL_ENVIO, data=data, headers={"Referer": URL_FORMULARIO}, timeout=30)
    except requests.RequestException:
        return {"subpartida": subpartida, "valida": None, "vigencia": None}
    texto = resp.content.decode("ISO-8859-1", errors="replace")
    invalida = "PARTIDA NO EXISTE" in texto.upper()
    m = re.search(r"FECHAS DE VIGENCIA DE PARTIDA:\s*[0-9/]+\s*-\s*[0-9/]+", texto)
    vigencia = m.group(0) if m else None
    return {"subpartida": subpartida, "valida": not invalida, "vigencia": vigencia}


# ---------------------------------------------------------------------------
# Envio de consultas
# ---------------------------------------------------------------------------
def fechas_del_anio(anio: int, mes_fin: int = 12, dia_fin: Optional[int] = None) -> tuple[str, str]:
    """Devuelve (fini, ffin) en formato dd/mm/aaaa para un anio completo, o
    recortado hasta mes_fin/dia_fin (util para el anio en curso)."""
    fini = f"01/01/{anio}"
    if dia_fin is None:
        dia_fin = DIAS_FIN_MES[mes_fin - 1]
    ffin = f"{dia_fin:02d}/{mes_fin:02d}/{anio}"
    return fini, ffin


def enviar_consulta(subpartida: str, fini: str, ffin: str, sesion: requests.Session, regi: str = "Impo") -> dict:
    """Envia el requerimiento de descarga para una subpartida y un rango de
    fechas (regi='Impo' para importaciones, 'Expo' para exportaciones)."""
    data = {
        "lcnan": subpartida, "fini": fini, "ffin": ffin,
        "ltotaduana": "T", "ltotpais": "T", "tipo": "DBF", "tcon": "E", "regi": regi,
    }
    resp = sesion.post(URL_ENVIO, data=data, headers={"Referer": URL_FORMULARIO}, timeout=30)
    texto = resp.content.decode("ISO-8859-1", errors="replace")
    m = re.search(r"\d{8}\.CON", texto)
    numero = m.group(0) if m else None
    partida_invalida = "PARTIDA NO EXISTE" in texto.upper()
    if numero:
        estado = "OK"
    elif partida_invalida:
        estado = "PARTIDA_INVALIDA"
    else:
        estado = "SIN_CONFIRMACION"
    return {
        "subpartida": subpartida, "fini": fini, "ffin": ffin,
        "numero_consulta": numero, "estado": estado, "status_code": resp.status_code,
    }


# ---------------------------------------------------------------------------
# Tabla de resultados y descarga
# ---------------------------------------------------------------------------
def obtener_tabla_resultados(sesion: requests.Session) -> pd.DataFrame:
    """Lee la tabla 'Obtencion de Resultados' del portal y extrae, ademas de
    las columnas visibles (Estado, Registros), los parametros REALES de
    descarga (fregistro/hregistro) desde el atributo onclick de cada enlace."""
    resp = sesion.get(URL_RESULTADOS, headers={"Referer": URL_FORMULARIO}, timeout=30)
    html = resp.content.decode("ISO-8859-1", errors="replace")
    soup = BeautifulSoup(html, "html.parser")

    filas_enlaces = []
    for a in soup.select("a[href*='jsDescargarArchivo']"):
        m = re.search(
            r"jsDescargarArchivo\('([^']+)'\s*,\s*'([^']+)'\s*,\s*'([^']+)'\)",
            a.get("href", ""),
        )
        if m:
            filas_enlaces.append({
                "archivo": m.group(1).strip(),
                "fregistro": m.group(2).strip(),
                "hregistro": m.group(3).strip(),
            })
    df_enlaces = pd.DataFrame(filas_enlaces).drop_duplicates(subset="archivo") if filas_enlaces else pd.DataFrame(
        columns=["archivo", "fregistro", "hregistro"]
    )

    # io.StringIO envuelve el HTML explicitamente como contenido -- si se le
    # pasa el string tal cual, lxml puede intentar interpretarlo como un
    # nombre de archivo (y truena con "No such file or directory: <html...").
    tablas = pd.read_html(io.StringIO(html))
    if not tablas:
        return pd.DataFrame(columns=["archivo", "estado", "registros", "fregistro", "hregistro"])
    tabla = max(tablas, key=len).copy()
    n_cols = tabla.shape[1]
    nombres = [
        "fecha_registro", "fecha_ini_consulta", "hora_ini",
        "hora_fin", "estado", "registros", "archivo",
    ][:n_cols]
    tabla.columns = nombres
    tabla = tabla.astype(str)
    tabla["archivo"] = tabla["archivo"].str.strip()
    tabla = tabla[(tabla["archivo"].notna()) & (tabla["archivo"] != "") & (tabla["archivo"] != "nan")]
    # SUNAT no usa <thead>, asi que pandas a veces lee la fila de encabezado
    # tambien como dato (archivo == "Archivo" literal) -- se descarta.
    tabla = tabla[tabla["archivo"].str.contains(r"\.\w+$", regex=True, na=False)]
    return tabla.merge(df_enlaces, on="archivo", how="left")


def descargar_resultado(
    archivo: str, fregistro: str, hregistro: str, sesion: requests.Session, carpeta_destino: Path
) -> Optional[str]:
    data = {
        "accion": "descargarArchivo",
        "filename": archivo.strip(),
        "fregistro": str(fregistro).strip(),
        "hregistro": str(hregistro).strip(),
    }
    resp = sesion.post(URL_DESCARGA, data=data, headers={"Referer": URL_RESULTADOS}, timeout=60)
    contenido = resp.content
    es_pagina_error = False
    try:
        txt = contenido.decode("ISO-8859-1", errors="ignore")
        es_pagina_error = ("Pagina de Errores" in txt) or ("La aplicaci" in txt)
    except Exception:
        pass
    if resp.status_code == 200 and len(contenido) > 0 and not es_pagina_error:
        carpeta_destino.mkdir(parents=True, exist_ok=True)
        destino = carpeta_destino / archivo.strip()
        destino.write_bytes(contenido)
        return str(destino)
    return None


def extraer_zip(zip_path: Path, carpeta_dbf: Path) -> list[Path]:
    carpeta_dbf.mkdir(parents=True, exist_ok=True)
    extraidos = []
    try:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(carpeta_dbf)
            extraidos = [carpeta_dbf / n for n in zf.namelist() if n.lower().endswith(".dbf")]
    except zipfile.BadZipFile:
        pass
    return extraidos


def leer_dbf(path: Path) -> Optional[pd.DataFrame]:
    if DBF is None:
        raise ImportError("Falta instalar 'dbfread' (pip install dbfread) para leer archivos .DBF")
    try:
        tabla = DBF(path, encoding="latin-1", ignore_missing_memofile=True)
        df = pd.DataFrame(iter(tabla))
        df["archivo_origen"] = path.name
        return df
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Helper compartido: una vez que una fila de la tabla de resultados quedo en
# estado "Reporte", descargarla, descomprimirla y leer el/los .DBF.
# ---------------------------------------------------------------------------
def _finalizar_descarga(
    subpartida: str,
    anio: int,
    fila_lista: pd.Series,
    sesion: requests.Session,
    carpeta_resultados: Path,
    carpeta_dbf: Path,
    avisar: Callable[..., None],
) -> ResultadoAnio:
    archivo = fila_lista["archivo"]
    fregistro = fila_lista.get("fregistro")
    hregistro = fila_lista.get("hregistro")
    n_registros = fila_lista.get("registros")

    if pd.isna(fregistro) or pd.isna(hregistro):
        avisar(ESTADO_ERROR, "No se encontraron fregistro/hregistro para descargar")
        return ResultadoAnio(subpartida, anio, ESTADO_ERROR, mensaje="Sin fregistro/hregistro")

    try:
        n_registros_int = int(float(str(n_registros).replace(",", "")))
    except (TypeError, ValueError):
        n_registros_int = 0

    if n_registros_int == 0:
        avisar(ESTADO_SIN_DATOS, "SUNAT no reporta registros para este periodo")
        return ResultadoAnio(subpartida, anio, ESTADO_SIN_DATOS, registros=0)

    avisar(ESTADO_DESCARGANDO, f"Descargando {archivo} ({n_registros_int} registros)")
    try:
        ruta_local = descargar_resultado(archivo, fregistro, hregistro, sesion, carpeta_resultados)
    except requests.RequestException as e:
        avisar(ESTADO_ERROR, f"Fallo la descarga: {e}")
        return ResultadoAnio(subpartida, anio, ESTADO_ERROR, mensaje=str(e))

    if not ruta_local:
        avisar(ESTADO_ERROR, "La descarga no devolvio contenido valido")
        return ResultadoAnio(subpartida, anio, ESTADO_ERROR, mensaje="Descarga vacia")

    avisar(ESTADO_LEYENDO, "Descomprimiendo y leyendo el .DBF")
    dbfs = extraer_zip(Path(ruta_local), carpeta_dbf)
    if not dbfs:
        avisar(ESTADO_ERROR, "El .ZIP no contenia archivos .DBF")
        return ResultadoAnio(subpartida, anio, ESTADO_ERROR, mensaje="Zip sin .dbf", archivo_local=ruta_local)

    partes = [leer_dbf(f) for f in dbfs]
    partes = [p for p in partes if p is not None]
    if not partes:
        avisar(ESTADO_ERROR, "No se pudo leer ningun .DBF")
        return ResultadoAnio(subpartida, anio, ESTADO_ERROR, mensaje="DBF ilegible", archivo_local=ruta_local)

    datos = pd.concat(partes, ignore_index=True)
    datos["subpartida_consultada"] = subpartida
    datos["anio_consultado"] = anio

    avisar(ESTADO_COMPLETADO, f"{len(datos)} filas descargadas", registros=len(datos))
    return ResultadoAnio(
        subpartida, anio, ESTADO_COMPLETADO,
        mensaje=f"{len(datos)} filas", registros=len(datos),
        archivo_local=ruta_local, datos=datos,
    )


# ---------------------------------------------------------------------------
# Orquestacion: TODOS los anios de una subpartida de una vez (envia todas las
# solicitudes primero, y hace un solo sondeo conjunto para todas) -- mucho
# mas rapido que procesar un anio a la vez cuando se piden varios anios,
# porque el tiempo total pasa a ser el maximo de espera entre anios y no la
# suma.
# ---------------------------------------------------------------------------
def procesar_subpartida_anios(
    subpartida: str,
    anios: list[int],
    sesion: requests.Session,
    carpeta_resultados: Path,
    carpeta_dbf: Path,
    regi: str = "Impo",
    anio_actual: Optional[int] = None,
    max_espera_seg: int = 1800,
    intervalo_poll_seg: int = 20,
    pausa_entre_envios_seg: float = 1.5,
    on_status: Optional[Callable[[dict], None]] = None,
) -> dict[int, ResultadoAnio]:
    """Version por lotes de procesar_subpartida_anio: manda las consultas de
    TODOS los anios primero, y despues sondea la tabla de resultados UNA vez
    por vuelta (en vez de una vez por anio) para ver cuales ya quedaron
    listos, descargando cada uno apenas aparece. Devuelve {anio: ResultadoAnio}.
    """
    if anio_actual is None:
        anio_actual = date.today().year

    def _avisar(anio: int, estado: str, mensaje: str = "", registros: int = 0):
        if on_status:
            on_status({
                "subpartida": subpartida, "anio": anio,
                "estado": estado, "mensaje": mensaje, "registros": registros,
            })

    resultados: dict[int, ResultadoAnio] = {}
    pendientes: dict[int, str] = {}  # anio -> numero_base

    # --- 1. Enviar TODAS las consultas primero ---
    for anio in anios:
        if anio == anio_actual:
            fini, ffin = fechas_del_anio(anio, mes_fin=date.today().month, dia_fin=date.today().day)
        else:
            fini, ffin = fechas_del_anio(anio)

        _avisar(anio, ESTADO_ENVIANDO, f"Consultando {fini} - {ffin}")
        try:
            envio = enviar_consulta(subpartida, fini, ffin, sesion, regi=regi)
        except requests.RequestException as e:
            _avisar(anio, ESTADO_ERROR, f"No se pudo enviar la consulta: {e}")
            resultados[anio] = ResultadoAnio(subpartida, anio, ESTADO_ERROR, mensaje=str(e))
            continue

        if envio["estado"] == "PARTIDA_INVALIDA":
            _avisar(anio, ESTADO_PARTIDA_INVALIDA, "SUNAT indica que la partida no existe")
            resultados[anio] = ResultadoAnio(subpartida, anio, ESTADO_PARTIDA_INVALIDA)
            continue

        if envio["estado"] != "OK" or not envio["numero_consulta"]:
            _avisar(anio, ESTADO_ERROR, "SUNAT no confirmo el requerimiento (numero_consulta vacio)")
            resultados[anio] = ResultadoAnio(subpartida, anio, ESTADO_ERROR, mensaje="Sin numero_consulta")
            continue

        pendientes[anio] = re.match(r"^(\d+)", envio["numero_consulta"]).group(1)
        _avisar(anio, ESTADO_ESPERANDO, "Requerimiento registrado, esperando que SUNAT genere el reporte...")
        time.sleep(pausa_entre_envios_seg)

    # --- 2. Sondeo conjunto: una sola consulta a la tabla de resultados por
    #        vuelta, revisando todos los anios pendientes contra ella ---
    transcurrido = 0
    while pendientes and transcurrido <= max_espera_seg:
        try:
            tabla = obtener_tabla_resultados(sesion)
        except requests.RequestException:
            tabla = pd.DataFrame()

        if not tabla.empty:
            tabla["numero_base"] = tabla["archivo"].str.extract(r"^(\d+)")
            for anio in list(pendientes.keys()):
                numero_base = pendientes[anio]
                fila = tabla[tabla["numero_base"] == numero_base]
                if fila.empty:
                    continue
                estado_resultado = str(fila.iloc[0]["estado"])
                interpretacion = _interpretar_estado_sunat(estado_resultado)
                if interpretacion == "listo":
                    avisar_anio = lambda estado, mensaje="", registros=0, _a=anio: _avisar(_a, estado, mensaje, registros)
                    resultados[anio] = _finalizar_descarga(
                        subpartida, anio, fila.iloc[0], sesion, carpeta_resultados, carpeta_dbf, avisar_anio
                    )
                    del pendientes[anio]
                elif interpretacion == "sin_datos":
                    _avisar(anio, ESTADO_SIN_DATOS, f"SUNAT: '{estado_resultado}' (no hay registros para este periodo)")
                    resultados[anio] = ResultadoAnio(subpartida, anio, ESTADO_SIN_DATOS, registros=0)
                    del pendientes[anio]
                else:
                    _avisar(anio, ESTADO_ESPERANDO, f"SUNAT: '{estado_resultado}' (esperando {transcurrido}s)")

        if pendientes:
            time.sleep(intervalo_poll_seg)
            transcurrido += intervalo_poll_seg

    # --- 3. Lo que nunca aparecio listo, se marca como timeout ---
    for anio in pendientes:
        _avisar(anio, ESTADO_ERROR, f"Se agoto la espera ({max_espera_seg}s) sin que el reporte quedara listo")
        resultados[anio] = ResultadoAnio(subpartida, anio, ESTADO_ERROR, mensaje="Timeout esperando reporte")

    return resultados


# ---------------------------------------------------------------------------
# Orquestacion de alto nivel: una subpartida x un anio, de punta a punta
# ---------------------------------------------------------------------------
def procesar_subpartida_anio(
    subpartida: str,
    anio: int,
    sesion: requests.Session,
    carpeta_resultados: Path,
    carpeta_dbf: Path,
    regi: str = "Impo",
    mes_fin: int = 12,
    dia_fin: Optional[int] = None,
    max_espera_seg: int = 1800,
    intervalo_poll_seg: int = 25,
    on_status: Optional[Callable[[dict], None]] = None,
) -> ResultadoAnio:
    """Flujo completo para UNA subpartida y UN anio:
    1. Envia la consulta a SUNAT.
    2. Hace polling de la tabla de resultados hasta que el reporte este
       listo (estado 'Reporte'), o hasta agotar max_espera_seg.
    3. Descarga el .ZIP, lo descomprime y lee el/los .DBF.
    4. Devuelve un ResultadoAnio con el dataframe consolidado (si hubo).

    on_status(dict) se invoca en cada cambio de estado -- pensado para que
    la UI (dashboard) pinte una tabla de progreso en vivo.
    """

    def _avisar(estado: str, mensaje: str = "", registros: int = 0):
        if on_status:
            on_status({
                "subpartida": subpartida, "anio": anio,
                "estado": estado, "mensaje": mensaje, "registros": registros,
            })

    fini, ffin = fechas_del_anio(anio, mes_fin=mes_fin, dia_fin=dia_fin)

    _avisar(ESTADO_ENVIANDO, f"Consultando {fini} - {ffin}")
    try:
        envio = enviar_consulta(subpartida, fini, ffin, sesion, regi=regi)
    except requests.RequestException as e:
        _avisar(ESTADO_ERROR, f"No se pudo enviar la consulta: {e}")
        return ResultadoAnio(subpartida, anio, ESTADO_ERROR, mensaje=str(e))

    if envio["estado"] == "PARTIDA_INVALIDA":
        _avisar(ESTADO_PARTIDA_INVALIDA, "SUNAT indica que la partida no existe")
        return ResultadoAnio(subpartida, anio, ESTADO_PARTIDA_INVALIDA)

    if envio["estado"] != "OK" or not envio["numero_consulta"]:
        _avisar(ESTADO_ERROR, "SUNAT no confirmo el requerimiento (numero_consulta vacio)")
        return ResultadoAnio(subpartida, anio, ESTADO_ERROR, mensaje="Sin numero_consulta")

    numero_base = re.match(r"^(\d+)", envio["numero_consulta"]).group(1)

    _avisar(ESTADO_ESPERANDO, "Requerimiento registrado, esperando que SUNAT genere el reporte...")
    transcurrido = 0
    fila_lista = None
    while transcurrido <= max_espera_seg:
        try:
            tabla = obtener_tabla_resultados(sesion)
        except requests.RequestException:
            tabla = pd.DataFrame()

        if not tabla.empty:
            tabla["numero_base"] = tabla["archivo"].str.extract(r"^(\d+)")
            fila = tabla[tabla["numero_base"] == numero_base]
            if not fila.empty:
                estado_resultado = str(fila.iloc[0]["estado"])
                interpretacion = _interpretar_estado_sunat(estado_resultado)
                if interpretacion == "listo":
                    fila_lista = fila.iloc[0]
                    break
                elif interpretacion == "sin_datos":
                    _avisar(ESTADO_SIN_DATOS, f"SUNAT: '{estado_resultado}' (no hay registros para este periodo)")
                    return ResultadoAnio(subpartida, anio, ESTADO_SIN_DATOS, registros=0)
                _avisar(ESTADO_ESPERANDO, f"SUNAT: '{estado_resultado}' (esperando {transcurrido}s)")

        time.sleep(intervalo_poll_seg)
        transcurrido += intervalo_poll_seg

    if fila_lista is None:
        _avisar(ESTADO_ERROR, f"Se agoto la espera ({max_espera_seg}s) sin que el reporte quedara listo")
        return ResultadoAnio(subpartida, anio, ESTADO_ERROR, mensaje="Timeout esperando reporte")

    return _finalizar_descarga(subpartida, anio, fila_lista, sesion, carpeta_resultados, carpeta_dbf, _avisar)
