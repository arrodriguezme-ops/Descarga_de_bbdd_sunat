<#
.SYNOPSIS
    Instala y configura Tesseract OCR (+ idioma español) para el servicio
    "Herramientas de PDF" > "OCR -> PDF" del panel.

.DESCRIPTION
    Automatiza los pasos manuales documentados en el README:
      1. Instala Tesseract OCR con winget (si no esta instalado).
      2. Crea una carpeta de datos de idioma escribible por el usuario
         (no requiere permisos de administrador).
      3. Copia eng.traineddata / osd.traineddata desde la instalacion
         original, y las subcarpetas configs/ y tessconfigs/ (sin esto
         ultimo, ocrmypdf falla con un error de configuracion).
      4. Descarga spa.traineddata (espanol) si no esta ya presente.
      5. Setea TESSDATA_PREFIX (alcance Usuario) y agrega Tesseract-OCR
         al PATH de Usuario si hiciera falta.

    Lo unico que este script NO puede hacer por vos: las variables de
    entorno nuevas solo las ve una terminal ABIERTA DESPUES de correrlo
    -- cerra y volve a abrir la tuya (o VS Code / la terminal donde vayas
    a correr `streamlit run app.py`) al terminar.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\instalar_tesseract_ocr.ps1
#>

$ErrorActionPreference = "Stop"

function Test-TesseractEnPath {
    return $null -ne (Get-Command tesseract -ErrorAction SilentlyContinue)
}

Write-Host "1) Verificando si Tesseract OCR ya esta instalado..." -ForegroundColor Cyan
if (Test-TesseractEnPath) {
    Write-Host "   Ya esta instalado y en el PATH." -ForegroundColor Green
} else {
    Write-Host "   No encontrado -- instalando con winget (puede tardar un par de minutos)..."
    winget install --id UB-Mannheim.TesseractOCR -e --accept-package-agreements --accept-source-agreements --disable-interactivity
    # refrescar el PATH de ESTA sesion de PowerShell -- winget ya lo dejo
    # en el registro, pero la sesion actual no lo relee sola
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path", "User")
}

Write-Host "2) Ubicando la carpeta de instalacion..." -ForegroundColor Cyan
$rutaPrograma = "C:\Program Files\Tesseract-OCR"
if (-not (Test-Path $rutaPrograma)) {
    $candidato = Get-ChildItem "C:\Program Files*" -Directory -Filter "Tesseract-OCR" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($candidato) { $rutaPrograma = $candidato.FullName }
}
if (-not (Test-Path $rutaPrograma)) {
    Write-Error "No se encontro la carpeta de instalacion de Tesseract-OCR. Si winget lo instalo en otra ruta, edita `$rutaPrograma` en este script y volve a correrlo."
    exit 1
}
Write-Host "   $rutaPrograma"

Write-Host "3) Preparando carpeta de datos de idioma (sin necesitar admin)..." -ForegroundColor Cyan
$carpetaCustom = Join-Path $env:LOCALAPPDATA "tessdata_custom"
New-Item -ItemType Directory -Force -Path $carpetaCustom | Out-Null

foreach ($archivo in @("eng.traineddata", "osd.traineddata")) {
    $origen = Join-Path $rutaPrograma "tessdata\$archivo"
    if (Test-Path $origen) {
        Copy-Item $origen -Destination $carpetaCustom -Force
        Write-Host "   copiado: $archivo"
    }
}
foreach ($carpeta in @("configs", "tessconfigs")) {
    $origen = Join-Path $rutaPrograma "tessdata\$carpeta"
    if (Test-Path $origen) {
        Copy-Item $origen -Destination $carpetaCustom -Recurse -Force
        Write-Host "   copiada: $carpeta\ (necesaria para que ocrmypdf no falle)"
    }
}

Write-Host "4) Descargando spa.traineddata (espanol, ~18 MB)..." -ForegroundColor Cyan
$destinoSpa = Join-Path $carpetaCustom "spa.traineddata"
if (Test-Path $destinoSpa) {
    Write-Host "   Ya existe -- se salta la descarga."
} else {
    Invoke-WebRequest -Uri "https://github.com/tesseract-ocr/tessdata/raw/main/spa.traineddata" -OutFile $destinoSpa
    Write-Host "   Descargado a $destinoSpa"
}

Write-Host "5) Configurando variables de entorno (alcance: Usuario)..." -ForegroundColor Cyan
[System.Environment]::SetEnvironmentVariable("TESSDATA_PREFIX", $carpetaCustom, "User")
Write-Host "   TESSDATA_PREFIX = $carpetaCustom"

$pathUsuario = [System.Environment]::GetEnvironmentVariable("Path", "User")
if ($pathUsuario -notlike "*Tesseract-OCR*") {
    [System.Environment]::SetEnvironmentVariable("Path", "$pathUsuario;$rutaPrograma", "User")
    Write-Host "   Agregado $rutaPrograma al PATH de Usuario."
} else {
    Write-Host "   $rutaPrograma ya estaba en el PATH de Usuario."
}

Write-Host ""
Write-Host "Listo. Cerra y volve a abrir la terminal (esto es obligatorio -- las" -ForegroundColor Yellow
Write-Host "variables de entorno nuevas solo las ve una terminal abierta DESPUES" -ForegroundColor Yellow
Write-Host "de este paso) y ya podes usar la pestana 'OCR -> PDF' en espanol." -ForegroundColor Yellow
