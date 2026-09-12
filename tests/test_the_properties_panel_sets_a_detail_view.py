"""A placed detail's view is editable beside its scale, without a command."""

from dataclasses import asdict
from itertools import product

import numpy as np
import pytest
from PySide6.QtWidgets import QComboBox

from serpentine3d.core import geometry as g
from serpentine3d.ui.camera import STANDARD_VIEWS
from tests.test_the_properties_panel_sets_a_detail_scale import (
    sheet, _items, _pick, _scale_combo,
)

VIEWS = ["Top", "Front", "Right", "Left", "Back", "Bottom", "Perspective"]


def _view_combo(panel):
    for combo in panel.findChildren(QComboBox):
        if set(VIEWS) <= set(_items(combo)):
            return combo
    return None


def _control(panel):
    combo = _view_combo(panel)
    assert combo is not None, "no View control on Properties for a selected detail"
    assert not combo.isHidden()
    return combo


@pytest.mark.parametrize("name", VIEWS)
def test_selected_detail_view_can_be_changed_without_a_command(sheet, name):
    w, panel, lay = sheet
    det = lay.details[0]
    _pick(w, det)
    combo = _control(panel)
    preserved = (det.x, det.y, det.w, det.h, list(det.target), det.scale_denom)
    combo.setCurrentText(name)
    assert (det.azimuth, det.elevation) == pytest.approx(STANDARD_VIEWS[name.lower()])
    assert det.perspective == (name == "Perspective")
    assert (det.x, det.y, det.w, det.h, det.target, det.scale_denom) == preserved
    assert not w.processor.busy
    if name != "Perspective":
        scale = _scale_combo(panel)
        assert scale is not None and scale.currentText() == "1:2"
        scale.setCurrentText("1:50")
        assert det.scale_denom == 50


def test_view_edit_is_one_undo_and_redo(sheet):
    w, panel, lay = sheet
    det = lay.details[0]
    before = asdict(det)
    _pick(w, det)
    _control(panel).setCurrentText("Front")
    after = asdict(det)
    assert before != after
    w.history.undo()
    assert asdict(w.scene.layouts[0].details[0]) == before
    w.history.redo()
    assert asdict(w.scene.layouts[0].details[0]) == after


@pytest.mark.parametrize("name", VIEWS)
def test_refresh_displays_the_selected_details_existing_view_without_editing(sheet, name):
    w, panel, lay = sheet
    det = lay.details[1]
    det.azimuth, det.elevation = STANDARD_VIEWS[name.lower()]
    det.perspective = name == "Perspective"
    before = asdict(det)
    _pick(w, lay.details[0])
    _control(panel)
    _pick(w, det)
    assert _control(panel).currentText() == name
    assert asdict(det) == before
    assert _scale_combo(panel).currentText() == det.scale_text()


def test_nonstandard_camera_displays_custom_and_survives_refresh(sheet):
    w, panel, lay = sheet
    det = lay.details[0]
    det.azimuth, det.elevation = 0.31, 0.72
    before = asdict(det)
    _pick(w, det)
    assert _control(panel).currentText() == "Custom"
    panel.refresh()
    assert asdict(det) == before
    _control(panel).setCurrentText("Top")
    assert (det.azimuth, det.elevation) == pytest.approx(STANDARD_VIEWS["top"])


def test_view_control_only_appears_for_a_single_selected_detail(sheet):
    w, panel, lay = sheet
    _pick(w, lay.details[0])
    combo = _control(panel)
    _pick(w)
    assert combo.isHidden()
    _pick(w, *lay.details)
    assert combo.isHidden()
    obj = w.scene.add(g.make_box((0, 0, 0), 10, 20, 30))
    w.switch_space("model")
    w.selection.set([obj.id])
    panel.refresh()
    assert combo.isHidden()


def test_switching_to_perspective_stands_back_to_show_the_model(sheet):
    w, panel, lay = sheet
    det = lay.details[0]
    # The default camera distance of 60 would put the eye inside this model.
    lo, hi = (-500, -500, -500), (1500, 1500, 1500)
    w.scene.add(g.make_box(lo, 2000, 2000, 2000))
    target = list(det.target)
    _pick(w, det)
    _control(panel).setCurrentText("Perspective")
    assert det.target == target
    proj, view = w.viewport.layout_view.detail_matrices(det, det.w * 4, det.h * 4)
    for point in product(*zip(lo, hi)):
        clip = proj @ view @ np.array([*point, 1.0])
        assert clip[3] > 0, "model corner ended behind the perspective camera"
        assert np.all(np.abs(clip[:3] / clip[3]) <= 1.00001), "model is clipped"
