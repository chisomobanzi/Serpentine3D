"""A hatch takes the commands its boundary would (#45).

A hatch in the model is a region with a pattern on it, so the two
commands that work on what a region is bounded by should work on it:
DupBorder hands back the closed curves around it, and Trim cuts it with
curves the way it cuts a surface, leaving hatches rather than a hole.

Trimming keeps the pattern where it was: the lines belong to the hatch's
own frame, not to the piece, so a cut hatch is the same drawing with
part of it taken away rather than two drawings restarted at their own
corners.
"""

from __future__ import annotations

import math

import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.hatch import HatchShape


def _square(size=10.0, corner=(0.0, 0.0), z=0.0):
    x, y = corner
    return g.make_polyline([(x, y, z), (x + size, y, z),
                            (x + size, y + size, z), (x, y + size, z)],
                           closed=True)


def _hatch(size=10.0, pattern="lines", angle=0.0, spacing=1.0):
    (face,) = g.planar_regions([_square(size)])
    return HatchShape(face, pattern, angle=angle, spacing=spacing)


def _pick(proc, *objs):
    for o in objs:
        proc.click_object(o.id)
    proc.finish_selection()


# -- the shape itself ------------------------------------------------------

def test_a_hatch_can_be_split_by_a_curve():
    hatch = _hatch()
    knife = g.make_polyline([(5, -2, 0), (5, 12, 0)])
    pieces = g.split_shape(hatch, [knife], direction=(0, 0, 1))
    assert len(pieces) == 2
    for piece in pieces:
        assert g.shape_kind(piece) == "hatch"
        assert g.surface_area(piece) == pytest.approx(50.0, rel=1e-6)


def test_the_pieces_keep_the_pattern_they_were_cut_from():
    hatch = _hatch(pattern="lines", angle=30.0, spacing=0.75)
    knife = g.make_polyline([(5, -2, 0), (5, 12, 0)])
    for piece in g.split_shape(hatch, [knife], direction=(0, 0, 1)):
        assert piece.pattern == "lines"
        assert piece.angle == pytest.approx(30.0)
        assert piece.spacing == pytest.approx(0.75)


def test_a_cut_hatch_draws_its_lines_where_the_whole_one_did():
    """The pattern is fixed to the hatch's frame, so the lines of the two
    halves still line up with each other across the cut."""
    whole = _hatch(angle=0.0, spacing=1.0)
    knife = g.make_polyline([(5, -2, 0), (5, 12, 0)])
    left, right = g.split_shape(whole, [knife], direction=(0, 0, 1))
    heights = lambda h: sorted({round(float(a[1]), 6)
                                for a, _b in h.pattern_segments()})
    assert heights(left) == heights(right)
    assert set(heights(left)) <= set(heights(whole))


def test_a_solid_hatch_cuts_too():
    hatch = _hatch(pattern="solid")
    knife = g.make_polyline([(5, -2, 0), (5, 12, 0)])
    pieces = g.split_shape(hatch, [knife], direction=(0, 0, 1))
    assert len(pieces) == 2
    assert all(p.pattern == "solid" for p in pieces)


# -- the commands ----------------------------------------------------------

def test_dupborder_gives_back_the_curves_around_a_hatch(env):
    scene, _sel, _hist, _ctx, proc = env
    hatch = scene.add(_hatch(), name="Hatch")

    proc.run("dupborder")
    _pick(proc, hatch)

    curves = [o for o in scene.all() if o.kind == "curve"]
    assert len(curves) == 1
    assert g.is_closed_curve(curves[0].shape)
    assert g.surface_area(g.planar_face(curves[0].shape)) \
        == pytest.approx(100.0, rel=1e-6)
    assert scene.get(hatch.id) is not None, "the hatch itself is kept"


def test_dupborder_gives_back_a_hole_as_its_own_curve(env):
    scene, _sel, _hist, _ctx, proc = env
    (face,) = g.planar_regions([_square(10.0), g.make_circle((5, 5, 0), 2.0)])
    hatch = scene.add(HatchShape(face, "lines"), name="Hatch")

    proc.run("dupborder")
    _pick(proc, hatch)

    curves = [o for o in scene.all() if o.kind == "curve"]
    assert len(curves) == 2, "the outline and the hole"
    areas = sorted(g.surface_area(g.planar_face(c.shape)) for c in curves)
    assert areas[0] == pytest.approx(math.pi * 4, rel=1e-3)
    assert areas[1] == pytest.approx(100.0, rel=1e-6)


def test_trim_takes_away_the_part_of_a_hatch_you_click(env):
    scene, _sel, _hist, _ctx, proc = env
    hatch = scene.add(_hatch(), name="Hatch")
    knife = scene.add(g.make_polyline([(5, -2, 0), (5, 12, 0)]), name="Knife")

    proc.run("trim")
    _pick(proc, knife)
    proc.click_object(hatch.id, at=(2.0, 5.0, 0.0))
    proc.finish_selection()

    left = [o for o in scene.all() if o.kind == "hatch"]
    assert len(left) == 1, "the clicked half went, the other stayed"
    assert g.surface_area(left[0].shape) == pytest.approx(50.0, rel=1e-6)
    assert left[0].name == "Hatch", "the piece keeps the name it had"
