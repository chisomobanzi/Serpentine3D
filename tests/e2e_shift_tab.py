"""Hold Shift, press Tab, let go: does the direction stay? Real keystrokes.

Not a pytest test. A hand-built QKeyEvent cannot catch this one, because
the bug was in which key the keyboard sends: Shift+Tab arrives as
Key_Backtab, a key of its own, so a synthetic Key_Tab sails through a
check that no real press ever reached.

    tests/run_e2e.sh tests/e2e_shift_tab.py
"""

import os
import subprocess
import sys
import time

sys.path.insert(0, "tests")
from rpc_client import SerpClient                            # noqa: E402

DISPLAY = ":2"
ENV = {"DISPLAY": DISPLAY, "PATH": "/usr/bin:/bin"}


def run(*args):
    return subprocess.run(["xdotool", *args], env=ENV,
                          capture_output=True, text=True)


def xdo(*args):
    run(*args)
    time.sleep(0.25)


def app_window() -> str:
    """The app's top-level, by area. Qt keeps a 1x1 one around as well.

    Xephyr has no window manager, so nothing hands the app the keyboard
    and there is no focus to type into: every key has to be aimed at the
    window itself.
    """
    best, area = "", -1
    for wid in run("search", "--name", "Serpentine3D").stdout.split():
        for tok in run("getwindowgeometry", wid).stdout.split():
            if tok.count("x") == 1 and tok.replace("x", "").isdigit():
                w, h = (int(v) for v in tok.split("x"))
                if w * h > area:
                    best, area = wid, w * h
    return best


def main() -> int:
    win = app_window()
    if not win:
        print("[FAIL] no app window on the display")
        return 1
    c = SerpClient()
    c.call("command", command="new", inputs=["Yes"])
    c.call("set_viewport", view="top")

    # Top view, so screen right is world +X and ortho will square the aim
    # onto it. Kept in fractions of the pane so the last click cannot land
    # outside it and go to whatever is behind.
    vp = c.call("viewport_info")
    ox, oy = vp["origin"]
    w, h = vp["size"]
    cx, cy = int(ox + w / 2), int(oy + h / 2)
    aim = (int(cx + 0.35 * w), int(cy - 0.15 * h))
    away = (int(cx + 0.42 * w), int(cy - 0.35 * h))

    xdo("mousemove", str(cx), str(cy))
    xdo("windowfocus", "--sync", win)
    xdo("type", "--window", win, "--delay", "30", "line")
    xdo("key", "--window", win, "Return")
    xdo("click", "1")                              # start of the line

    xdo("keydown", "--window", win, "shift")
    xdo("mousemove", str(aim[0]), str(aim[1]))     # ortho squares this off
    xdo("key", "--window", win, "Tab")             # ... and Tab freezes it
    xdo("keyup", "--window", win, "shift")

    xdo("mousemove", str(away[0]), str(away[1]))   # well off the axis now
    xdo("click", "1")
    time.sleep(0.4)

    os.makedirs("screenshots", exist_ok=True)
    c.call("screenshot", path=os.path.abspath("screenshots/shift_tab.png"))
    info = c.call("scene_info")
    if info["object_count"] != 1 or not info["bounds"]:
        print(f"[FAIL] no line drawn: {info['object_count']} objects")
        return 1
    (x0, y0, _z0), (x1, y1, _z1) = info["bounds"]
    across, along = abs(y1 - y0), abs(x1 - x0)
    held = across < 1e-6 and along > 1.0
    print(f"[{'PASS' if held else 'FAIL'}] shift-tab-holds-the-direction "
          f"along={along:.3f} across={across:.6f}")
    return 0 if held else 1


if __name__ == "__main__":
    raise SystemExit(main())
