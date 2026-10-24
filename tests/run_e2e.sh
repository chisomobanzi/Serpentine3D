#!/usr/bin/env bash
# Full E2E run: Xephyr + clean-config app + tests/e2e_dod.py (24 checks).
# Pass another script to run that one against the same app instead.
#
# The app MUST be launched with a clean SERP3D_CONFIG, so these scripts can
# assume the shipped defaults — the right button orbits, Shift pans, Ctrl
# zooms (Rhino's chords, since 0.7.2) — rather than whatever the developer
# has remapped for themselves (a middle-button orbit, F1=Delete). Stuck
# synthetic modifiers from earlier xdotool runs are cleared first, for the
# same reason: a held Ctrl would turn every later orbit into a zoom.
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
# Says this run is still going, to the port check of any run after it.
echo $$ > "$WORK/runner.pid"

# Every process listening on a port: an app and any worker it forked.
port_pids() {
    ss -ltnpH "sport = :$1" 2>/dev/null | grep -o 'pid=[0-9]*' \
        | cut -d= -f2 | sort -u || true
}

# The client asks for $PORT by number, so no other copy of the app can take
# its calls, except one already on $PORT: the new app would move up a port
# and the script would drive the old one. An e2e app whose run is over (its
# work folder gone, or the runner that started it dead) is a leftover, and
# is stopped. Anything else (a dev window, the AppImage, another session's
# run going now) is left alone, and this run stops instead.
for pid in $(port_pids "$PORT"); do
    cfg="$(tr '\0' '\n' 2>/dev/null <"/proc/$pid/environ" \
           | sed -n 's/^SERP3D_CONFIG=//p' || true)"
    case "$cfg" in /tmp/serp3d-e2e.*/config.json) ;; *) continue ;; esac
    run="${cfg%/config.json}"
    if [ -d "$run" ]; then
        owner="$(cat "$run/runner.pid" 2>/dev/null || true)"
        { [ -n "$owner" ] && ! kill -0 "$owner" 2>/dev/null; } || continue
    fi
    kill "$pid" 2>/dev/null || true
done
for _ in $(seq 10); do
    [ -z "$(port_pids "$PORT")" ] && break
    sleep 0.5
done
if [ -n "$(port_pids "$PORT")" ]; then
    echo "port $PORT is taken by pid $(port_pids "$PORT" | xargs); stop it," \
         "or give this run another port with E2E_RPC_PORT" >&2
    exit 1
fi

# A socket left behind by a dead Xephyr looks exactly like a live one, and
# the app then fails to open a display with nothing in the log to say why.
if ! xdpyinfo -display "$DISPLAY_NUM" >/dev/null 2>&1; then
    rm -f "/tmp/.X11-unix/X${DISPLAY_NUM#:}"
    Xephyr "$DISPLAY_NUM" -screen 1600x1000 -title "Serp3D E2E" \
        >/dev/null 2>&1 &
    XEPHYR_PID=$!
    sleep 2
fi

# Clean but for one answer: on any machine where the app isn't yet the
# default for .serp files it asks to be, and that modal takes every click,
# so each mouse check would fail.
echo '{"file_assoc": {"asked": true}}' > "$WORK/config.json"
DISPLAY="$DISPLAY_NUM" LIBGL_ALWAYS_SOFTWARE=1 SERP3D_NO_RECOVER=1 SERP3D_NO_SPLASH=1 SERP3D_NO_WELCOME=1 SERP3D_NO_UPDATE_CHECK=1 \
    SERP3D_CONFIG="$WORK/config.json" SERP3D_AUTOSAVE_DIR="$WORK" \
    SERP3D_JOURNAL_DIR="$WORK/journals" SERP3D_RPC_PORT="$PORT" \
    "$VENV/bin/python" -m serpentine3d.app >"$WORK/app.log" 2>&1 &
APP_PID=$!

# Up once the app this run started holds $PORT. Not `ss -tln | grep -q`:
# under pipefail that failed about once in 170 tries, when grep quit at
# the match and ss died of SIGPIPE, and the run killed a working app.
app_up() { port_pids "$PORT" | grep -qx "$APP_PID"; }
for _ in $(seq 60); do
    app_up && break
    sleep 0.5
done
if ! app_up; then
    echo "app never came up on port $PORT; log follows:" >&2
    cat "$WORK/app.log" >&2
    exit 1
fi

DISPLAY="$DISPLAY_NUM" xdotool keyup Control_L Control_R Shift_L Shift_R \
    Alt_L Alt_R 2>/dev/null || true
DISPLAY="$DISPLAY_NUM" SERP3D_RPC_PORT="$PORT" \
    "$VENV/bin/python" "${1:-tests/e2e_dod.py}"
