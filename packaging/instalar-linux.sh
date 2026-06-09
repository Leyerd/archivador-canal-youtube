#!/usr/bin/env bash
# Integra el Archivador en el menú de aplicaciones de Linux (lanzador + icono).
# Uso:   ./packaging/instalar-linux.sh            (instala)
#        ./packaging/instalar-linux.sh --uninstall (desinstala)
set -e

DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_ID="archivador-canal"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
DESKTOP_DIR="$DATA/applications"
ICON_DIR="$DATA/icons/hicolor"

if [ "$1" = "--uninstall" ]; then
  rm -f "$DESKTOP_DIR/$APP_ID.desktop"
  rm -f "$ICON_DIR/scalable/apps/$APP_ID.svg"
  for s in 16 32 48 64 128 256 512; do rm -f "$ICON_DIR/${s}x${s}/apps/$APP_ID.png"; done
  update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
  echo "✓ Archivador desinstalado del menú."
  exit 0
fi

chmod +x "$DIR/run.sh"

# Iconos
for s in 16 32 48 64 128 256 512; do
  install -Dm644 "$DIR/assets/icon-$s.png" "$ICON_DIR/${s}x${s}/apps/$APP_ID.png"
done
install -Dm644 "$DIR/assets/icon.svg" "$ICON_DIR/scalable/apps/$APP_ID.svg"

# Lanzador
mkdir -p "$DESKTOP_DIR"
cat > "$DESKTOP_DIR/$APP_ID.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Archivador de canal
GenericName=Descargador de YouTube
Comment=Descarga y organiza los videos de tu canal de YouTube
Exec="$DIR/run.sh"
Path=$DIR
Icon=$APP_ID
Terminal=false
Categories=AudioVideo;
Keywords=youtube;descargar;video;canal;archivar;yt-dlp;
StartupNotify=true
EOF
chmod +x "$DESKTOP_DIR/$APP_ID.desktop"

update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
gtk-update-icon-cache -t "$ICON_DIR" 2>/dev/null || true

echo "✓ Instalado. Busca «Archivador de canal» en tu lanzador de aplicaciones."
echo "  (Hyprland/wofi/rofi lo verán tras refrescar la base de datos de .desktop)."
