#!/usr/bin/env bash
# Full E2E run: Xephyr + clean-config app + tests/e2e_dod.py (24 checks).
#
# The app MUST be launched with a clean SERP3D_CONFIG — the developer's real
# config remaps mouse buttons (RMB orbit) and shortcuts (F1=Delete), which
# breaks the suite's Rhino-default input assumptions. Stuck synthetic
# modifiers from earlier xdotool runs are cleared first for the same reason.
set -euo pipefail

DISPLAY_NUM="${E2E_DISPLAY:-:2}"
WORK="$(mktemp -d /tmp/serp3d-e2e.XXXXXX)"
VENV="${VENV:-.venv}"
APP_PID=""
XEPHYR_PID=""
trap 'kill $APP_PID $XEPHYR_PID 2>/dev/null || true; rm -rf "$WORK"' EXIT

# Any other running dev instance clobbers ~/.serpentine3d/rpc.port
# (last-writer-wins), so the test client would drive the wrong window.
# Only clear venv-launched dev instances — never the user's AppImage,
# which runs from a mounted path.
pkill -f "${VENV}/bin/python -m serpentine3d.app" 2>/dev/null || true
sleep 1

if ! [ -e "/tmp/.X11-unix/X${DISPLAY_NUM#:}" ]; then
    Xephyr "$DISPLAY_NUM" -screen 1600x1000 -title "Serp3D E2E" \
        >/dev/null 2>&1 &
    XEPHYR_PID=$!
    sleep 2
fi

echo '{}' > "$WORK/config.json"
DISPLAY="$DISPLAY_NUM" LIBGL_ALWAYS_SOFTWARE=1 SERP3D_NO_RECOVER=1 SERP3D_NO_SPLASH=1 SERP3D_NO_WELCOME=1 \
    SERP3D_CONFIG="$WORK/config.json" SERP3D_AUTOSAVE_DIR="$WORK" \
    "$VENV/bin/python" -m serpentine3d.app >"$WORK/app.log" 2>&1 &
APP_PID=$!

for _ in $(seq 30); do
    ss -tln | grep -q 127.0.0.1:5757 && break
    sleep 0.5
done

DISPLAY="$DISPLAY_NUM" xdotool keyup Control_L Control_R Shift_L Shift_R \
    Alt_L Alt_R 2>/dev/null || true
DISPLAY="$DISPLAY_NUM" "$VENV/bin/python" tests/e2e_dod.py
