"""Orbit with a real mouse, then take the view back.

The unit tests (tests/test_view_history.py) drive the history by hand. This
one drives it the way it is actually used: a middle-button drag across the
pane inside Xephyr, a burst of wheel zooms, and `undoview` after each. What
it is really checking is that a whole gesture is one step back rather than
a hundred, which no unit test can see because the frames come from Qt.

It also checks that lockother leaves the rest of the drawing where it is and
unpickable, by clicking on a locked object and finding nothing selected.

    tests/run_e2e.sh tests/e2e_view_history.py
"""

import math
import subprocess
import sys
import time

sys.path.insert(0, "tests")
from rpc_client import SerpClient                              # noqa: E402

DISPLAY = ":2"
ENV = {"DISPLAY": DISPLAY, "PATH": "/usr/bin:/bin"}

BOX_A = [(-40.0, -20.0, 0.0), 20.0, 20.0, 20.0]
BOX_B = [(20.0, -20.0, 0.0), 20.0, 20.0, 20.0]


def xdo(*args, pause=0.2):
    subprocess.run(["xdotool", *args], env=ENV, check=True)
    time.sleep(pause)


def cam(c):
    return c.call("viewport_info")["camera"]


def moved(a, b) -> float:
    """How far apart two camera poses are, in one number."""
    return (abs(a["azimuth"] - b["azimuth"])
            + abs(a["elevation"] - b["elevation"])
            + abs(a["distance"] - b["distance"]) / max(a["distance"], 1e-9)
            + math.dist(a["target"], b["target"]) / max(a["distance"], 1e-9))


def same(a, b) -> bool:
    return moved(a, b) < 1e-6


def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' ' + detail if detail else ''}")
    return ok


def centre(c):
    vp = c.call("viewport_info")
    ox, oy = vp["origin"]
    w, h = vp["size"]
    return int(ox + w / 2), int(oy + h / 2)


def drag_orbit(c):
    """One middle-button drag, in several steps, like a hand would."""
    x, y = centre(c)
    xdo("mousemove", str(x), str(y), pause=0.1)
    xdo("mousedown", "2", pause=0.15)
    for i in range(1, 9):
        xdo("mousemove", str(x + i * 14), str(y + i * 5), pause=0.05)
    xdo("mouseup", "2", pause=0.5)


def to_screen(c, world):
    vp = c.call("viewport_info", project=[list(world)])
    ox, oy = vp["origin"]
    x, y = vp["projected"][0]
    return int(round(ox + x)), int(round(oy + y))


def main() -> int:
    c = SerpClient()
    ok = True

    c.call("command", command="new", inputs=["Yes"])
    c.call("set_viewport", view="perspective")
    c.call("command", command="max")
    c.call("command", command="box", inputs=[BOX_A[0], BOX_A[1], BOX_A[2],
                                             BOX_A[3]])
    c.call("command", command="box", inputs=[BOX_B[0], BOX_B[1], BOX_B[2],
                                             BOX_B[3]])
    c.call("command", command="zoomextents")
    time.sleep(0.5)

    # --- a drag is one step back
    before = cam(c)
    drag_orbit(c)
    after = cam(c)
    ok &= check("a-drag-moves-the-view", moved(before, after) > 0.05,
                f"(moved {moved(before, after):.3f})")
    c.call("command", command="undoview")
    time.sleep(0.3)
    ok &= check("undoview-puts-the-whole-drag-back", same(cam(c), before),
                f"(left {moved(cam(c), before):.6f} away)")

    c.call("command", command="redoview")
    time.sleep(0.3)
    ok &= check("redoview-goes-forward-again", same(cam(c), after))

    # --- a burst of wheel clicks is also one step back
    turned = cam(c)
    x, y = centre(c)
    xdo("mousemove", str(x), str(y), pause=0.1)
    for _ in range(5):
        xdo("click", "4", pause=0.08)
    time.sleep(0.4)
    zoomed = cam(c)
    ok &= check("the-wheel-zooms", abs(zoomed["distance"]
                                       - turned["distance"]) > 1.0)
    c.call("command", command="undoview")
    time.sleep(0.3)
    ok &= check("one-step-back-covers-the-whole-burst", same(cam(c), turned),
                f"(left {moved(cam(c), turned):.6f} away)")

    # --- and a standard view is a step like any other
    c.call("set_viewport", view="top")
    time.sleep(0.5)
    c.call("command", command="undoview")
    time.sleep(0.3)
    ok &= check("undoview-takes-back-a-named-view", same(cam(c), turned))

    # --- lockother
    names = [o["name"] for o in c.call("scene_info")["objects"]]
    c.call("select", names=names[:1])
    c.call("command", command="lockother", inputs=[""])
    info = {o["name"]: o for o in c.call("scene_info")["objects"]}
    ok &= check("lockother-locks-the-rest",
                info[names[1]]["locked"] and not info[names[0]]["locked"])
    ok &= check("lockother-hides-nothing", info[names[1]]["visible"])
    ok &= check("what-you-kept-is-still-picked",
                c.call("viewport_info")["selected"] == names[:1])

    # A locked object is one you cannot pick, which is the whole point. The
    # same click has to land on it after unlockall, or an empty selection
    # only means the click went somewhere there was nothing anyway.
    spot = to_screen(c, [30.0, -10.0, 10.0])

    def click_the_locked_one():
        c.call("command", command="selnone")
        xdo("mousemove", str(spot[0]), str(spot[1]), pause=0.1)
        xdo("click", "1", pause=0.4)
        return c.call("viewport_info")["selected"]

    got = click_the_locked_one()
    ok &= check("and-you-cannot-pick-it", got == [], f"(selected {got})")
    c.call("command", command="unlockall")
    got = click_the_locked_one()
    ok &= check("the-same-click-picks-it-once-unlocked", got == [names[1]],
                f"(selected {got}, wanted {[names[1]]})")

    c.call("command", command="new", inputs=["No"])
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
