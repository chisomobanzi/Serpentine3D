"""Dragging out a rectangle.

The second corner was asked for the way the end of a line is: with a rubber
band from the first corner to the cursor. But the rectangle is drawn under
the cursor too, so the band ran from corner to opposite corner — a diagonal
slash across the middle of the very shape it was helping you place.

The band was still earning its keep in one way: it is what puts a number on
screen while you draw. The number it put there was the length of that
diagonal, which is not a measurement anybody asks a rectangle for. A frame
is two numbers, and it already knows where its own corner is.
"""

from __future__ import annotations

import math

import pytest

from serpentine3d.app import MainWindow
from serpentine3d.commands.base import PointReq


@pytest.fixture
def win():
    w = MainWindow()
    w.resize(1000, 700)
    return w


def _drag(w, cmd, first, cursor):
    """Start `cmd`, pick `first`, and hold the cursor at `cursor`."""
    w.run_command(cmd)
    w.processor.provide_text(first)
    w._on_mouse_world(cursor)
    return w.processor.request


def test_no_band_is_drawn_across_the_rectangle(win):
    _drag(win, "rectangle", "0,0,0", (100.0, 50.0, 0.0))
    assert len(win.viewport._preview_data) == 0


def test_the_first_corner_is_still_marked(win):
    """Losing the band must not lose the point it was hung from."""
    _drag(win, "rectangle", "0,0,0", (100.0, 50.0, 0.0))
    assert win.viewport._marker_points == [(0.0, 0.0, 0.0)]


def test_the_first_corner_is_still_what_snapping_measures_from(win):
    _drag(win, "rectangle", "0,0,0", (100.0, 50.0, 0.0))
    assert win.viewport.snap_base == (0.0, 0.0, 0.0)


def test_the_readout_gives_both_sides(win):
    """Not the diagonal: nobody asks a rectangle how far it is corner to
    corner."""
    _drag(win, "rectangle", "0,0,0", (100.0, 50.0, 0.0))
    text = win.viewport._draw_readout.text()
    assert not win.viewport._draw_readout.isHidden()
    assert "100" in text and "50" in text
    assert str(round(math.hypot(100.0, 50.0))) not in text


def test_the_sides_are_the_cplane_sides_not_the_world_ones(win):
    """A rectangle on a tilted plane has the sides it was drawn with."""
    from serpentine3d.core.cplane import PRESETS
    win.viewport.cplane = PRESETS["right"]()          # u is +Y, v is +Z
    req = _drag(win, "rectangle", "0,0,0", (0.0, 30.0, 40.0))
    assert req.rubber_sides((0.0, 30.0, 40.0)) == pytest.approx((30.0, 40.0))


def test_a_flat_rectangle_reads_out_nothing_rather_than_a_line(win):
    """Before the second corner is off the first row, there is no frame."""
    _drag(win, "rectangle", "0,0,0", (100.0, 0.0, 0.0))
    assert win.viewport._draw_readout.isHidden()


@pytest.mark.parametrize("cmd", ["rectangle", "box", "clippingplane"])
def test_nothing_dragged_out_as_a_frame_is_crossed_by_a_band(cmd, win):
    """Three commands ask for an opposite corner over a ghost of the frame
    itself. All three were drawing a diagonal through it."""
    _drag(win, cmd, "0,0,0", (100.0, 50.0, 0.0))
    assert len(win.viewport._preview_data) == 0
    assert win.viewport._draw_readout.text() == "100 mm × 50 mm"


def test_the_height_of_a_box_is_still_a_leg(win):
    """The base is a frame; the pull upwards from it is a line, and the one
    number it has is the height."""
    win.run_command("box")
    win.processor.provide_text("0,0,0")
    win.processor.provide_text("100,50,0")
    win._on_mouse_world((100.0, 50.0, 25.0))
    assert len(win.viewport._preview_data) == 2
    assert win.viewport._draw_readout.text() == "25 mm"


def test_the_line_command_still_gets_its_band(win):
    """The band is right for a line: it is the line."""
    req = _drag(win, "line", "0,0,0", (100.0, 50.0, 0.0))
    assert getattr(req, "rubber_sides", None) is None
    assert len(win.viewport._preview_data) == 2


def test_a_circle_keeps_the_leg_that_is_its_radius(win):
    """Not every ghost makes its band redundant — the leg to a circle's edge
    is the radius, and the number beside it is the one you want."""
    _drag(win, "circle", "0,0,0", (30.0, 0.0, 0.0))
    assert len(win.viewport._preview_data) == 2
    assert "30" in win.viewport._draw_readout.text()


def test_the_frame_readout_goes_when_the_command_does(win):
    _drag(win, "rectangle", "0,0,0", (100.0, 50.0, 0.0))
    win.processor.cancel()
    win._sync_command_state()
    assert win.viewport._draw_readout.isHidden()


def test_rubber_sides_is_a_pair_of_lengths(win):
    req = _drag(win, "rectangle", "0,0,0", (100.0, 50.0, 0.0))
    assert isinstance(req, PointReq)
    assert req.rubber_sides((100.0, 50.0, 0.0)) == pytest.approx((100.0, 50.0))
