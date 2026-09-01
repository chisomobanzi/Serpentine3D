"""Hold Ctrl, drag the orbit button: does the view zoom? Real mouse events.

Not a pytest test. tests/test_ctrl_and_the_orbit_button_zoom_like_rhino.py
already drives the viewport with hand-built QMouseEvents, and a hand-built
event carries whatever modifier you put in it — which is exactly what this
gesture can lose. A modifier has to survive the trip through the X server
and Qt's own handling before `mouseMoveEvent` ever sees it, and on the
Windows box these chords were written on, synthetic Ctrl never arrived at
the app at all while Shift did. So the one thing worth checking here is
whether Ctrl is really on the drag when it lands.

Rhino's three chords on the orbit button are drag, Shift and Ctrl for
orbit, pan and zoom, plus Ctrl+Shift to orbit out of a parallel view, where
a plain drag pans. All five are checked, because the value of the set is
that each one does its own thing and no other.

    tests/run_e2e.sh tests/e2e_ctrl_zoom.py

Xephyr has no window manager, so a pass here means Qt delivers the chord.
A desktop that grabs Ctrl-drag for itself is a separate matter.
"""

import subprocess
import sys
import time

sys.path.insert(0, "tests")
from rpc_client import SerpClient                            # noqa: E402

DISPLAY = ":2"
ENV = {"DISPLAY": DISPLAY, "PATH": "/usr/bin:/bin"}

# Button 3: the right button orbits on a clean config since 0.7.2, and the
# chords ride on whichever button orbits.
NAV = "3"

# A drag has to beat the four-pixel band that tells a click from a drag,
# or a right-button release is Enter instead of the end of a gesture.
TRAVEL = 180


def xdo(*args, pause=0.15):
    subprocess.run(["xdotool", *args], env=ENV, capture_output=True,
                   text=True)
    time.sleep(pause)


def nav_drag(cx, cy, dx, dy, mods=()):
    """A press, several moves and a release, as a hand would make them.

    Several moves rather than one: the camera reads each move against the
    last, so a single jump would be one huge step and would not exercise
    the accumulation a real drag does.
    """
    xdo("mousemove", str(cx), str(cy))
    for m in mods:
        xdo("keydown", m)
    xdo("mousedown", NAV)
    for step in (0.25, 0.5, 0.75, 1.0):
        xdo("mousemove", str(int(cx + dx * step)), str(int(cy + dy * step)),
            pause=0.08)
    xdo("mouseup", NAV)
    for m in reversed(mods):
        xdo("keyup", m)
    time.sleep(0.3)


def cam(c):
    return c.call("viewport_info")["camera"]


def centre(c):
    vp = c.call("viewport_info")
    ox, oy = vp["origin"]
    w, h = vp["size"]
    return int(ox + w / 2), int(oy + h / 2)


def turned(a, b) -> bool:
    """Whether the camera swung round between two poses."""
    return (abs(a["azimuth"] - b["azimuth"]) > 1e-6
            or abs(a["elevation"] - b["elevation"]) > 1e-6)


def moved(a, b) -> float:
    """How far the camera's target slid between two poses."""
    return sum((x - y) ** 2 for x, y in zip(a["target"], b["target"])) ** 0.5


def main() -> int:
    c = SerpClient()
    c.call("command", command="new", inputs=["Yes"])
    # Something to look at, so the pane is framed on a real extent rather
    # than on the empty default distance.
    c.call("command", command="box", inputs=["0,0,0", "40,30,0", "20"])
    c.call("set_viewport", view="perspective")
    c.call("set_viewport", zoom_extents=True)
    cx, cy = centre(c)
    ok = True

    def check(name, passed, detail=""):
        nonlocal ok
        ok &= bool(passed)
        print(f"[{'PASS' if passed else 'FAIL'}] {name} {detail}")

    # --- Ctrl: zoom, and only zoom ----------------------------------------
    # Dragging up brings the camera closer, the way pushing the model away
    # from you would not: it is the view that moves, and up is in.
    before = cam(c)
    nav_drag(cx, cy, 0, -TRAVEL, mods=("ctrl",))
    after = cam(c)
    check("ctrl-drag-up-zooms-in",
          after["distance"] < before["distance"] * 0.99,
          f"{before['distance']:.2f} -> {after['distance']:.2f}")
    check("ctrl-zoom-does-not-turn-the-view", not turned(before, after),
          f"dAz={after['azimuth'] - before['azimuth']:.6f}")
    check("ctrl-zoom-does-not-pan", moved(before, after) < 1e-6,
          f"target moved {moved(before, after):.4f}")

    before = cam(c)
    nav_drag(cx, cy, 0, TRAVEL, mods=("ctrl",))
    after = cam(c)
    check("ctrl-drag-down-zooms-out",
          after["distance"] > before["distance"] * 1.01,
          f"{before['distance']:.2f} -> {after['distance']:.2f}")

    # --- the other chords still do their own thing ------------------------
    before = cam(c)
    nav_drag(cx, cy, TRAVEL, 60)
    after = cam(c)
    check("plain-drag-still-orbits", turned(before, after),
          f"dAz={after['azimuth'] - before['azimuth']:.4f}")
    check("orbit-holds-the-distance",
          abs(after["distance"] - before["distance"]) < 1e-6,
          f"{before['distance']:.2f} -> {after['distance']:.2f}")

    before = cam(c)
    nav_drag(cx, cy, TRAVEL, 0, mods=("shift",))
    after = cam(c)
    check("shift-drag-still-pans", moved(before, after) > 0.1,
          f"target moved {moved(before, after):.2f}")
    check("pan-holds-the-distance",
          abs(after["distance"] - before["distance"]) < 1e-6,
          f"{before['distance']:.2f} -> {after['distance']:.2f}")

    # --- parallel view: Ctrl+Shift is the way out -------------------------
    # Top is parallel, where a plain drag pans like a drawing. Ctrl+Shift is
    # then the only chord that swings the camera off the axis.
    c.call("set_viewport", view="top")
    c.call("set_viewport", zoom_extents=True)
    cx, cy = centre(c)

    before = cam(c)
    nav_drag(cx, cy, TRAVEL, 0)
    after = cam(c)
    check("plain-drag-pans-a-parallel-view",
          not turned(before, after) and moved(before, after) > 0.1,
          f"target moved {moved(before, after):.2f}")

    before = cam(c)
    nav_drag(cx, cy, TRAVEL, 60, mods=("ctrl", "shift"))
    after = cam(c)
    check("ctrl-shift-orbits-out-of-a-parallel-view", turned(before, after),
          f"dAz={after['azimuth'] - before['azimuth']:.4f} "
          f"dEl={after['elevation'] - before['elevation']:.4f}")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
