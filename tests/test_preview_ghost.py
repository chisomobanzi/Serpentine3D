"""The ghost of what a command would make, and where it gets drawn.

`rectangle` asks for the opposite corner with a rubber leg from the first
corner *and* a ghost of the rectangle under the cursor. On a sheet only the
leg arrived: the layout branch of `paintGL` drew the rubber band and never
called the ghost at all, so a rectangle looked like a line, and so did an
arc, a circle and everything else that previews a shape. Technical display
mode had lost it the same way.

So the two are drawn by one call now, and the ghost is remapped onto the
paper the way the rubber band already was.
"""

from __future__ import annotations

import numpy as np
import pytest

from serpentine3d.app import MainWindow
from serpentine3d.core import geometry as g
from serpentine3d.core.layout import DetailView, Layout, detail_project

DET = {"x": 20.0, "y": 30.0, "w": 160.0, "h": 120.0,
       "scale_denom": 2.0, "target": [400.0, 250.0, 0.0]}


@pytest.fixture
def sheet():
    w = MainWindow()
    w.resize(1200, 800)
    lay = Layout(name="Sheet1")
    lay.details.append(DetailView(**DET))
    w.scene.layouts.append(lay)
    w.viewport.space = lay.id
    lv = w.viewport.layout_view
    lv.fit()
    lv._fitted_for = lay.id
    return w, lv, lay


# --------------------------------------------------- what there is to draw

def test_a_wire_ghost_has_lines_even_though_it_has_no_faces():
    w = MainWindow()
    vp = w.viewport
    vp.set_ghost(g.make_rectangle((0.0, 0.0, 0.0), (10.0, 5.0, 0.0)))
    tris, segs = vp._ghost_geometry()
    assert tris is None
    assert segs is not None
    assert len(segs) == 8            # four sides, two ends each


def test_a_solid_ghost_has_both():
    w = MainWindow()
    vp = w.viewport
    vp.set_ghost(g.make_box((0.0, 0.0, 0.0), 10.0, 5.0, 3.0))
    tris, segs = vp._ghost_geometry()
    assert tris is not None and len(tris)
    assert segs is not None and len(segs)


def test_no_ghost_is_nothing_to_draw():
    w = MainWindow()
    assert w.viewport._ghost_geometry() == (None, None)


# ------------------------------------------------------------- on a sheet

def test_a_ghost_on_bare_paper_is_already_millimetres(sheet):
    """Nothing to remap: the command was handed paper mm and drew in them."""
    w, lv, _lay = sheet
    lv.entered_detail = None
    w.viewport.point_space = "any"
    w.viewport.set_ghost(g.make_rectangle((10.0, 20.0, 0.0),
                                          (110.0, 70.0, 0.0)))
    _tris, segs = w.viewport._ghost_geometry()
    assert segs[:, 0].min() == pytest.approx(10.0)
    assert segs[:, 1].max() == pytest.approx(70.0)


def test_a_ghost_inside_a_detail_lands_on_the_paper(sheet):
    """A ghost of model geometry comes back out through the detail it was
    drawn through, or it sits on the sheet at the model's own numbers."""
    w, lv, lay = sheet
    det = lay.details[0]
    lv.entered_detail = det.id
    w.viewport.point_space = "any"
    a = (400.0, 250.0, 0.0)
    b = (440.0, 270.0, 0.0)
    w.viewport.set_ghost(g.make_line(a, b))
    _tris, segs = w.viewport._ghost_geometry()
    want = np.asarray([detail_project(det, a), detail_project(det, b)])
    got = np.asarray(sorted(segs[:, :2].tolist()))
    assert got == pytest.approx(np.asarray(sorted(want.tolist())), abs=1e-4)


def test_the_rectangle_preview_on_a_sheet_is_a_rectangle(sheet):
    """The bug as reported: a preview line from corner to corner, no
    rectangle. The ghost is what draws the other three sides."""
    w, lv, _lay = sheet
    lv.entered_detail = None
    w.run_command("rectangle")
    w.processor.provide_text("10,20")
    w._on_mouse_world((110.0, 70.0, 0.0))
    _tris, segs = w.viewport._ghost_geometry()
    assert segs is not None, "no ghost: only the rubber leg would be drawn"
    assert len(segs) == 8


# --------------------------------------------- one call, so neither is lost

def test_the_ghost_and_the_rubber_band_are_drawn_together():
    w = MainWindow()
    vp = w.viewport
    drawn = []
    vp._draw_ghost = lambda mvp: drawn.append("ghost")
    vp._draw_preview = lambda mvp: drawn.append("rubber")
    vp._draw_pending(np.eye(4, dtype=np.float32))
    assert drawn == ["ghost", "rubber"]


def test_no_paint_path_can_draw_one_without_the_other():
    """Why the sheet lost the ghost: three paint paths, and only the one
    for shaded model space remembered to ask for it. There is one thing to
    ask for now, and this is the only test that can see that — a paint path
    needs a GL context no offscreen test has."""
    import inspect

    from serpentine3d.ui.viewport import Viewport
    src = inspect.getsource(Viewport.paintGL)
    assert "_draw_pending" in src
    assert "_draw_preview" not in src
    assert "_draw_ghost" not in src
