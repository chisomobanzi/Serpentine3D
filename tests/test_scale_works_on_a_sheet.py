"""Scale, Scale1D and Scale2D work on what is picked on a sheet (#36).

Reported: the scale commands did not recognise anything on a layout. Pick
a polyline, a detail or a dimension on a sheet, type `scale`, and the
command put up a model "Select objects" prompt that no click on paper can
answer, so it could only be cancelled. `move` and `rotate` had learned to
ask the sheet first; the scale family never had, and being declared
model-only it would have refused a paper point anyway.

On a sheet they now scale what is picked there, in paper millimetres.
Everything a sheet holds scales: paper geometry and pictures as shapes,
a detail's frame (keeping its drawing scale, so a 1:50 detail stays 1:50
and shows more or less of the model), and annotations by their points,
with text height, dimension offset and hatch spacing following a uniform
scale. A one-way stretch moves text and dimensions without distorting
them. A locked detail stays where it is, as it does for move.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.layout import (AngularDim, DetailView, Hatch, Layout,
                                      Leader, LinearDim, PaperObject,
                                      RadialDim, TextNote,
                                      transform_sheet_item)


# --- the sheet --------------------------------------------------------------

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


def _box(obj):
    lo, hi = g.bbox(obj.shape)
    return (round(lo[0], 6), round(lo[1], 6), round(hi[0], 6), round(hi[1], 6))


# --- the reported case: the commands take the sheet's picks -----------------

def test_scale_scales_a_paper_polyline(sheet):
    w, lv, lay, said = sheet
    rule = lay.objects[0]
    lv.selected = [("object", rule)]

    _run(w, "scale", "0,0", "2")

    assert not w.processor.busy
    assert _box(rule) == (20.0, 20.0, 60.0, 40.0)
    assert "Scaled 1" in said[-1], said


def test_scale2d_scales_a_paper_polyline(sheet):
    w, lv, lay, _said = sheet
    rule = lay.objects[0]
    lv.selected = [("object", rule)]

    _run(w, "scale2d", "10,10", "0.5")

    assert _box(rule) == (10.0, 10.0, 20.0, 15.0)


def test_scale1d_stretches_one_way_only(sheet):
    w, lv, lay, _said = sheet
    rule = lay.objects[0]
    lv.selected = [("object", rule)]

    _run(w, "scale1d", "10,10", "20,10", "30,10")    # 10 out becomes 20: x2

    assert _box(rule) == (10.0, 10.0, 50.0, 20.0)


def test_a_detail_frame_scales_and_keeps_its_drawing_scale(sheet):
    w, lv, lay, _said = sheet
    det = lay.details[0]
    lv.selected = [("detail", det)]

    _run(w, "scale", "20,30", "2")

    assert (det.x, det.y, det.w, det.h) == pytest.approx((20, 30, 200, 120))
    assert det.scale_denom == 50.0, "a 1:50 detail stays 1:50"


def test_a_locked_detail_stays_and_says_so(sheet):
    w, lv, lay, said = sheet
    det = lay.details[0]
    det.locked = True
    rule = lay.objects[0]
    lv.selected = [("detail", det), ("object", rule)]

    _run(w, "scale", "0,0", "2")

    assert (det.x, det.y, det.w, det.h) == (20.0, 30.0, 100.0, 60.0)
    assert _box(rule) == (20.0, 20.0, 60.0, 40.0)
    assert "locked" in said[-1].lower(), said


def test_a_dimension_scales_with_its_points(sheet):
    w, lv, lay, _said = sheet
    dim = lay.dims[0]
    lv.selected = [("dim", dim)]

    _run(w, "scale", "0,0", "2")

    assert (dim.x1, dim.y1, dim.x2, dim.y2) == pytest.approx((20, 10, 60, 10))
    assert dim.offset == pytest.approx(8.0)


def test_a_mixed_pick_all_scales_in_one_go(sheet):
    w, lv, lay, said = sheet
    lv.selected = [("detail", lay.details[0]), ("object", lay.objects[0]),
                   ("dim", lay.dims[0]), ("note", lay.notes[0])]

    _run(w, "scale", "0,0", "2")

    assert "Scaled 4" in said[-1], said
    assert lay.notes[0].height == pytest.approx(6.0)


def test_nothing_picked_says_so_and_does_not_wait(sheet):
    w, lv, _lay, said = sheet
    lv.selected = []

    w.run_command("scale")

    assert not w.processor.busy, "left waiting for a pick paper cannot give"
    assert "picked" in said[-1].lower(), said


def test_one_undo_puts_the_sheet_back(sheet):
    w, lv, lay, _said = sheet
    lv.selected = [("object", lay.objects[0]), ("dim", lay.dims[0])]
    _run(w, "scale", "0,0", "2")

    w.history.undo()

    lay = w.scene.layouts[0]
    assert _box(lay.objects[0]) == (10.0, 10.0, 30.0, 20.0)
    assert lay.dims[0].x2 == pytest.approx(30.0)


def test_a_typed_one_way_factor_with_no_cursor_stretches_along_x(sheet):
    w, lv, lay, _said = sheet
    rule = lay.objects[0]
    lv.selected = [("object", rule)]
    w.ctx.aim_direction = lambda: None

    _run(w, "scale1d", "10,10", "3")

    assert _box(rule) == (10.0, 10.0, 70.0, 20.0)


# --- every kind a sheet holds -----------------------------------------------

def _uniform(f, cx=0.0, cy=0.0):
    return np.array([[f, 0, cx * (1 - f)], [0, f, cy * (1 - f)], [0, 0, 1.0]])


def _stretch_x(f):
    return np.array([[f, 0, 0], [0, 1.0, 0], [0, 0, 1.0]])


def test_a_note_moves_its_anchor_and_grows(sheet):
    note = TextNote(x=10.0, y=5.0, text="A", height=3.0)

    transform_sheet_item("note", note, _uniform(2.0), size=2.0)

    assert (note.x, note.y, note.height) == pytest.approx((20.0, 10.0, 6.0))


def test_a_styled_note_keeps_its_look_when_it_grows():
    """A named style owns the height; scaling is a per-note edit, so the
    note leaves the style at the size it rendered at, times the factor."""
    from serpentine3d.core.scene import Scene
    scene = Scene()
    note = TextNote(x=0.0, y=0.0, text="A", height=3.0, style="Standard")
    from serpentine3d.core.layout import note_text_height
    before = note_text_height(note, scene)

    transform_sheet_item("note", note, _uniform(2.0), size=2.0, scene=scene)

    assert note.style == ""
    assert note.height == pytest.approx(before * 2.0)


def test_a_stretch_moves_text_without_distorting_it():
    note = TextNote(x=10.0, y=5.0, text="A", height=3.0)

    transform_sheet_item("note", note, _stretch_x(2.0), size=1.0)

    assert (note.x, note.y, note.height) == pytest.approx((20.0, 5.0, 3.0))


def test_an_associative_dimension_lets_go_of_the_model():
    """Its points no longer project from the model points it held."""
    dim = LinearDim(x1=0, y1=0, x2=10, y2=0, detail_id="d1",
                    m1=[0, 0, 0], m2=[5, 0, 0])

    transform_sheet_item("dim", dim, _uniform(2.0), size=2.0)

    assert (dim.m1, dim.m2, dim.detail_id) == (None, None, "")


def test_radial_and_angular_dimensions_scale():
    rdim = RadialDim(cx=1.0, cy=1.0, px=3.0, py=1.0)
    adim = AngularDim(vx=0, vy=0, x1=10, y1=0, x2=0, y2=10, radius=5.0)

    transform_sheet_item("rdim", rdim, _uniform(2.0), size=2.0)
    transform_sheet_item("adim", adim, _uniform(2.0), size=2.0)

    assert (rdim.cx, rdim.cy, rdim.px, rdim.py) == pytest.approx((2, 2, 6, 2))
    assert (adim.x1, adim.y2, adim.radius) == pytest.approx((20, 20, 10))


def test_a_leader_scales_its_points_and_text():
    leader = Leader(points=[[0, 0], [10, 5]], text="Note", height=2.5)

    transform_sheet_item("leader", leader, _uniform(2.0), size=2.0)

    assert leader.points == [[0.0, 0.0], [20.0, 10.0]]
    assert leader.height == pytest.approx(5.0)


def test_a_hatch_scales_its_region_holes_and_spacing():
    hatch = Hatch(points=[[0, 0], [10, 0], [10, 10], [0, 10]],
                  holes=[[[4, 4], [6, 4], [6, 6], [4, 6]]], spacing=3.0)

    transform_sheet_item("hatch", hatch, _uniform(2.0), size=2.0)

    assert hatch.points[2] == [20.0, 20.0]
    assert hatch.holes[0][0] == [8.0, 8.0]
    assert hatch.spacing == pytest.approx(6.0)


def test_a_stretched_hatch_keeps_its_spacing():
    hatch = Hatch(points=[[0, 0], [10, 0], [10, 10]], spacing=3.0)

    transform_sheet_item("hatch", hatch, _stretch_x(2.0), size=1.0)

    assert hatch.points[1] == [20.0, 0.0]
    assert hatch.spacing == pytest.approx(3.0)


def test_a_detail_frame_turned_inside_out_is_still_a_frame():
    """A negative factor flips the corners; the frame is where they land."""
    det = DetailView(x=10.0, y=10.0, w=20.0, h=10.0)

    transform_sheet_item("detail", det, _uniform(-1.0), size=1.0)

    assert (det.x, det.y, det.w, det.h) == pytest.approx((-30, -20, 20, 10))


def test_a_paper_object_scales_as_a_shape():
    obj = PaperObject(shape=g.make_circle((10.0, 0.0, 0.0), 2.0))

    transform_sheet_item("object", obj, _uniform(3.0), size=3.0)

    lo, hi = g.bbox(obj.shape)
    assert ((lo[0] + hi[0]) / 2, hi[0] - lo[0]) == pytest.approx((30.0, 12.0))
    assert lo[2] == pytest.approx(0.0, abs=1e-6) and hi[2] == pytest.approx(
        0.0, abs=1e-6), "paper geometry stays on the paper"
