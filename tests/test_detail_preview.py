"""Drawing a detail with something to look at while you draw it.

`detail` used to ask for two corners and show nothing at all between them: no
rectangle, no size, and no hint of what the frame would end up containing. You
picked blind and found out afterwards, which on a sheet means undo, again, and
again until the model happens to fit.

So the view and the scale are chosen first — you cannot preview a view nobody
has picked — and the frame is then dragged with the model live inside it.
"""

from __future__ import annotations

import inspect
import math

import pytest

import serpentine3d.commands  # registers all commands  # noqa: F401
from serpentine3d.app import MainWindow
from serpentine3d.commands.drafting import _frame
from serpentine3d.core import geometry as g
from serpentine3d.core.layout import DetailView, Layout
from serpentine3d.ui.camera import STANDARD_VIEWS
from serpentine3d.ui.layout_view import LayoutView


@pytest.fixture
def sheet():
    """A window on a sheet, with something in the model to look at."""
    w = MainWindow()
    w.resize(1200, 800)
    w.scene.add(g.make_box((0.0, 0.0, 0.0), 40.0, 30.0, 20.0))
    lay = Layout(name="Sheet1")
    w.scene.layouts.append(lay)
    w.switch_space(lay.id)
    return w, w.processor, lay


def _prompt(proc) -> str:
    return proc.request.prompt.lower()


# ------------------------------------------------------ what it asks, and when

def test_it_asks_which_view_before_the_frame(sheet):
    """The frame is the last question, because it is the only one the other
    two can be shown answering."""
    _w, proc, _lay = sheet
    proc.run("detail")
    assert "view" in _prompt(proc)
    proc.provide("Top")
    assert "scale" in _prompt(proc)
    proc.provide("1:5")
    assert "corner" in _prompt(proc)


def test_the_frame_is_the_rectangle_the_two_corners_make():
    assert _frame((120.0, 100.0, 0.0), (20.0, 20.0, 0.0)) == (
        20.0, 20.0, 100.0, 80.0)


def test_the_detail_still_comes_out_where_you_drew_it(sheet):
    _w, proc, lay = sheet
    proc.run("detail")
    for value in ("Top", "1:5", (120.0, 100.0, 0.0), (20.0, 20.0, 0.0)):
        proc.provide(value)
    assert not proc.busy
    det = lay.details[0]
    assert (det.x, det.y, det.w, det.h) == (20.0, 20.0, 100.0, 80.0)
    assert det.scale_denom == pytest.approx(5.0)
    assert det.display_mode == "hidden"


def test_a_frame_too_small_is_still_refused(sheet):
    _w, proc, lay = sheet
    proc.run("detail")
    for value in ("Top", "1:5", (20.0, 20.0, 0.0), (23.0, 60.0, 0.0)):
        proc.provide(value)
    assert not proc.busy
    assert lay.details == []


# --------------------------------------------------------------- the ghost

def _to_frame(proc, view="Top", scale="1:5", c1=(20.0, 20.0, 0.0)):
    """Run `detail` up to the corner that drags the frame."""
    proc.run("detail")
    for value in (view, scale, c1):
        proc.provide(value)
    return proc


def test_there_is_a_ghost_while_the_frame_is_drawn(sheet):
    """The bug as reported: nothing at all appeared between the two
    corners."""
    _w, proc, _lay = sheet
    _to_frame(proc)
    ghost = proc.preview_for((120.0, 100.0, 0.0))
    assert isinstance(ghost, DetailView)
    assert (ghost.x, ghost.y, ghost.w, ghost.h) == (20.0, 20.0, 100.0, 80.0)


def test_the_ghost_shows_the_view_and_the_scale_you_chose(sheet):
    _w, proc, _lay = sheet
    _to_frame(proc, view="Front", scale="1:20")
    ghost = proc.preview_for((120.0, 100.0, 0.0))
    az, el = STANDARD_VIEWS["front"]
    assert ghost.azimuth == pytest.approx(az)
    assert ghost.elevation == pytest.approx(el)
    assert ghost.scale_denom == pytest.approx(20.0)
    assert ghost.scale_text() == "1:20"


def test_the_ghost_looks_at_the_model(sheet):
    """An empty frame previews nothing, so it aims where the model is."""
    _w, proc, _lay = sheet
    _to_frame(proc)
    ghost = proc.preview_for((120.0, 100.0, 0.0))
    assert ghost.target == pytest.approx([20.0, 15.0, 10.0])


def test_a_perspective_ghost_stands_back_far_enough_to_see(sheet):
    _w, proc, _lay = sheet
    _to_frame(proc, view="Perspective")
    ghost = proc.preview_for((120.0, 100.0, 0.0))
    assert ghost.perspective is True
    assert ghost.perspective_distance > 0


def test_the_ghost_is_the_same_detail_all_the_way_along(sheet):
    """Its hidden lines are cached under its id, so a ghost that got a new id
    every mouse move would re-project the whole model every mouse move."""
    _w, proc, lay = sheet
    _to_frame(proc)
    first = proc.preview_for((100.0, 90.0, 0.0))
    second = proc.preview_for((120.0, 100.0, 0.0))
    assert first is second
    assert (second.w, second.h) == (100.0, 80.0)
    proc.provide((120.0, 100.0, 0.0))
    assert lay.details[0] is first, "the ghost is what gets placed"


def test_a_frame_with_no_width_yet_has_nothing_to_show(sheet):
    _w, proc, _lay = sheet
    _to_frame(proc)
    assert proc.preview_for((20.0, 20.0, 0.0)) is None
    assert proc.preview_for((20.4, 90.0, 0.0)) is None


def test_the_ghost_is_drawn_cheaply_while_it_moves(sheet):
    """One hidden-line pass over the model per frame size is not a preview;
    the placed detail is the one that gets the hidden-line treatment."""
    _w, proc, lay = sheet
    _to_frame(proc)
    assert proc.preview_for((120.0, 100.0, 0.0)).display_mode == "wireframe"
    proc.provide((120.0, 100.0, 0.0))
    assert lay.details[0].display_mode == "hidden"


# ------------------------------------------------- how it reaches the sheet

def test_the_viewport_hands_a_pending_detail_to_the_sheet(sheet):
    """A detail is a window onto the model, not a shape, so there is nothing
    to tessellate."""
    w, _proc, _lay = sheet
    det = DetailView(x=20.0, y=20.0, w=100.0, h=80.0)
    w.viewport.set_ghost(det)
    assert w.viewport.layout_view.ghost_detail is det
    assert w.viewport._ghost is None


def test_clearing_the_ghost_clears_the_pending_detail(sheet):
    w, _proc, _lay = sheet
    w.viewport.set_ghost(DetailView())
    w.viewport.set_ghost(None)
    assert w.viewport.layout_view.ghost_detail is None


def test_an_abandoned_ghost_does_not_keep_the_whole_model(sheet):
    """Its hidden lines are held under its id; a ghost nobody placed would
    leave the model's linework behind it for good."""
    w, _proc, _lay = sheet
    lv = w.viewport.layout_view
    det = DetailView()
    w.viewport.set_ghost(det)
    lv._hlr_cache[det.id] = ("key", {"visible": []})
    w.viewport.set_ghost(None)
    assert det.id not in lv._hlr_cache


def test_a_ghost_that_got_placed_keeps_its_hidden_lines(sheet):
    w, _proc, lay = sheet
    lv = w.viewport.layout_view
    det = DetailView()
    w.viewport.set_ghost(det)
    lv._hlr_cache[det.id] = ("key", {"visible": []})
    lay.details.append(det)                  # the command finished with it
    w.viewport.set_ghost(None)
    assert det.id in lv._hlr_cache


def test_the_sheet_paints_the_pending_detail(sheet):
    """A GL draw path cannot be called from here, so this is the wiring: a
    sheet that never asks for the ghost cannot draw it."""
    assert "_paint_ghost_detail" in inspect.getsource(LayoutView.paint)


def test_every_pane_lets_go_of_the_ghost(sheet):
    """Ghosts are set on every pane, so one pane's worth of clearing leaves
    a detail sitting on the others that no command owns."""
    w, _proc, _lay = sheet
    w.set_view_layout("quad")
    panes = w.all_viewports()
    assert len(panes) > 1
    for vp in panes:
        vp.set_ghost(DetailView())
    w._sync_command_state()
    assert all(vp.layout_view.ghost_detail is None for vp in panes)


# --------------------------------------------------------------- the readout

def test_the_frame_is_dragged_without_a_rubber_band(sheet):
    """The gold frame already shows both corners, and a green diagonal drawn
    across the view being framed hides the one thing the preview is for."""
    _w, proc, _lay = sheet
    _to_frame(proc)
    assert proc.request.rubber_from is None
    assert not proc.request.rubber_pts


def test_the_readout_says_how_big_the_frame_is(sheet):
    """A width, a height and the scale — a detail is not a leg, so the
    diagonal between the corners is not the number anyone wants."""
    w, _proc, _lay = sheet
    vp = w.viewport
    vp.set_ghost(DetailView(x=20.0, y=20.0, w=100.0, h=80.0,
                            scale_denom=5.0))
    assert vp._draw_readout.text() == "100.0 × 80.0 mm · 1:5"
    assert not vp._draw_readout.isHidden(), (
        "there is no rubber band to hang it off, and it is still shown")


def test_the_readout_sits_at_the_corner_the_two_sides_meet(sheet):
    """Which is where the width and the height are, rather than out at the
    end of a band that is not drawn any more."""
    w, _proc, _lay = sheet
    vp, lv = w.viewport, w.viewport.layout_view
    lv.fit()
    vp.set_ghost(DetailView(x=20.0, y=20.0, w=100.0, h=80.0))
    label = vp._draw_readout
    mid = (label.x() + label.width() / 2, label.y() + label.height() / 2)
    assert (math.dist(mid, lv.paper_to_screen(120.0, 100.0))
            < math.dist(mid, lv.paper_to_screen(20.0, 20.0)))


def test_the_readout_goes_back_to_a_length_without_one(sheet):
    """Every other paper pick is still a leg of millimetres."""
    w, _proc, _lay = sheet
    vp = w.viewport
    vp.set_preview([[(20.0, 20.0, 0.0), (20.0, 100.0, 0.0)]])
    assert "×" not in vp._draw_readout.text()
    assert "80" in vp._draw_readout.text()


def test_the_readout_goes_when_the_frame_does(sheet):
    w, _proc, _lay = sheet
    vp = w.viewport
    vp.set_ghost(DetailView(x=20.0, y=20.0, w=100.0, h=80.0))
    vp.set_ghost(None)
    assert not vp._draw_readout.isVisible()
