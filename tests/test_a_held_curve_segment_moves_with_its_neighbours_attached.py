"""A segment of a polyline or polycurve can be moved on its own (issue #25).

Rhino lets you Ctrl+Shift-click one segment of a polycurve and drag it
with the gumball: the segment goes where you take it and the segments
either side stretch so the curve stays in one piece, which is how you
drag one side of a rectangle to resize it. `transform_segments` is the
geometry of that: a point map applied to the held segments, and the
neighbours' shared ends carried along.
"""

import math

import numpy as np
import pytest

from serpentine3d.core import geometry as g


def _rect():
    return g.make_polyline(
        [(0, 0, 0), (10, 0, 0), (10, 6, 0), (0, 6, 0)], closed=True)


def _edge_at(shape, mid):
    """Index (in edges_of order) of the edge whose midpoint is `mid`."""
    for i, e in enumerate(g.edges_of(shape)):
        if math.dist(g.centroid(e), mid) < 1e-6:
            return i
    raise AssertionError(f"no edge with midpoint {mid}")


def _ends(shape):
    return [tuple(round(v, 6) for v in p)
            for e in g.edges_of(shape) for p in g.curve_endpoints(e)]


def _shift(delta):
    d = np.asarray(delta, float)
    return lambda p: np.asarray(p, float) + d


def test_moving_one_side_of_a_rectangle_resizes_it():
    rect = _rect()
    bottom = _edge_at(rect, (5, 0, 0))
    out = g.transform_segments(rect, [bottom], _shift((0, -2, 0)))
    assert g.is_closed_curve(out)
    assert len(g.edges_of(out)) == 4
    lo, hi = g.bbox(out)
    assert lo == pytest.approx((0, -2, 0), abs=1e-6)
    assert hi == pytest.approx((10, 6, 0), abs=1e-6)
    ends = set(_ends(out))
    assert (0.0, -2.0, 0.0) in ends and (10.0, -2.0, 0.0) in ends
    assert (0.0, 6.0, 0.0) in ends and (10.0, 6.0, 0.0) in ends
    assert (0.0, 0.0, 0.0) not in ends, "the old corners are gone"


def test_move_segments_is_the_same_by_a_delta():
    rect = _rect()
    bottom = _edge_at(rect, (5, 0, 0))
    a = g.transform_segments(rect, [bottom], _shift((0, -2, 0)))
    b = g.move_segments(rect, [bottom], (0, -2, 0))
    assert set(_ends(a)) == set(_ends(b))


def test_the_middle_of_an_open_polyline_takes_both_neighbours_with_it():
    pl = g.make_polyline([(0, 0, 0), (10, 0, 0), (20, 0, 0), (30, 0, 0)])
    mid = _edge_at(pl, (15, 0, 0))
    out = g.transform_segments(pl, [mid], _shift((0, 5, 0)))
    assert not g.is_closed_curve(out)
    assert len(g.edges_of(out)) == 3
    ends = set(_ends(out))
    # the free ends stay, the shared corners moved with the segment
    assert {(0.0, 0.0, 0.0), (30.0, 0.0, 0.0),
            (10.0, 5.0, 0.0), (20.0, 5.0, 0.0)} <= ends
    assert (10.0, 0.0, 0.0) not in ends and (20.0, 0.0, 0.0) not in ends


def test_an_end_segment_only_stretches_the_one_neighbour_it_has():
    pl = g.make_polyline([(0, 0, 0), (10, 0, 0), (20, 0, 0)])
    last = _edge_at(pl, (15, 0, 0))
    out = g.transform_segments(pl, [last], _shift((0, 5, 0)))
    ends = set(_ends(out))
    assert {(0.0, 0.0, 0.0), (10.0, 5.0, 0.0), (20.0, 5.0, 0.0)} <= ends
    assert len(g.edges_of(out)) == 2


def test_a_curved_neighbour_keeps_hold_of_the_moved_corner():
    line = g.make_line((0, 0, 0), (10, 0, 0))
    arc = g.make_arc_3pt((10, 0, 0), (13, 3, 0), (10, 6, 0))
    poly = g.join_curves([line, arc])
    assert len(g.edges_of(poly)) == 2
    straight = _edge_at(poly, (5, 0, 0))
    out = g.transform_segments(poly, [straight], _shift((0, -2, 0)))
    edges = g.edges_of(out)
    assert len(edges) == 2
    curved = next(e for e in edges if math.dist(g.centroid(e), (5, -2, 0)) > 1e-6)
    a, b = g.curve_endpoints(curved)
    ends = {tuple(round(v, 6) for v in a), tuple(round(v, 6) for v in b)}
    assert ends == {(10.0, -2.0, 0.0), (10.0, 6.0, 0.0)}
    assert g.curve_length(curved) > 8, "still an arc, not collapsed to a line"


def test_turning_a_side_swings_its_neighbours_after_it():
    rect = _rect()
    bottom = _edge_at(rect, (5, 0, 0))
    anchor = np.array([5.0, 0.0, 0.0])

    def quarter_turn(p):
        v = np.asarray(p, float) - anchor
        return anchor + np.array([-v[1], v[0], v[2]])

    out = g.transform_segments(rect, [bottom], quarter_turn)
    ends = set(_ends(out))
    assert {(5.0, -5.0, 0.0), (5.0, 5.0, 0.0),
            (0.0, 6.0, 0.0), (10.0, 6.0, 0.0)} <= ends
    assert g.is_closed_curve(out)


def test_two_adjoining_segments_move_as_one():
    rect = _rect()
    bottom = _edge_at(rect, (5, 0, 0))
    right = _edge_at(rect, (10, 3, 0))
    out = g.transform_segments(rect, [bottom, right], _shift((1, -1, 0)))
    ends = set(_ends(out))
    # the corner they share moved once, the far corners stayed
    assert {(1.0, -1.0, 0.0), (11.0, -1.0, 0.0), (11.0, 5.0, 0.0),
            (0.0, 6.0, 0.0)} <= ends
    assert (10.0, 0.0, 0.0) not in ends
    assert g.is_closed_curve(out)


def test_a_lone_line_just_moves_whole():
    line = g.make_line((0, 0, 0), (10, 0, 0))
    out = g.transform_segments(line, [0], _shift((0, 3, 0)))
    assert set(_ends(out)) == {(0.0, 3.0, 0.0), (10.0, 3.0, 0.0)}


def test_a_bad_index_is_refused():
    with pytest.raises(g.GeometryError):
        g.transform_segments(_rect(), [7], _shift((0, 1, 0)))
