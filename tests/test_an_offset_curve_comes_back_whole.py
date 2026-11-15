"""Offset keeps a curve's corners sharp (#137), and never hands back a
broken curve.

OpenCascade's sharp join gives up where a spline meets another segment at
an angle, or at a corner too sharp to extend, and still says it is done: it
returns nothing, an open curve for a closed one, or a piece of the curve. A
sharp corner is never shorter than an arc round the same corner, so the
round offset is what a sharp one is measured against, and what is used
where the sharp one comes back short.
"""

import pytest

import serpentine3d.commands  # registers all commands  # noqa: F401
from serpentine3d.commands.base import CommandContext, CommandProcessor
from serpentine3d.core import geometry as g
from serpentine3d.core.history import History
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager


def _spline_over_a_line():
    """A D lying down: a spline arching over a straight base."""
    return g.join_curves([
        g.make_interp_curve([(0, 0, 0), (5, 2, 0), (10, 0, 0)]),
        g.make_line((10, 0, 0), (0, 0, 0))])


def _rectangle_with_a_spline_top():
    return g.join_curves([
        g.make_line((0, 10, 0), (0, 0, 0)),
        g.make_line((0, 0, 0), (20, 0, 0)),
        g.make_line((20, 0, 0), (20, 10, 0)),
        g.make_interp_curve([(20, 10, 0), (14, 13, 0), (6, 12, 0),
                             (0, 10, 0)])])


def _line_into_a_spline():
    return g.join_curves([
        g.make_line((-10, 0, 0), (0, 0, 0)),
        g.make_interp_curve([(0, 0, 0), (5, 5, 0), (10, 4, 0)])])


def _sliver():
    """A triangle with a corner of under three degrees."""
    return g.make_polyline([(0, 0, 0), (20, 0, 0), (0, 1, 0)], closed=True)


def test_a_spline_over_a_line_offsets_to_a_closed_curve_round_it():
    curve = _spline_over_a_line()
    off = g.offset_curve(curve, 1.0)
    assert g.is_closed_curve(off)
    assert g.curve_length(off) > g.curve_length(curve)


def test_a_rectangle_with_a_spline_top_offsets_whole():
    curve = _rectangle_with_a_spline_top()
    off = g.offset_curve(curve, 1.0)
    assert g.is_closed_curve(off)
    assert g.curve_length(off) > g.curve_length(curve)


def test_a_line_running_into_a_spline_offsets_its_whole_length():
    curve = _line_into_a_spline()
    off = g.offset_curve(curve, 1.0)
    assert not g.is_closed_curve(off)
    assert g.curve_length(off) == pytest.approx(g.curve_length(curve),
                                                abs=2.0)


def test_a_corner_too_sharp_to_extend_is_rounded_instead():
    curve = _sliver()
    off = g.offset_curve(curve, 2.0)
    assert g.is_closed_curve(off)
    assert g.curve_length(off) > g.curve_length(curve)


def test_lines_and_arcs_keep_their_corners_sharp():
    """A half disc offset outward: the arc runs on round its own circle
    until it meets the base line, so two pieces and no arc at the corners."""
    half_disc = g.join_curves([
        g.make_arc_3pt((-10, 0, 0), (0, -10, 0), (10, 0, 0)),
        g.make_line((10, 0, 0), (-10, 0, 0))])
    off = g.offset_curve(half_disc, 2.0)
    assert len(g.edges_of(off)) == 2
    # the base at y = 2 meets the radius-12 circle at x = +-sqrt(140)
    base = 2 * 140 ** 0.5
    arc = 12 * (3.141592653589793 + 2 * 0.16744807921968935)
    assert g.curve_length(off) == pytest.approx(base + arc, rel=1e-6)


def test_an_offset_that_leaves_nothing_says_so():
    with pytest.raises(g.GeometryError):
        g.offset_curve(_sliver(), -2.0)


def test_an_offset_in_past_the_middle_leaves_no_sliver_of_a_corner():
    """The D is barely 2 high: 1 in from every side there is nothing left,
    though a sharp join still makes a speck of a corner there."""
    with pytest.raises(g.GeometryError):
        g.offset_curve(_spline_over_a_line(), -1.0)


@pytest.fixture
def env():
    scene = Scene()
    selection = SelectionManager(scene)
    ctx = CommandContext(scene, selection, History(scene))
    return scene, selection, ctx, CommandProcessor(ctx)


def test_offset_adds_nothing_when_the_curve_closes_up(env):
    scene, sel, ctx, proc = env
    said = []
    ctx.echo = said.append
    sliver = scene.add(_sliver())
    sel.set([sliver.id])
    proc.run("offset")
    proc.provide_text("-2")
    assert not proc.busy
    assert [o.id for o in scene.all()] == [sliver.id]
    assert any("nothing" in line for line in said)
