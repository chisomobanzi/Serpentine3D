"""A detail cut through a pipe draws a ring of wall, not a solid bar.

Turning on a section in a detail used to build its own cutting plane and
hand on a flat list of outlines, so a pipe arrived as two unrelated
circles and the hatch filled the bore in. The detail now asks the same
question the `section` command asks, and gets back regions: the ring
around the outside, and the rings punched out of it.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from serpentine3d.core import geometry as g
from serpentine3d.ui.layout_view import _section_cut


def _pipe():
    return g.boolean_difference(g.make_cylinder((0, 0, 0), 10, 30),
                                g.make_cylinder((0, 0, 0), 6, 30))


def _cut(shapes, offset=0.0, target=(0.0, 0.0, 15.0)):
    """The cut a top-down detail makes, plane through the target."""
    return _section_cut(shapes, np.asarray(target, float),
                        np.array([0.0, 0.0, 1.0]),
                        np.array([1.0, 0.0, 0.0]),
                        np.array([0.0, 1.0, 0.0]), offset)


def _reach(loop):
    return max(math.hypot(x, y) for x, y in loop)


def test_a_pipe_comes_back_as_one_region_with_its_bore_punched_out():
    _shapes, regions = _cut([_pipe()])
    assert len(regions) == 1, f"expected one cut region, got {len(regions)}"
    assert len(regions[0]) == 2, \
        "the bore is not a hole in the ring, so a hatch would fill it"
    outer, hole = regions[0]
    assert _reach(outer) == pytest.approx(10.0, rel=1e-2)
    assert _reach(hole) == pytest.approx(6.0, rel=1e-2)


def test_the_ring_comes_before_the_hole_so_it_reads_as_the_outside():
    _shapes, regions = _cut([_pipe()])
    outer, hole = regions[0]
    assert _reach(outer) > _reach(hole)


def test_a_solid_bar_is_one_region_and_has_nothing_punched_out():
    _shapes, regions = _cut([g.make_box((-5, -5, 0), 10, 10, 30)])
    assert len(regions) == 1 and len(regions[0]) == 1


def test_two_solids_are_two_regions_and_the_gap_between_is_not_material():
    near = g.make_box((-20, -5, 0), 10, 10, 30)
    far = g.make_box((20, -5, 0), 10, 10, 30)
    _shapes, regions = _cut([near, far])
    assert len(regions) == 2, \
        "two bars merged into one region, so the air between them fills in"


def test_the_plane_still_takes_away_what_is_in_front_of_it():
    """The other half of the job: a section detail also clips the model."""
    shapes, _regions = _cut([g.make_box((-5, -5, 0), 10, 10, 30)])
    assert g.volume(shapes[0]) == pytest.approx(1500.0, rel=1e-3), \
        "the near half of the box survived the cut"


def test_a_plane_that_misses_leaves_the_shape_alone_and_cuts_nothing():
    shapes, regions = _cut([g.make_box((-5, -5, 0), 10, 10, 30)],
                           target=(0.0, 0.0, 500.0))
    assert regions == []
    assert g.volume(shapes[0]) == pytest.approx(3000.0, rel=1e-6)


def test_a_surface_is_left_alone_because_there_is_nothing_to_cut_into():
    face = g.planar_face(g.make_polyline(
        [(0, 0, 15), (10, 0, 15), (10, 10, 15), (0, 10, 15)], closed=True))
    shapes, regions = _cut([face])
    assert len(shapes) == 1 and regions == []
