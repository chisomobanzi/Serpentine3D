"""What a picked point means on a sheet, and what it must not mean.

A sheet has two spaces on it. The paper is millimetres; a detail is a window
onto the model. Until now a pick was paper millimetres either way, and every
command that draws believed it had been handed a model point — so `line` on a
sheet put a curve in the *model* at the paper coordinates, and doing it inside
a detail did the same thing rather than drawing where the detail was looking.

So: inside a detail you are drawing in the model, on the plane the detail
looks at. On bare paper a model command has nothing to draw on, and says so
instead of guessing.
"""

from __future__ import annotations

import numpy as np
import pytest

from serpentine3d.app import MainWindow
from serpentine3d.core.layout import (
    DetailView,
    Layout,
    detail_project,
    detail_unproject,
)

# a detail at 1:2 looking down at a target away from the origin, so that
# paper millimetres, model units and the sheet's own corner cannot be
# confused for one another
DET = {"x": 20.0, "y": 30.0, "w": 160.0, "h": 120.0,
       "scale_denom": 2.0, "target": [400.0, 250.0, 0.0]}


@pytest.fixture
def sheet():
    w = MainWindow()
    w.resize(1200, 800)
    lay = Layout(name="Sheet1")
    lay.details.append(DetailView(**DET))
    w.scene.layouts.append(lay)
    w.viewport.space = lay.id
    lv = w.viewport.layout_view
    lv.fit()
    lv._fitted_for = lay.id
    return w, lv, lay


def _at(w, lv, px, py):
    """What the viewport says is under the pixel showing paper (px, py)."""
    return w.viewport.world_point_at(*lv.paper_to_screen(px, py))


# ------------------------------------------------- inside a detail: the model

def test_a_point_in_an_entered_detail_is_the_model_point_it_shows(sheet):
    w, lv, lay = sheet
    det = lay.details[0]
    lv.entered_detail = det.id
    w.viewport.point_space = "model"
    # the middle of the frame looks straight at the target
    assert _at(w, lv, 100.0, 90.0) == pytest.approx((400.0, 250.0, 0.0))


def test_the_scale_is_honoured_going_back_out_to_the_model(sheet):
    """1:2 means one millimetre of paper is two model units."""
    w, lv, lay = sheet
    det = lay.details[0]
    lv.entered_detail = det.id
    w.viewport.point_space = "model"
    got = _at(w, lv, 110.0, 90.0)            # 10mm right of the middle
    assert got == pytest.approx((420.0, 250.0, 0.0))    # so 20 model units
    assert got == pytest.approx(tuple(detail_unproject(det, 110.0, 90.0)))


def test_a_front_view_detail_draws_on_the_plane_it_looks_at(sheet):
    """The plane is the detail's, not the world's z=0."""
    w, lv, lay = sheet
    det = lay.details[0]
    det.azimuth, det.elevation = 0.0, 0.0    # looking along -x: a front view
    lv.entered_detail = det.id
    w.viewport.point_space = "model"
    x, y, z = _at(w, lv, 110.0, 90.0)
    assert x == pytest.approx(400.0)         # the plane through the target
    assert (y, z) != pytest.approx((250.0, 0.0))


def test_the_grid_snaps_in_model_units_inside_a_detail(sheet):
    """A round number inside a detail is a round model coordinate, since
    that is what the geometry gets built from."""
    w, lv, lay = sheet
    det = lay.details[0]
    lv.entered_detail = det.id
    w.viewport.point_space = "model"
    w.viewport.grid_snap = True
    w.viewport.grid_snap_step = 5.0
    x, y, _ = _at(w, lv, 100.3, 90.4)
    assert x % 5.0 == pytest.approx(0.0)
    assert y % 5.0 == pytest.approx(0.0)


# --------------------------------------------------- on the paper: the paper

def test_a_point_on_bare_paper_is_still_paper_millimetres(sheet):
    w, lv, _ = sheet
    w.viewport.point_space = "model"
    assert _at(w, lv, 100.0, 90.0) == pytest.approx((100.0, 90.0, 0.0))


def test_a_paper_command_in_a_detail_still_gets_paper_millimetres(sheet):
    """`dim` and `text` land on the sheet wherever the cursor is — being
    inside a detail must not turn their coordinates into model ones."""
    w, lv, lay = sheet
    lv.entered_detail = lay.details[0].id
    w.viewport.point_space = "paper"
    assert _at(w, lv, 100.0, 90.0) == pytest.approx((100.0, 90.0, 0.0))


def test_what_you_picked_in_a_detail_projects_back_to_where_you_clicked(sheet):
    """A wrong sign or a swapped axis would still pass a plane test, so the
    round trip is what pins the point down."""
    w, lv, lay = sheet
    det = lay.details[0]
    lv.entered_detail = det.id
    w.viewport.point_space = "model"
    for px, py in ((40.0, 45.0), (100.0, 90.0), (175.0, 145.0)):
        model = _at(w, lv, px, py)
        assert detail_project(det, model) == pytest.approx((px, py))


# ------------------------------------------------ what a command is allowed

def _run(w, name, *inputs):
    w.run_command(name)
    for text in inputs:
        w.processor.provide_text(text)


def _click(w, lv, px, py):
    """Pick what the mouse would pick over paper (px, py).

    Typed coordinates are a different question — they never go through the
    viewport at all, so they are always in the command's own space.
    """
    w.processor.provide(_at(w, lv, px, py))


def test_a_command_declares_which_space_its_points_are_in():
    """`mutates` already gates checkpointing from the registry; the space a
    command's points live in belongs in the same place."""
    from serpentine3d.commands.base import resolve
    assert resolve("box").space == "model"       # nothing else it could mean
    assert resolve("text").space == "paper"
    assert resolve("dim").space == "paper"
    assert resolve("detail").space == "paper"
    assert resolve("move").space == "any"        # handles either itself
    # a curve draws in the model, or on the paper — see test_paper_geometry.py
    assert resolve("line").space == "any"


def test_drawing_inside_a_detail_puts_geometry_in_the_model(sheet):
    """The whole point: a line drawn through a detail is model geometry at
    model coordinates, not paper millimetres pretending to be them."""
    from serpentine3d.core import geometry as g
    w, lv, lay = sheet
    lv.entered_detail = lay.details[0].id
    w.run_command("line")
    _click(w, lv, 100.0, 90.0)                   # the middle of the frame
    _click(w, lv, 150.0, 90.0)                   # 50mm right, so 100 units
    objs = w.scene.all()
    assert len(objs) == 1
    lo, hi = g.bbox(objs[0].shape)
    assert lo == pytest.approx((400.0, 250.0, 0.0), abs=1e-6)
    assert hi == pytest.approx((500.0, 250.0, 0.0), abs=1e-6)


def test_typed_coordinates_in_a_detail_are_model_coordinates(sheet):
    """Typing is how you say an exact coordinate, and inside a detail you are
    working in the model — so the numbers are the model's, not the paper's.
    The unprojection is what the *cursor* needs; nothing translates a number
    you already knew."""
    from serpentine3d.core import geometry as g
    w, lv, lay = sheet
    lv.entered_detail = lay.details[0].id
    _run(w, "line", "400,250,0", "500,250,0")
    objs = w.scene.all()
    assert len(objs) == 1
    lo, hi = g.bbox(objs[0].shape)
    assert lo == pytest.approx((400.0, 250.0, 0.0), abs=1e-6)
    assert hi == pytest.approx((500.0, 250.0, 0.0), abs=1e-6)


def test_drawing_on_bare_paper_is_refused_rather_than_guessed(sheet):
    """A curve on bare paper is drawn on the paper (test_paper_geometry.py); a
    solid has nowhere to go, since paper geometry is flat millimetres, and says
    so rather than landing in the model at the sheet's numbers."""
    w, lv, lay = sheet
    lv.entered_detail = None
    said = []
    w.ctx.add_echo_listener(said.append)
    _run(w, "box", "50,50,0", "150,100,0", "30")
    assert w.scene.all() == []
    assert lay.objects == []
    # the message has to name both ways out, or it only says no
    told = " ".join(said).lower()
    assert "detail" in told and "model" in told
    # and it has to be the last thing said: only the newest line or two of the
    # history is on screen, so "cancelled" on top of it hides the reason
    assert "detail" in said[-1].lower()


def test_a_refused_command_leaves_nothing_to_undo(sheet):
    w, lv, _ = sheet
    lv.entered_detail = None
    assert not w.history.can_undo
    _run(w, "box", "50,50,0")
    assert not w.history.can_undo


def test_the_refusal_waits_for_the_point_it_cannot_answer(sheet):
    """`zoom` only needs a point for its Window mode, so the other modes go
    on working on a sheet. Refusing at the prompt, not at the command, is
    what keeps that true."""
    w, lv, _ = sheet
    lv.entered_detail = None
    w.run_command("zoom")
    assert w.processor.busy                      # asking which zoom
    w.processor.provide_text("Extents")
    assert not w.processor.busy


def test_a_paper_command_still_works_on_bare_paper(sheet):
    w, lv, lay = sheet
    lv.entered_detail = None
    _run(w, "text", "60,70,0", "SECTION A-A", "5")
    assert len(lay.notes) == 1
    assert (lay.notes[0].x, lay.notes[0].y) == pytest.approx((60.0, 70.0))


def test_a_paper_command_inside_a_detail_still_writes_on_the_paper(sheet):
    """Being inside a detail is about the model; a note is still a note on
    the sheet, at the millimetres you pointed at."""
    w, lv, lay = sheet
    lv.entered_detail = lay.details[0].id
    _run(w, "text", "60,70,0", "SECTION A-A", "5")
    assert len(lay.notes) == 1
    assert (lay.notes[0].x, lay.notes[0].y) == pytest.approx((60.0, 70.0))
    assert w.scene.all() == []


# --------------------------------------------- what you can see while drawing

def _drag(w, frm, to):
    """The rubber band mid-pick: one leg from the last picked point to the
    cursor, in whatever space the command's points are in."""
    w.viewport.set_preview(np.asarray([[frm, to]], np.float32), [frm])


def test_the_readout_follows_the_cursor_on_the_paper(sheet):
    """The length label is no use if it sits where the model camera thinks the
    cursor is — on a sheet there is no model camera on screen at all."""
    w, lv, _ = sheet
    w.viewport.point_space = "paper"
    _drag(w, (40.0, 50.0, 0.0), (90.0, 50.0, 0.0))
    ro = w.viewport._draw_readout
    assert not ro.isHidden()
    sx, sy = lv.paper_to_screen(90.0, 50.0)
    assert abs(ro.x() - sx) < 40 and abs(ro.y() - sy) < 40


def test_a_paper_leg_is_measured_in_millimetres(sheet):
    """Paper is millimetres whatever the model is drawn in."""
    w, _, _ = sheet
    w.scene.units = "ft"
    w.viewport.point_space = "paper"
    _drag(w, (40.0, 50.0, 0.0), (90.0, 50.0, 0.0))
    assert w.viewport._draw_readout.text() == "50 mm"


def test_a_leg_inside_a_detail_is_measured_in_the_model(sheet):
    """50mm of paper at 1:2 is 100 units of model, and it is the model that
    is being drawn."""
    w, lv, lay = sheet
    lv.entered_detail = lay.details[0].id
    w.viewport.point_space = "model"
    _drag(w, (400.0, 250.0, 0.0), (500.0, 250.0, 0.0))
    ro = w.viewport._draw_readout
    assert ro.text() == w.scene.format_length(100.0)
    # and it hangs by the cursor, which is 50mm right of the frame's middle
    sx, sy = lv.paper_to_screen(150.0, 90.0)
    assert abs(ro.x() - sx) < 40 and abs(ro.y() - sy) < 40


def test_the_rubber_band_in_a_detail_is_drawn_on_the_paper(sheet):
    """Model points have to come back out through the window they were picked
    in, or the band lands on the sheet at the model's own numbers."""
    w, lv, lay = sheet
    lv.entered_detail = lay.details[0].id
    w.viewport.point_space = "model"
    got = w.viewport._on_paper([(400.0, 250.0, 0.0), (500.0, 250.0, 0.0)])
    assert got[0][:2] == pytest.approx((100.0, 90.0))
    assert got[1][:2] == pytest.approx((150.0, 90.0))


def test_the_rubber_band_of_a_paper_command_is_left_alone(sheet):
    w, lv, lay = sheet
    lv.entered_detail = lay.details[0].id
    w.viewport.point_space = "paper"
    got = w.viewport._on_paper([(60.0, 70.0, 0.0)])
    assert got[0][:2] == pytest.approx((60.0, 70.0))


def test_a_model_command_is_untouched_in_model_space():
    from serpentine3d.core import geometry as g
    w = MainWindow()
    w.resize(1200, 800)
    assert w.viewport.space == "model"
    _run(w, "line", "0,0,0", "10,0,0")
    assert len(w.scene.all()) == 1
    assert g.bbox(w.scene.all()[0].shape)[1] == pytest.approx(
        (10.0, 0.0, 0.0), abs=1e-6)
