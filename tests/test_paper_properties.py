"""The properties panel, for the geometry that lives on the paper.

Picking a border on a sheet said "No selection" in the panel, so there was
nowhere to change its name, its ink, its dash pattern or its weight — the three
things a border is ever fiddled with. The panel reads the model-space selection,
and a sheet pick is held by the layout view instead, so it had nothing to show.

Paper geometry is not a model object: it has no layer (the sheet is its own
ink), and it is measured in millimetres of paper whatever the document's units
are. So the rows on offer differ, and the panel says which world it is in.
"""

from __future__ import annotations

import pytest

from serpentine3d.app import MainWindow
from serpentine3d.core import geometry as g
from serpentine3d.core.layout import DetailView, Layout
from serpentine3d.ui.layout_view import LINE_VISIBLE

DET = {"x": 200.0, "y": 30.0, "w": 160.0, "h": 120.0,
       "scale_denom": 2.0, "target": [400.0, 250.0, 0.0]}


def _rect(a=(20.0, 20.0, 0.0), b=(120.0, 80.0, 0.0)):
    return g.make_rectangle(a, b)


@pytest.fixture
def sheet():
    """A window showing a sheet with one rectangle on the paper."""
    w = MainWindow()
    w.resize(1200, 800)
    lay = Layout(name="Sheet1")
    lay.details.append(DetailView(**DET))
    obj = lay.add(_rect(), name="Border")
    w.scene.layouts.append(lay)
    w.switch_space(lay.id)
    return w, w.properties, lay, obj


def _pick(w, *objs):
    """Select paper geometry the way a click does, panel and all."""
    lv = w.viewport.layout_view
    lv.selected = [("object", o) for o in objs]
    w.viewport.layoutSelectionChanged.emit()


# ------------------------------------------------------------- what it shows

def test_an_empty_sheet_still_says_no_selection(sheet):
    _w, panel, _lay, _obj = sheet
    assert panel.header.text() == "No selection"


def test_picking_paper_geometry_names_it(sheet):
    """The bug as reported: the panel sat on "No selection" while a rectangle
    on the sheet was plainly picked."""
    w, panel, _lay, obj = sheet
    _pick(w, obj)
    assert panel.header.text() == obj.name
    assert panel.name_edit.text() == obj.name
    assert panel.name_edit.isEnabled()


def test_the_type_says_which_world_it_is_in(sheet):
    w, panel, _lay, obj = sheet
    _pick(w, obj)
    assert panel.kind_label.text() == "Curve on paper"


def test_it_is_measured_in_millimetres_of_paper(sheet):
    """Paper is millimetres whatever the document's units are, so this is not
    the scene's length formatter."""
    w, panel, _lay, obj = sheet
    w.scene.units = "inches"
    _pick(w, obj)
    assert panel.measure_label.text() == "Length: 320.00 mm"


def test_two_of_them_only_get_counted(sheet):
    """And nothing is left showing one of the two's own values: a greyed-out
    "Dashed" reads as something they have in common."""
    w, panel, lay, obj = sheet
    other = lay.add(_rect((200.0, 200.0, 0.0), (260.0, 240.0, 0.0)))
    obj.linetype = "Dashed"
    _pick(w, obj)
    _pick(w, obj, other)
    assert panel.header.text() == "2 objects selected"
    assert not panel.name_edit.isEnabled()
    assert not panel.color_widget.isEnabled()
    assert panel.name_edit.text() == ""
    assert panel.linetype_combo.currentText() == ""
    assert panel.lineweight_edit.text() == ""
    _pick(w, other)                     # and the rows come back for one of them
    assert panel.linetype_combo.currentText() == "Continuous"
    assert panel.lineweight_edit.text() == "0.25"


# ------------------------------------------------------ which rows are on offer

def test_paper_geometry_has_no_layer_row(sheet):
    """It is not on a model layer, and a disabled combo showing someone else's
    layer would just invite the question."""
    w, panel, _lay, obj = sheet
    _pick(w, obj)
    assert panel.form.isRowVisible(panel.layer_combo) is False
    assert panel.form.isRowVisible(panel.linetype_combo) is True
    assert panel.form.isRowVisible(panel.lineweight_edit) is True


def test_a_model_object_keeps_the_rows_it_had(sheet):
    """Linetype and lineweight are the sheet's business; the model panel is
    left exactly as it was."""
    w, panel, _lay, _obj = sheet
    w.switch_space("model")
    assert panel.form.isRowVisible(panel.layer_combo) is True
    assert panel.form.isRowVisible(panel.linetype_combo) is False
    assert panel.form.isRowVisible(panel.lineweight_edit) is False


def test_leaving_the_sheet_lets_the_selection_go(sheet):
    w, panel, _lay, obj = sheet
    _pick(w, obj)
    w.switch_space("model")
    assert panel.header.text() == "No selection"


# --------------------------------------------------------------- editing it

def test_renaming_it(sheet):
    w, panel, _lay, obj = sheet
    _pick(w, obj)
    panel.name_edit.setText("Title block")
    panel._rename()
    assert obj.name == "Title block"


def test_renaming_it_is_one_undo(sheet):
    w, panel, _lay, obj = sheet
    _pick(w, obj)
    panel.name_edit.setText("Title block")
    panel._rename()
    w.history.undo()
    back = w.scene.layouts[0].objects[0]
    assert back.name == "Border"


def test_the_linetype_row_offers_the_patterns(sheet):
    w, panel, _lay, obj = sheet
    _pick(w, obj)
    names = [panel.linetype_combo.itemText(i)
             for i in range(panel.linetype_combo.count())]
    assert "Continuous" in names and "Dashed" in names
    assert panel.linetype_combo.currentText() == "Continuous"


def test_choosing_a_linetype_dashes_it(sheet):
    w, panel, _lay, obj = sheet
    _pick(w, obj)
    panel.linetype_combo.setCurrentText("Dashed")
    assert obj.linetype == "Dashed"
    w.history.undo()
    assert w.scene.layouts[0].objects[0].linetype == "Continuous"


def test_a_lineweight_is_typed_in_millimetres(sheet):
    w, panel, _lay, obj = sheet
    _pick(w, obj)
    assert panel.lineweight_edit.text() == "0.25"
    panel.lineweight_edit.setText("0.7")
    panel._change_lineweight()
    assert obj.lineweight == pytest.approx(0.7)


def test_a_lineweight_that_is_not_a_width_is_refused(sheet):
    """Nonsense goes back to what it was rather than making the border
    vanish."""
    w, panel, _lay, obj = sheet
    _pick(w, obj)
    for junk in ("hairline", "-1", ""):
        panel.lineweight_edit.setText(junk)
        panel._change_lineweight()
        assert obj.lineweight == pytest.approx(0.25)
    assert panel.lineweight_edit.text() == "0.25"


def test_the_colour_swatch_starts_at_the_sheet_ink(sheet):
    w, panel, _lay, obj = sheet
    _pick(w, obj)
    assert panel._ink_of(obj) == pytest.approx(LINE_VISIBLE[:3], abs=1e-6)
    assert panel.color_reset.text() == "By sheet"
    assert not panel.color_reset.isEnabled()


def test_giving_it_a_colour(sheet):
    w, panel, _lay, obj = sheet
    _pick(w, obj)
    panel._set_color((1.0, 0.0, 0.0))
    assert obj.color == pytest.approx((1.0, 0.0, 0.0))
    assert panel.color_reset.isEnabled()
    assert panel._ink_of(obj) == pytest.approx((1.0, 0.0, 0.0))


def test_putting_the_colour_back_to_the_sheet_ink(sheet):
    w, panel, _lay, obj = sheet
    _pick(w, obj)
    panel._set_color((1.0, 0.0, 0.0))
    panel._reset_color()
    assert obj.color is None
    w.history.undo()
    assert w.scene.layouts[0].objects[0].color == pytest.approx((1.0, 0.0, 0.0))


def test_an_edit_repaints_the_sheet(sheet):
    """Paper geometry is not in the scene's object table, so nothing else
    would notice it had changed."""
    w, panel, _lay, obj = sheet
    _pick(w, obj)
    before = w.scene.revision
    panel._set_color((0.0, 0.0, 1.0))
    assert w.scene.revision > before


def test_undo_shows_up_on_the_panel(sheet):
    """Undo swaps the whole sheet for a clone, so the pick does not survive it,
    and the panel has to notice: going on offering to rename an object that is
    no longer on the sheet would edit something nothing draws."""
    w, panel, _lay, obj = sheet
    _pick(w, obj)
    panel.name_edit.setText("Title block")
    panel._rename()
    assert panel.header.text() == "Title block"
    w.history.undo()
    assert w.scene.layouts[0].objects[0].name == "Border"
    assert panel.header.text() == "No selection"


# ------------------------------------------------------ the model still works

def test_a_model_object_is_shown_the_way_it_was(sheet):
    w, panel, _lay, _obj = sheet
    w.switch_space("model")
    box = w.scene.add(g.make_box((0, 0, 0), 10, 10, 10))
    w.selection.set([box.id])
    assert panel.header.text() == box.name
    assert panel.kind_label.text() == "Solid"
    assert panel.color_reset.text() == "By layer"
    assert panel.layer_combo.isEnabled()


def test_a_model_object_is_not_asked_for_a_lineweight(sheet):
    """A model object has no such field; the row is not for it."""
    w, panel, _lay, _obj = sheet
    w.switch_space("model")
    box = w.scene.add(g.make_box((0, 0, 0), 10, 10, 10))
    w.selection.set([box.id])
    assert panel.form.isRowVisible(panel.lineweight_edit) is False
