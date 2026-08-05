"""A curve used as a cutter is swept along the plane it was drawn on.

An open curve is not a cutting tool on its own, so split makes one out of
it by sweeping it into a surface. Which way it sweeps decides which way the
solid falls apart, and it used to sweep straight up the world Z axis
whatever pane you were looking at. Draw a line across a box in Front and
you would ask for a cut through the middle and get one down the end.

The sweep now goes along the normal of the plane the command is drawing on,
which in a Front pane is front to back, so the cut lands where the line
looked like it was.
"""

from __future__ import annotations

import math

import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.cplane import PRESETS
from tests.conftest import StubViewport


def _box():
    """10 x 4 x 6 at the origin: 240 units, and no two sides alike, so half
    of it is only ever half of one axis."""
    return g.make_box((0, 0, 0), 10, 4, 6)


def _line_across_the_front():
    """A line drawn in a Front pane, halfway up and running past both ends.

    It lies flat in the pane, so nothing about the line itself says which
    way it should sweep: only the pane does.
    """
    return g.make_line((-2, 0, 3), (12, 0, 3))


def test_a_line_drawn_in_front_cuts_the_box_in_half_front_to_back():
    pieces = g.split_shape(_box(), [_line_across_the_front()],
                           direction=(0, -1, 0))
    assert len(pieces) == 2
    assert sorted(g.volume(p) for p in pieces) == pytest.approx(
        [120, 120], rel=1e-6)


def test_the_halves_are_stacked_one_above_the_other():
    """Not side by side: the line was at z = 3 and that is where the cut
    is, so one piece sits under it and the other on top."""
    pieces = g.split_shape(_box(), [_line_across_the_front()],
                           direction=(0, -1, 0))
    zs = sorted(g.centroid(p)[2] for p in pieces)
    assert zs == pytest.approx([1.5, 4.5], abs=1e-6)


def test_the_same_line_drawn_in_top_still_sweeps_upward():
    """The way it always worked, and still the right answer there."""
    line = g.make_line((-2, 2, 0), (12, 2, 0))
    pieces = g.split_shape(_box(), [line], direction=(0, 0, 1))
    assert len(pieces) == 2
    assert sorted(g.volume(p) for p in pieces) == pytest.approx(
        [120, 120], rel=1e-6)


def test_a_sweep_up_the_world_is_what_you_get_if_nobody_says():
    """The old call still means the old thing, so a caller with no pane to
    speak for it is no worse off than it was."""
    line = g.make_line((-2, 2, 0), (12, 2, 0))
    assert len(g.split_shape(_box(), [line])) == 2


def test_a_slanted_sweep_cuts_slantwise():
    """Nothing here is special about the world axes: the sweep goes
    whichever way it is handed, and the pieces still add up to the box."""
    d = (0.0, -math.cos(math.radians(30)), math.sin(math.radians(30)))
    pieces = g.split_shape(_box(), [_line_across_the_front()], direction=d)
    assert len(pieces) == 2
    assert sum(g.volume(p) for p in pieces) == pytest.approx(240, rel=1e-6)


def _in_the_front_pane(ctx):
    """The context as it stands when you are working in Front."""
    vp = StubViewport("model")
    vp.cplane = PRESETS["front"]()
    ctx.viewport = vp


def _solids(scene):
    return [o for o in scene.all() if o.kind == "solid"]


@pytest.mark.parametrize("name", ["booleansplit", "split"])
def test_the_command_cuts_the_way_the_pane_is_facing(env, name):
    """The whole bug, from the command line: a box, a line drawn across it
    in Front, and two halves stacked rather than two ends."""
    scene, sel, _hist, ctx, proc = env
    _in_the_front_pane(ctx)
    box = scene.add(_box())
    line = scene.add(_line_across_the_front())
    sel.set([box.id])
    proc.run(name)
    proc.click_object(line.id)
    proc.finish_selection()
    pieces = _solids(scene)
    assert len(pieces) == 2
    zs = sorted(g.centroid(p.shape)[2] for p in pieces)
    assert zs == pytest.approx([1.5, 4.5], abs=1e-6)


def test_trim_cuts_the_same_way(env):
    """Trim splits first and asks which piece to throw away second, so it
    has the same sweep to get right."""
    scene, sel, _hist, ctx, proc = env
    _in_the_front_pane(ctx)
    box = scene.add(_box())
    line = scene.add(_line_across_the_front())
    sel.set([line.id])
    proc.run("trim")
    proc.click_object(box.id)
    proc.finish_selection()
    pieces = _solids(scene)
    assert len(pieces) == 2
    zs = sorted(g.centroid(p.shape)[2] for p in pieces)
    assert zs == pytest.approx([1.5, 4.5], abs=1e-6)
