"""Run Dir on real geometry and photograph the arrows.

The unit tests (tests/test_direction.py) say where each arrow stands and
which way it points. This one says the screen shows them: the app runs
inside Xephyr, `dir` is typed at the prompt, and the framebuffer is grabbed
while the command is still up. The arrows are the only green thing that
comes and goes, so counting green pixels before, during and after is enough
to tell whether anything was actually drawn.

    tests/run_e2e.sh tests/e2e_direction.py

The pictures land in screenshots/ for a look afterwards.
"""

import os
import subprocess
import sys
import time

from PIL import Image

sys.path.insert(0, "tests")
from rpc_client import SerpClient                              # noqa: E402

DISPLAY = ":2"
ENV = {"DISPLAY": DISPLAY, "PATH": "/usr/bin:/bin"}
SHOT = "screenshots"

CURVE = [(-40.0, -20.0, 0.0), (-15.0, 20.0, 0.0),
         (15.0, -20.0, 0.0), (40.0, 20.0, 0.0)]
RECT = [(-30.0, 30.0, 0.0), (30.0, 55.0, 0.0)]


def xdo(*args, pause=0.25):
    subprocess.run(["xdotool", *args], env=ENV, check=True)
    time.sleep(pause)


def type_cmd(text):
    xdo("type", "--delay", "30", text)
    xdo("key", "Return", pause=0.6)


def shot(c, name):
    path = os.path.join(SHOT, f"direction_{name}.png")
    c.call("screenshot", path=path)
    return path


def green_pixels(path):
    """How much of the picture is arrow-coloured.

    The arrows are the green in a viewport that is otherwise grey, white and
    gold. The grid's Y axis is green too, which is why this is only ever read
    as a difference: the grid is in every shot, the arrows are not.
    """
    im = Image.open(path).convert("RGB")
    px = im.load()
    w, h = im.size
    n = 0
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            r, g, b = px[x, y]
            if g - max(r, b) > 30 and g > 90:
                n += 1
    return n


def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' ' + detail if detail else ''}")
    return ok


def main() -> int:
    os.makedirs(SHOT, exist_ok=True)
    c = SerpClient()
    ok = True

    c.call("command", command="new", inputs=["Yes"])
    c.call("set_viewport", view="top")
    c.call("command", command="max")
    c.call("command", command="curve",
           inputs=[list(p) for p in CURVE] + [""])
    c.call("command", command="rectangle", inputs=[list(p) for p in RECT])
    rect = c.call("scene_info")["objects"][-1]["name"]
    c.call("command", command="planarsrf", inputs=[rect, ""])
    c.call("command", command="zoomextents")
    names = [o["name"] for o in c.call("scene_info")["objects"]]
    print(f"       drawing: {names}")

    # One baseline per view: the grid's Y axis is green too, and it shows
    # much more of itself down a perspective than it does from straight above
    bare = green_pixels(shot(c, "0_before"))
    c.call("set_viewport", view="perspective")
    time.sleep(0.4)
    bare_persp = green_pixels(shot(c, "0_before_perspective"))
    c.call("set_viewport", view="top")
    time.sleep(0.4)

    # preselect, then type it: `dir` takes what is already picked, and the
    # command has to stay up for the picture, so it cannot go over RPC
    c.call("select", names=names)
    type_cmd("dir")
    on_top = green_pixels(shot(c, "1_arrows_top"))
    ok &= check("arrows-are-drawn", on_top > bare + 200,
                f"(green pixels {bare} -> {on_top})")

    # perspective as well: in top view a surface normal points straight at
    # you, which is the case where a badly built arrowhead disappears
    c.call("set_viewport", view="perspective")
    time.sleep(0.4)
    persp = green_pixels(shot(c, "2_arrows_perspective"))
    ok &= check("arrows-survive-an-orbit", persp > bare_persp + 200,
                f"(green pixels {bare_persp} -> {persp})")

    type_cmd("Flip")
    flipped = green_pixels(shot(c, "3_flipped"))
    ok &= check("still-showing-after-a-flip", flipped > bare_persp + 200,
                f"(green pixels {flipped})")

    xdo("key", "Escape", pause=0.6)
    gone = green_pixels(shot(c, "4_after_escape"))
    ok &= check("escape-puts-them-away", gone <= bare_persp + 40,
                f"(green pixels {gone}, bare {bare_persp})")

    c.call("command", command="new", inputs=["No"])
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
