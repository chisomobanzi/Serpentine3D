"""What a command on a sheet is talking about.

A sheet has two things on it a command could mean: the sheet's own geometry,
frames and annotations, and the model seen through a detail. Which one is meant
is answered by what is picked, not by which space happens to be showing.

`delete` never asked the sheet at all, so a border picked on a sheet and deleted
left the command waiting for a model selection that no click on paper can make.
`move` asked only the sheet, so a model object picked through a detail was told
that nothing was picked, when plainly something was.
"""

from __future__ import annotations

import pytest

from serpentine3d.app import MainWindow
from serpentine3d.core import geometry as g
from serpentine3d.core.layout import DetailView, Layout, PaperObject

DET = {"x": 20.0, "y": 30.0, "w": 160.0, "h": 120.0,
       "scale_denom": 2.0, "target": [0.0, 0.0, 0.0]}


@pytest.fixture
def sheet():
    """A sheet with a border on it and a box in the model, seen in a detail."""
    w = MainWindow()
    w.resize(1200, 800)
    box = w.scene.add(g.make_box((0.0, 0.0, 0.0), 10.0, 10.0, 10.0))
    lay = Layout(name="Sheet1")
    lay.details.append(DetailView(**DET))
    lay.objects.append(PaperObject(
        shape=g.make_line((10.0, 10.0, 0.0), (90.0, 10.0, 0.0)), name="Rule"))
    w.scene.layouts.append(lay)
    w.switch_space(lay.id)
    lv = w.viewport.layout_view
    lv.fit()
    lv._fitted_for = lay.id
    lv.entered_detail = None
    said: list = []
    w.ctx.add_echo_listener(said.append)
    return w, lv, lay, box, said


# -- deleting what is on the sheet ---------------------------------------------

def test_delete_removes_the_paper_geometry_that_is_picked(sheet):
    w, lv, lay, _box, said = sheet
    lv.selected = [("object", lay.objects[0])]
    w.run_command("delete")
    assert not w.processor.busy          # it did not sit waiting for a pick
    assert lay.objects == []
    assert "1" in said[-1]


def test_delete_removes_a_picked_detail(sheet):
    w, lv, lay, _box, _said = sheet
    lv.selected = [("detail", lay.details[0])]
    w.run_command("delete")
    assert lay.details == []


def test_deleting_from_a_sheet_can_be_undone(sheet):
    w, lv, lay, _box, _said = sheet
    lv.selected = [("object", lay.objects[0])]
    w.run_command("delete")
    assert lay.objects == []
    assert w.history.can_undo
    w.history.undo()
    assert len(w.scene.layouts[0].objects) == 1


def test_delete_leaves_the_model_alone_when_the_sheet_is_what_is_picked(sheet):
    w, lv, lay, _box, _said = sheet
    lv.selected = [("object", lay.objects[0])]
    w.run_command("delete")
    assert len(w.scene.all()) == 1


def test_delete_says_so_rather_than_waiting_when_nothing_is_picked(sheet):
    """Waiting is the worst answer: no click on bare paper can name a model
    object, so the command would never come back."""
    w, _lv, _lay, _box, said = sheet
    w.run_command("delete")
    assert not w.processor.busy
    assert "picked" in said[-1].lower()


# -- and the model, when the model is what is picked ---------------------------

def test_delete_in_a_detail_removes_the_model_object(sheet):
    w, lv, lay, box, _said = sheet
    lv.entered_detail = lay.details[0].id
    w.selection.set([box.id])
    w.run_command("delete")
    assert w.scene.all() == []
    assert len(lay.objects) == 1         # the sheet's own is untouched


def test_move_in_a_detail_moves_the_model_object(sheet):
    """The same question the other way round: `move` asked only the sheet."""
    w, lv, lay, box, _said = sheet
    lv.entered_detail = lay.details[0].id
    w.selection.set([box.id])
    w.run_command("move")
    w.processor.provide_text("0,0,0")
    w.processor.provide_text("50,0,0")
    assert not w.processor.busy
    lo, _hi = g.bbox(w.scene.get(box.id).shape)
    assert lo[0] == pytest.approx(50.0, abs=1e-4)


def test_delete_in_a_detail_still_asks_for_a_pick_when_there_is_none(sheet):
    """Inside a detail the model is what you are working on, so a command that
    wants objects waits to be given them — clicked through the frame, which is
    a pick that can actually be made. It is bare paper that has none."""
    w, lv, lay, _box, _said = sheet
    lv.entered_detail = lay.details[0].id
    w.run_command("delete")
    assert w.processor.busy


def test_bare_paper_means_the_sheet_even_with_a_model_pick_left_over(sheet):
    """A selection made in the model window survives switching to a sheet, and
    it is not what a click on bare paper could have meant."""
    w, lv, lay, box, _said = sheet
    w.selection.set([box.id])
    lv.selected = [("object", lay.objects[0])]
    w.run_command("delete")
    assert lay.objects == []
    assert len(w.scene.all()) == 1


def test_move_on_paper_still_moves_what_is_on_the_paper(sheet):
    w, lv, lay, _box, _said = sheet
    lv.selected = [("detail", lay.details[0])]
    w.run_command("move")
    w.processor.provide_text("0,0,0")
    w.processor.provide_text("10,0,0")
    assert lay.details[0].x == pytest.approx(DET["x"] + 10.0)


def test_a_sheet_with_nothing_picked_is_still_the_sheets_question(sheet):
    """Nothing picked anywhere means the sheet, since that is what is showing:
    the answer is to say what to pick, not to fall through to the model."""
    w, _lv, _lay, _box, said = sheet
    w.run_command("move")
    assert not w.processor.busy
    assert "picked" in said[-1].lower()
