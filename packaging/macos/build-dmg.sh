#!/usr/bin/env bash
# Build the macOS .app bundle and a drag-to-Applications .dmg.
# Run from this directory in a venv that has serpentine3d installed:
#   ./build-dmg.sh [path/to/venv/bin/python]
#
# Produces:  Serpentine3D-<version>-arm64.dmg
#
# The .app is UNSIGNED. Gatekeeper on the user's Mac will quarantine it;
# see the README for the right-click-Open / notarization follow-up.
set -euo pipefail
cd "$(dirname "$0")"

PY="${1:-python3}"
VERSION="0.4.0"
APPNAME="Serpentine3D"
ARCH="$(uname -m)"
DMG="${APPNAME}-${VERSION}-${ARCH}.dmg"

echo "=== ensure pip (uv-created venvs ship without it) ==="
if ! "$PY" -m pip --version >/dev/null 2>&1; then
    "$PY" -m ensurepip --upgrade >/dev/null 2>&1 \
        || { command -v uv >/dev/null && uv pip install --python "$PY" pip; } \
        || { echo "ERROR: no pip and cannot bootstrap one"; exit 1; }
fi

echo "=== ensure build tools + real (non-editable) install ==="
"$PY" -m pip install --quiet pyinstaller
# PyInstaller cannot trace PEP 660 editable installs — install real files.
"$PY" -m pip install --quiet --force-reinstall --no-deps ../..

echo "=== generate serp3d.icns from serp3d_icon.png ==="
ICONSET="serp3d.iconset"
rm -rf "$ICONSET" serp3d.icns
mkdir -p "$ICONSET"
for sz in 16 32 128 256 512; do
    sips -z "$sz" "$sz"       serp3d_icon.png --out "$ICONSET/icon_${sz}x${sz}.png"       >/dev/null
    sips -z $((sz*2)) $((sz*2)) serp3d_icon.png --out "$ICONSET/icon_${sz}x${sz}@2x.png"  >/dev/null
done
iconutil -c icns "$ICONSET" -o serp3d.icns
rm -rf "$ICONSET"

echo "=== PyInstaller build ==="
# a failed run leaves a poisoned Analysis-00.toc that later runs reuse
rm -rf build dist
"$PY" -m PyInstaller --clean -y serp3d.spec

APP="dist/${APPNAME}.app"
[ -d "$APP" ] || { echo "ERROR: $APP was not produced"; exit 1; }

echo "=== bundle selftest (headless: Qt + OCCT + file I/O) ==="
set +e
"$APP/Contents/MacOS/serp3d" --selftest
set -e
cat "${TMPDIR:-/tmp}/serp3d-selftest.txt"
grep -q "SELFTEST OK" "${TMPDIR:-/tmp}/serp3d-selftest.txt" \
    || { echo "ERROR: bundle selftest failed"; exit 1; }

echo "=== assemble .dmg (drag onto Applications) ==="
STAGING="$(mktemp -d)"
cp -R "$APP" "$STAGING/"
ln -s /Applications "$STAGING/Applications"
rm -f "$DMG"
hdiutil create -volname "$APPNAME" -srcfolder "$STAGING" \
    -fs HFS+ -format UDZO -ov "$DMG" >/dev/null
rm -rf "$STAGING"

SIZE=$(du -h "$DMG" | cut -f1)
echo "DMG OK: $(pwd)/$DMG ($SIZE)"
