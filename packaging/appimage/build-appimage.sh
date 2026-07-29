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

# {{ python-executable }} is substituted by python-appimage at build time.
# -P: without it `-m` puts the launch directory first on sys.path, so starting
# the AppImage from anywhere containing a serpentine3d/ folder — a checkout,
# say — runs that code instead of the bundled package, silently.
cat > "$RECIPE/entrypoint.sh" << 'EOF'
{{ python-executable }} -P -m serpentine3d "$@"
EOF

# no spaces: python-appimage word-splits requirement lines when invoking pip
printf 'serpentine3d@file://%s\n' "$ROOT" > "$RECIPE/requirements.txt"

if command -v uvx > /dev/null 2>&1; then
    BUILDER=(uvx python-appimage)
else
    python3 -m pip install --user --upgrade python-appimage
    BUILDER=(python3 -m python_appimage)
fi

# pip keys its wheel cache on name+version, and our version only moves at
# release time — so without this a rebuild between releases quietly reuses the
# wheel from the last one and bundles yesterday's code while the source tree
# looks correct. Only ours: the third-party wheels are worth caching.
CACHE="${PIP_CACHE_DIR:-$HOME/.cache/pip}/wheels"
if [ -d "$CACHE" ]; then
    find "$CACHE" -name 'serpentine3d-*.whl' -delete
fi

# setuptools copies the packages it is told to build into build/lib and never
# takes anything out again, but the wheel is zipped from whatever it finds
# there. We renamed serpentine -> serpentine3d and the old tree stayed put, so
# every wheel after the rename also shipped 73 files of dead code under the old
# top-level name. Staging is pure copying for a pure-Python package; rebuilding
# it from scratch costs a second and removes the whole class of problem.
rm -rf "$ROOT/build"

cd "$DIST"
"${BUILDER[@]}" build app --python-version "$PYVER" "$RECIPE"

BUILT="$(ls "$DIST"/Serpentine3D-*.AppImage 2>/dev/null | head -1)"
ls -lh "$BUILT"

# The staging purge above stops the cause we know about; this catches the next
# one. Any top-level serpentine* package besides serpentine3d is a name we did
# not mean to put on the user's import path. Extracting one file per candidate
# package is enough to list them, and costs milliseconds.
if [ -n "$BUILT" ]; then
    PROBE="$(mktemp -d)"
    trap 'rm -rf "$PROBE"' EXIT
    ( cd "$PROBE" && "$BUILT" --appimage-extract \
        'opt/python*/lib/python*/site-packages/serpentine*/__init__.py' \
        > /dev/null 2>&1 ) || true
    STOWAWAYS="$(find "$PROBE/squashfs-root" -mindepth 1 -type d \
        -name 'serpentine*' -printf '%f\n' 2>/dev/null \
        | sort -u | grep -vx 'serpentine3d' || true)"
    if [ -n "$STOWAWAYS" ]; then
        echo "ERROR: the bundle ships top-level packages we did not intend:" >&2
        echo "$STOWAWAYS" | sed 's/^/  /' >&2
        echo "Stale setuptools staging, or a rename that left a tree behind." >&2
        exit 1
    fi
fi

# Keep the desktop-installed copy (what the dock/launcher runs) in sync
# with this build, so a rebuild is immediately live and never drifts from
# dist/. Only touches an existing install; skip with SERP3D_NO_INSTALL_REFRESH=1.
INSTALLED="$HOME/Applications/Serpentine3D.AppImage"
if [ -n "$BUILT" ] && [ -f "$INSTALLED" ] \
        && [ "${SERP3D_NO_INSTALL_REFRESH:-}" != "1" ]; then
    install -m 755 "$BUILT" "$INSTALLED"
    echo "Refreshed installed copy: $INSTALLED"
fi
