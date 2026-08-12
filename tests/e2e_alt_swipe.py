"""Hold Alt, swipe the middle button: does the view turn? Real mouse events.

Not a pytest test. A hand-built QMouseEvent carries whatever modifier you
put in it, which proves nothing about the one thing this gesture can lose:
Alt with a drag is what many desktops use to move a window, so the real
question is whether the press reaches the pane at all, and with Alt on it.

    tests/run_e2e.sh tests/e2e_alt_swipe.py

Xephyr has no window manager, so a pass here means Qt delivers it. A desktop
that grabs Alt-drag for itself is a separate matter, and documented.
"""

import math
import subprocess
import sys
import time

sys.path.insert(0, "tests")
from rpc_client import SerpClient                            # noqa: E402

DISPLAY = ":2"
ENV = {"DISPLAY": DISPLAY, "PATH": "/usr/bin:/bin"}
LEFT = (math.pi, 0.0)          # STANDARD_VIEWS["left"]


def xdo(*args, pause=0.15):
    subprocess.run(["xdotool", *args], env=ENV, capture_output=True,
                   text=True)
    time.sleep(pause)


def middle_drag(cx, cy, dx, alt: bool):
    """A press, a few moves and a release, as a hand would make them."""
    xdo("mousemove", str(cx), str(cy))
    if alt:
        xdo("keydown", "alt")
    xdo("mousedown", "2")
    for step in (0.3, 0.7, 1.0):
        xdo("mousemove", str(int(cx + dx * step)), str(cy), pause=0.08)
    xdo("mouseup", "2")
    if alt:
        xdo("keyup", "alt")
    time.sleep(0.3)


def pose(c):
    cam = c.call("viewport_info")["camera"]
    return cam["azimuth"], cam["elevation"]


def main() -> int:
    c = SerpClient()
    c.call("command", command="new", inputs=["Yes"])
    c.call("set_viewport", view="perspective")

    vp = c.call("viewport_info")
    ox, oy = vp["origin"]
    w, h = vp["size"]
    cx, cy = int(ox + w / 2), int(oy + h / 2)

    middle_drag(cx, cy, 160, alt=True)
    az, el = pose(c)
    landed = (abs(az - LEFT[0]) < 1e-9 and abs(el - LEFT[1]) < 1e-9)
    print(f"[{'PASS' if landed else 'FAIL'}] alt-swipe-lands-on-left "
          f"azimuth={az:.4f} elevation={el:.4f}")

    # Still a perspective pane, which is the point of it: a plain drag
    # orbits away again. In a parallel pane the same drag would pan and
    # leave the angles exactly where the swipe put them.
    middle_drag(cx, cy, 60, alt=False)
    az2 = pose(c)[0]
    orbited = abs(az2 - az) > 1e-6
    print(f"[{'PASS' if orbited else 'FAIL'}] still-perspective-after "
          f"azimuth={az2:.4f}")

    return 0 if (landed and orbited) else 1


if __name__ == "__main__":
    raise SystemExit(main())
