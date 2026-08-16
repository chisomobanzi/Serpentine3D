"""Draw a curve with a real mouse and photograph it before it is finished.

The complaint this answers: while drawing a curve you only saw the points
you had clicked, and the curve itself appeared when you pressed Enter. The
unit tests (tests/test_command_previews.py) say the processor hands back a
curve for the cursor position. This one says the screen shows it: the app
runs inside Xephyr, xdotool clicks the control points, the cursor parks on
the next one and the framebuffer is grabbed mid-command.

    tests/run_e2e.sh tests/e2e_curve_preview.py

The pictures land in screenshots/ for a look afterwards.
"""

import os
import subprocess
import sys
import time

sys.path.insert(0, "tests")
from rpc_client import SerpClient                              # noqa: E402

DISPLAY = ":2"
ENV = {"DISPLAY": DISPLAY, "PATH": "/usr/bin:/bin"}
SHOT = "screenshots"

# A zigzag, so the curve and the straight chain between the picks cannot be
# mistaken for one another. The last one is only ever hovered.
PICKS = [(-30.0, -15.0, 0.0), (-10.0, 15.0, 0.0), (10.0, -15.0, 0.0)]
HOVER = (30.0, 15.0, 0.0)


def xdo(*args, pause=0.2):
    subprocess.run(["xdotool", *args], env=ENV, check=True)
    time.sleep(pause)


def type_cmd(text):
    xdo("type", "--delay", "30", text)
    xdo("key", "Return")


def to_screen(c, world):
    """World points as pixels on the actual screen, and whether they fit."""
    vp = c.call("viewport_info", project=[list(p) for p in world])
    ox, oy = vp["origin"]
    w, h = vp["size"]
    pts = [(int(round(ox + x)), int(round(oy + y)))
           for x, y in vp["projected"]]
    inside = all(0 < x - ox < w and 0 < y - oy < h for x, y in pts)
    return pts, inside


def click(x, y):
    xdo("mousemove", str(x), str(y), pause=0.1)
    xdo("click", "1")


def hover(x, y):
    """A move the app cannot miss: land nearby, then step onto the spot."""
    xdo("mousemove", str(x - 12), str(y - 12), pause=0.1)
    xdo("mousemove", str(x), str(y), pause=0.4)


def shot(c, name, full=False):
    path = os.path.join(SHOT, f"curve_preview_{name}.png")
    c.call("screenshot", path=path, full_window=full)
    print(f"       wrote {path}")
    return path


def draw_and_watch(c, command, tag):
    """Type the command, click the picks, hover the next one, grab the screen."""
    pts, inside = to_screen(c, PICKS + [HOVER])
    if not inside:
        print(f"[FAIL] {tag}-picks-are-on-screen {pts}")
        return False
    *clicks, park = pts
    xdo("mousemove", str(clicks[0][0]), str(clicks[0][1]), pause=0.1)
    type_cmd(command)
    for i, (x, y) in enumerate(clicks):
        click(x, y)
        if i == 1:                       # two picks and a cursor is already
            hover(*park)                 # a curve worth showing
            shot(c, f"{tag}_two_picks")
    hover(*park)
    shot(c, f"{tag}_three_picks")
    return True


def main() -> int:
    os.makedirs(SHOT, exist_ok=True)
    c = SerpClient()
    ok = True

    c.call("command", command="new", inputs=["Yes"])
    c.call("set_viewport", view="top")
    c.call("command", command="max")           # one big pane to look at

    for command, tag in (("curve", "control"), ("interpcrv", "interp")):
        print(f"--- {command}")
        ok &= draw_and_watch(c, command, tag)
        before = len(c.call("scene_info")["objects"])
        xdo("key", "Escape")
        after = len(c.call("scene_info")["objects"])
        good = before == after == 0
        print(f"[{'PASS' if good else 'FAIL'}] {tag}-was-still-mid-command "
              f"(objects before Escape {before}, after {after})")
        ok &= good

    # --- and the knot previews, on a curve that already exists
    print("--- insertknot")
    c.call("command", command="curve",
           inputs=[list(p) for p in PICKS] + [list(HOVER), ""])
    names = [o["name"] for o in c.call("scene_info")["objects"]]
    if names:
        c.call("select", names=names[:1])
        pts, _inside = to_screen(c, [(-18.0, -6.0, 0.0), (14.0, 1.0, 0.0)])
        xdo("mousemove", str(pts[0][0]), str(pts[0][1]), pause=0.1)
        type_cmd("insertknot")
        for i, p in enumerate(pts):
            hover(*p)
            shot(c, f"insertknot_{i}")
        shot(c, "insertknot_prompt", full=True)
        xdo("key", "Escape")
    else:
        print("[FAIL] a curve to add a knot to")
        ok = False

    c.call("command", command="new", inputs=["No"])
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
