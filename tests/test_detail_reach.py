"""Reaching through a detail: snapping to the model, and picking it.

A detail you have stepped into shows the model, and both of the things you do
to model geometry with a mouse were answered by the paper instead. Object snap
searched through the model camera, which on a sheet is aimed at nothing you can
see, so nothing was ever near the cursor. And a press inside a detail asked
`layout_view.press`, which only knows the sheet's own items, so the model
objects in plain view could not be selected at all.

Both ask a camera the same two questions — where does this model point land on
screen, and what does this pixel look along — so both are answered by the same
detail-shaped camera.
"""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent

import serpentine3d.commands  # registers all commands  # noqa: F401
from serpentine3d.app import MainWindow
from serpentine3d.core import geometry as g
from serpentine3d.core.layout import DetailView, Layout, detail_project
from serpentine3d.ui.camera import STANDARD_VIEWS
from serpentine3d.ui.layout_view import DetailEye

BOX_MIN = (-100.0, -80.0, 0.0)
BOX_MAX = (100.0, 80.0, 60.0)
# a curve whose ends do not land on top of anything else in a front view
WIRE = ((10.0, 20.0, 40.0), (90.0, 20.0, 40.0))


@pytest.fixture
def sheet():
    """A front-view detail of a box and a wire, stepped into."""
    w = MainWindow()
    w.resize(1200, 800)
    box = w.scene.add(g.make_box(BOX_MIN, 200.0, 160.0, 60.0))
    wire = w.scene.add(g.make_line(*WIRE))
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
    return w, lay, det, box, wire


def _screen(w, det, model_pt, dx: float = 0.0, dy: float = 0.0) -> QPointF:
    """Where a detail shows a model point, `dx`/`dy` pixels off."""
    px, py = detail_project(det, model_pt)
    sx, sy = w.viewport.layout_view.paper_to_screen(px, py)
    return QPointF(sx + dx, sy + dy)


def _frame(w, det, fx: float, fy: float) -> QPointF:
    lv = w.viewport.layout_view
    return QPointF(*lv.paper_to_screen(det.x + det.w * fx,
                                       det.y + det.h * fy))


def _ev(kind, pos, mods=Qt.KeyboardModifier.NoModifier, buttons=None):
    return QMouseEvent(kind, pos, pos, Qt.MouseButton.LeftButton,
                       Qt.MouseButton.LeftButton if buttons is None
                       else buttons, mods)


def _click(w, pos, mods=Qt.KeyboardModifier.NoModifier):
    w.viewport.mousePressEvent(_ev(QEvent.Type.MouseButtonPress, pos, mods))
    w.viewport.mouseReleaseEvent(_ev(
        QEvent.Type.MouseButtonRelease, pos, mods, Qt.MouseButton.NoButton))


def _drag(w, start: QPointF, end: QPointF):
    w.viewport.mousePressEvent(_ev(QEvent.Type.MouseButtonPress, start))
    w.viewport.mouseMoveEvent(_ev(QEvent.Type.MouseMove, end))
    w.viewport.mouseReleaseEvent(_ev(
        QEvent.Type.MouseButtonRelease, end, buttons=Qt.MouseButton.NoButton))


# --------------------------------------------------- the detail as a camera

def test_the_eye_projects_where_a_pick_unprojects(sheet):
    """The two have to be inverses or a snap would not sit under the cursor
    that found it."""
    w, _lay, det, _box, _wire = sheet
    eye = DetailEye(w.viewport.layout_view, det)
    pos = _frame(w, det, 0.3, 0.65)
    pt = w.viewport.world_point_at(pos.x(), pos.y())
    vp = w.viewport
    scr = eye.project(np.asarray([pt], float), vp.width(), vp.height())
    assert scr[0, 0] == pytest.approx(pos.x(), abs=1e-6)
    assert scr[0, 1] == pytest.approx(pos.y(), abs=1e-6)


def test_nearer_the_viewer_is_less_deep(sheet):
    """Depth is what decides which of two things under the cursor was hit."""
    w, _lay, det, _box, _wire = sheet
    eye = DetailEye(w.viewport.layout_view, det)
    near, far = (0.0, -80.0, 30.0), (0.0, 80.0, 30.0)
    vp = w.viewport
    scr = eye.project(np.asarray([near, far], float), vp.width(), vp.height())
    assert scr[0, 2] > 0 and scr[1, 2] > 0
    assert scr[0, 2] < scr[1, 2]


def test_outside_the_frame_counts_as_behind(sheet):
    """A detail clips what it shows to its rectangle, so a point outside it is
    not under the cursor however close the paper says it came."""
    w, _lay, det, _box, _wire = sheet
    eye = DetailEye(w.viewport.layout_view, det)
    beyond = (0.0, 0.0, 30.0 + det.h * det.scale_denom)   # far above the frame
    vp = w.viewport
    scr = eye.project(np.asarray([beyond], float), vp.width(), vp.height())
    assert scr[0, 2] <= 0


def test_a_pixel_looks_along_the_view(sheet):
    w, _lay, det, _box, _wire = sheet
    eye = DetailEye(w.viewport.layout_view, det)
    pos = _frame(w, det, 0.4, 0.4)
    vp = w.viewport
    origin, direction = eye.ray_through(pos.x(), pos.y(), vp.width(),
                                        vp.height())
    assert direction == pytest.approx([0.0, 1.0, 0.0])   # front view: +y in
    on_plane = w.viewport.world_point_at(pos.x(), pos.y())
    # the ray starts back from the plane and reaches the pick on the way
    t = np.dot(np.asarray(on_plane) - origin, direction)
    assert t > 0
    assert origin + t * np.asarray(direction) == pytest.approx(on_plane,
                                                               abs=1e-6)


# --------------------------------------------------------------- object snap

def test_a_pick_snaps_to_model_geometry_through_a_detail(sheet):
    w, _lay, det, _box, _wire = sheet
    vp = w.viewport
    vp.point_space = "model"
    pt = vp.world_point_at(*_screen(w, det, WIRE[0], 3, -2).toTuple())
    assert pt == pytest.approx(WIRE[0], abs=1e-9)
    assert vp._active_snap is not None
    assert vp._active_snap[1] == "end"


def test_the_snap_reaches_off_the_plane_the_detail_looks_at(sheet):
    """Which is the whole point: the wire is 20mm behind the plane the picks
    land on, and snapping to its end gives you the end, not its shadow."""
    w, _lay, det, _box, _wire = sheet
    w.viewport.point_space = "model"
    pt = w.viewport.world_point_at(*_screen(w, det, WIRE[1], 2, 2).toTuple())
    assert pt[1] == pytest.approx(20.0)


def test_a_midpoint_is_offered_too(sheet):
    w, _lay, det, _box, _wire = sheet
    mid = tuple((a + b) / 2 for a, b in zip(*WIRE))
    w.viewport.point_space = "model"
    pt = w.viewport.world_point_at(*_screen(w, det, mid, 0, 0).toTuple())
    assert pt == pytest.approx(mid, abs=1e-9)
    assert w.viewport._active_snap[1] == "mid"


def test_a_snap_beats_the_grid(sheet):
    """The grid is where a point goes when nothing better is near it."""
    w, _lay, det, _box, _wire = sheet
    vp = w.viewport
    vp.point_space = "model"
    vp.grid_snap = True
    vp.grid_snap_step = 30.0
    pt = vp.world_point_at(*_screen(w, det, WIRE[0], 2, 0).toTuple())
    assert pt == pytest.approx(WIRE[0], abs=1e-9), \
        "the end of the wire, not the round number 20mm of grid away"


def test_nothing_near_the_cursor_still_lands_on_the_plane(sheet):
    w, _lay, det, _box, _wire = sheet
    vp = w.viewport
    vp.point_space = "model"
    pos = _frame(w, det, 0.05, 0.95)
    pt = vp.world_point_at(pos.x(), pos.y())
    assert vp._active_snap is None
    assert pt[1] == pytest.approx(0.0), "on the detail's own plane"


def test_snaps_off_means_off(sheet):
    w, _lay, det, _box, _wire = sheet
    vp = w.viewport
    vp.point_space = "model"
    vp.snaps.enabled = False
    pt = vp.world_point_at(*_screen(w, det, WIRE[0], 0, 0).toTuple())
    assert vp._active_snap is None
    assert pt[1] == pytest.approx(0.0)


def test_a_paper_command_snaps_to_nothing_in_the_model(sheet):
    """It is writing on the sheet, and a model corner is not a place on it."""
    w, _lay, det, _box, _wire = sheet
    vp = w.viewport
    vp.point_space = "paper"
    pos = _screen(w, det, WIRE[0], 0, 0)
    pt = vp.world_point_at(pos.x(), pos.y())
    assert pt[2] == 0.0
    assert pt[:2] == pytest.approx(
        w.viewport.layout_view.screen_to_paper(pos.x(), pos.y()))


def test_a_line_drawn_between_two_snaps_lands_on_them(sheet):
    """End to end: the exact model coordinates, out of two clicks on a sheet."""
    w, _lay, det, _box, _wire = sheet
    w.processor.run("line")
    for end in WIRE:
        pos = _screen(w, det, end, 2, -2)
        w.viewport.mousePressEvent(_ev(QEvent.Type.MouseButtonPress, pos))
    made = list(w.scene.objects.values())[-1]
    lo, hi = g.bbox(made.shape)
    assert lo == pytest.approx(WIRE[0], abs=1e-6)
    assert hi == pytest.approx(WIRE[1], abs=1e-6)


# ------------------------------------------------------------------ picking

def test_an_object_is_pickable_through_a_detail(sheet):
    w, _lay, det, box, _wire = sheet
    edge_pt = (0.0, -80.0, 60.0)             # top edge of the box, front-on
    pos = _screen(w, det, edge_pt)
    assert w.viewport.pick_object(pos.x(), pos.y()) == box.id


def test_a_curve_behind_the_plane_is_pickable_too(sheet):
    w, _lay, det, _box, wire = sheet
    mid = tuple((a + b) / 2 for a, b in zip(*WIRE))
    pos = _screen(w, det, mid)
    assert w.viewport.pick_object(pos.x(), pos.y()) == wire.id


def test_empty_space_inside_a_detail_picks_nothing(sheet):
    w, _lay, det, _box, _wire = sheet
    pos = _frame(w, det, 0.5, 0.97)
    assert w.viewport.pick_object(pos.x(), pos.y()) is None


def test_faces_answer_to_the_detail_display_mode(sheet):
    """A wireframe detail has no faces to hit, whatever the model window
    behind it is set to."""
    w, _lay, det, box, _wire = sheet
    w.viewport.display_mode = "shaded"
    middle = _screen(w, det, (-50.0, -80.0, 30.0))   # clear of every edge
    assert w.viewport.pick_object(middle.x(), middle.y()) is None
    det.display_mode = "shaded"
    assert w.viewport.pick_object(middle.x(), middle.y()) == box.id


def test_a_subobject_is_pickable_through_a_detail(sheet):
    w, _lay, det, box, _wire = sheet
    pos = _screen(w, det, (0.0, -80.0, 60.0))
    hit = w.viewport.pick_subobject(pos.x(), pos.y())
    assert hit is not None and hit[0] == box.id


def test_clicking_in_a_detail_selects_the_model_object(sheet):
    w, _lay, det, box, _wire = sheet
    _click(w, _screen(w, det, (0.0, -80.0, 60.0)))
    assert w.selection.ids == [box.id]
    assert w.viewport.layout_view.selected == [], "and nothing on the sheet"


def test_clicking_empty_space_in_a_detail_clears_the_selection(sheet):
    w, _lay, det, box, _wire = sheet
    w.selection.set([box.id])
    # a corner of the frame: past the end of the box, and outside the reach of
    # the gumball the selection puts at its centre
    _click(w, _frame(w, det, 0.03, 0.03))
    assert w.selection.ids == []


def test_clicking_in_a_detail_does_not_leave_it(sheet):
    w, _lay, det, _box, _wire = sheet
    _click(w, _screen(w, det, (0.0, -80.0, 60.0)))
    assert w.viewport.layout_view.entered_detail == det.id


def test_a_band_swept_inside_a_detail_selects_what_it_covers(sheet):
    w, _lay, det, box, wire = sheet
    _drag(w, _frame(w, det, 0.02, 0.02), _frame(w, det, 0.98, 0.98))
    assert set(w.selection.ids) == {box.id, wire.id}
    assert not w.viewport._box_active, "the band is gone once it is used"


def test_the_band_shows_while_it_is_swept(sheet):
    w, _lay, det, _box, _wire = sheet
    start, end = _frame(w, det, 0.1, 0.1), _frame(w, det, 0.8, 0.8)
    w.viewport.mousePressEvent(_ev(QEvent.Type.MouseButtonPress, start))
    w.viewport.mouseMoveEvent(_ev(QEvent.Type.MouseMove, end))
    assert w.viewport._box_active


def test_a_command_asking_for_objects_gets_them_through_a_detail(sheet):
    """`delete` and its like ask to be given objects, and inside a detail the
    objects to give it are the model's."""
    w, _lay, det, box, _wire = sheet
    w.processor.run("delete")
    assert w.processor.busy
    _click(w, _screen(w, det, (0.0, -80.0, 60.0)))
    assert w.selection.ids == [box.id]


# ----------------------------------------------------------- and it says so

def test_the_readout_counts_what_was_picked_in_the_detail(sheet):
    """A sheet counts the items picked on the paper, but inside a detail what
    is picked is the model's, and a readout still saying nothing is selected is
    what makes a working pick look broken."""
    w, _lay, det, box, _wire = sheet
    _click(w, _screen(w, det, (0.0, -80.0, 60.0)))
    assert w.selection.ids == [box.id]
    assert "1 selected" in w.statusBar().currentMessage()


def test_the_readout_still_counts_the_paper_outside_a_detail(sheet):
    w, _lay, det, _box, _wire = sheet
    w.viewport.layout_view.entered_detail = None
    _click(w, QPointF(*w.viewport.layout_view.paper_to_screen(det.x + 5,
                                                              det.y + 5)))
    assert "1 selected" in w.statusBar().currentMessage()


# ------------------------------------------------------- what must not change

def test_the_sheet_still_selects_its_own_items(sheet):
    """Outside the detail nothing has changed: the click leaves the detail,
    and the next one picks the sheet's own geometry."""
    w, _lay, det, _box, _wire = sheet
    lv = w.viewport.layout_view
    _click(w, QPointF(*lv.paper_to_screen(30.0, 30.0)))
    assert lv.entered_detail is None
    assert w.viewport._press_pos is None
    _click(w, QPointF(*lv.paper_to_screen(det.x + 5, det.y + 5)))
    assert lv.selected and lv.selected[0][0] == "detail"


def test_the_model_window_picks_through_its_own_camera(sheet):
    w, _lay, _det, box, _wire = sheet
    w.switch_space("model")
    vp = w.viewport
    vp.camera.zoom_extents((BOX_MIN, BOX_MAX), vp.width() / vp.height())
    scr = vp.camera.project(np.asarray([[0.0, -80.0, 60.0]]), vp.width(),
                            vp.height())
    assert vp.pick_object(float(scr[0, 0]), float(scr[0, 1])) == box.id


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
