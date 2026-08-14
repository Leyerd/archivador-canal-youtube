@echo off
REM Lanzador para Windows.
REM Crea un entorno virtual, instala yt-dlp y abre el Archivador en el navegador.
setlocal
cd /d "%~dp0"

REM Consola en UTF-8: sin esto los acentos y simbolos rompen la salida.
chcp 65001 >nul 2>nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

where python >nul 2>nul
if errorlevel 1 (
  echo X No se encontro Python. Instalalo desde https://www.python.org/ y marca "Add to PATH".
  pause
  exit /b 1
)

if not exist ".venv" (
  echo Creando entorno virtual...
  python -m venv .venv
)

call .venv\Scripts\activate.bat
echo Instalando/actualizando dependencias...
python -m pip install --quiet --upgrade pip
python -m pip install --quiet --upgrade -r requirements.txt

where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo [aviso] ffmpeg no esta en el PATH: se recomienda para fusionar video+audio.
  echo         Instala con: winget install Gyan.FFmpeg
)

python app.py %*
endlocal
