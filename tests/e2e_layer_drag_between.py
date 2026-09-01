"""Drag a layer between two others with a real mouse: does it land there?

Not a pytest test. The panel's own tests build a QDropEvent and hand it
straight to `dropEvent`, which skips everything a hand goes through: the
few pixels that tell a click from a drag, the QDrag Qt runs in a nested
event loop of its own, and the quarter of a row that has to be hit for
the drop to mean "beside this one" rather than "inside it". A band that
is only ever aimed at from Python proves the arithmetic, not that anyone
can hit it.

Companion to `e2e_sublayer_drag.py`, which drags a layer *onto* another
one, and set up the same way. Needs a display of its own - a real one
would have the pointer warped out from under whoever is using it:

    Xephyr :2 -screen 1600x1000 &
    DISPLAY=:2 .venv/bin/python tests/e2e_layer_drag_between.py
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
        # Sideways first. A drag only begins once the pointer has left the
        # ten-odd pixels around the press that Qt reads as a click, and the
        # gap between two rows is not that far: without this the drag would
        # begin on the last move of the walk, with no move left to tell it
        # where the pointer ended up.
        xdo("mousemove", str(start[0] + 14), str(start[1]), pause=0.25)
        for i in (2, 5, 8, 10, 10):
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
             "start an Xephyr and point DISPLAY at that")

_TMP = tempfile.mkdtemp(prefix="serp3d-e2e-")
os.environ.update(SERP3D_CONFIG=os.path.join(_TMP, "config.json"),
                  SERP3D_JOURNAL_DIR=os.path.join(_TMP, "journals"),
                  SERP3D_AUTOSAVE_DIR=os.path.join(_TMP, "autosave"),
                  SERP3D_NO_RECOVER="1", SERP3D_NO_SPLASH="1",
                  SERP3D_NO_WELCOME="1", SERP3D_NO_UPDATE_CHECK="1",
                  LIBGL_ALWAYS_SOFTWARE="1")

from PySide6.QtCore import QPoint                   # noqa: E402
from PySide6.QtWidgets import QApplication          # noqa: E402

from serpentine3d.app import MainWindow             # noqa: E402
from serpentine3d.ui import theme                   # noqa: E402


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
    inner = layers.create("Interior", parent=walls.id)
    roof = layers.create("Roof")
    site = layers.create("Site")
    win.scene.notify()
    QApplication.processEvents()

    panel = win.layers_panel
    tree = panel.tree
    tree.expandAll()     # a row nobody can see is a row nobody can drag
    QApplication.processEvents()

    def rows():
        """Every row on screen now, by layer id: the tree is rebuilt from
        the scene after every drop, so yesterday's items are gone."""
        out = {}

        def walk(item):
            out[panel._layer_id(item)] = item
            for i in range(item.childCount()):
                walk(item.child(i))

        for i in range(tree.topLevelItemCount()):
            walk(tree.topLevelItem(i))
        return out

    def at(layer_id, where="on"):
        """A point on a row, on screen: its middle, or its top edge."""
        rect = tree.visualItemRect(rows()[layer_id])
        y = rect.center().y() if where == "on" else rect.top() + 3
        point = tree.viewport().mapToGlobal(QPoint(rect.center().x(), y))
        return point.x(), point.y()

    move = panel._move_layers

    def watched(ids, parent, before=None):
        """Say what the drop made of where it landed, before it lands."""
        print(f"  -> into {parent!r}, in front of {before!r}", flush=True)
        move(ids, parent, before)

    tree.on_drop = watched

    def drag_to(what, target, where="on"):
        start, end = at(what), at(target, where)
        print(f"dragging {start} to {end} ({where})", flush=True)
        driver = subprocess.Popen(
            [sys.executable, __file__, "--drive",
             str(start[0]), str(start[1]), str(end[0]), str(end[1])])
        # Pumped, not `app.exec()` once per drag: a second `exec` after a
        # `quit` comes back with the window no longer taking a drag at all,
        # and every drag but the first quietly does nothing.
        while driver.poll() is None:
            QApplication.processEvents()
            time.sleep(0.02)
        for _ in range(20):        # let the panel redraw from the scene
            QApplication.processEvents()
            time.sleep(0.05)

    ok = True

    def check(name, passed, detail=""):
        nonlocal ok
        ok &= bool(passed)
        print(f"[{'PASS' if passed else 'FAIL'}] {name} {detail}", flush=True)

    def top():
        return [la.name for la in layers.children(None)]

    # 1. between two top-level layers
    drag_to(site.id, walls.id, "above")
    check("a-layer-lands-where-it-was-dropped",
          top() == ["Default", "Site", "Walls", "Roof"], f"{top()}")
    check("it-did-not-land-inside-the-layer-under-the-line",
          layers.get(site.id).parent is None,
          f"Site hangs from {layers.full_path(layers.get(site.id).parent)}"
          if layers.get(site.id).parent else "")

    # 2. a sublayer dragged out of its branch, no button involved
    drag_to(inner.id, roof.id, "above")
    check("a-sublayer-can-be-dragged-back-out",
          layers.get(inner.id).parent is None,
          f"Interior is still under "
          f"{layers.full_path(layers.get(inner.id).parent)}"
          if layers.get(inner.id).parent else "")
    check("and-it-lands-in-the-gap-it-was-dropped-in",
          top() == ["Default", "Site", "Walls", "Interior", "Roof"],
          f"{top()}")

    # 3. the gesture that was already there
    drag_to(roof.id, walls.id, "on")
    check("a-drop-on-a-layer-still-puts-it-inside",
          layers.get(roof.id).parent == walls.id,
          f"Roof hangs from {layers.full_path(layers.get(roof.id).parent)}"
          if layers.get(roof.id).parent else "at the top level")

    win.history.undo()
    check("one-drop-is-one-undo", layers.get(roof.id).parent is None,
          f"{[la.name for la in layers.children(walls.id)]}")

    win.mark_saved()
    win.close()          # journalling stops in closeEvent, not at exit
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
