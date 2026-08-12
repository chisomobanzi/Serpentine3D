"""The gumball on a sheet: handles you can take hold of through a detail.

What is picked in a detail is a model object, and until now the only way to
move it from there was to type. The gumball is drawn and hit-tested through
the same eye everything else on a sheet uses, so the arrows point the way the
detail looks and are the size they are in the model window.

An orthographic window cannot offer all of it: the arrow, pad and circle that
need depth the view does not have are drawn and refused rather than moving
things by wild amounts, which is what a nearly-parallel ray does.
"""

from __future__ import annotations

import inspect

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent

import serpentine3d.commands  # registers all commands  # noqa: F401
from serpentine3d.app import MainWindow
from serpentine3d.core import geometry as g
from serpentine3d.core.layout import DetailView, Layout, detail_project
from serpentine3d.ui.camera import STANDARD_VIEWS
from serpentine3d.ui.gumball import CONE1, SHAFT0
from serpentine3d.ui.layout_view import detail_plane

BOX_MIN = (-100.0, -80.0, 0.0)


@pytest.fixture
def sheet():
    """A sheet with one front detail, stepped into, one box picked in it."""
    w = MainWindow()
    w.resize(1200, 800)
    box = w.scene.add(g.make_box(BOX_MIN, 200.0, 160.0, 60.0))
    lay = Layout(name="Sheet1")
    az, el = STANDARD_VIEWS["front"]
    det = DetailView(x=160.0, y=100.0, w=120.0, h=90.0, azimuth=az,
                     elevation=el, target=[0.0, 0.0, 30.0], scale_denom=2.0,
                     display_mode="wireframe")
    lay.details.append(det)
    w.scene.layouts.append(lay)
    w.switch_space(lay.id)
    lv = w.viewport.layout_view
    lv.fit()
    lv._fitted_for = lay.id
    lv.entered_detail = det.id
    w.viewport.grid_snap = False        # about the handles, not the grid
    w.selection.set([box.id])
    return w, det, box


def _screen(w, pt) -> tuple[float, float]:
    """Where a model point appears on screen, through the entered detail."""
    vp = w.viewport
    scr = vp._eye().project([pt], vp.width(), vp.height())[0]
    return float(scr[0]), float(scr[1])


def _handle(w, kind: str, axis: int) -> tuple[float, float]:
    """A pixel on the given handle, as it is drawn."""
    gb = w.viewport.gumball
    anchor, axes = gb.anchor_and_axes()
    s = gb._size_world(anchor)
    reach = {"move": (SHAFT0 + CONE1) / 2}[kind]
    return _screen(w, anchor + axes[axis] * reach * s)


def _ev(kind, pos, buttons=Qt.MouseButton.LeftButton):
    return QMouseEvent(kind, pos, pos, Qt.MouseButton.LeftButton, buttons,
                       Qt.KeyboardModifier.NoModifier)


# ------------------------------------------------------------ when it shows

def test_the_gumball_is_offered_inside_a_detail(sheet):
    w, _det, _box = sheet
    assert w.viewport.gumball.active()


def test_bare_paper_has_no_gumball(sheet):
    """This one. Off a detail a sheet is millimetres of paper, and the model
    object picked in one is not there to be dragged. The paper has handles of
    its own for its own things: see `test_gumball_on_paper`."""
    w, _det, _box = sheet
    w.viewport.layout_view.entered_detail = None
    assert not w.viewport.gumball.active()


def test_a_command_asking_for_a_point_hides_it(sheet):
    w, _det, _box = sheet
    w.viewport.point_mode = True
    assert not w.viewport.gumball.active()


def test_nothing_picked_means_no_gumball(sheet):
    w, _det, _box = sheet
    w.selection.clear()
    assert not w.viewport.gumball.active()


# ------------------------------------------------------- where its axes point

def test_the_axes_are_the_ones_the_detail_looks_at(sheet):
    """Squared to the view, so the arrows lie along what you can see: the
    world axes would put two of the three into the paper at an angle."""
    w, det, _box = sheet
    _anchor, axes = w.viewport.gumball.anchor_and_axes()
    cp = detail_plane(det)
    assert axes[0] == pytest.approx(cp.xdir)
    assert axes[1] == pytest.approx(cp.ydir)
    assert axes[2] == pytest.approx(cp.normal)


def test_the_anchor_is_the_middle_of_what_is_picked(sheet):
    w, _det, box = sheet
    anchor, _axes = w.viewport.gumball.anchor_and_axes()
    lo, hi = g.bbox(box.shape)
    assert anchor == pytest.approx((np.asarray(lo) + np.asarray(hi)) / 2)


# ------------------------------------------------------------- how big it is

def test_it_is_sized_in_pixels_through_the_detail(sheet):
    """The same handful of pixels whatever the detail's scale is — a gumball
    measured in model millimetres is invisible at 1:100 and fills the frame
    at 5:1."""
    w, det, _box = sheet
    gb = w.viewport.gumball
    anchor, _axes = gb.anchor_and_axes()
    small = gb._size_world(anchor)
    det.scale_denom *= 4.0
    assert gb._size_world(anchor) == pytest.approx(small * 4.0, rel=1e-6)


def test_the_shaft_is_drawn_the_length_it_is_hit(sheet):
    """Hit testing and drawing measure the same handle: a pixel on the drawn
    arrow is the one the hit test answers to."""
    w, _det, _box = sheet
    px, py = _handle(w, "move", 0)
    assert w.viewport.gumball.hit_test(px, py) == ("move", 0)


def test_the_other_in_view_arrow_is_there_too(sheet):
    w, _det, _box = sheet
    px, py = _handle(w, "move", 1)
    assert w.viewport.gumball.hit_test(px, py) == ("move", 1)


def test_a_handle_reaching_past_the_frame_is_still_there(sheet):
    """What a detail shows is cut off at its frame; the handles drawn over it
    are not. An object nearly filling its window would otherwise be held by
    arrows sticking out into paper nobody can click."""
    w, det, _box = sheet
    gb = w.viewport.gumball
    anchor, axes = gb.anchor_and_axes()
    s = gb._size_world(anchor)
    tip = anchor + axes[0] * CONE1 * s
    px_paper, _py_paper = detail_project(det, tip)
    assert px_paper > det.x + det.w, "the test is about a handle over the edge"
    # the arrow is hit along its whole length, tip included
    assert gb.hit_test(*_screen(w, tip)) == ("move", 0)
    assert gb.hit_test(*_screen(w, anchor + axes[0] * SHAFT0 * s)) \
        == ("move", 0)


def test_empty_paper_hits_no_handle(sheet):
    w, det, _box = sheet
    lv = w.viewport.layout_view
    px, py = lv.paper_to_screen(det.x + det.w + 40.0, det.y)
    assert w.viewport.gumball.hit_test(px, py) is None


# ------------------------------------------------------------ taking hold

def test_dragging_an_arrow_moves_the_model_object(sheet):
    """The distance is the pixels dragged read back through the detail: its
    scale and the sheet's zoom, the same two steps a pick runs."""
    w, det, box = sheet
    lv = w.viewport.layout_view
    gb = w.viewport.gumball
    px, py = _handle(w, "move", 0)
    assert gb.begin_drag(("move", 0), px, py, Qt.KeyboardModifier.NoModifier)
    gb.drag_to(px + 40.0, py, Qt.KeyboardModifier.NoModifier)
    gb.end_drag()
    expected = 40.0 / lv.px_per_mm * det.scale_denom
    lo, _hi = g.bbox(w.scene.get(box.id).shape)
    assert lo[0] == pytest.approx(BOX_MIN[0] + expected, abs=0.5)
    assert lo[1] == pytest.approx(BOX_MIN[1], abs=1e-6), "only along the arrow"


def test_the_arrow_pointing_into_the_view_is_refused(sheet):
    """A detail is a flat window: dragging the axis that runs away from you
    is a ray parallel to its own line, which answers with anything at all."""
    w, _det, _box = sheet
    gb = w.viewport.gumball
    px, py = _screen(w, gb.anchor_and_axes()[0])
    assert not gb.begin_drag(("move", 2), px, py,
                             Qt.KeyboardModifier.NoModifier)
    assert gb.drag is None


def test_the_pad_flat_to_the_view_still_works(sheet):
    """The one plane you are looking at square-on is the one you can slide
    something about in, and it is the useful one."""
    w, _det, box = sheet
    gb = w.viewport.gumball
    px, py = _screen(w, gb.anchor_and_axes()[0])
    assert gb.begin_drag(("pad", 2), px, py, Qt.KeyboardModifier.NoModifier)
    gb.drag_to(px + 30.0, py - 20.0, Qt.KeyboardModifier.NoModifier)
    gb.end_drag()
    lo, _hi = g.bbox(w.scene.get(box.id).shape)
    assert lo[0] > BOX_MIN[0] + 1.0
    assert lo[2] > BOX_MIN[2] + 1.0


def test_a_typed_distance_moves_it_exactly(sheet):
    w, _det, box = sheet
    gb = w.viewport.gumball
    px, py = _handle(w, "move", 1)
    assert gb.begin_drag(("move", 1), px, py, Qt.KeyboardModifier.NoModifier)
    gb.apply_scalar(25.0)
    gb.end_drag()
    lo, _hi = g.bbox(w.scene.get(box.id).shape)
    assert lo[2] == pytest.approx(BOX_MIN[2] + 25.0, abs=1e-6)


# --------------------------------------------------------- through the mouse

def test_a_press_on_a_handle_takes_it_rather_than_picking(sheet):
    w, _det, _box = sheet
    vp = w.viewport
    px, py = _handle(w, "move", 0)
    vp.mousePressEvent(_ev(QEvent.Type.MouseButtonPress, QPointF(px, py)))
    assert vp.gumball.drag is not None
    assert vp._press_pos is None, "not also the start of a selection band"


def test_a_press_off_the_handles_still_picks(sheet):
    w, det, _box = sheet
    vp = w.viewport
    lv = vp.layout_view
    pos = QPointF(*lv.paper_to_screen(det.x + 4.0, det.y + 4.0))
    vp.mousePressEvent(_ev(QEvent.Type.MouseButtonPress, pos))
    assert vp.gumball.drag is None
    assert vp._press_pos is not None


def test_the_mouse_drags_and_lets_go(sheet):
    w, _det, box = sheet
    vp = w.viewport
    px, py = _handle(w, "move", 0)
    vp.mousePressEvent(_ev(QEvent.Type.MouseButtonPress, QPointF(px, py)))
    vp.mouseMoveEvent(_ev(QEvent.Type.MouseMove, QPointF(px + 50.0, py)))
    vp.mouseReleaseEvent(_ev(QEvent.Type.MouseButtonRelease,
                             QPointF(px + 50.0, py),
                             Qt.MouseButton.NoButton))
    assert vp.gumball.drag is None, "let go at the end of a real drag"
    lo, _hi = g.bbox(w.scene.get(box.id).shape)
    assert lo[0] > BOX_MIN[0] + 1.0


def test_dragging_a_handle_leaves_the_detail_where_it_is(sheet):
    """The press is on the model, not on the frame it is seen in."""
    w, det, _box = sheet
    vp = w.viewport
    before = (det.x, det.y)
    px, py = _handle(w, "move", 0)
    vp.mousePressEvent(_ev(QEvent.Type.MouseButtonPress, QPointF(px, py)))
    vp.mouseMoveEvent(_ev(QEvent.Type.MouseMove, QPointF(px + 50.0, py)))
    vp.mouseReleaseEvent(_ev(QEvent.Type.MouseButtonRelease,
                             QPointF(px + 50.0, py),
                             Qt.MouseButton.NoButton))
    assert (det.x, det.y) == before


def test_hovering_lights_the_handle_under_the_cursor(sheet):
    w, _det, _box = sheet
    vp = w.viewport
    px, py = _handle(w, "move", 0)
    vp.mouseMoveEvent(_ev(QEvent.Type.MouseMove, QPointF(px, py),
                          Qt.MouseButton.NoButton))
    assert vp.gumball.hover == ("move", 0)


# ------------------------------------------------------------- and drawn on

def test_it_is_drawn_on_the_paper_it_is_seen_on(sheet):
    """Gumball geometry is built in the model, like everything a detail shows,
    so it comes back out through the window rather than landing on the sheet
    at the model's own numbers."""
    w, det, _box = sheet
    gb = w.viewport.gumball
    anchor, _axes = gb.anchor_and_axes()
    out = gb._paper(np.asarray([anchor], np.float32))
    assert out[0, :2] == pytest.approx(detail_project(det, anchor), abs=1e-4)
    assert out[0, 2] == pytest.approx(0.0)


def test_in_the_model_window_it_is_left_alone(sheet):
    w, _det, _box = sheet
    w.switch_space("model")
    gb = w.viewport.gumball
    anchor, _axes = gb.anchor_and_axes()
    pts = np.asarray([anchor], np.float32)
    assert gb._paper(pts) is pts


def test_the_sheet_paints_it(sheet):
    """Offscreen tests cannot run the GL path, so this is about the sheet
    being told to draw the gumball at all."""
    vp = type(sheet[0].viewport)
    sheet_branch = inspect.getsource(vp._paint_frame).split(
        'if self.space != "model":')[1]
    assert "_draw_gumball_in_detail" in sheet_branch
    assert "_update_gumball_readout" in sheet_branch
    assert "gumball.paint" in inspect.getsource(vp._draw_gumball_in_detail)


def test_the_readout_sits_by_the_anchor_in_the_detail(sheet):
    w, _det, _box = sheet
    gb = w.viewport.gumball
    px, py = _handle(w, "move", 0)
    gb.begin_drag(("move", 0), px, py, Qt.KeyboardModifier.NoModifier)
    gb.drag_to(px + 30.0, py, Qt.KeyboardModifier.NoModifier)
    text, (rx, ry) = gb.readout()
    ax, ay = _screen(w, gb.drag["anchor"])
    assert text
    assert (rx, ry) == (int(ax) + 18, int(ay) - 14)


# ------------------------------------------------------- what must not change

def test_the_model_window_keeps_its_own_gumball(sheet):
    w, _det, box = sheet
    w.switch_space("model")
    vp = w.viewport
    vp.camera.zoom_extents(g.bbox(box.shape), vp.width() / vp.height())
    gb = vp.gumball
    assert gb.active()
    anchor, axes = gb.anchor_and_axes()
    s = gb._size_world(anchor)
    scr = vp.camera.project([anchor + axes[0] * (SHAFT0 + CONE1) / 2 * s],
                            vp.width(), vp.height())[0]
    assert gb.hit_test(float(scr[0]), float(scr[1])) == ("move", 0)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
