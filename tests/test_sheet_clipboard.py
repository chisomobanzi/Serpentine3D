"""Ctrl+C and Ctrl+V on a sheet.

Copy and paste only knew about model objects, so on bare paper Ctrl+C either
did nothing or quietly took a model selection left over from before, and there
was no way to carry a title block from one sheet to the next.

The two halves ask different questions, and that is deliberate. Copy asks
where you are, because a sheet has two things on it that could be meant.
Paste asks the clipboard, because what it is holding is not in doubt — only
where to put it, and there is one answer to that.
"""

from __future__ import annotations

import pytest

from serpentine3d.app import MainWindow
from serpentine3d.core import geometry as g
from serpentine3d.core.layout import (DetailView, Layout, PaperObject,
                                      TextNote, paper_object_bounds)

DET = {"x": 20.0, "y": 30.0, "w": 160.0, "h": 120.0,
       "scale_denom": 2.0, "target": [0.0, 0.0, 0.0]}


def _layout(name: str) -> Layout:
    lay = Layout(name=name)
    lay.details.append(DetailView(**DET))
    lay.objects.append(PaperObject(
        shape=g.make_line((10.0, 10.0, 0.0), (90.0, 10.0, 0.0)), name="Rule"))
    lay.notes.append(TextNote(x=50.0, y=200.0, text="SECTION A-A"))
    return lay


@pytest.fixture
def sheets():
    """Two sheets, so that pasting somewhere else can be asked about."""
    w = MainWindow()
    w.resize(1200, 800)
    box = w.scene.add(g.make_box((0.0, 0.0, 0.0), 10.0, 10.0, 10.0))
    one, two = _layout("Sheet1"), _layout("Sheet2")
    two.objects.clear()
    two.notes.clear()
    two.details.clear()
    w.scene.layouts += [one, two]
    w.switch_space(one.id)
    lv = w.viewport.layout_view
    lv.fit()
    lv._fitted_for = one.id
    lv.entered_detail = None
    said: list = []
    w.ctx.add_echo_listener(said.append)
    return w, lv, one, two, box, said


# -- copying what is on the sheet ----------------------------------------------

def test_copy_takes_the_sheet_pick_not_the_model_one(sheets):
    w, lv, one, _two, box, _said = sheets
    w.selection.set([box.id])            # left over from the model window
    lv.selected = [("object", one.objects[0])]
    w._copy_selected()
    w._paste()
    assert len(one.objects) == 2
    assert len(w.scene.all()) == 1


def test_pasting_puts_the_item_back_on_the_sheet(sheets):
    w, lv, one, _two, _box, _said = sheets
    lv.selected = [("object", one.objects[0])]
    w._copy_selected()
    w._paste()
    first, second = one.objects
    assert second.id != first.id
    assert second.name == first.name
    assert paper_object_bounds(second) == pytest.approx(
        paper_object_bounds(first))


def test_pasting_twice_makes_two_of_it(sheets):
    w, lv, one, _two, _box, _said = sheets
    lv.selected = [("object", one.objects[0])]
    w._copy_selected()
    w._paste()
    w._paste()
    assert len(one.objects) == 3
    assert len({o.id for o in one.objects}) == 3


def test_what_is_pasted_is_what_is_picked_afterwards(sheets):
    """So it can be moved into place at once, and so you can see it landed
    on top of what it was copied from."""
    w, lv, one, _two, _box, _said = sheets
    lv.selected = [("object", one.objects[0])]
    w._copy_selected()
    w._paste()
    assert lv.selected == [("object", one.objects[1])]


def test_everything_picked_travels_together(sheets):
    w, lv, one, _two, _box, _said = sheets
    lv.selected = [("object", one.objects[0]), ("note", one.notes[0]),
                   ("detail", one.details[0])]
    w._copy_selected()
    w._paste()
    assert (len(one.objects), len(one.notes), len(one.details)) == (2, 2, 2)


# -- and onto another sheet ----------------------------------------------------

def test_a_title_block_can_be_carried_to_the_next_sheet(sheets):
    w, lv, one, two, _box, _said = sheets
    lv.selected = [("object", one.objects[0]), ("note", one.notes[0])]
    w._copy_selected()
    w.switch_space(two.id)
    w.viewport.layout_view.entered_detail = None
    w._paste()
    assert len(two.objects) == 1
    assert len(two.notes) == 1
    assert len(one.objects) == 1         # the sheet it came from is untouched


def test_a_pasted_frame_keeps_its_scale_and_looks_where_it_looked(sheets):
    w, lv, one, two, _box, _said = sheets
    lv.selected = [("detail", one.details[0])]
    w._copy_selected()
    w.switch_space(two.id)
    w.viewport.layout_view.entered_detail = None
    w._paste()
    src, dup = one.details[0], two.details[0]
    assert dup.scale_denom == src.scale_denom
    assert dup.target == src.target
    assert dup.target is not src.target  # a shared list would swing both
    assert dup.id != src.id


def test_the_clipboard_survives_the_original_being_deleted(sheets):
    """It holds a copy, not a way back to the thing copied."""
    w, lv, one, _two, _box, _said = sheets
    lv.selected = [("object", one.objects[0])]
    w._copy_selected()
    lv.selected = [("object", one.objects[0])]
    lv.delete_selected()
    assert one.objects == []
    w._paste()
    assert len(one.objects) == 1
    assert one.objects[0].name == "Rule"


def test_pasting_on_a_sheet_can_be_undone(sheets):
    w, lv, one, _two, _box, _said = sheets
    lv.selected = [("object", one.objects[0])]
    w._copy_selected()
    w._paste()
    assert len(one.objects) == 2
    w.history.undo()
    assert len(w.scene.layouts[0].objects) == 1


# -- the two spaces stay apart -------------------------------------------------

def test_copy_in_a_detail_takes_the_model_object(sheets):
    w, lv, one, _two, box, _said = sheets
    lv.entered_detail = one.details[0].id
    w.selection.set([box.id])
    w._copy_selected()
    w._paste()
    assert len(w.scene.all()) == 2
    assert len(one.objects) == 1         # nothing landed on the paper


def test_model_objects_pasted_from_a_sheet_go_to_the_model_and_say_so(sheets):
    """Otherwise they arrive somewhere you cannot see from bare paper, and
    the paste looks like it did nothing."""
    w, _lv, one, _two, box, said = sheets
    w.viewport.set_space("model")
    w.selection.set([box.id])
    w._copy_selected()
    w.switch_space(one.id)
    w.viewport.layout_view.entered_detail = None
    w._paste()
    assert len(w.scene.all()) == 2
    assert len(one.objects) == 1
    assert "model" in said[-1].lower()


def test_sheet_items_pasted_in_the_model_say_where_they_can_go(sheets):
    w, lv, one, _two, _box, said = sheets
    lv.selected = [("object", one.objects[0])]
    w._copy_selected()
    w.viewport.set_space("model")
    w._paste()
    assert len(w.scene.all()) == 1       # nothing became a model object
    assert len(one.objects) == 1
    assert "sheet" in said[-1].lower()


def test_copying_nothing_leaves_the_clipboard_alone(sheets):
    w, lv, one, _two, _box, _said = sheets
    lv.selected = [("object", one.objects[0])]
    w._copy_selected()
    lv.selected = []
    w._copy_selected()                   # nothing picked: not a way to empty it
    w._paste()
    assert len(one.objects) == 2
