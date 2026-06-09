#!/usr/bin/env bash
# Genera "Archivador de canal.app" en /Applications (o donde indiques) en macOS.
# Uso:  ./packaging/crear-app-macos.sh  [carpeta_destino]
set -e

DIR="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${1:-/Applications}"
APP="$DEST/Archivador de canal.app"

mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$DIR/assets/icon.icns" "$APP/Contents/Resources/icon.icns"

cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Archivador de canal</string>
  <key>CFBundleDisplayName</key><string>Archivador de canal</string>
  <key>CFBundleIdentifier</key><string>com.leyerd.archivador-canal</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>launcher</string>
  <key>CFBundleIconFile</key><string>icon</string>
  <key>LSMinimumSystemVersion</key><string>10.13</string>
</dict>
</plist>
EOF

cat > "$APP/Contents/MacOS/launcher" <<EOF
#!/usr/bin/env bash
cd "$DIR"
exec "$DIR/run.sh"
EOF
chmod +x "$APP/Contents/MacOS/launcher"

echo "✓ Creada: $APP"
echo "  Ábrela desde Launchpad o Aplicaciones. (La primera vez instala dependencias)."
