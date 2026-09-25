"""An assistant adds to a scene someone already has open, over the RPC bridge.

Run through the harness, which starts its own window in Xephyr on its own port:

    tests/run_e2e.sh tests/e2e_assistant_edits_an_open_scene.py

Each check is something that went wrong building a trade-show booth in an open
scene from outside the window: importing a .serp wiped the scene, a picture on
a wall could not be seen, a typed point beside an imported mesh raised and left
the app refusing every call until Escape, and each import moved the camera.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image

sys.path.insert(0, "tests")
from rpc_client import SerpClient  # noqa: E402

WORK = tempfile.mkdtemp(prefix="serp3d-e2e-open-scene-")
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def names(c):
    return sorted(o["name"] for o in c.call("scene_info")["objects"])


def write_mesh_obj(path):
    with open(path, "w", encoding="utf-8") as f:
        f.write("o Tablet\nv 0 0 0\nv 20 0 0\nv 20 0 14\nv 0 0 14\nf 1 2 3\nf 1 3 4\n")


def write_picture(path):
    Image.new("RGB", (64, 48), (255, 0, 0)).save(path)


def write_kit_serp(c, path):
    """A small .serp to import, made by the running app itself."""
    c.call("command", command="new", inputs=["Yes"])
    c.call("command", command="box", inputs=["0,0,0", "4,4,0", "4"])
    c.call("export_file", path=path)
    c.call("command", command="new", inputs=["Yes"])


def pointer_over_the_viewport():
    """Park the real pointer in the pane, as a modeller's would be: snapping
    looks for something under the cursor while a point is being asked for."""
    env = {"DISPLAY": os.environ.get("DISPLAY", ":2"), "PATH": "/usr/bin:/bin"}
    wins = subprocess.run(["xdotool", "search", "--name", "Serpentine3D"],
                          env=env, capture_output=True, text=True).stdout.split()
    if wins:
        subprocess.run(["xdotool", "mousemove", "--window", wins[-1], "700", "450"],
                       env=env, capture_output=True)


def camera(c):
    return c.call("viewport_info")["camera"]


def main() -> int:
    c = SerpClient()
    kit = os.path.join(WORK, "kit.serp")
    write_kit_serp(c, kit)

    # The modeller's own scene: a wall, and something hidden they care about.
    c.call("command", command="box", inputs=["-50,20,0", "50,22,0", "60"])
    c.call("command", command="box", inputs=["100,100,0", "110,110,0", "10"])
    mine = names(c)
    c.call("set_viewport", view="perspective")
    c.call("command", command="camera", inputs=["Place", "0,-200,40", "0,20,30"])
    before = camera(c)

    # 1 · a .serp imported into an open scene adds to it
    added = c.call("import_file", path=kit)["imported"]
    after = names(c)
    check("importing a .serp keeps the open scene",
          all(n in after for n in mine) and len(after) == len(mine) + added,
          f"{len(mine)} + {added} -> {len(after)}")

    # 5 · importing leaves the camera where the modeller put it
    moved = camera(c)
    same = (np.allclose(before["target"], moved["target"])
            and abs(before["distance"] - moved["distance"]) < 1e-6)
    check("import leaves the camera alone", same)

    # 4 · typed points beside an imported mesh, then the app still answers
    mesh = os.path.join(WORK, "tablet.obj")
    write_mesh_obj(mesh)
    c.call("import_file", path=mesh)
    c.call("command", command="camera", inputs=["Place", "10,-60,7", "10,0,7"])
    pointer_over_the_viewport()
    try:
        c.call("command", command="cplane",
               inputs=["3Point", "0,0,0", "10,0,0", "0,0,10"])
        c.call("command", command="line", inputs=["0,0,0", "20,0,14"])
        typed = True
        err = ""
    except RuntimeError as exc:
        typed, err = False, str(exc)
    check("typed points beside an imported mesh", typed, err)
    try:
        c.call("command", command="cplane", inputs=["World"])
        answering = True
    except RuntimeError as exc:
        answering, err = False, str(exc)
    check("the app still answers after that", answering, err)

    # 2 · a picture hung just in front of a wall is seen, not the wall
    pic = os.path.join(WORK, "red.png")
    write_picture(pic)
    c.call("command", command="cplane",
           inputs=["3Point", "-30,19.7,10", "0,19.7,10", "-30,19.7,40"])
    c.call("command", command="pictureframe",
           inputs=["Add", pic, "-30,19.7,10", "30,19.7,55"])
    c.call("command", command="cplane", inputs=["World"])
    c.call("command", command="camera", inputs=["Place", "0,-200,40", "0,20,30"])
    c.call("set_viewport", display_mode="shaded")
    shot = c.call("screenshot", width=800)
    print("picture check frame:", shot["path"])
    img = np.asarray(Image.open(shot["path"]).convert("RGB")).astype(int)
    h, w, _ = img.shape
    centre = img[h // 2 - 20:h // 2 + 20, w // 2 - 20:w // 2 + 20].reshape(-1, 3)
    red = ((centre[:, 0] > 180) & (centre[:, 1] < 90) & (centre[:, 2] < 90)).mean()
    check("a picture in front of a wall is drawn over it", red > 0.8,
          f"{red:.0%} of the centre is the picture")

    def red_pixels():
        # A new object is left selected and drawn heavier; count with none.
        c.call("select", mode="clear")
        shot = c.call("screenshot", width=800)
        im = np.asarray(Image.open(shot["path"]).convert("RGB")).astype(int)
        return int(((im[..., 0] > 180) & (im[..., 1] < 90) & (im[..., 2] < 90)).sum())

    # A curve traced on the picture's own plane shows on top of it, whole.
    # The yardstick is the same pair of lines 0.7 in front of the picture,
    # on the same pixel rows, which nothing can hide; on the plane they
    # z-fight unless the picture sits back, and about half disappear.
    bare = red_pixels()
    c.call("command", command="line", inputs=["-25,19,32", "25,19,32"])
    c.call("command", command="line", inputs=["-25,19,34", "25,19,34"])
    in_front = bare - red_pixels()
    c.call("undo")
    c.call("undo")
    c.call("command", command="line", inputs=["-25,19.7,32", "25,19.7,32"])
    c.call("command", command="line", inputs=["-25,19.7,34", "25,19.7,34"])
    traced = red_pixels()
    on_plane = bare - traced
    check("a curve traced on a picture shows on top of it",
          on_plane >= 0.9 * in_front,
          f"{on_plane} px on the plane vs {in_front} px just in front")

    # Something standing in front of the picture still hides it.
    c.call("command", command="box", inputs=["-10,5,15", "10,7,15", "20"])
    hidden = red_pixels()
    check("an object in front of a picture hides it", hidden < traced * 0.9,
          f"{traced} -> {hidden} picture pixels")

    passed = sum(RESULTS)
    print(f"\n{passed}/{len(RESULTS)} checks passed")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
