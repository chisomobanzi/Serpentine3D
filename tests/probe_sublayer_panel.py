"""Grab the Layers dock as the app builds it, with a layer tree in it.

Not a pytest test. A panel that resizes its own widget proves nothing
about the width the app gives it, and a panel built without the
stylesheet proves nothing about the font it paints with, so build
`MainWindow`, put a tree of layers in it, and look at the dock.

    QT_QPA_PLATFORM=offscreen uv run python \
        tests/probe_sublayer_panel.py OUT.png
"""

from __future__ import annotations

import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="serp3d-probe-")
os.environ["SERP3D_CONFIG"] = os.path.join(_TMP, "config.json")
os.environ["SERP3D_JOURNAL_DIR"] = os.path.join(_TMP, "journals")
os.environ["SERP3D_AUTOSAVE_DIR"] = os.path.join(_TMP, "autosave")
os.environ["SERP3D_NO_RECOVER"] = "1"
os.environ["SERP3D_NO_SPLASH"] = "1"
os.environ["SERP3D_NO_WELCOME"] = "1"
os.environ["SERP3D_NO_UPDATE_CHECK"] = "1"

from PySide6.QtWidgets import (QApplication,          # noqa: E402
                               QPushButton)
from serpentine3d.app import MainWindow               # noqa: E402
from serpentine3d.ui import theme                     # noqa: E402

def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else "sublayers-dock.png"
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.QSS)
    win = MainWindow()
    win.resize(1600, 900)
    win.show()
    QApplication.processEvents()

    layers = win.scene.layers
    walls = layers.create("Walls")
    layers.create("Interior", parent=walls.id)
    ext = layers.create("Exterior", parent=walls.id)
    layers.create("Cladding", parent=ext.id)
    roof = layers.create("Roof")
    layers.create("Interior", parent=roof.id)
    hidden = layers.create("Site")
    kid = layers.create("Survey", parent=hidden.id)
    layers.set_visible(hidden.id, False)
    win.scene.notify()
    QApplication.processEvents()

    panel = win.layers_panel
    tree = panel.tree
    print("dock width:", win._layer_dock.width(),
          "tree viewport:", tree.viewport().width())
    print("columns:", [tree.columnWidth(c)
                       for c in range(tree.columnCount())],
          "sum:", sum(tree.columnWidth(c)
                      for c in range(tree.columnCount())))
    print("sideways scrollbar:", tree.horizontalScrollBar().isVisible())
    print("top level rows:", tree.topLevelItemCount())
    print("Survey is effectively visible:", layers.is_visible(kid.id))
    for button in panel.findChildren(QPushButton):
        print("button:", repr(button.text()), "|", button.toolTip())

    win._layer_dock.grab().save(out)
    print("wrote", out)

    # The way back out of a branch, as the user meets it: the row menu on
    # the deepest layer, which is the only one offered both moves.
    clad = layers.find_by_path("Walls::Exterior::Cladding")
    menu = panel._menu_for(clad.id)
    menu.show()
    QApplication.processEvents()
    print("menu:", [a.text() or "-" for a in menu.actions()])
    menu_out = out.replace(".png", "-menu.png")
    menu.grab().save(menu_out)
    print("wrote", menu_out)
    menu.hide()
    win.mark_saved()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
