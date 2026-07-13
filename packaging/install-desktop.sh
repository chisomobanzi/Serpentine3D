#!/usr/bin/env bash
# Install Serpentine into the user's desktop (Ubuntu/GNOME, no sudo):
# app in ~/Applications, launcher entry + icon in ~/.local/share, and a
# MIME type so .serp files open with it from the file manager.
#
#   ./packaging/install-desktop.sh            # install the AppImage
#   ./packaging/install-desktop.sh --venv     # launch the dev checkout instead
#   ./packaging/install-desktop.sh --uninstall
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"

APPS_DIR="$HOME/Applications"
DESKTOP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"
MIME_DIR="$HOME/.local/share/mime"
DESKTOP_FILE="$DESKTOP_DIR/serpentine.desktop"

refresh() {
    update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
    update-mime-database "$MIME_DIR" 2>/dev/null || true
    gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" \
        2>/dev/null || true
}

if [ "${1:-}" = "--uninstall" ]; then
    rm -f "$DESKTOP_FILE" "$ICON_DIR/serpentine.png" \
          "$MIME_DIR/packages/serpentine.xml" \
          "$APPS_DIR/Serpentine.AppImage"
    refresh
    echo "Serpentine removed from the desktop."
    exit 0
fi

if [ "${1:-}" = "--venv" ]; then
    # run the working copy: picks up code changes without reinstalling
    EXEC_LINE="$ROOT/.venv/bin/python -m serpentine.app %F"
    [ -x "$ROOT/.venv/bin/python" ] || {
        echo "error: $ROOT/.venv/bin/python not found" >&2; exit 1; }
else
    APPIMAGE_SRC="$HERE/appimage/dist/Serpentine-x86_64.AppImage"
    [ -f "$APPIMAGE_SRC" ] || {
        echo "error: $APPIMAGE_SRC not found — run" \
             "packaging/appimage/build-appimage.sh first" >&2; exit 1; }
    mkdir -p "$APPS_DIR"
    install -m 755 "$APPIMAGE_SRC" "$APPS_DIR/Serpentine.AppImage"
    EXEC_LINE="$APPS_DIR/Serpentine.AppImage %F"
fi

mkdir -p "$DESKTOP_DIR" "$ICON_DIR" "$MIME_DIR/packages"
install -m 644 "$HERE/appimage/serpentine.png" "$ICON_DIR/serpentine.png"

cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Type=Application
Name=Serpentine
GenericName=NURBS Modeller
Comment=NURBS surface modeller for set design, architecture and product design
Exec=$EXEC_LINE
Icon=serpentine
Terminal=false
Categories=Graphics;3DGraphics;Engineering;
MimeType=application/x-serpentine;
Keywords=CAD;NURBS;3D;modelling;rhino;surface;drafting;
StartupWMClass=serpentine
EOF

cat > "$MIME_DIR/packages/serpentine.xml" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">
  <mime-type type="application/x-serpentine">
    <comment>Serpentine 3D model</comment>
    <glob pattern="*.serp"/>
    <icon name="serpentine"/>
  </mime-type>
</mime-info>
EOF

refresh
command -v desktop-file-validate > /dev/null \
    && desktop-file-validate "$DESKTOP_FILE"

echo "Installed. Search for 'Serpentine' in Activities;"
echo ".serp files now open with it from the file manager."
