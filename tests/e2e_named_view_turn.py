"""F1 and F2 through real key events: does the pane arrive at the view?

Not a pytest test. The unit tests drive the command; this drives the key,
which is the part that goes through Qt's shortcut plumbing and a real GL
pane repainting on a timer.

    tests/run_e2e.sh tests/e2e_named_view_turn.py
"""

import math
import subprocess
import sys
import time

sys.path.insert(0, "tests")
from rpc_client import SerpClient                            # noqa: E402

DISPLAY = ":2"
ENV = {"DISPLAY": DISPLAY, "PATH": "/usr/bin:/bin"}
VIEWS = {"F1": ("top", math.radians(-90), math.radians(89.9)),
         "F2": ("front", math.radians(-90), 0.0)}


def run(*args):
    return subprocess.run(["xdotool", *args], env=ENV, capture_output=True,
                          text=True)


def app_window() -> str:
    """The app's top-level, by area. Xephyr has no window manager, so there
    is no focus to type into and every key has to be aimed at the window."""
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
    run("windowfocus", "--sync", win)

    def key(name):
        run("key", "--window", win, name)
        time.sleep(0.05)                 # mid-turn: nothing has arrived yet

    c = SerpClient()
    c.call("command", command="new", inputs=["Yes"])
    c.call("set_viewport", view="perspective")

    ok = True
    for k, (name, az, el) in VIEWS.items():
        key(k)
        # viewport_info lands a turn in progress, which is the whole point:
        # a script never sees a camera partway to somewhere.
        cam = c.call("viewport_info")["camera"]
        good = (abs(cam["azimuth"] - az) < 1e-9
                and abs(cam["elevation"] - el) < 1e-9)
        ok = ok and good
        print(f"[{'PASS' if good else 'FAIL'}] {k}-arrives-at-{name} "
              f"azimuth={cam['azimuth']:.4f} elevation={cam['elevation']:.4f}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
