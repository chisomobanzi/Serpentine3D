"""`copy` on a sheet.

The command only knew how to copy model objects, so on bare paper it waited
for a selection no click there can make — the same way `delete` did. What is
picked on a sheet can be copied now: geometry, detail frames and annotations,
by an offset in paper millimetres, repeating until Enter the way the model
command does.

A copy is a new thing on the sheet and not a second name for the old one, so
it gets its own id and its own shape, and nothing mutable is shared with what
it was copied from.
"""

from __future__ import annotations

import pytest

from serpentine3d.app import MainWindow
from serpentine3d.core import geometry as g
from serpentine3d.core.layout import (DetailView, Layout, PaperObject,
                                      TextNote, paper_object_bounds)

DET = {"x": 20.0, "y": 30.0, "w": 160.0, "h": 120.0,
       "scale_denom": 2.0, "target": [0.0, 0.0, 0.0]}


@pytest.fixture
def sheet():
    w = MainWindow()
    w.resize(1200, 800)
    box = w.scene.add(g.make_box((0.0, 0.0, 0.0), 10.0, 10.0, 10.0))
    lay = Layout(name="Sheet1")
    lay.details.append(DetailView(**DET))
    lay.objects.append(PaperObject(
        shape=g.make_line((10.0, 10.0, 0.0), (90.0, 10.0, 0.0)), name="Rule"))
    lay.notes.append(TextNote(x=50.0, y=200.0, text="SECTION A-A"))
    w.scene.layouts.append(lay)
    w.switch_space(lay.id)
    lv = w.viewport.layout_view
    lv.fit()
    lv._fitted_for = lay.id
    lv.entered_detail = None
    said: list = []
    w.ctx.add_echo_listener(said.append)
    return w, lv, lay, box, said


def _copy(w, *points):
    w.run_command("copy")
    for p in points:
        w.processor.provide_text(p)
    w.processor.provide_text("")             # Enter finishes


# -- the geometry --------------------------------------------------------------

def test_copying_paper_geometry_leaves_two_of_it(sheet):
    w, lv, lay, _box, _said = sheet
    lv.selected = [("object", lay.objects[0])]
    _copy(w, "0,0,0", "0,40,0")
    assert len(lay.objects) == 2
    assert paper_object_bounds(lay.objects[0])[1] == pytest.approx(10.0)
    assert paper_object_bounds(lay.objects[1])[1] == pytest.approx(50.0)


def test_the_copy_is_its_own_object(sheet):
    w, lv, lay, _box, _said = sheet
    lv.selected = [("object", lay.objects[0])]
    _copy(w, "0,0,0", "0,40,0")
    first, second = lay.objects
    assert first.id != second.id
    assert first.shape is not second.shape
    assert second.name == first.name


def test_it_keeps_copying_until_you_say_stop(sheet):
    w, lv, lay, _box, _said = sheet
    lv.selected = [("object", lay.objects[0])]
    _copy(w, "0,0,0", "0,40,0", "0,80,0")
    ys = sorted(paper_object_bounds(o)[1] for o in lay.objects)
    assert ys == pytest.approx([10.0, 50.0, 90.0])


def test_every_copy_is_measured_from_the_same_base_point(sheet):
    """Not from the last copy: two 40mm hops land at 40 and 80, not 40 and
    120, which is what the model command does."""
    w, lv, lay, _box, _said = sheet
    lv.selected = [("object", lay.objects[0])]
    _copy(w, "0,0,0", "0,40,0", "0,80,0")
    assert len(lay.objects) == 3


# -- frames and annotations ----------------------------------------------------

def test_a_detail_frame_can_be_copied(sheet):
    w, lv, lay, _box, _said = sheet
    lv.selected = [("detail", lay.details[0])]
    _copy(w, "0,0,0", "200,0,0")
    assert len(lay.details) == 2
    first, second = lay.details
    assert second.x == pytest.approx(first.x + 200.0)
    assert second.y == pytest.approx(first.y)
    assert second.id != first.id
    assert second.scale_denom == first.scale_denom


def test_a_copied_frame_looks_where_the_original_looked(sheet):
    """Its target is a list, so a copy that shared it would swing both frames
    when either one was panned."""
    w, lv, lay, _box, _said = sheet
    lv.selected = [("detail", lay.details[0])]
    _copy(w, "0,0,0", "200,0,0")
    first, second = lay.details
    assert second.target == first.target
    assert second.target is not first.target


def test_a_locked_frame_is_copied_and_the_copy_is_still_locked(sheet):
    """Copying does not disturb the original, which is what the lock is for,
    and a copy of a locked frame is a locked frame."""
    w, lv, lay, _box, _said = sheet
    lay.details[0].locked = True
    lv.selected = [("detail", lay.details[0])]
    _copy(w, "0,0,0", "200,0,0")
    assert len(lay.details) == 2
    assert lay.details[1].locked


def test_an_annotation_can_be_copied(sheet):
    w, lv, lay, _box, _said = sheet
    lv.selected = [("note", lay.notes[0])]
    _copy(w, "0,0,0", "0,-30,0")
    assert len(lay.notes) == 2
    assert lay.notes[1].text == "SECTION A-A"
    assert lay.notes[1].y == pytest.approx(lay.notes[0].y - 30.0)
    assert lay.notes[1].id != lay.notes[0].id


def test_everything_picked_is_copied_at_once(sheet):
    w, lv, lay, _box, _said = sheet
    lv.selected = [("object", lay.objects[0]), ("note", lay.notes[0])]
    _copy(w, "0,0,0", "0,40,0")
    assert len(lay.objects) == 2
    assert len(lay.notes) == 2


# -- what it says and what it leaves behind ------------------------------------

def test_the_originals_stay_picked(sheet):
    """So a second `copy` copies what you were copying, not what you made."""
    w, lv, lay, _box, _said = sheet
    original = lay.objects[0]
    lv.selected = [("object", original)]
    _copy(w, "0,0,0", "0,40,0")
    assert lv.selected == [("object", original)]


def test_copying_on_a_sheet_can_be_undone(sheet):
    w, lv, lay, _box, _said = sheet
    lv.selected = [("object", lay.objects[0])]
    _copy(w, "0,0,0", "0,40,0")
    assert w.history.can_undo
    w.history.undo()
    assert len(w.scene.layouts[0].objects) == 1


def test_copy_says_so_rather_than_waiting_when_nothing_is_picked(sheet):
    w, _lv, _lay, _box, said = sheet
    w.run_command("copy")
    assert not w.processor.busy
    assert "picked" in said[-1].lower()


def test_copy_counts_what_it_made(sheet):
    w, lv, lay, _box, said = sheet
    lv.selected = [("object", lay.objects[0])]
    _copy(w, "0,0,0", "0,40,0")
    assert "1" in said[-1]


def test_the_model_is_untouched_by_a_copy_on_paper(sheet):
    w, lv, lay, _box, _said = sheet
    lv.selected = [("object", lay.objects[0])]
    _copy(w, "0,0,0", "0,40,0")
    assert len(w.scene.all()) == 1


# -- and through a detail ------------------------------------------------------

def test_copy_is_allowed_on_a_sheet(sheet):
    from serpentine3d.commands.base import resolve
    assert resolve("copy").space == "any"


def test_copy_in_a_detail_copies_the_model_object(sheet):
    w, lv, lay, box, _said = sheet
    lv.entered_detail = lay.details[0].id
    w.selection.set([box.id])
    _copy(w, "0,0,0", "50,0,0")
    assert len(w.scene.all()) == 2
    assert lay.objects == [lay.objects[0]]   # nothing landed on the paper
    xs = sorted(g.bbox(o.shape)[0][0] for o in w.scene.all())
    assert xs == pytest.approx([0.0, 50.0], abs=1e-4)
