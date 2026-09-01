"""A section hands back the cut itself, not just its outline.

Cutting a solid with a plane is how you get a section drawing out of a
model, and what a section drawing shows is material: the face the saw
went through, filled in. An outline cannot say which side is solid, so a
pipe cut across reads as two unrelated circles rather than a ring of
wall with a bore down the middle. Once the cut is a face, the hole is a
hole, and hatching it is a matter of filling the face.

Surfaces are different and stay curves: a surface has no inside, so
there is nothing for the plane to cut a face out of.
"""

from __future__ import annotations

import math

import pytest

from serpentine3d.core import geometry as g


# -- what the plane cuts out of a solid --

def test_a_plane_through_a_box_gives_the_rectangle_it_cut():
    box = g.make_box((0, 0, 0), 10, 20, 30)
    faces = g.section_regions(box, (0, 0, 15), (0, 0, 1))
    assert len(faces) == 1, f"expected one cut face, got {len(faces)}"
    assert g.surface_area(faces[0]) == pytest.approx(200.0, rel=1e-6), \
        "the cut face is not the 10 by 20 rectangle the plane went through"


def test_a_section_through_a_pipe_keeps_the_hole():
    """The whole reason a section is a face and not an outline.

    A pipe cut across is a ring of wall. Given only the outline you get
    two circles and no way to tell which one is material, so a hatch
    fills the bore in as though the pipe were a solid bar.
    """
    outer = g.make_cylinder((0, 0, 0), 10, 30)
    inner = g.make_cylinder((0, 0, 0), 6, 30)
    pipe = g.boolean_difference(outer, inner)
    faces = g.section_regions(pipe, (0, 0, 15), (0, 0, 1))
    assert len(faces) == 1, f"expected one cut face, got {len(faces)}"
    ring = math.pi * (10 ** 2 - 6 ** 2)
    assert g.surface_area(faces[0]) == pytest.approx(ring, rel=1e-3), \
        "the bore was filled in, so the cut reads as a solid bar"


def test_the_hole_comes_back_as_a_loop_inside_the_outer_one():
    """Whoever draws or hatches the cut needs to know which ring is which."""
    outer = g.make_cylinder((0, 0, 0), 10, 30)
    inner = g.make_cylinder((0, 0, 0), 6, 30)
    pipe = g.boolean_difference(outer, inner)
    face = g.section_regions(pipe, (0, 0, 15), (0, 0, 1))[0]
    loops = g.face_loops(face, 96)
    assert len(loops) == 2, \
        f"expected an outer ring and a hole, got {len(loops)}"

    def radius(loop):
        return max(math.hypot(p[0], p[1]) for p in loop)

    assert radius(loops[0]) > radius(loops[1]), \
        "the hole came back first, so the outer ring would be read as a hole"


# -- when the plane misses --

def test_a_plane_that_misses_the_solid_gives_nothing_rather_than_failing():
    """A section is usually asked of several objects at once.

    Some of them will not be anywhere near the line you drew, and that
    is normal, not an error. Only the command knows whether missing
    everything is worth complaining about.
    """
    box = g.make_box((0, 0, 0), 10, 10, 10)
    assert g.section_regions(box, (0, 0, 500), (0, 0, 1)) == []
    assert g.section_curves(box, (0, 0, 500), (0, 0, 1)) == []


# -- surfaces stay curves --

def test_a_section_of_a_surface_gives_a_curve_because_it_has_no_inside():
    face = g.planar_face(g.make_polyline(
        [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)], closed=True))
    curves = g.section_curves(face, (5, 0, 0), (1, 0, 0))
    assert curves, "the plane crossed the surface but gave no curve"
    assert g.section_regions(face, (5, 0, 0), (1, 0, 0)) == [], \
        "a surface has no inside, so there is no face to cut out of it"
