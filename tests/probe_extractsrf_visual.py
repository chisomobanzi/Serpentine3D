"""Extract a face in a real window and look at the hole. Not a test.

    DISPLAY=:1 .venv/bin/python tests/probe_extractsrf_visual.py OUT.png
"""

import os
import sys

os.environ.setdefault("SERP3D_NO_RECOVER", "1")
os.environ.setdefault("SERP3D_NO_JOURNAL", "1")

from PySide6.QtWidgets import QApplication            # noqa: E402

from serpentine3d.core import geometry as g           # noqa: E402


def main() -> int:
    out = sys.argv[1]
    app = QApplication.instance() or QApplication([])
    from serpentine3d.app import MainWindow
    w = MainWindow()
    w.resize(1100, 800)
    w.show()
    app.processEvents()

    box = w.scene.add(g.make_box((0.0, 0.0, 0.0), 40.0, 40.0, 40.0))
    top = max(range(len(g.faces_of(box.shape))),
              key=lambda i: g.face_point_normal(
                  g.faces_of(box.shape)[i])[0][2])
    print("top face index:", top)
    w.selection.subobjects.append((box.id, "face", top))
    w.processor.run("extractsrf")
    w.processor.provide_text("No")
    print("busy:", w.processor.busy,
          "objects:", [(o.name, o.kind, len(g.faces_of(o.shape)))
                       for o in w.scene.all()])

    # slide the extracted face clear so the hole is visible
    face = next(o for o in w.scene.all() if o.id != box.id)
    w.scene.replace_shape(face.id, g.translate(face.shape, (70.0, 0.0, 0.0)))

    vp = w.viewport
    vp.resize(1000, 700)
    if hasattr(vp, "zoom_extents"):
        vp.zoom_extents()
    app.processEvents()
    vp.repaint()
    app.processEvents()
    vp.grab().save(out)
    print("wrote", out)
    w.mark_saved()
    w.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
