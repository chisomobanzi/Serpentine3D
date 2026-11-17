"""A locked detail keeps its view, and only its view (#130).

From the report: double-click a detail to fix a line, pan out of habit, and
the view has moved, with the notes beside it now pointing at nothing. Rhino's
answer is a lock on the detail's view: its camera and scale stay, while the
frame can still be moved, resized and deleted like anything on the sheet.
Serpentine's lock froze the frame as well, and lived only in a command.
"""

from __future__ import annotations

from dataclasses import asdict

import numpy as np
import pytest
from PySide6.QtWidgets import QCheckBox, QComboBox

from serpentine3d.app import MainWindow
from serpentine3d.core import geometry as g
from serpentine3d.core.layout import (
    DetailView,
    Layout,
    detail_project,
    move_sheet_item,
    nudge_detail_corners,
    transform_sheet_item,
)

FRAME = {"x": 10.0, "y": 10.0, "w": 150.0, "h": 100.0}
VIEW = {"scale_denom": 2.0, "target": [20.0, 15.0, 0.0]}
POINT = (32.0, 21.0, 0.0)        # a model point the detail shows


def _detail(**kw) -> DetailView:
    return DetailView(**{**FRAME, **VIEW, "locked": True, **kw})


def _view(det) -> tuple:
    return (det.azimuth, det.elevation, det.perspective, det.scale_denom)


# ------------------------------------------------------- the paper maths

def test_cropping_a_locked_detail_leaves_its_picture_where_it_was():
    """A corner shows more or less of the model. Nothing it already showed
    moves, so notes placed beside the drawing still point at it."""
    det = _detail()
    before, view = detail_project(det, POINT), _view(det)
    nudge_detail_corners(det, [0], 10.0, 5.0)
    assert (det.x, det.y, det.w, det.h) == pytest.approx((20, 15, 140, 95))
    assert detail_project(det, POINT) == pytest.approx(before)
    assert _view(det) == view


@pytest.mark.parametrize(("corners", "dx", "dy"), [
    ([2], -12.0, 7.0), ([3], -12.0, 7.0),
    ([1, 2], -12.0, 0.0), ([0, 3], 9.0, 0.0), ([0, 1], 0.0, 7.0),
])
def test_any_crop_leaves_the_picture_where_it_was(corners, dx, dy):
    det = _detail()
    before = detail_project(det, POINT)
    nudge_detail_corners(det, corners, dx, dy)
    assert detail_project(det, POINT) == pytest.approx(before)


def test_an_edge_slid_along_itself_carries_the_picture_that_way():
    """Both corners of the right edge go up, so the frame does too: that
    much is a move, and only the sideways part is a crop."""
    det = _detail()
    bx, by = detail_project(det, POINT)
    nudge_detail_corners(det, [1, 2], -12.0, 7.0)
    assert detail_project(det, POINT) == pytest.approx((bx, by + 7.0))


def test_moving_all_four_corners_carries_the_picture_along():
    det = _detail()
    bx, by = detail_project(det, POINT)
    nudge_detail_corners(det, [0, 1, 2, 3], 12.0, -4.0)
    assert (det.w, det.h) == pytest.approx((FRAME["w"], FRAME["h"]))
    assert detail_project(det, POINT) == pytest.approx((bx + 12.0, by - 4.0))


def test_a_locked_frame_moves_and_its_picture_goes_with_it():
    det = _detail()
    bx, by = detail_project(det, POINT)
    move_sheet_item("detail", det, 30.0, -5.0)
    assert (det.x, det.y) == pytest.approx((40.0, 5.0))
    assert detail_project(det, POINT) == pytest.approx((bx + 30.0, by - 5.0))


def test_a_locked_frame_scales_but_keeps_its_drawing_scale():
    det = _detail()
    view = _view(det)
    matrix = np.diag([2.0, 2.0, 1.0])
    assert transform_sheet_item("detail", det, matrix, 2.0)
    assert (det.x, det.y, det.w, det.h) == pytest.approx((20, 20, 300, 200))
    assert _view(det) == view


# -------------------------------------------------------------- the sheet

@pytest.fixture
def sheet():
    w = MainWindow()
    w.resize(1200, 800)
    w.scene.add(g.make_box((0.0, 0.0, 0.0), 40.0, 30.0, 20.0))
    lay = Layout(name="Sheet1")
    lay.details.append(DetailView(**FRAME, **VIEW))
    lay.details.append(DetailView(x=200.0, y=150.0, w=150.0, h=100.0, **VIEW))
    w.scene.layouts.append(lay)
    w.switch_space(lay.id)
    lv = w.viewport.layout_view
    lv.fit()
    lv._fitted_for = lay.id
    said: list = []
    w.ctx.add_echo_listener(said.append)
    return w, lv, lay, said


def _pick(w, *details):
    """Select details the way a click does, panel and all."""
    lv = w.viewport.layout_view
    lv.selected = [("detail", d) for d in details]
    w.viewport.layoutSelectionChanged.emit()


def _run(w, cmd, *texts):
    w.run_command(cmd)
    for t in texts:
        w.processor.provide_text(t)


def test_move_moves_a_locked_detail(sheet):
    w, lv, lay, said = sheet
    det = lay.details[0]
    det.locked = True
    lv.selected = [("detail", det)]
    _run(w, "move", "0,0", "15,10")
    assert (det.x, det.y) == pytest.approx((25.0, 20.0))
    assert "locked" not in said[-1].lower(), said


def test_the_gumball_takes_hold_of_a_locked_detail(sheet):
    _w, lv, lay, _said = sheet
    lay.details[0].locked = True
    lv.selected = [("detail", lay.details[0])]
    assert lv.gumball.active()


def test_inside_a_locked_detail_the_wheel_and_a_pan_change_nothing(sheet):
    _w, lv, lay, _said = sheet
    det = lay.details[0]
    det.locked = True
    lv.entered_detail = det.id
    before = asdict(det)
    lv.wheel(3.0, 300.0, 300.0)
    lv.drag(40.0, 25.0, orbit=False)
    lv.drag(40.0, 25.0, orbit=True)
    assert asdict(det) == before


def test_detailscale_leaves_a_locked_detail_at_its_scale(sheet):
    w, lv, lay, said = sheet
    det = lay.details[0]
    det.locked = True
    lv.entered_detail = det.id
    _run(w, "detailscale", "1:5")
    assert det.scale_denom == VIEW["scale_denom"]
    assert not w.processor.busy
    assert any("locked" in line.lower() for line in said), said


# ------------------------------------------------------------- Properties

def _lock_box(panel) -> QCheckBox:
    box = panel.findChild(QCheckBox, "detail_locked")
    assert box is not None, "no lock on Properties for a detail"
    return box


def _combo(panel, offers: str) -> QComboBox:
    return next(c for c in panel.findChildren(QComboBox)
                if offers in [c.itemText(i) for i in range(c.count())])


def test_properties_offers_the_lock_for_one_detail(sheet):
    w, _lv, lay, _said = sheet
    panel = w.properties
    _pick(w, lay.details[0])
    box = _lock_box(panel)
    assert not box.isHidden()
    assert not box.isChecked()
    _pick(w, *lay.details)
    assert box.isHidden()
    _pick(w)
    assert box.isHidden()


def test_ticking_the_lock_is_one_undo_step(sheet):
    w, _lv, lay, _said = sheet
    det = lay.details[0]
    _pick(w, det)
    _lock_box(w.properties).click()
    assert det.locked
    w.history.undo()
    assert not w.scene.layouts[0].details[0].locked
    w.history.redo()
    assert w.scene.layouts[0].details[0].locked


def test_a_locked_detail_greys_its_view_and_scale_in_properties(sheet):
    w, _lv, lay, _said = sheet
    det = lay.details[0]
    det.locked = True
    _pick(w, det)
    panel = w.properties
    view, scale = _combo(panel, "Perspective"), _combo(panel, "1:50")
    assert _lock_box(panel).isChecked()
    assert not view.isEnabled() and not scale.isEnabled()
    _lock_box(panel).click()
    assert not det.locked
    assert view.isEnabled() and scale.isEnabled()


def test_the_box_follows_the_detaillock_command(sheet):
    w, lv, lay, _said = sheet
    det = lay.details[0]
    lv.entered_detail = det.id
    w.properties.refresh()
    box = _lock_box(w.properties)
    assert not box.isChecked()
    w.run_command("detaillock")
    assert det.locked and box.isChecked()
