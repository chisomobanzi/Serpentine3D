"""Rotate turns everything picked on a sheet (#36, finishing the family).

Rotate already worked on a sheet, but only for paper geometry and
pictures: with a detail, a dimension or a note in the pick it refused the
lot. Scale and mirror now take anything a sheet holds, and rotate does
the same.

What cannot turn is placed rather than bent. A note is always drawn
level, so it orbits the pivot and keeps reading level, its middle landing
where the turned text's middle would be; a detail frame likewise moves to
its turned place at its own size. Dimensions, leaders and hatches turn
properly, a hatch's lines with them. A locked detail stays put and says
so, as for move, scale and mirror.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.layout import (DetailView, Hatch, Layout, LinearDim,
                                      PaperObject, TextNote,
                                      annotation_bounds, transform_sheet_item)


@pytest.fixture
def sheet():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from serpentine3d.app import MainWindow
    w = MainWindow()
    w.resize(1200, 800)
    lay = Layout(name="Sheet1")
    lay.details.append(DetailView(x=20.0, y=30.0, w=100.0, h=60.0,
                                  scale_denom=50.0))
    lay.objects.append(PaperObject(shape=g.make_polyline(
        [(10, 10, 0), (30, 10, 0), (30, 20, 0), (10, 20, 0)]), name="Rule"))
    lay.dims.append(LinearDim(x1=10.0, y1=5.0, x2=30.0, y2=5.0, offset=4.0))
    lay.notes.append(TextNote(x=40.0, y=40.0, text="Plan", height=3.0))
    lay.hatches.append(Hatch(points=[[0, 0], [10, 0], [10, 10]], angle=30.0))
    w.scene.layouts.append(lay)
    w.switch_space(lay.id)
    lv = w.viewport.layout_view
    lv.fit()
    lv._fitted_for = lay.id
    lv.entered_detail = None
    said: list = []
    w.ctx.add_echo_listener(said.append)
    try:
        yield w, lv, lay, said
    finally:
        if w.processor.busy:
            w.processor.cancel()
        w.mark_saved()
        w.close()


def _run(w, command, *inputs):
    w.run_command(command)
    for text in inputs:
        assert w.processor.busy, f"{command} stopped before '{text}'"
        w.processor.provide_text(text)


def _turn(p, deg, about=(0.0, 0.0)):
    a = math.radians(deg)
    x, y = p[0] - about[0], p[1] - about[1]
    return (about[0] + x * math.cos(a) - y * math.sin(a),
            about[1] + x * math.sin(a) + y * math.cos(a))


def _middle(kind, obj):
    x0, y0, x1, y1 = annotation_bounds(kind, obj)
    return ((x0 + x1) / 2, (y0 + y1) / 2)


# --- the command on a sheet -------------------------------------------------

def test_rotate_takes_a_mixed_pick(sheet):
    w, lv, lay, said = sheet
    lv.selected = [("detail", lay.details[0]), ("object", lay.objects[0]),
                   ("dim", lay.dims[0]), ("note", lay.notes[0]),
                   ("hatch", lay.hatches[0])]

    _run(w, "rotate", "0,0", "90")

    assert not w.processor.busy
    assert "Rotated 5" in said[-1], said


def test_paper_geometry_still_turns_as_a_shape(sheet):
    w, lv, lay, _said = sheet
    rule = lay.objects[0]
    lv.selected = [("object", rule)]

    _run(w, "rotate", "0,0", "90")

    lo, hi = g.bbox(rule.shape)
    assert (lo[0], lo[1], hi[0], hi[1]) == pytest.approx((-20, 10, -10, 30))


def test_a_dimension_turns_about_the_pivot(sheet):
    w, lv, lay, _said = sheet
    dim = lay.dims[0]
    lv.selected = [("dim", dim)]

    _run(w, "rotate", "0,0", "90")

    assert (dim.x1, dim.y1) == pytest.approx(_turn((10, 5), 90))
    assert (dim.x2, dim.y2) == pytest.approx(_turn((30, 5), 90))
    assert dim.offset == pytest.approx(4.0), "a turn keeps its side"


def test_a_note_orbits_and_stays_level(sheet):
    w, lv, lay, _said = sheet
    note = lay.notes[0]
    before = _middle("note", note)
    lv.selected = [("note", note)]

    _run(w, "rotate", "0,0", "90")

    assert _middle("note", note) == pytest.approx(_turn(before, 90))
    assert note.height == pytest.approx(3.0)


def test_a_hatch_turns_its_lines(sheet):
    w, lv, lay, _said = sheet
    hatch = lay.hatches[0]
    lv.selected = [("hatch", hatch)]

    _run(w, "rotate", "0,0", "90")

    assert hatch.angle % 180 == pytest.approx(120.0)
    assert hatch.points[1] == pytest.approx(list(_turn((10, 0), 90)))


def test_a_detail_frame_moves_to_its_turned_place_at_its_own_size(sheet):
    w, lv, lay, _said = sheet
    det = lay.details[0]
    centre = (det.x + det.w / 2, det.y + det.h / 2)
    lv.selected = [("detail", det)]

    _run(w, "rotate", "0,0", "30")

    assert (det.w, det.h) == pytest.approx((100.0, 60.0))
    assert (det.x + det.w / 2, det.y + det.h / 2) == pytest.approx(
        _turn(centre, 30))
    assert det.scale_denom == 50.0


def test_a_locked_detail_stays_and_says_so(sheet):
    w, lv, lay, said = sheet
    det = lay.details[0]
    det.locked = True
    lv.selected = [("detail", det), ("object", lay.objects[0])]

    _run(w, "rotate", "0,0", "90")

    assert (det.x, det.y) == (20.0, 30.0)
    assert "Rotated 1" in said[-1] and "locked" in said[-1].lower(), said


def test_the_angle_can_be_dragged_with_reference_points(sheet):
    w, lv, lay, _said = sheet
    dim = lay.dims[0]
    lv.selected = [("dim", dim), ("note", lay.notes[0])]

    _run(w, "rotate", "0,0", "10,0", "0,10")      # a quarter turn

    assert (dim.x2, dim.y2) == pytest.approx(_turn((30, 5), 90))


def test_nothing_picked_says_so_and_does_not_wait(sheet):
    w, lv, _lay, said = sheet
    lv.selected = []

    w.run_command("rotate")

    assert not w.processor.busy
    assert "picked" in said[-1].lower(), said


def test_one_undo_puts_the_sheet_back(sheet):
    w, lv, lay, _said = sheet
    lv.selected = [("dim", lay.dims[0]), ("note", lay.notes[0])]
    _run(w, "rotate", "0,0", "90")

    w.history.undo()

    lay = w.scene.layouts[0]
    assert (lay.dims[0].x1, lay.notes[0].x) == pytest.approx((10.0, 40.0))


# --- the rules underneath ---------------------------------------------------

def _rotation(deg, about=(0.0, 0.0)):
    a = math.radians(deg)
    r = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
    m = np.eye(3)
    m[:2, :2] = r
    m[:2, 2] = np.asarray(about) - r @ np.asarray(about)
    return m


def test_a_note_turned_upside_down_by_a_negative_scale_is_placed_too():
    """Scale by -1 is a half turn: the text's middle goes through the
    pivot, rather than its left end, which left the text beside itself."""
    note = TextNote(x=10.0, y=5.0, text="Plan", height=3.0)
    before = _middle("note", note)
    half_turn = np.array([[-1.0, 0, 0], [0, -1.0, 0], [0, 0, 1.0]])

    transform_sheet_item("note", note, half_turn, size=-1.0)

    assert _middle("note", note) == pytest.approx((-before[0], -before[1]))
    assert note.height == pytest.approx(3.0)


def test_a_turned_and_scaled_frame_grows_by_the_scale():
    det = DetailView(x=0.0, y=0.0, w=20.0, h=10.0)
    m = _rotation(30)
    m[:2, :2] *= 2.0

    transform_sheet_item("detail", det, m, size=2.0)

    assert (det.w, det.h) == pytest.approx((40.0, 20.0))


def test_a_paper_object_turns_exactly():
    obj = PaperObject(shape=g.make_line((10, 0, 0), (20, 0, 0)))

    transform_sheet_item("object", obj, _rotation(90, about=(10, 0)))

    lo, hi = g.bbox(obj.shape)
    assert (lo[0], lo[1], hi[0], hi[1]) == pytest.approx((10, 0, 10, 10), abs=1e-6)
