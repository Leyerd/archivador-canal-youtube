#!/usr/bin/env bash
# Lanzador para Linux y macOS.
# Crea un entorno virtual, instala yt-dlp y abre el Archivador en el navegador.
set -e
cd "$(dirname "$0")"

PY=python3
command -v python3 >/dev/null 2>&1 || PY=python

if ! command -v "$PY" >/dev/null 2>&1; then
  echo "✗ No se encontró Python 3. Instálalo desde https://www.python.org/"
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "▶ Creando entorno virtual…"
  "$PY" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate
echo "▶ Instalando/actualizando dependencias…"
pip install --quiet --upgrade pip
pip install --quiet --upgrade -r requirements.txt

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "⚠ ffmpeg no está instalado: se recomienda para fusionar video+audio y subtítulos."
  echo "  Linux (Arch): sudo pacman -S ffmpeg  ·  Debian/Ubuntu: sudo apt install ffmpeg  ·  macOS: brew install ffmpeg"
fi

exec python app.py "$@"
