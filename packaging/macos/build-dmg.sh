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

# Default to the repo's own venv. The system python3 has none of the runtime
# deps, and PyInstaller happily builds a 4 MB bundle out of it that only fails
# when someone opens it.
DEFAULT_PY="../../.venv/bin/python"
[ -x "$DEFAULT_PY" ] || DEFAULT_PY="python3"
PY="${1:-$DEFAULT_PY}"
VERSION="0.5.11"
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
# setuptools stages the package into the repo's build/ and never takes
# anything out again, so a rename leaves the old tree there to be installed
# alongside the new one. `rm -rf build` further down clears PyInstaller's
# workspace in this directory, which is a different build/ entirely.
rm -rf ../../build
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
# Delete last run's report first: a bundle that dies before writing one used
# to leave the previous release's file behind, and the grep below passed on it.
REPORT="${TMPDIR:-/tmp}/serp3d-selftest.txt"
rm -f "$REPORT"
set +e
"$APP/Contents/MacOS/serp3d" --selftest
STATUS=$?
set -e
[ -f "$REPORT" ] && cat "$REPORT"
[ "$STATUS" -eq 0 ] || { echo "ERROR: bundle exited $STATUS"; exit 1; }
grep -q "SELFTEST OK" "$REPORT" \
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
