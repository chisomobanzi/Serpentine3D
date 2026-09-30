"""Mirror works on what is picked on a sheet (#36, the same fault as scale).

Mirror had the fault #36 reported for the scale commands: with paper
picked on a layout it put up a model "Select objects" prompt no click on
paper can answer, and being declared model-only it refused a paper point
besides.

On a sheet it now mirrors what is picked there across the line drawn, in
paper millimetres, keeping the original or not as in the model. Paper
geometry and pictures mirror as shapes. Text keeps reading forwards: a
note moves to where its mirror image would be, the way AutoCAD and Rhino
treat text by default, rather than coming out backwards. A dimension stays
on the mirrored side of what it measures, a hatch's lines turn with it,
and a detail frame moves to its mirrored place (a view of the model cannot
itself be mirrored). A locked detail stays where it is, as for move and
scale, unless the original is kept, when it is the copy that goes.
"""

from __future__ import annotations

import numpy as np
import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.layout import (AngularDim, DetailView, Hatch, Layout,
                                      LinearDim, PaperObject, TextNote,
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
    return tuple(round(v, 6) for v in (lo[0], lo[1], hi[0], hi[1]))


# a mirror line straight up the sheet at x = 50
UP_X50 = ("50,0", "50,10")


# --- the command on a sheet -------------------------------------------------

def test_mirror_moves_a_paper_polyline_across_the_line(sheet):
    w, lv, lay, said = sheet
    rule = lay.objects[0]
    lv.selected = [("object", rule)]

    _run(w, "mirror", *UP_X50, "No")

    assert not w.processor.busy
    assert len(lay.objects) == 1
    assert _box(rule) == (70.0, 10.0, 90.0, 20.0)
    assert "Mirrored 1" in said[-1], said


def test_keeping_the_original_leaves_it_and_adds_the_mirror(sheet):
    w, lv, lay, _said = sheet
    rule = lay.objects[0]
    lv.selected = [("object", rule)]

    _run(w, "mirror", *UP_X50, "Yes")

    assert len(lay.objects) == 2
    assert sorted(_box(o) for o in lay.objects) == [
        (10.0, 10.0, 30.0, 20.0), (70.0, 10.0, 90.0, 20.0)]


def test_a_mixed_pick_all_mirrors(sheet):
    w, lv, lay, said = sheet
    lv.selected = [("detail", lay.details[0]), ("object", lay.objects[0]),
                   ("dim", lay.dims[0]), ("note", lay.notes[0])]

    _run(w, "mirror", *UP_X50, "No")

    assert "Mirrored 4" in said[-1], said
    det = lay.details[0]
    assert (det.x, det.y, det.w, det.h) == pytest.approx((-20, 30, 100, 60))
    assert det.scale_denom == 50.0


def test_a_locked_detail_stays_unless_the_original_is_kept(sheet):
    w, lv, lay, said = sheet
    det = lay.details[0]
    det.locked = True
    lv.selected = [("detail", det)]

    _run(w, "mirror", *UP_X50, "No")

    assert (det.x, det.y) == (20.0, 30.0)
    assert "locked" in said[-1].lower(), said

    lv.selected = [("detail", det)]
    _run(w, "mirror", *UP_X50, "Yes")

    assert len(lay.details) == 2, "the copy is the one that goes"
    copy = next(d for d in lay.details if d is not det)
    assert (copy.x, copy.y) == pytest.approx((-20.0, 30.0))
    assert (det.x, det.y) == (20.0, 30.0)


def test_nothing_picked_says_so_and_does_not_wait(sheet):
    w, lv, _lay, said = sheet
    lv.selected = []

    w.run_command("mirror")

    assert not w.processor.busy
    assert "picked" in said[-1].lower(), said


def test_one_undo_puts_the_sheet_back(sheet):
    w, lv, lay, _said = sheet
    lv.selected = [("object", lay.objects[0]), ("dim", lay.dims[0])]
    _run(w, "mirror", *UP_X50, "No")

    w.history.undo()

    lay = w.scene.layouts[0]
    assert _box(lay.objects[0]) == (10.0, 10.0, 30.0, 20.0)
    assert lay.dims[0].x1 == pytest.approx(10.0)


def test_a_mirror_line_of_no_length_is_refused(sheet):
    w, lv, lay, said = sheet
    lv.selected = [("object", lay.objects[0])]

    _run(w, "mirror", "50,0", "50,0")

    assert not w.processor.busy
    assert _box(lay.objects[0]) == (10.0, 10.0, 30.0, 20.0)
    assert "cancelled" in said[-1].lower(), said


# --- each kind, mirrored the way a drawing wants it -------------------------

def _mirror_x50():
    """Reflection across the line x = 50, as the command builds it."""
    return np.array([[-1.0, 0.0, 100.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])


def test_text_keeps_reading_forwards_and_lands_mirrored():
    note = TextNote(x=10.0, y=5.0, text="Plan", height=3.0)
    x0, y0, x1, y1 = annotation_bounds("note", note)
    centre = ((x0 + x1) / 2, (y0 + y1) / 2)

    transform_sheet_item("note", note, _mirror_x50())

    nx0, ny0, nx1, ny1 = annotation_bounds("note", note)
    assert ((nx0 + nx1) / 2, (ny0 + ny1) / 2) == pytest.approx(
        (100.0 - centre[0], centre[1]))
    assert note.height == pytest.approx(3.0)
    assert note.alignment == "left", "the text is not turned round"


def test_a_dimension_stays_on_the_mirrored_side():
    """Its line is drawn to the left of first-to-second point: mirrored
    as they were, it would jump to the other side of what it measures."""
    dim = LinearDim(x1=10.0, y1=5.0, x2=30.0, y2=5.0, offset=4.0)

    def side(d):
        a, b = np.array([d.x1, d.y1]), np.array([d.x2, d.y2])
        u = (b - a) / np.linalg.norm(b - a)
        return (a + b) / 2 + np.array([-u[1], u[0]]) * d.offset

    before = side(dim)
    transform_sheet_item("dim", dim, _mirror_x50())

    assert side(dim) == pytest.approx((100.0 - before[0], before[1]))
    assert sorted((dim.x1, dim.x2)) == pytest.approx([70.0, 90.0])


def test_an_angular_dimension_mirrors_its_rays():
    adim = AngularDim(vx=40.0, vy=0.0, x1=45.0, y1=0.0, x2=40.0, y2=5.0)

    transform_sheet_item("adim", adim, _mirror_x50())

    assert (adim.vx, adim.x1, adim.x2) == pytest.approx((60.0, 55.0, 60.0))


def test_a_hatch_turns_its_lines_with_the_mirror():
    hatch = Hatch(points=[[0, 0], [10, 0], [10, 10]], angle=30.0, spacing=2.0)

    transform_sheet_item("hatch", hatch, _mirror_x50())

    assert hatch.angle % 180 == pytest.approx(150.0)
    assert hatch.spacing == pytest.approx(2.0)
    assert hatch.points[1] == [90.0, 0.0]


def test_a_detail_frame_moves_to_its_mirrored_place_at_its_own_size():
    det = DetailView(x=20.0, y=30.0, w=100.0, h=60.0)
    diagonal = np.array([[0.0, 1.0, 0.0], [1.0, 0.0, 0.0], [0, 0, 1.0]])

    transform_sheet_item("detail", det, diagonal)

    assert (det.w, det.h) == pytest.approx((100.0, 60.0)), \
        "a frame cannot turn, so it keeps its shape"
    assert (det.x + det.w / 2, det.y + det.h / 2) == pytest.approx((60.0, 70.0))


def test_a_paper_object_mirrors_as_a_shape():
    obj = PaperObject(shape=g.make_polyline([(10, 0, 0), (20, 0, 0), (10, 5, 0)]))

    transform_sheet_item("object", obj, _mirror_x50())

    lo, hi = g.bbox(obj.shape)
    assert (lo[0], hi[0], hi[1]) == pytest.approx((80.0, 90.0, 5.0))
    assert lo[2] == pytest.approx(0.0, abs=1e-6)


# --- what worked stays working ----------------------------------------------

def test_scale_still_moves_a_notes_anchor():
    """The mirrored-text rule is for reflections only."""
    note = TextNote(x=10.0, y=5.0, text="A", height=3.0)
    double = np.array([[2.0, 0, 0], [0, 2.0, 0], [0, 0, 1.0]])

    transform_sheet_item("note", note, double, size=2.0)

    assert (note.x, note.y, note.height) == pytest.approx((20.0, 10.0, 6.0))


def test_mirror_in_the_model_is_unchanged(sheet):
    w, _lv, _lay, _said = sheet
    w.switch_space("model")
    line = w.scene.add(g.make_line((10, 0, 0), (20, 0, 0)), name="L")
    w.selection.set([line.id])

    _run(w, "mirror", *UP_X50, "No")

    lo, hi = g.bbox(w.scene.get(line.id).shape)
    assert (lo[0], hi[0]) == pytest.approx((80.0, 90.0))
