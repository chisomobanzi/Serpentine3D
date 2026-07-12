#!/usr/bin/env bash
# Build a Serpentine AppImage with python-appimage.
#
#   ./packaging/appimage/build-appimage.sh
#
# Produces Serpentine-<version>-x86_64.AppImage in packaging/appimage/dist.
# Needs network access (downloads a relocatable CPython runtime) and
# ~2 GB of scratch space; run from the repository root.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
DIST="$HERE/dist"
VERSION="$(python3 -c 'import tomllib;print(tomllib.load(open("'"$ROOT"'/pyproject.toml","rb"))["project"]["version"])')"

mkdir -p "$DIST"
cd "$DIST"

python3 -m pip install --upgrade python-appimage

# recipe directory consumed by python-appimage
RECIPE="$DIST/recipe"
rm -rf "$RECIPE" && mkdir -p "$RECIPE"
cp "$HERE/serpentine.desktop" "$RECIPE/"
cp "$HERE/serpentine.png" "$RECIPE/" 2>/dev/null || {
    # fall back to a generated placeholder icon
    python3 - "$RECIPE/serpentine.png" << 'PY'
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
}
printf '%s\n' "serpentine @ file://$ROOT" > "$RECIPE/requirements.txt"
printf '%s\n' "-m serpentine.app" > "$RECIPE/entrypoint.sh"

python3 -m python_appimage build app \
    --python-version 3.12 \
    --name "Serpentine-$VERSION" \
    "$RECIPE"

echo "AppImage written to $DIST"
