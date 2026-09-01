"""Drag a layer onto another with a real mouse: does it become a sublayer?

Not a pytest test. The panel's own tests build a QDropEvent and hand it
straight to `dropEvent`, which skips everything a hand goes through: the
few pixels that tell a click from a drag, the QDrag Qt runs in a nested
event loop of its own, the mime data it carries. A drop that only ever
arrives hand-built proves the handler works, not that a drag ever starts.

Brings its own window rather than talking to a running one over RPC,
because the rows have to be found on screen and nothing on the socket
knows where a panel row is. Needs a display of its own - a real one would
have the pointer warped out from under whoever is using it:

    Xephyr :2 -screen 1600x1000 &
    DISPLAY=:2 .venv/bin/python tests/e2e_sublayer_drag.py

The pointer is driven from a second process, not a thread. A drag runs a
nested event loop inside the mouse-move handler it started in, so the
thread that is supposed to keep moving the pointer is the one the loop is
waiting on, and both sit there until something kills them.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time

# -- the pointer, run as its own process ------------------------------------

def drag(start, end):
    """Press on one row, walk to another, let go.

    Several moves, not one: a drag only begins once the pointer has left
    the few pixels around the press that Qt reads as a click, and each
    move has to land inside the tree for the drop to be offered a row.
    """
    def xdo(*args, pause=0.15):
        subprocess.run(["xdotool", *args], capture_output=True, text=True)
        time.sleep(pause)

    time.sleep(1.0)
    xdo("mousemove", str(start[0]), str(start[1]))
    xdo("mousedown", "1")
    try:
        for i in (1, 3, 6, 10):
            x = start[0] + (end[0] - start[0]) * i / 10
            y = start[1] + (end[1] - start[1]) * i / 10
            xdo("mousemove", str(int(x)), str(int(y)), pause=0.25)
    finally:
        xdo("mouseup", "1", pause=0.5)


if len(sys.argv) > 1 and sys.argv[1] == "--drive":
    x1, y1, x2, y2 = (int(a) for a in sys.argv[2:6])
    drag((x1, y1), (x2, y2))
    raise SystemExit(0)

# -- the app ----------------------------------------------------------------

DISPLAY = os.environ.get("DISPLAY", "")
if DISPLAY in ("", ":0", ":1"):
    sys.exit(f"refusing to drive the pointer on DISPLAY={DISPLAY!r}; "
             "start a Xephyr and point DISPLAY at that")

_TMP = tempfile.mkdtemp(prefix="serp3d-e2e-")
os.environ.update(SERP3D_CONFIG=os.path.join(_TMP, "config.json"),
                  SERP3D_JOURNAL_DIR=os.path.join(_TMP, "journals"),
                  SERP3D_AUTOSAVE_DIR=os.path.join(_TMP, "autosave"),
                  SERP3D_NO_RECOVER="1", SERP3D_NO_SPLASH="1",
                  SERP3D_NO_WELCOME="1", SERP3D_NO_UPDATE_CHECK="1",
                  LIBGL_ALWAYS_SOFTWARE="1")

from PySide6.QtCore import QTimer                     # noqa: E402
from PySide6.QtWidgets import QApplication            # noqa: E402
from serpentine3d.app import MainWindow               # noqa: E402
from serpentine3d.ui import theme                     # noqa: E402


def main() -> int:
    app = QApplication(sys.argv[:1])
    app.setStyleSheet(theme.QSS)
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    for _ in range(20):
        QApplication.processEvents()
        time.sleep(0.05)

    layers = win.scene.layers
    walls = layers.create("Walls")
    roof = layers.create("Roof")
    win.scene.notify()
    QApplication.processEvents()

    panel = win.layers_panel
    tree = panel.tree
    rows = {panel._layer_id(tree.topLevelItem(i)): tree.topLevelItem(i)
            for i in range(tree.topLevelItemCount())}

    def at(layer_id):
        point = tree.viewport().mapToGlobal(
            tree.visualItemRect(rows[layer_id]).center())
        return point.x(), point.y()

    start, end = at(roof.id), at(walls.id)
    print(f"dragging Roof at {start} onto Walls at {end}", flush=True)
    driver = subprocess.Popen(
        [sys.executable, __file__, "--drive",
         str(start[0]), str(start[1]), str(end[0]), str(end[1])])

    watch = QTimer()
    watch.setInterval(200)
    watch.timeout.connect(
        lambda: driver.poll() is None or app.quit())
    watch.start()
    QTimer.singleShot(60000, app.quit)
    app.exec()
    driver.poll() is None and driver.kill()

    ok = True

    def check(name, passed, detail=""):
        nonlocal ok
        ok &= bool(passed)
        print(f"[{'PASS' if passed else 'FAIL'}] {name} {detail}", flush=True)

    parent = layers.get(roof.id).parent
    check("a-dragged-layer-becomes-a-sublayer", parent == walls.id,
          f"Roof hangs from "
          f"{layers.full_path(parent) if parent else None}")
    check("the-panel-drew-it-under-walls",
          [la.name for la in layers.children(walls.id)] == ["Roof"],
          f"{[la.name for la in layers.children(walls.id)]}")
    win.history.undo()
    back = layers.get(roof.id).parent
    check("one-undo-puts-it-back", back is None,
          f"parent is {layers.full_path(back) if back else None}")

    win.mark_saved()
    win.close()          # journalling stops in closeEvent, not at exit
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
