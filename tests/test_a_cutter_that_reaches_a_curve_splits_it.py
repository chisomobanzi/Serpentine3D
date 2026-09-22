"""A cutting curve that reaches a curve splits it (issue #32).

The sibling of issue #22, which was the same complaint about surfaces. A
cutting curve only split the target if it overran it; one whose end sat on
the curve did nothing, and the only way through was to draw it longer.

"Exactly on" was never the real case. A cutter whose end is truly
coincident splits today, and so does one that overruns by 1e-12. What
fails is an end that stops a whisker *short*: a gap of 1e-6 is already
enough, while the document tolerance is 1e-3. So OCCT's splitter wants
coincidence a thousand times tighter than the drawing's own idea of
touching, and anything drawn or snapped by hand lands in between.

The cutter is therefore stretched a little past its ends before it is
used, exactly as for a surface. Two things have to agree about what
"reaching" means: the splitter, which needs the stretched cutter to find
a crossing, and `_curve_pieces`, which decides which vertices are cuts
rather than joins. Given the original cutter it would measure the gap,
call the vertex a join and thread the two pieces back into one.
"""

from __future__ import annotations

import pytest

import serpentine3d.commands  # registers the commands  # noqa: F401
from serpentine3d.commands.base import CommandContext, CommandProcessor
from serpentine3d.core import geometry as g
from serpentine3d.core.history import History
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.core.tolerance import tol


def _line():
    return g.make_line((0, 0, 0), (10, 0, 0))


@pytest.fixture
def env():
    scene = Scene()
    selection = SelectionManager(scene)
    ctx = CommandContext(scene, selection, History(scene))
    return scene, CommandProcessor(ctx)


def _lengths(pieces):
    return sorted(g.curve_length(p) for p in pieces)


# --- the reported bug ------------------------------------------------------

@pytest.mark.parametrize("short", [1e-6, 1e-4, tol() / 2, tol(), 0.01])
def test_a_cutter_stopping_a_whisker_short_of_the_curve_splits_it(short):
    cutter = g.make_line((5, -3, 0), (5, -short, 0))

    pieces = g.split_shape(_line(), [cutter])

    assert _lengths(pieces) == pytest.approx([5, 5], abs=1e-6)


def test_the_pieces_are_the_curve_and_nothing_more():
    """Two pieces of five, not one of ten threaded back together."""
    pieces = g.split_shape(_line(), [g.make_line((5, -3, 0), (5, -0.01, 0))])

    assert len(pieces) == 2
    assert sum(_lengths(pieces)) == pytest.approx(10, abs=1e-6)


def test_the_split_command_splits(env):
    """What the report is actually about: the command, not the helper."""
    scene, proc = env
    line = scene.add(_line())
    cutter = scene.add(g.make_line((5, -3, 0), (5, -1e-4, 0)))

    proc.run("split")
    proc.click_object(line.id)
    proc.click_object(cutter.id)
    proc.finish_selection()

    pieces = [o for o in scene.all() if o.id != cutter.id]
    assert len(pieces) == 2
    assert _lengths(p.shape for p in pieces) == pytest.approx([5, 5], abs=1e-6)


def test_the_trim_command_trims(env):
    """Trim shares the same splitter, and #22 named them together."""
    scene, proc = env
    line = scene.add(_line(), name="Target")
    cutter = scene.add(g.make_line((5, -3, 0), (5, -1e-4, 0)), name="Cutter")

    proc.run("trim")
    proc.click_object(cutter.id)
    proc.finish_selection()
    proc.click_object(line.id)

    pieces = [o for o in scene.all() if o.id != cutter.id]
    assert len(pieces) == 2, "nothing to choose between means nothing was cut"
    proc.click_object(pieces[0].id)
    proc.finish_selection()

    left = [o for o in scene.all() if o.id != cutter.id]
    assert len(left) == 1
    assert g.curve_length(left[0].shape) == pytest.approx(5, abs=1e-6)


def test_a_polyline_cutter_stopping_short_splits():
    cutter = g.make_polyline([(3, -2, 0), (5, -1, 0), (5, -1e-4, 0)])

    pieces = g.split_shape(_line(), [cutter])

    assert _lengths(pieces) == pytest.approx([5, 5], abs=1e-6)


def test_a_cutter_touching_at_both_ends_makes_three_pieces():
    arc = g.make_arc_3pt((2, -1e-4, 0), (5, -3, 0), (8, -1e-4, 0))

    pieces = g.split_shape(_line(), [arc])

    assert _lengths(pieces) == pytest.approx([2, 2, 6], abs=1e-3)


# --- what already worked keeps working ------------------------------------

def test_a_cutter_ending_exactly_on_the_curve_still_splits():
    pieces = g.split_shape(_line(), [g.make_line((5, -3, 0), (5, 0, 0))])

    assert _lengths(pieces) == pytest.approx([5, 5], abs=1e-6)


def test_a_cutter_crossing_clean_through_still_splits():
    pieces = g.split_shape(_line(), [g.make_line((5, -3, 0), (5, 3, 0))])

    assert _lengths(pieces) == pytest.approx([5, 5], abs=1e-6)


def test_a_closed_cutter_crossing_the_curve_still_splits():
    """A circle has no ends to stretch, so it must come through untouched."""
    circle = g.make_circle((5, 0, 0), 2, normal=(0, 0, 1))

    pieces = g.split_shape(_line(), [circle])

    assert _lengths(pieces) == pytest.approx([3, 3, 4], abs=1e-6)


# --- a real gap is still a real gap ---------------------------------------

def test_a_cutter_that_stops_well_short_still_refuses():
    cutter = g.make_line((5, -3, 0), (5, -2, 0))

    with pytest.raises(g.GeometryError):
        g.split_shape(_line(), [cutter])


def test_a_cutter_off_to_one_side_still_refuses():
    """Stretching is along the cutter's own tangent, so a cutter pointing
    away from the curve must not suddenly reach it."""
    cutter = g.make_line((5, -3, 0), (8, -3, 0))

    with pytest.raises(g.GeometryError):
        g.split_shape(_line(), [cutter])
