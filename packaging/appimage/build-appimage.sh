#!/usr/bin/env bash
# Build a Serpentine3D AppImage with python-appimage.
#
#   ./packaging/appimage/build-appimage.sh
#
# Produces Serpentine3D-x86_64.AppImage in packaging/appimage/dist.
# Needs network access (PyPI wheels + a relocatable CPython runtime)
# and a few GB of scratch space. FUSE is not required to build.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
DIST="$HERE/dist"
PYVER="${SERP3D_APPIMAGE_PYTHON:-3.12}"

# recipe directory: its basename is the fallback app name; the .desktop
# Name= field (Serpentine3D) names the final AppImage.
RECIPE="$DIST/serpentine3d"
rm -rf "$RECIPE"
mkdir -p "$RECIPE"

cp "$HERE/serpentine3d.desktop" "$RECIPE/"
if [ -f "$HERE/serpentine3d.png" ]; then
    cp "$HERE/serpentine3d.png" "$RECIPE/"
else
    # placeholder icon so the recipe is self-sufficient
    python3 - "$RECIPE/serpentine3d.png" << 'PY'
import struct, sys, zlib
w = h = 64
row = b"\x00" + bytes((30, 160, 90, 255)) * w
raw = zlib.compress(row * h)
def chunk(t, d):
    c = struct.pack(">I", len(d)) + t + d
    return c + struct.pack(">I", zlib.crc32(t + d))
png = (b"\x89PNG\r\n\x1a\n"
       + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
       + chunk(b"IDAT", raw) + chunk(b"IEND", b""))
open(sys.argv[1], "wb").write(png)
PY
fi

# {{ python-executable }} is substituted by python-appimage at build time
cat > "$RECIPE/entrypoint.sh" << 'EOF'
{{ python-executable }} -m serpentine3d "$@"
EOF

# no spaces: python-appimage word-splits requirement lines when invoking pip
printf 'serpentine3d@file://%s\n' "$ROOT" > "$RECIPE/requirements.txt"

if command -v uvx > /dev/null 2>&1; then
    BUILDER=(uvx python-appimage)
else
    python3 -m pip install --user --upgrade python-appimage
    BUILDER=(python3 -m python_appimage)
fi

cd "$DIST"
"${BUILDER[@]}" build app --python-version "$PYVER" "$RECIPE"

BUILT="$(ls "$DIST"/Serpentine3D-*.AppImage 2>/dev/null | head -1)"
ls -lh "$BUILT"

# Keep the desktop-installed copy (what the dock/launcher runs) in sync
# with this build, so a rebuild is immediately live and never drifts from
# dist/. Only touches an existing install; skip with SERP3D_NO_INSTALL_REFRESH=1.
INSTALLED="$HOME/Applications/Serpentine3D.AppImage"
if [ -n "$BUILT" ] && [ -f "$INSTALLED" ] \
        && [ "${SERP3D_NO_INSTALL_REFRESH:-}" != "1" ]; then
    install -m 755 "$BUILT" "$INSTALLED"
    echo "Refreshed installed copy: $INSTALLED"
fi
