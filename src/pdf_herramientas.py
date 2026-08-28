"""
pdf_herramientas.py

Conversores PDF <-> Markdown y OCR, usando librerias open source ya
probadas en vez de reinventar el parseo de PDFs:

- PDF -> Markdown: pymupdf4llm (extension de PyMuPDF pensada justo para
  esto -- convierte la estructura del PDF a Markdown sin bajar ningun
  modelo, muy rapida en PDFs con texto nativo).
- OCR -> PDF: ocrmypdf (el estandar de facto para esto -- le agrega una
  capa de texto OCR a un PDF escaneado/con imagenes, usando Tesseract por
  debajo, y deja un PDF con el mismo aspecto pero con texto seleccionable
  y buscable).

Ambas corren 100% local, no mandan el documento a ningun servicio externo.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

# Asegura que Tesseract encuentre los idiomas instalados aunque
# TESSDATA_PREFIX no este seteado en el proceso que corre Streamlit.
_TESSDATA_LOCAL = Path.home() / "AppData" / "Local" / "tessdata_custom"
if _TESSDATA_LOCAL.exists() and "TESSDATA_PREFIX" not in os.environ:
    os.environ["TESSDATA_PREFIX"] = str(_TESSDATA_LOCAL)


def pdf_a_markdown(ruta_pdf: Path) -> str:
    """Convierte un PDF a Markdown con pymupdf4llm. Funciona bien con PDFs
    de texto nativo (no escaneados); para PDFs escaneados, primero pasa el
    archivo por 'OCR -> PDF' y despues conviertelo a Markdown."""
    import pymupdf4llm

    return pymupdf4llm.to_markdown(str(ruta_pdf))


def idiomas_ocr_disponibles() -> list[str]:
    import subprocess

    try:
        salida = subprocess.run(
            ["tesseract", "--list-langs"], capture_output=True, text=True, timeout=10
        )
        lineas = [l.strip() for l in salida.stdout.splitlines()[1:] if l.strip()]
        return lineas or ["spa", "eng"]
    except Exception:  # noqa: BLE001
        return ["spa", "eng"]


def ocr_a_pdf(
    ruta_entrada: Path,
    ruta_salida: Path,
    idiomas: list[str] | None = None,
    forzar_ocr: bool = False,
    deskew: bool = True,
    invalidar_firma_digital: bool = False,
) -> tuple[bool, str]:
    """Agrega una capa de texto OCR a ruta_entrada (PDF escaneado, o
    imagen JPG/PNG) y la guarda en ruta_salida. Devuelve (exito, mensaje).

    forzar_ocr=True re-hace el OCR incluso en paginas que ya tienen texto
    (util si el texto existente es basura); deskew=True endereza paginas
    torcidas antes de aplicar OCR. Muchos PDFs oficiales (ej. gob.pe) traen
    firma digital -- ocrmypdf se niega a tocarlos por defecto porque OCR
    invalidaria esa firma; invalidar_firma_digital=True lo permite de
    todas formas (el PDF de salida deja de estar firmado).
    """
    import ocrmypdf

    idiomas = idiomas or ["spa", "eng"]
    try:
        resultado = ocrmypdf.ocr(
            str(ruta_entrada),
            str(ruta_salida),
            language=idiomas,
            force_ocr=forzar_ocr,
            deskew=deskew,
            invalidate_digital_signatures=invalidar_firma_digital,
            progress_bar=False,
        )
        return True, f"OK (código {resultado})"
    except ocrmypdf.exceptions.PriorOcrFoundError:
        return False, (
            "El PDF ya tiene una capa de texto OCR. Activa 'Forzar OCR' si "
            "quieres rehacerla de todas formas."
        )
    except ocrmypdf.exceptions.DigitalSignatureError:
        return False, (
            "El PDF tiene firma digital -- el OCR la invalidaría. Activa "
            "'Permitir invalidar firma digital' si igual quieres continuar."
        )
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def ruta_temporal(sufijo: str) -> Path:
    with tempfile.NamedTemporaryFile(suffix=sufijo, delete=False) as tmp:
        return Path(tmp.name)
