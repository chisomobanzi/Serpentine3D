"""A detail's corners snap, dragged or picked (#129).

From the report: a detail's four corners resize it, "but with limited
accuracy". Dragging a grip never snapped and showed no marker, so there was
no telling a snapped corner from one dropped near it. And Scale or Scale1D on
a picked detail had no start or end points to grab: a click on the frame,
meant for a reference point, stepped into the detail instead and handed the
command a point in the model.

A command working on what is picked on the sheet now takes paper points
throughout, which snap to the frame's corners like any paper point. A dragged
grip, or a dragged item's grab point, lands on a snap the way a picked point
does, marker and all, and what is being dragged is not something to snap to.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from serpentine3d.core import geometry as g
from serpentine3d.core.layout import DetailView, Layout, PaperObject

FRAME = {"x": 40.0, "y": 40.0, "w": 150.0, "h": 100.0}
RULE_START, RULE_END = (230.0, 40.0), (300.0, 160.0)


@pytest.fixture
def sheet(_qapp):
    from serpentine3d.app import MainWindow
    w = MainWindow()
    w.set_view_layout("single")
    w.resize(1400, 900)
    w.show()
    w.scene.add(g.make_box((0, 0, 0), 40, 30, 20), name="Box")
    lay = Layout(name="Sheet")
    lay.details.append(DetailView(**FRAME, scale_denom=1.0,
                                  target=[20.0, 15.0, 10.0]))
    lay.objects.append(PaperObject(shape=g.make_polyline(
        [(*RULE_START, 0.0), (*RULE_END, 0.0)]), name="Rule"))
    w.scene.layouts.append(lay)
    w.switch_space(lay.id)
    QApplication.processEvents()
    vp = w.active_viewport
    lv = vp.layout_view
    lv.fit()
    vp.grid_snap = False
    _only(vp, "end")
    said: list = []
    w.ctx.add_echo_listener(said.append)
    yield w, vp, lv, lay, said
    w.processor.cancel()
    w.mark_saved()
    w.close()


def _only(vp, kind):
    vp.snaps.enabled = True
    for key in vp.snaps.types:
        vp.snaps.types[key] = key == kind


def _at(lv, x, y) -> QPoint:
    sx, sy = lv.paper_to_screen(x, y)
    return QPoint(round(sx), round(sy))


def _click(vp, lv, x, y):
    QTest.mouseClick(vp, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, _at(lv, x, y))
    QApplication.processEvents()


def _drag(vp, lv, start, end, *, hold=None):
    """Press at `start`, move to `end` by way of a step, and let go; `hold`
    is called while the button is still down."""
    QTest.mousePress(vp, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, _at(lv, *start))
    mid = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
    for at in (mid, end):
        QTest.mouseMove(vp, _at(lv, *at))
        QApplication.processEvents()
    if hold is not None:
        hold()
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier, _at(lv, *end))
    QApplication.processEvents()


def _pick_detail(w, lv, det):
    lv.selected = [("detail", det)]
    w.active_viewport.layoutSelectionChanged.emit()


# ------------------------------------------- commands keep to the paper

@pytest.mark.parametrize("command", ["scale", "scale1d", "scale2d", "move",
                                     "copy", "rotate", "mirror"])
def test_a_click_inside_the_frame_is_a_point_on_the_paper(sheet, command):
    """Not a step into the detail: the command is working on the frame."""
    w, vp, lv, lay, said = sheet
    det = lay.details[0]
    _pick_detail(w, lv, det)
    w.run_command(command)
    first = w.processor.request.prompt
    _click(vp, lv, det.x + 30.0, det.y + 30.0)
    assert lv.entered_detail is None
    assert not any("inside the detail" in line for line in said), said
    assert w.processor.request is None or w.processor.request.prompt != first
    assert w.ctx.last_point[:2] == pytest.approx(
        (det.x + 30.0, det.y + 30.0), abs=1.0)


def test_scale1d_takes_its_points_from_the_frames_corners(sheet):
    """Grabbed just inside the frame, the corners are what the points land
    on: base at the bottom-left, the reference stretched from the
    bottom-right out by half again."""
    w, vp, lv, lay, _said = sheet
    det = lay.details[0]
    _pick_detail(w, lv, det)
    w.run_command("scale1d")
    _click(vp, lv, det.x + 0.6, det.y + 0.6)
    _click(vp, lv, det.x + det.w - 0.6, det.y + 0.6)
    assert lv.entered_detail is None
    w.processor.provide((det.x + det.w * 1.5, det.y, 0.0))
    assert not w.processor.busy
    assert (det.x, det.w) == pytest.approx((FRAME["x"], FRAME["w"] * 1.5))
    assert det.h == pytest.approx(FRAME["h"])


# ----------------------------------------------------- dragging, snapped

def test_a_dragged_grip_lands_on_a_snap_and_shows_the_marker(sheet):
    w, vp, lv, lay, _said = sheet
    det = lay.details[0]
    _pick_detail(w, lv, det)
    live = {}
    _drag(vp, lv, (det.x + det.w, det.y + det.h),
          (RULE_END[0] - 1.2, RULE_END[1] + 0.9),
          hold=lambda: live.update(snap=vp._active_snap,
                                   drawn=vp._snap_to_draw()))
    assert (det.x + det.w, det.y + det.h) == pytest.approx(RULE_END)
    assert (det.x, det.y) == pytest.approx((FRAME["x"], FRAME["y"]))
    assert live["snap"] is not None and live["snap"][1] == "end"
    assert live["drawn"] is live["snap"], "no marker while dragging"
    assert vp._snap_to_draw() is None, "the marker outlived the drag"


def test_a_dragged_grip_does_not_stick_to_where_it_was(sheet):
    """Its own corners are not snaps: a frame dragged a little way would
    otherwise find the corner it is moving and stay there."""
    w, vp, lv, lay, _said = sheet
    det = lay.details[0]
    _pick_detail(w, lv, det)
    corner = (det.x + det.w, det.y + det.h)
    _drag(vp, lv, corner, (corner[0] + 25.0, corner[1] + 15.0))
    assert (det.x + det.w, det.y + det.h) == pytest.approx(
        (corner[0] + 25.0, corner[1] + 15.0), abs=1.0)


def test_a_dragged_item_is_carried_from_the_point_it_was_grabbed_by(sheet):
    """Grab the rule by its end and drop that end on the frame's corner."""
    _w, vp, lv, lay, _said = sheet
    rule = lay.objects[0]
    det = lay.details[0]
    lv.selected = [("object", rule)]
    _drag(vp, lv, (RULE_START[0] + 0.8, RULE_START[1] + 0.5),
          (det.x + det.w + 1.1, det.y + det.h - 0.9))
    start = g.curve_endpoints(rule.shape)[0]
    assert start[:2] == pytest.approx((det.x + det.w, det.y + det.h))


def test_with_snaps_off_a_grip_follows_the_cursor(sheet):
    w, vp, lv, lay, _said = sheet
    vp.snaps.enabled = False
    det = lay.details[0]
    _pick_detail(w, lv, det)
    to = (RULE_END[0] - 1.2, RULE_END[1] + 0.9)
    _drag(vp, lv, (det.x + det.w, det.y + det.h), to)
    assert (det.x + det.w, det.y + det.h) == pytest.approx(to, abs=0.5)
    assert vp._snap_to_draw() is None
