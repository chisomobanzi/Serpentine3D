"""A named view on a sheet turns the detail you are in, or the one you picked
(#131).

Top, Front, Perspective and the rest turned the pane's model camera, which a
sheet does not show, so typed inside a detail they looked as if they did
nothing. On a sheet the detail is the camera you are looking through, as in
Rhino: typed or chosen from the pane's menu, the view turns that.
"""

from __future__ import annotations

from dataclasses import asdict
from itertools import product

import numpy as np
import pytest

from serpentine3d.app import MainWindow
from serpentine3d.core import geometry as g
from serpentine3d.core.layout import DetailView, Layout
from serpentine3d.ui.camera import STANDARD_VIEWS

VIEWS = ["top", "bottom", "front", "back", "right", "left", "isometric",
         "perspective"]
MENU_VIEWS = {"Perspective", "Isometric", "Top", "Bottom", "Front", "Back",
              "Right", "Left"}
# Aimed by hand, so that every named view is a change.
HAND = {"azimuth": 0.31, "elevation": 0.72}


@pytest.fixture
def sheet():
    w = MainWindow()
    w.resize(1200, 800)
    w.scene.add(g.make_box((0.0, 0.0, 0.0), 40.0, 30.0, 20.0))
    lay = Layout(name="Sheet1")
    for x in (20.0, 200.0):
        lay.details.append(DetailView(x=x, y=30.0, w=160.0, h=120.0,
                                      scale_denom=2.0,
                                      target=[20.0, 15.0, 10.0], **HAND))
    w.scene.layouts.append(lay)
    w.switch_space(lay.id)
    lv = w.viewport.layout_view
    lv.entered_detail = None
    said: list = []
    w.ctx.add_echo_listener(said.append)
    return w, lv, lay, said


def _camera(vp):
    vp.land_flight()
    cam = vp.camera
    return (cam.azimuth, cam.elevation, cam.projection, vp._view_name)


def _view_actions(w, vp) -> dict:
    return {a.text(): a for a in w._viewport_menu(vp).actions()
            if a.text() in MENU_VIEWS}


# ------------------------------------------------------- typed in a detail

@pytest.mark.parametrize("name", VIEWS)
def test_a_view_typed_inside_a_detail_turns_that_detail(sheet, name):
    w, lv, lay, _said = sheet
    det, other = lay.details
    lv.entered_detail = det.id
    left_be = asdict(other)
    kept = (det.x, det.y, det.w, det.h, list(det.target), det.scale_denom)
    w.run_command(name)
    assert not w.processor.busy
    assert (det.azimuth, det.elevation) == pytest.approx(STANDARD_VIEWS[name])
    assert det.perspective == (name == "perspective")
    assert (det.x, det.y, det.w, det.h, det.target, det.scale_denom) == kept
    assert asdict(other) == left_be


def test_the_sheet_stays_on_screen_and_the_model_camera_is_left_alone(sheet):
    w, lv, lay, said = sheet
    vp = w.viewport
    before = _camera(vp)
    lv.entered_detail = lay.details[0].id
    w.run_command("front")
    assert _camera(vp) == before
    assert vp.space == lay.id and w.space == lay.id
    assert lv.entered_detail == lay.details[0].id
    assert not any("model space" in line.lower() for line in said)
    assert any(line == "Front view in the detail." for line in said)


def test_turning_a_detail_is_one_undo_and_redo(sheet):
    w, lv, lay, _said = sheet
    det = lay.details[0]
    lv.entered_detail = det.id
    before = asdict(det)
    w.run_command("right")
    after = asdict(det)
    assert after != before
    w.history.undo()
    assert asdict(w.scene.layouts[0].details[0]) == before
    w.history.redo()
    assert asdict(w.scene.layouts[0].details[0]) == after


def test_a_view_the_detail_already_has_adds_no_undo_step(sheet):
    w, lv, lay, _said = sheet
    det = lay.details[0]
    lv.entered_detail = det.id
    w.run_command("left")
    steps = len(w.history._undo)
    w.run_command("left")
    assert len(w.history._undo) == steps


def test_a_locked_detail_keeps_its_view_and_says_why(sheet):
    w, lv, lay, said = sheet
    det = lay.details[0]
    det.locked = True
    lv.entered_detail = det.id
    before = asdict(det)
    camera = _camera(w.viewport)
    w.run_command("top")
    assert asdict(det) == before
    assert _camera(w.viewport) == camera
    assert any("locked" in line.lower() for line in said)
    assert any("detaillock" in line.lower() for line in said)


def test_perspective_stands_back_far_enough_to_show_the_model(sheet):
    """The camera distance a detail starts with would put the eye inside a
    model this size."""
    w, lv, lay, _said = sheet
    det = lay.details[0]
    lo, hi = (-500.0, -500.0, -500.0), (1500.0, 1500.0, 1500.0)
    w.scene.add(g.make_box(lo, 2000.0, 2000.0, 2000.0))
    lv.entered_detail = det.id
    w.run_command("perspective")
    proj, view = lv.detail_matrices(det, det.w * 4, det.h * 4)
    for point in product(*zip(lo, hi)):
        clip = proj @ view @ np.array([*point, 1.0])
        assert clip[3] > 0, "model corner ended behind the perspective camera"
        assert np.all(np.abs(clip[:3] / clip[3]) <= 1.00001), "model is clipped"


# ------------------------------------------------------------ bare paper

def test_on_bare_paper_the_detail_you_picked_turns(sheet):
    w, lv, lay, _said = sheet
    det, other = lay.details
    left_be = asdict(det)
    lv.selected = [("detail", other)]
    w.run_command("perspective")
    assert (other.azimuth, other.elevation) == pytest.approx(
        STANDARD_VIEWS["perspective"])
    assert other.perspective
    assert asdict(det) == left_be


def test_on_bare_paper_with_no_detail_picked_nothing_turns(sheet):
    w, _lv, lay, said = sheet
    before = [asdict(d) for d in lay.details]
    camera = _camera(w.viewport)
    w.run_command("top")
    assert [asdict(d) for d in lay.details] == before
    assert _camera(w.viewport) == camera
    assert w.space == lay.id
    assert any("double-click a detail" in line.lower() for line in said)


def test_two_picked_details_are_not_a_choice_between_them(sheet):
    w, lv, lay, _said = sheet
    before = [asdict(d) for d in lay.details]
    lv.selected = [("detail", d) for d in lay.details]
    w.run_command("front")
    assert [asdict(d) for d in lay.details] == before


# ------------------------------------------------------- the pane's menu

def test_the_pane_menu_ticks_the_details_view_and_turns_it(sheet):
    w, lv, lay, _said = sheet
    det = lay.details[0]
    det.azimuth, det.elevation = STANDARD_VIEWS["front"]
    lv.entered_detail = det.id
    camera = _camera(w.viewport)
    acts = _view_actions(w, w.viewport)
    assert set(acts) == MENU_VIEWS
    assert [n for n, a in acts.items() if a.isChecked()] == ["Front"]
    assert all(a.isEnabled() for a in acts.values())
    acts["Left"].trigger()
    assert (det.azimuth, det.elevation) == pytest.approx(STANDARD_VIEWS["left"])
    assert _camera(w.viewport) == camera
    assert w.viewport.space == lay.id


def test_with_no_detail_to_turn_the_menus_views_are_greyed(sheet):
    w, _lv, _lay, _said = sheet
    acts = _view_actions(w, w.viewport)
    assert set(acts) == MENU_VIEWS
    assert not any(a.isEnabled() for a in acts.values())
    assert not any(a.isChecked() for a in acts.values())


def test_a_locked_detail_greys_the_menus_views_but_still_says_its_own(sheet):
    w, lv, lay, _said = sheet
    det = lay.details[0]
    det.azimuth, det.elevation = STANDARD_VIEWS["top"]
    det.locked = True
    lv.entered_detail = det.id
    acts = _view_actions(w, w.viewport)
    assert not any(a.isEnabled() for a in acts.values())
    assert [n for n, a in acts.items() if a.isChecked()] == ["Top"]


def test_in_the_model_the_views_still_turn_the_camera(sheet):
    w, _lv, lay, said = sheet
    w.switch_space("model")
    vp = w.viewport
    w.run_command("front")
    vp.land_flight()
    assert (vp.camera.azimuth, vp.camera.elevation) == pytest.approx(
        STANDARD_VIEWS["front"])
    assert vp._view_name == "front"
    assert "Front view." in said
    assert all(d.azimuth == HAND["azimuth"] for d in lay.details)
