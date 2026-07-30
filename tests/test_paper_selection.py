"""Picking the geometry that lives on the paper.

Notes, dimensions, hatches and detail frames could all be clicked on a sheet.
Paper geometry — the border, the bubble, the north arrow — could not: it was
drawn and then forgotten, absent from the pools the sheet picks out of, so a
click on a line you had just drawn selected nothing and Delete had nothing to
take. It is a shape, so it is picked by its ink the way a curve is in the
model, not by the area it happens to enclose.
"""

from __future__ import annotations

import pytest

from serpentine3d.app import MainWindow
from serpentine3d.core import geometry as g
from serpentine3d.core.layout import (
    DetailView, Layout, TextNote, move_paper_object, paper_object_at,
    paper_object_bounds,
)

DET = {"x": 200.0, "y": 30.0, "w": 160.0, "h": 120.0,
       "scale_denom": 2.0, "target": [400.0, 250.0, 0.0]}


def _rect(a=(20.0, 20.0, 0.0), b=(120.0, 80.0, 0.0)):
    return g.make_rectangle(a, b)


@pytest.fixture
def bare_sheet():
    lay = Layout(name="Sheet1")
    obj = lay.add(_rect(), name="Border")
    return lay, obj


@pytest.fixture
def sheet():
    """A window on a sheet, so screen pixels and paper millimetres both work."""
    w = MainWindow()
    w.resize(1200, 800)
    lay = Layout(name="Sheet1")
    lay.details.append(DetailView(**DET))
    obj = lay.add(_rect(), name="Border")
    w.scene.layouts.append(lay)
    w.viewport.space = lay.id
    lv = w.viewport.layout_view
    lv.fit()
    lv._fitted_for = lay.id
    return w, lv, lay, obj


# ------------------------------------------------------- what is under a point

def test_a_point_on_the_ink_finds_the_object(bare_sheet):
    lay, obj = bare_sheet
    assert paper_object_at(lay, 70.0, 20.0) is obj      # on the bottom side


def test_empty_paper_finds_nothing(bare_sheet):
    lay, _obj = bare_sheet
    assert paper_object_at(lay, 300.0, 200.0) is None


def test_the_inside_of_a_rectangle_is_not_the_rectangle(bare_sheet):
    """A curve is picked by its ink, the same as in the model. Otherwise a
    border would swallow every click on the page it frames."""
    lay, _obj = bare_sheet
    assert paper_object_at(lay, 70.0, 50.0) is None


def test_tolerance_is_the_caller_s_to_widen(bare_sheet):
    lay, obj = bare_sheet
    assert paper_object_at(lay, 70.0, 23.0, tol=0.5) is None
    assert paper_object_at(lay, 70.0, 23.0, tol=4.0) is obj


def test_the_topmost_object_wins(bare_sheet):
    """Drawn last is drawn on top, so it is what a click means."""
    lay, first = bare_sheet
    second = lay.add(_rect(), name="Twin")
    assert first is not second
    assert paper_object_at(lay, 70.0, 20.0) is second


# --------------------------------------------------------------- its extent

def test_bounds_come_from_the_geometry(bare_sheet):
    _lay, obj = bare_sheet
    assert paper_object_bounds(obj) == pytest.approx((20.0, 20.0, 120.0, 80.0),
                                                     abs=1e-6)


# ------------------------------------------------------------------ moving it

def test_moving_it_moves_the_shape(bare_sheet):
    """Not an x/y offset kept alongside: paper geometry has no such field, so
    the move is a real translation and the shape it is asked about after is a
    different shape."""
    _lay, obj = bare_sheet
    before = obj.shape
    move_paper_object(obj, 10.0, -5.0)
    assert obj.shape is not before
    assert paper_object_bounds(obj) == pytest.approx((30.0, 15.0, 130.0, 75.0),
                                                     abs=1e-6)


# ------------------------------------------------------ clicking on the sheet

def test_clicking_paper_geometry_selects_it(sheet):
    """The bug as reported: a click on a rectangle on the sheet selected
    nothing at all."""
    _w, lv, _lay, obj = sheet
    sx, sy = lv.paper_to_screen(70.0, 20.0)
    assert lv.press(sx, sy) is True
    assert lv.selected == [("object", obj)]


def test_clicking_empty_paper_lets_it_go(sheet):
    _w, lv, _lay, obj = sheet
    lv.selected = [("object", obj)]
    sx, sy = lv.paper_to_screen(70.0, 200.0)
    lv.press(sx, sy)
    assert lv.selected == []


def test_shift_adds_a_second_object_and_takes_it_back_off(sheet):
    _w, lv, lay, obj = sheet
    other = lay.add(_rect((200.0, 200.0, 0.0), (260.0, 240.0, 0.0)), name="Bar")
    lv.press(*lv.paper_to_screen(70.0, 20.0))
    lv.release_drag()
    lv.press(*lv.paper_to_screen(230.0, 200.0), add=True)
    lv.release_drag()
    assert lv.selected == [("object", obj), ("object", other)]
    lv.press(*lv.paper_to_screen(230.0, 200.0), add=True)
    lv.release_drag()
    assert lv.selected == [("object", obj)]


def test_a_note_on_top_of_a_line_is_still_the_note(sheet):
    """Annotations are painted over the geometry, so they are picked first."""
    _w, lv, lay, _obj = sheet
    note = TextNote(x=70.0, y=20.0, text="A", height=5.0)
    lay.notes.append(note)
    sx, sy = lv.paper_to_screen(71.0, 21.0)
    lv.press(sx, sy)
    assert lv.selected == [("note", note)]


def test_a_line_over_a_detail_is_the_line_not_the_detail(sheet):
    """A bubble drawn on top of a view is meant to be grabbed, and the frame
    under it is the coarser thing — same order as the paint."""
    _w, lv, lay, _obj = sheet
    det = lay.details[0]
    bubble = lay.add(_rect((det.x + 10, det.y + 10, 0.0),
                           (det.x + 40, det.y + 40, 0.0)), name="Bubble")
    sx, sy = lv.paper_to_screen(det.x + 25, det.y + 10)
    lv.press(sx, sy)
    assert lv.selected == [("object", bubble)]


def test_the_detail_still_wins_where_no_geometry_is(sheet):
    _w, lv, lay, _obj = sheet
    det = lay.details[0]
    sx, sy = lv.paper_to_screen(det.x + 80, det.y + 60)
    lv.press(sx, sy)
    assert lv.selected == [("detail", det)]


def test_a_band_takes_paper_geometry_too(sheet):
    _w, lv, _lay, obj = sheet
    x0, y0 = lv.paper_to_screen(10.0, 10.0)
    x1, y1 = lv.paper_to_screen(130.0, 90.0)
    lv.press(x0, y0)                      # empty paper: starts a band
    lv.drag_selected(x1, y1)
    lv.release_drag()
    assert ("object", obj) in lv.selected


def test_a_crossing_band_inside_a_border_leaves_the_border_alone(sheet):
    """A bounding box would say yes to this — a border's box is the whole page,
    so every band anywhere on the sheet would drag the border along with it."""
    _w, lv, lay, obj = sheet
    inner = lay.add(_rect((40.0, 40.0, 0.0), (60.0, 60.0, 0.0)), name="Blob")
    x1, y1 = lv.paper_to_screen(70.0, 70.0)
    x0, y0 = lv.paper_to_screen(30.0, 30.0)
    lv.press(x1, y1)                      # right to left: crossing
    lv.drag_selected(x0, y0)
    lv.release_drag()
    assert ("object", inner) in lv.selected
    assert ("object", obj) not in lv.selected


def test_a_crossing_band_over_the_ink_takes_it(sheet):
    _w, lv, _lay, obj = sheet
    x1, y1 = lv.paper_to_screen(40.0, 30.0)     # straddles the bottom side
    x0, y0 = lv.paper_to_screen(30.0, 10.0)
    lv.press(x1, y1)
    lv.drag_selected(x0, y0)
    lv.release_drag()
    assert ("object", obj) in lv.selected


def test_a_window_band_must_enclose_the_whole_object(sheet):
    _w, lv, _lay, obj = sheet
    x0, y0 = lv.paper_to_screen(10.0, 10.0)
    x1, y1 = lv.paper_to_screen(70.0, 90.0)      # cuts it in half
    lv.press(x0, y0)
    lv.drag_selected(x1, y1)
    lv.release_drag()
    assert ("object", obj) not in lv.selected


# ------------------------------------------------------------ dragging it about

def test_dragging_a_selected_object_moves_it(sheet):
    _w, lv, _lay, obj = sheet
    sx, sy = lv.paper_to_screen(70.0, 20.0)
    lv.press(sx, sy)
    lv.drag_selected(*lv.paper_to_screen(80.0, 25.0))
    lv.release_drag()
    assert paper_object_bounds(obj) == pytest.approx((30.0, 25.0, 130.0, 85.0),
                                                     abs=1e-4)


def test_typed_coordinates_move_it_the_same_way(sheet):
    _w, lv, _lay, obj = sheet
    lv.selected = [("object", obj)]
    assert lv.move_selected(10.0, -5.0) == 1
    assert paper_object_bounds(obj) == pytest.approx((30.0, 15.0, 130.0, 75.0),
                                                     abs=1e-6)


# ----------------------------------------------------------------- deleting it

def test_delete_takes_it_off_the_sheet(sheet):
    _w, lv, lay, obj = sheet
    lv.selected = [("object", obj)]
    assert lv.delete_selected() is True
    assert obj not in lay.objects
    assert lv.selected == []


def test_delete_is_one_undo(sheet):
    """Undo swaps in a clone of the sheet, so ask the scene, not the old
    object."""
    w, lv, _lay, obj = sheet
    lv.selected = [("object", obj)]
    lv.delete_selected()
    assert w.history.can_undo
    w.history.undo()
    back = w.scene.layouts[0].objects
    assert [o.name for o in back] == [obj.name]


# ----------------------------------------------------- selection outlives none

def test_geometry_taken_off_the_sheet_leaves_the_selection(sheet):
    """Undo can take an object out from under a pick, and a selection holding
    a shape that is no longer on the sheet would draw and move a ghost."""
    _w, lv, lay, obj = sheet
    lv.selected = [("object", obj)]
    lay.objects.remove(obj)
    lv._prune()
    assert lv.selected == []


# ------------------------------------------------------------ how it is drawn

def test_a_selected_object_is_drawn_in_the_selection_colour(sheet):
    """Gold ink rather than a dashed box around it: two lines that overlap
    share a box, and the point of picking is knowing which one you have."""
    _w, lv, _lay, obj = sheet
    plain = lv._object_ink(obj)
    lv.selected = [("object", obj)]
    picked = lv._object_ink(obj)
    assert picked != plain
    from serpentine3d.ui import theme
    assert picked[:3] == pytest.approx(theme.SELECTION_COLOR, abs=1e-6)
