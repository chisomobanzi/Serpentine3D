"""A cutting curve that reaches a surface's edge splits it (issue #22).

Only a curve that overlapped the edges would split or trim a surface; one
snapped so its ends sat on the edges did nothing. The exact case worked all
along, but a snapped end lands a micron to a fraction of a millimetre inside
and OCCT's splitter then finds no crossing. Rhino counts a curve that gets
to the edge within tolerance as reaching it, so the cutter is stretched a
little past its ends before it is swept into the tool.
"""

import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.tolerance import tol


def _square():
    return g.planar_face(g.make_polyline(
        [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)], closed=True))


def _areas(pieces):
    return sorted(g.surface_area(p) for p in pieces)


@pytest.mark.parametrize("short", [1e-6, 1e-4, tol() / 2, tol()])
def test_a_cutter_ending_within_tolerance_of_the_edges_splits(short):
    cutter = g.make_line((5, short, 0), (5, 10 - short, 0))
    pieces = g.split_shape(_square(), [cutter])
    assert _areas(pieces) == pytest.approx([50, 50], abs=1e-6)


def test_a_slanted_cutter_ending_just_inside_splits():
    cutter = g.make_line((1e-5, 1e-5, 0), (10 - 1e-5, 7 - 1e-5, 0))
    pieces = g.split_shape(_square(), [cutter])
    assert len(pieces) == 2
    assert sum(_areas(pieces)) == pytest.approx(100, abs=1e-6)


def test_a_polyline_cutter_reaching_both_edges_splits():
    cutter = g.make_polyline([(5, 1e-4, 0), (6, 5, 0), (5, 10 - 1e-4, 0)])
    pieces = g.split_shape(_square(), [cutter])
    assert len(pieces) == 2
    assert sum(_areas(pieces)) == pytest.approx(100, abs=1e-6)


def test_a_cutter_stopping_well_inside_still_does_not_split():
    cutter = g.make_line((5, 2, 0), (5, 8, 0))
    with pytest.raises(g.GeometryError):
        g.split_shape(_square(), [cutter])


def test_a_solid_is_cut_by_a_curve_reaching_its_silhouette():
    box = g.make_box((0, 0, 0), 10, 10, 10)
    cutter = g.make_line((5, 1e-4, 0), (5, 10 - 1e-4, 0))
    pieces = g.split_shape(box, [cutter], direction=(0, 0, 1))
    assert len(pieces) == 2
