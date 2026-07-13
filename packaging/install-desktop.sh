#!/usr/bin/env bash
# Install Serpentine3D into the user's desktop (Ubuntu/GNOME, no sudo):
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
DESKTOP_FILE="$DESKTOP_DIR/serpentine3d.desktop"

refresh() {
    update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
    update-mime-database "$MIME_DIR" 2>/dev/null || true
    gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" \
        2>/dev/null || true
}

remove_legacy() {
    # pre-rebrand names ("Serpentine"): drop them so search shows one app
    rm -f "$DESKTOP_DIR/serpentine.desktop" "$ICON_DIR/serpentine.png" \
          "$MIME_DIR/packages/serpentine.xml" \
          "$APPS_DIR/Serpentine.AppImage"
}

if [ "${1:-}" = "--uninstall" ]; then
    remove_legacy
    rm -f "$DESKTOP_FILE" "$ICON_DIR/serpentine3d.png" \
          "$MIME_DIR/packages/serpentine3d.xml" \
          "$APPS_DIR/Serpentine3D.AppImage"
    refresh
    echo "Serpentine3D removed from the desktop."
    exit 0
fi

if [ "${1:-}" = "--venv" ]; then
    # run the working copy: picks up code changes without reinstalling
    EXEC_LINE="$ROOT/.venv/bin/python -m serpentine3d.app %F"
    [ -x "$ROOT/.venv/bin/python" ] || {
        echo "error: $ROOT/.venv/bin/python not found" >&2; exit 1; }
else
    APPIMAGE_SRC="$HERE/appimage/dist/Serpentine3D-x86_64.AppImage"
    [ -f "$APPIMAGE_SRC" ] || {
        echo "error: $APPIMAGE_SRC not found — run" \
             "packaging/appimage/build-appimage.sh first" >&2; exit 1; }
    mkdir -p "$APPS_DIR"
    install -m 755 "$APPIMAGE_SRC" "$APPS_DIR/Serpentine3D.AppImage"
    EXEC_LINE="$APPS_DIR/Serpentine3D.AppImage %F"
fi

remove_legacy
mkdir -p "$DESKTOP_DIR" "$ICON_DIR" "$MIME_DIR/packages"
install -m 644 "$HERE/appimage/serpentine3d.png" "$ICON_DIR/serpentine3d.png"

cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Type=Application
Name=Serpentine3D
GenericName=NURBS Modeller
Comment=NURBS surface modeller for set design, architecture and product design
Exec=$EXEC_LINE
Icon=serpentine3d
Terminal=false
Categories=Graphics;3DGraphics;Engineering;
MimeType=application/x-serpentine3d;
Keywords=CAD;NURBS;3D;modelling;rhino;surface;drafting;
StartupWMClass=serpentine3d
EOF

cat > "$MIME_DIR/packages/serpentine3d.xml" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">
  <mime-type type="application/x-serpentine3d">
    <comment>Serpentine3D 3D model</comment>
    <glob pattern="*.serp"/>
    <icon name="serpentine3d"/>
  </mime-type>
</mime-info>
EOF

refresh
command -v desktop-file-validate > /dev/null \
    && desktop-file-validate "$DESKTOP_FILE"

echo "Installed. Search for 'Serpentine3D' in Activities;"
echo ".serp files now open with it from the file manager."
