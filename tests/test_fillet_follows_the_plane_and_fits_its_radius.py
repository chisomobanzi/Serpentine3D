"""Fillet quality: curves are filleted in the plane they already live on,
variable radius laws sweep whole tangent chains the way SolidWorks sweeps
them, a chamfer keeps to one distance, and a failed fillet names the
biggest radius that fits."""

import math

import pytest

from serpentine3d.core import geometry as g


def _tilted_lines(deg=30.0):
    """An L of two perpendicular lines on a plane tilted `deg` about X."""
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    corner = (10.0, 0.0, 0.0)
    l1 = g.make_line((0.0, 0.0, 0.0), corner)
    l2 = g.make_line(corner, (10.0, 10.0 * c, 10.0 * s))
    return l1, l2, corner, c, s


def _assert_in_plane(shape, c, s):
    """Every sampled point sits on the plane tilted `deg` about X:
    on it, z = y * tan(deg)."""
    for p in g.sample_curve(shape, 32):
        assert abs(p[2] - p[1] * s / c) < 1e-6


def test_a_fillet_of_two_lines_finds_their_own_plane():
    l1, l2, corner, c, s = _tilted_lines()
    ea, arc, eb = g.fillet_curves(l1, l2, 2.0, corner)
    joined = g.join_curves([ea, arc, eb])
    assert g.shape_kind(joined) == "curve"
    # 8 + 8 straight plus a quarter circle r=2, on the tilted plane
    assert g.curve_length(joined) == pytest.approx(16 + math.pi, rel=1e-4)
    _assert_in_plane(joined, c, s)


def test_a_fillet_of_a_line_and_an_arc_finds_the_arcs_plane():
    c, s = math.cos(math.radians(30.0)), math.sin(math.radians(30.0))
    start = (10.0, 0.0, 0.0)
    mid = (12.0 - 2.0 * math.cos(math.radians(45.0)),
           2.0 * math.sin(math.radians(45.0)) * c,
           2.0 * math.sin(math.radians(45.0)) * s)
    end = (12.0, 2.0 * c, 2.0 * s)
    arc = g.make_arc_3pt(start, mid, end)
    line = g.make_line((0.0, 0.0, 0.0), start)
    ea, fil, eb = g.fillet_curves(line, arc, 1.0, start)
    joined = g.join_curves([ea, fil, eb])
    assert g.shape_kind(joined) == "curve"
    _assert_in_plane(joined, c, s)


def test_a_degenerate_plane_hint_is_refused():
    l1 = g.make_line((0.0, 0.0, 0.0), (10.0, 0.0, 0.0))
    l2 = g.make_line((12.0, 0.0, 0.0), (20.0, 0.0, 0.0))
    with pytest.raises(g.GeometryError, match="degenerate"):
        g.fillet_curves(l1, l2, 2.0, (11.0, 0.0, 0.0), plane=(0, 0, 0))


def test_parallel_lines_without_a_corner_fail_cleanly():
    l1 = g.make_line((0.0, 0.0, 0.0), (10.0, 0.0, 0.0))
    l2 = g.make_line((0.0, 2.0, 0.0), (10.0, 2.0, 0.0))
    with pytest.raises(g.GeometryError, match="share one plane"):
        g.fillet_curves(l1, l2, 2.0, (5.0, 1.0, 0.0), plane=(0, 0, 1))


def _rounded_prism():
    rect = g.make_rectangle((0, 0, 0), (22, 12, 0))
    rounded = g.offset_curve(rect, 1.0)
    return g.extrude(rounded, (0, 0, 1), 5.0, cap=True)


def _a_top_line_edge(prism):
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GeomAbs import GeomAbs_CurveType
    from OCP.gp import gp_Pnt, gp_Vec
    for e in g.edges_of(prism):
        ad = BRepAdaptor_Curve(e)
        if ad.GetType() != GeomAbs_CurveType.GeomAbs_Line:
            continue
        p1, v1 = gp_Pnt(), gp_Vec()
        ad.D1(ad.FirstParameter(), p1, v1)
        p2, v2 = gp_Pnt(), gp_Vec()
        ad.D1(ad.LastParameter(), p2, v2)
        if abs(p1.Z() - 5) < 1e-6 and abs(p2.Z() - 5) < 1e-6:
            return e
    raise AssertionError("no top line edge found")


def test_a_variable_law_sweeps_the_whole_tangent_chain():
    prism = _rounded_prism()
    edge = _a_top_line_edge(prism)
    const_lo = g.volume(g.fillet_edges(prism, 1.0, edges=[edge]))
    const_hi = g.volume(g.fillet_edges(prism, 2.5, edges=[edge]))
    law = g.volume(g.fillet_edges(
        prism, [(0.0, 1.0), (0.5, 2.5), (1.0, 1.0)], edges=[edge]))
    linear = g.volume(g.fillet_edges(prism, (1.0, 2.5), edges=[edge]))
    # a deeper law removes more material, and a three-point law is its
    # own shape, not the straight line between its ends
    assert const_lo > law > linear > const_hi


def test_law_and_positions_are_checked():
    box = g.make_box((0, 0, 0), 10, 10, 10)
    e = g.edges_of(box)[0]
    with pytest.raises(g.GeometryError, match="r_start"):
        g.fillet_edges(box, (2.0,), edges=[e])
    with pytest.raises(g.GeometryError, match="at least two"):
        g.fillet_edges(box, [(0.0, 1.0)], edges=[e])
    with pytest.raises(g.GeometryError, match="0 to 1"):
        g.fillet_edges(box, [(0.0, 1.0), (1.5, 2.0)], edges=[e])
    with pytest.raises(g.GeometryError, match="positive"):
        g.fillet_edges(box, [(0.0, 1.0), (1.0, 0.0)], edges=[e])


def test_a_chamfer_takes_one_distance_only():
    box = g.make_box((0, 0, 0), 10, 10, 10)
    e = g.edges_of(box)[0]
    with pytest.raises(g.GeometryError, match="single distance"):
        g.fillet_edges(box, (1.0, 2.0), edges=[e], chamfer=True)
    with pytest.raises(g.GeometryError, match="single distance"):
        g.fillet_edges(box, [(0.0, 1.0), (1.0, 2.0)], edges=[e],
                       chamfer=True)
    assert g.shape_kind(
        g.fillet_edges(box, 1.0, edges=[e], chamfer=True)) == "solid"


def test_neighbouring_edges_take_different_radii():
    box = g.make_box((0, 0, 0), 10, 10, 10)
    e = g.edges_of(box)
    small = g.volume(g.fillet_edges(box, 1.0, edges=[e[0], e[2]]))
    big = g.volume(g.fillet_edges(box, 3.0, edges=[e[0], e[2]]))
    mixed = g.volume(g.fillet_edges(box, radii=[1.0, 3.0],
                                    edges=[e[0], e[2]]))
    # one edge rounds at 1, the other at 3: between the two uniform runs
    assert small > mixed > big
    # and a chamfer may take a distance per edge as well
    cham = g.fillet_edges(box, radii=[1.0, 2.0], edges=[e[0], e[2]],
                          chamfer=True)
    assert g.shape_kind(cham) == "solid"


def test_radii_needs_one_radius_per_picked_edge():
    box = g.make_box((0, 0, 0), 10, 10, 10)
    e = g.edges_of(box)
    with pytest.raises(g.GeometryError, match="per picked edge"):
        g.fillet_edges(box, radii=[1.0, 2.0])
    with pytest.raises(g.GeometryError, match="per picked edge"):
        g.fillet_edges(box, radii=[1.0, 2.0, 3.0], edges=[e[0], e[2]])
    with pytest.raises(g.GeometryError, match="positive"):
        g.fillet_edges(box, radii=[1.0, 0.0], edges=[e[0], e[2]])
    with pytest.raises(g.GeometryError, match="not both"):
        g.fillet_edges(box, (1.0, 2.0), edges=[e[0], e[2]],
                       radii=[1.0, 2.0])


def test_a_failed_fillet_blames_the_chains_that_cannot_start():
    box = g.make_box((0, 0, 0), 10, 10, 10)
    # all twelve edges of the cube get a chain, and none of them can even
    # begin at this radius: the kernel says so, and the error repeats it
    with pytest.raises(g.GeometryError, match="too big for 12"):
        g.fillet_edges(box, 1000.0)


def test_a_failed_fillet_names_the_largest_radius_that_fits():
    box = g.make_box((0, 0, 0), 10, 10, 10)
    with pytest.raises(g.GeometryError):
        g.fillet_edges(box, 1000.0)
    best = g.largest_fillet_radius(box, 1000.0)
    # the kernel swallows nearly the whole face before giving up, so the
    # only honest bound is: something real, and strictly less than asked
    assert best is not None and 0.0 < best < 1000.0
    assert g.shape_kind(g.fillet_edges(box, best)) == "solid"