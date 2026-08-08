"""Render a NURBS-profiled prism and look at it. Not a test.

Run with a real display:
    DISPLAY=:1 .venv/bin/python tests/probe_isocurves_visual.py OUT.png
Pass `--old` to restore the previous surface-type-only flatness rule,
so the two PNGs can be compared side by side.
"""

import os
import sys

os.environ.setdefault("SERP3D_NO_RECOVER", "1")
os.environ.setdefault("SERP3D_NO_JOURNAL", "1")

from PySide6.QtWidgets import QApplication            # noqa: E402

from serpentine3d.core import geometry as g           # noqa: E402


def main() -> int:
    out = sys.argv[1]
    if "--old" in sys.argv:
        from OCP.GeomAbs import GeomAbs_SurfaceType as T
        import serpentine3d.core.tessellate as tess
        tess._is_flat = (
            lambda face, surf: surf.GetType() == T.GeomAbs_Plane)

    app = QApplication.instance() or QApplication([])
    from serpentine3d.app import MainWindow
    w = MainWindow()
    w.resize(1100, 800)
    w.show()
    app.processEvents()

    # a plain rectangular prism whose profile is a NURBS curve: exactly
    # what an extrusion read out of a .3dm looks like
    profile = g.make_control_curve(
        [(0.0, 0.0, 0.0), (60.0, 0.0, 0.0), (120.0, 0.0, 0.0)])
    w.scene.add(g.extrude(profile, (0.0, 0.0, 1.0), 60.0), name="wall")
    side = g.make_control_curve(
        [(120.0, 0.0, 0.0), (120.0, 40.0, 0.0), (120.0, 80.0, 0.0)])
    w.scene.add(g.extrude(side, (0.0, 0.0, 1.0), 60.0), name="return")
    # one genuinely curved thing, to prove isocurves still appear
    w.scene.add(g.make_cylinder((60.0, 120.0, 0.0), 30.0, 60.0),
                name="drum")

    vp = w.viewport
    vp.resize(1000, 700)
    vp.camera.set_standard_view("perspective") \
        if hasattr(vp.camera, "set_standard_view") else None
    vp.zoom_extents() if hasattr(vp, "zoom_extents") else None
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
