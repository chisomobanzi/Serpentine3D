#!/usr/bin/env bash
# Full E2E run: Xephyr + clean-config app + tests/e2e_dod.py (24 checks).
# Pass another script to run that one against the same app instead.
#
# The app MUST be launched with a clean SERP3D_CONFIG — the developer's real
# config remaps mouse buttons (RMB orbit) and shortcuts (F1=Delete), which
# breaks the suite's Rhino-default input assumptions. Stuck synthetic
# modifiers from earlier xdotool runs are cleared first for the same reason.
set -euo pipefail

DISPLAY_NUM="${E2E_DISPLAY:-:2}"
WORK="$(mktemp -d /tmp/serp3d-e2e.XXXXXX)"
VENV="${VENV:-.venv}"
# A port of its own, away from the 5757 a normal launch takes. The
# developer's own copy of the app is usually open on the real display with
# real work in it, and the first thing these scripts do is run `new`.
PORT="${E2E_RPC_PORT:-5777}"
PORT_FILE="$HOME/.serpentine3d/rpc.port"
APP_PID=""
XEPHYR_PID=""
trap 'kill $APP_PID $XEPHYR_PID 2>/dev/null || true;
      [ -f "$WORK/rpc.port.bak" ] && cp "$WORK/rpc.port.bak" "$PORT_FILE";
      rm -rf "$WORK"' EXIT

# Every launch writes its port to the shared file, so put the running
# instance's back when this one is done and leave it addressable.
[ -f "$PORT_FILE" ] && cp "$PORT_FILE" "$WORK/rpc.port.bak"

# Only clear venv-launched dev instances — never the user's AppImage,
# which runs from a mounted path.
pkill -f "${VENV}/bin/python -m serpentine3d.app" 2>/dev/null || true
sleep 1

# A socket left behind by a dead Xephyr looks exactly like a live one, and
# the app then fails to open a display with nothing in the log to say why.
if ! xdpyinfo -display "$DISPLAY_NUM" >/dev/null 2>&1; then
    rm -f "/tmp/.X11-unix/X${DISPLAY_NUM#:}"
    Xephyr "$DISPLAY_NUM" -screen 1600x1000 -title "Serp3D E2E" \
        >/dev/null 2>&1 &
    XEPHYR_PID=$!
    sleep 2
fi

echo '{}' > "$WORK/config.json"
DISPLAY="$DISPLAY_NUM" LIBGL_ALWAYS_SOFTWARE=1 SERP3D_NO_RECOVER=1 SERP3D_NO_SPLASH=1 SERP3D_NO_WELCOME=1 SERP3D_NO_UPDATE_CHECK=1 \
    SERP3D_CONFIG="$WORK/config.json" SERP3D_AUTOSAVE_DIR="$WORK" \
    SERP3D_RPC_PORT="$PORT" \
    "$VENV/bin/python" -m serpentine3d.app >"$WORK/app.log" 2>&1 &
APP_PID=$!

for _ in $(seq 60); do
    ss -tln | grep -q "127.0.0.1:$PORT" && break
    sleep 0.5
done
if ! ss -tln | grep -q "127.0.0.1:$PORT"; then
    echo "app never came up on port $PORT; log follows:" >&2
    cat "$WORK/app.log" >&2
    exit 1
fi

DISPLAY="$DISPLAY_NUM" xdotool keyup Control_L Control_R Shift_L Shift_R \
    Alt_L Alt_R 2>/dev/null || true
DISPLAY="$DISPLAY_NUM" SERP3D_RPC_PORT="$PORT" \
    "$VENV/bin/python" "${1:-tests/e2e_dod.py}"
