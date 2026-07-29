"""Where an editing command measures a dragged distance from.

A primitive measures its size from the point you just clicked. An editing
command has no such point, so serpentine3d.commands.dragging works one out
from the geometry that is about to change. These tests pin down that choice,
because getting it wrong makes every drag in every edit command feel wrong.
"""

import math

import pytest

from serpentine3d.commands import dragging as d
from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene


@pytest.fixture
def box():
    scene = Scene()
    return scene.add(g.make_box((0, 0, 0), 10, 10, 10))


def test_bounds_spans_everything_selected():
    scene = Scene()
    a = scene.add(g.make_box((0, 0, 0), 1, 1, 1))
    b = scene.add(g.make_box((5, 5, 5), 1, 1, 1))
    lo, hi = d.bounds([a, b])
    assert lo == pytest.approx((0, 0, 0), abs=1e-6)
    assert hi == pytest.approx((6, 6, 6), abs=1e-6)


def test_bounds_of_nothing_is_nothing():
    assert d.bounds([]) is None


def test_edge_point_sits_on_the_outside_not_the_middle(box):
    """A 2 mm wall on a 100 mm box should be a 2 mm drag, so distances are
    measured from the surface of the thing you are changing."""
    p = d.edge_point([box], (1, 0, 0))
    assert p == pytest.approx((10, 5, 5), abs=1e-6)


def test_edge_point_follows_the_direction_given(box):
    assert d.edge_point([box], (0, -1, 0)) == pytest.approx((5, 0, 5), abs=1e-6)


def test_edge_point_takes_an_unnormalised_direction(box):
    assert d.edge_point([box], (7, 0, 0)) == pytest.approx((10, 5, 5), abs=1e-6)


def test_edge_point_of_nothing_is_the_origin():
    assert d.edge_point([], (1, 0, 0)) == (0.0, 0.0, 0.0)


def test_signed_along_is_negative_on_the_other_side():
    f = d.signed_along((0, 0, 0), (0, 0, 1))
    assert f((3, 4, 5)) == pytest.approx(5)
    assert f((3, 4, -5)) == pytest.approx(-5)


def test_signed_along_ignores_the_sideways_part():
    """You are dragging along one axis; where the cursor wanders off it is
    not part of the answer."""
    f = d.signed_along((1, 1, 1), (1, 0, 0))
    assert f((4, 99, -99)) == pytest.approx(3)


def test_signed_along_normalises_the_direction():
    f = d.signed_along((0, 0, 0), (0, 0, 4))
    assert f((0, 0, 5)) == pytest.approx(5)


def test_distance_from_has_no_sign():
    f = d.distance_from((1, 0, 0))
    assert f((4, 4, 0)) == pytest.approx(5)
    assert f((-2, -4, 0)) == pytest.approx(5)


def test_curve_middle_is_on_the_curve():
    line = g.make_line((0, 0, 0), (10, 0, 0))
    assert d.curve_middle(line) == pytest.approx((5, 0, 0), abs=1e-6)


def test_sideways_is_perpendicular_to_the_curve():
    """Offsetting a curve moves it sideways, so that is the way to drag."""
    line = g.make_line((0, 0, 0), (10, 0, 0))
    v = d.sideways(line, (0, 0, 1))
    assert abs(v[2]) < 1e-9, "sideways should stay in the plane"
    assert abs(v[0]) < 1e-6 and abs(abs(v[1]) - 1) < 1e-6
    assert math.isclose(math.dist(v, (0, 0, 0)), 1.0, rel_tol=1e-6)


def test_middle_is_the_centre_of_everything_selected():
    scene = Scene()
    a = scene.add(g.make_box((0, 0, 0), 2, 2, 2))
    b = scene.add(g.make_box((8, 8, 8), 2, 2, 2))
    assert d.middle([a, b]) == pytest.approx((5, 5, 5), abs=1e-6)


def test_middle_of_nothing_is_the_origin():
    assert d.middle([]) == (0.0, 0.0, 0.0)


def test_end_direction_leaves_the_curve_the_way_it_was_going():
    line = g.make_line((0, 0, 0), (10, 0, 0))
    assert d.end_direction(line, "end") == pytest.approx((1, 0, 0), abs=1e-6)
    assert d.end_direction(line, "start") == pytest.approx(
        (-1, 0, 0), abs=1e-6)


def test_grow_direction_reports_which_way_the_shape_went():
    """Some commands grow geometry in a direction only the operation knows.
    Rather than guess it, do a small one and look."""
    box = g.make_box((0, 0, 0), 10, 10, 10)
    v = d.grow_direction(box, lambda t: g.make_box((0, 0, 0), 10 + t, 10, 10))
    assert v == pytest.approx((1, 0, 0), abs=1e-3)


def test_grow_direction_falls_back_when_the_probe_fails():
    box = g.make_box((0, 0, 0), 10, 10, 10)

    def boom(_t):
        raise g.GeometryError("nope")

    assert d.grow_direction(box, boom, fallback=(0, 1, 0)) == (0.0, 1.0, 0.0)
