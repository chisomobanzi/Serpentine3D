"""Inside a detail, what you pick is the model, and the panel says so (#93).

Double-clicking a detail goes inside it, and the click before the double
one picks the detail on the sheet, as does the `detail` command that
placed it. Going inside left that pick behind, so it went on competing
with the model: a box picked through the detail could be moved and
changed, but Properties stayed on the detail, and Delete took the whole
detail off the sheet and left the box where it was.

Going into a detail now lets go of what was picked on the sheet. Inside
one, Properties shows what is picked in the model and Delete deletes it;
with nothing picked it shows the detail you are in, the way Rhino's does
for an active detail, so its scale and view can still be changed from
there. Coming out again takes the panel back to the sheet.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from serpentine3d.core import geometry as g
from serpentine3d.core.layout import DetailView, Layout, detail_project
from serpentine3d.ui.camera import STANDARD_VIEWS


@pytest.fixture
def sheet(_qapp):
    """A box in the model and a sheet with a top detail of it, picked the
    way the `detail` command leaves a detail it has just placed."""
    from serpentine3d.app import MainWindow
    w = MainWindow()
    w.set_view_layout("single")
    w.resize(1400, 900)
    w.show()
    box = w.scene.add(g.make_box((-20, -20, 0), 40, 40, 40), name="Box")
    az, el = STANDARD_VIEWS["top"]
    det = DetailView(x=20, y=40, w=180, h=150, azimuth=az, elevation=el,
                     target=[0.0, 0.0, 0.0], scale_denom=1.0,
                     display_mode="hidden")
    lay = Layout(name="Sheet")
    lay.details.append(det)
    w.scene.layouts.append(lay)
    w.switch_space(lay.id)
    QApplication.processEvents()
    vp = w.active_viewport
    lv = vp.layout_view
    lv.fit()
    lv.selected = [("detail", det)]
    vp.layoutSelectionChanged.emit()
    yield w, vp, lv, lay, det, box
    w.mark_saved()
    w.close()


def _at(lv, paper) -> QPoint:
    x, y = lv.paper_to_screen(*paper)
    return QPoint(int(round(x)), int(round(y)))


def _go_in(vp, lv, det):
    """Double-click the detail, away from the box, as a person would."""
    QTest.mouseDClick(vp, Qt.MouseButton.LeftButton,
                      Qt.KeyboardModifier.NoModifier,
                      _at(lv, (det.x + det.w * 0.9, det.y + det.h * 0.9)))
    QApplication.processEvents()
    assert lv._entered() is det, "the double-click did not go inside"


def _pick_box(vp, lv, det):
    """Click the top of the box, seen through the detail."""
    QTest.mouseClick(vp, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier,
                     _at(lv, detail_project(det, (5.0, 5.0, 40.0))))
    QApplication.processEvents()


def _heading(w):
    said = w.properties.describe("objects")
    return None if said is None else (said.kind, said.title)


def test_going_inside_lets_go_of_the_detail_picked_on_the_sheet(sheet):
    w, vp, lv, lay, det, box = sheet
    _go_in(vp, lv, det)
    assert lv.selected == [] and lv.corners == []


def test_a_box_picked_inside_is_what_properties_shows(sheet):
    w, vp, lv, lay, det, box = sheet
    _go_in(vp, lv, det)
    _pick_box(vp, lv, det)
    assert [o.id for o in w.selection.objects()] == [box.id]
    assert _heading(w) == ("Object", "Box")
    props = w.properties
    assert props.form.isRowVisible(props.layer_combo), \
        "the box's own rows are not the ones shown"
    assert not props.form.isRowVisible(props.scale_combo), \
        "the detail's rows are still shown"


def test_delete_inside_deletes_the_box_and_keeps_the_detail(sheet):
    w, vp, lv, lay, det, box = sheet
    _go_in(vp, lv, det)
    _pick_box(vp, lv, det)
    vp.setFocus()
    QTest.keyClick(vp, Qt.Key.Key_Delete)
    QApplication.processEvents()
    assert lay.details == [det], "Delete took the detail off the sheet"
    assert w.scene.get(box.id) is None, "the box picked inside is still there"


def test_with_nothing_picked_inside_the_panel_shows_the_detail(sheet):
    w, vp, lv, lay, det, box = sheet
    _go_in(vp, lv, det)
    assert w.selection.ids == []
    assert _heading(w) == ("Detail", "Top view")
    props = w.properties
    assert props.form.isRowVisible(props.scale_combo)
    assert "objects" in props.subjects()
    # and it is the detail you are in that its rows change
    props._set_scale("1:2")
    assert lv._entered().scale_denom == pytest.approx(2.0)


def test_letting_go_of_the_box_inside_brings_the_detail_back(sheet):
    w, vp, lv, lay, det, box = sheet
    _go_in(vp, lv, det)
    _pick_box(vp, lv, det)
    w.selection.clear()
    QApplication.processEvents()
    assert _heading(w) == ("Detail", "Top view")


def test_coming_out_takes_the_panel_back_to_the_sheet(sheet):
    w, vp, lv, lay, det, box = sheet
    _go_in(vp, lv, det)
    QTest.mouseClick(vp, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier,
                     _at(lv, (det.x + det.w + 40, det.y + det.h / 2)))
    QApplication.processEvents()
    assert lv._entered() is None
    assert _heading(w) is None


def test_switching_to_the_model_leaves_the_detail_behind(sheet):
    w, vp, lv, lay, det, box = sheet
    _go_in(vp, lv, det)
    w.switch_space("model")
    QApplication.processEvents()
    assert _heading(w) is None


def test_a_picked_layer_is_kept_when_you_go_inside(sheet):
    """Going into a detail is not picking something else: a layer you
    were looking at stays on show, with the detail one tab along."""
    w, vp, lv, lay, det, box = sheet
    lv.selected = []
    vp.layoutSelectionChanged.emit()
    layer = w.scene.layers.all()[0]
    panel = w.layers_panel
    panel.tree.clearSelection()
    panel._all_rows()[layer.id].setSelected(True)
    QApplication.processEvents()
    assert w.properties.shown() == "layers"
    _go_in(vp, lv, det)
    assert w.properties.shown() == "layers"
    assert w.properties.subjects() == ["objects", "layers"]


def test_the_status_bar_counts_the_model_as_soon_as_you_are_inside(sheet):
    """It already counts the model inside a detail; going in has to tell
    it so, or it goes on saying one detail is selected."""
    w, vp, lv, lay, det, box = sheet
    _go_in(vp, lv, det)
    assert "  0 selected  " in w.statusBar().currentMessage()
