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
    """Parallel lines have no corner, however far they are carried out,
    and that is what is said rather than anything about the radius."""
    l1 = g.make_line((0.0, 0.0, 0.0), (10.0, 0.0, 0.0))
    l2 = g.make_line((0.0, 2.0, 0.0), (10.0, 2.0, 0.0))
    with pytest.raises(g.GeometryError, match="do not cross"):
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


def test_a_variable_law_runs_straight_when_asked():
    prism = _rounded_prism()
    edge = _a_top_line_edge(prism)
    const_lo = g.volume(g.fillet_edges(prism, 1.0, edges=[edge]))
    const_hi = g.volume(g.fillet_edges(prism, 2.5, edges=[edge]))
    smooth = g.volume(g.fillet_edges(
        prism, [(0.0, 1.0), (0.5, 2.5), (1.0, 1.0)], edges=[edge]))
    straight = g.volume(g.fillet_edges(
        prism, [(0.0, 1.0), (0.5, 2.5), (1.0, 1.0)], edges=[edge],
        transition="straight"))
    assert const_lo > smooth > const_hi
    assert const_lo > straight > const_hi
    assert abs(smooth - straight) > 1e-3
    with pytest.raises(g.GeometryError, match="'smooth' or 'straight'"):
        g.fillet_edges(prism, [(0.0, 1.0), (1.0, 2.0)], edges=[edge],
                       transition="wobbly")


def test_law_and_positions_are_checked():
    box = g.make_box((0, 0, 0), 10, 10, 10)
    e = g.edges_of(box)[0]
    with pytest.raises(g.GeometryError, match="r_start"):
        g.fillet_edges(box, (2.0,), edges=[e])
    with pytest.raises(g.GeometryError, match="at least two"):
        g.fillet_edges(box, [(0.0, 1.0)], edges=[e])
    with pytest.raises(g.GeometryError, match="0 to 1"):
        g.fillet_edges(box, [(0.0, 1.0), (1.5, 2.0)], edges=[e])
    with pytest.raises(g.GeometryError, match="negative"):
        g.fillet_edges(box, [(0.0, 1.0), (1.0, -1.0)], edges=[e])
    # zero radii may taper a law's ends, never fill it
    with pytest.raises(g.GeometryError, match="zero radius may end"):
        g.fillet_edges(box, [(0.0, 1.0), (0.5, 0.0), (1.0, 1.0)], edges=[e])
    with pytest.raises(g.GeometryError, match="zero radius may end"):
        g.fillet_edges(box, [(0.0, 0.0), (1.0, 0.0)], edges=[e])


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


def test_fillet_corners_rounds_a_closed_rectangle_in_one_go():
    rect = g.make_rectangle((0, 0, 0), (20, 10, 0))
    out = g.fillet_corners(rect, 2.0)
    assert g.shape_kind(out) == "curve"
    assert g.is_closed_curve(out)
    # perimeter 60, four rounds eat 2r each and give back four quarter arcs
    assert g.curve_length(out) == pytest.approx(44 + 4 * math.pi, rel=1e-4)


def test_fillet_corners_handles_left_and_right_turns():
    # an open U: one left turn, one right turn
    u = g.make_polyline([(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)])
    out = g.fillet_corners(u, 1.0)
    assert not g.is_closed_curve(out)
    assert g.curve_length(out) == pytest.approx(26 + math.pi, rel=1e-4)


def test_fillet_corners_skips_corners_that_are_already_smooth():
    rect = g.make_rectangle((0, 0, 0), (22, 12, 0))
    rounded = g.offset_curve(rect, 1.0)     # every corner is an arc joint
    out = g.fillet_corners(rounded, 2.0)
    assert g.curve_length(out) == pytest.approx(
        g.curve_length(rounded), rel=1e-6)


def test_fillet_corners_refuses_a_radius_that_overlaps_a_piece():
    rect = g.make_rectangle((0, 0, 0), (10, 10, 0))
    with pytest.raises(g.GeometryError, match="overlap"):
        g.fillet_corners(rect, 6.0)


def test_fillet_corners_rounds_an_arc_corner_with_exact_length():
    # line (0,0)->(10,0) meets an arc of radius 3 centred on (13,0) head
    # on: its tangent at (10,0) points straight down. The round of r=1
    # touches the line where the circle of centres around (13,0) at
    # distance 3+1 meets distance 1 from the line: x = 13 - sqrt(15).
    # From there the geometry is exact: the round sweeps acos(1/4) and
    # the original arc keeps 3*(pi/2 - acos(sqrt(15)/4)).
    line = g.make_line((0, 0, 0), (10, 0, 0))
    arc = g.make_arc_3pt(
        (10, 0, 0), (13 - 3 / math.sqrt(2), -3 / math.sqrt(2), 0), (13, -3, 0))
    open_curve = g.join_curves([line, arc])
    out = g.fillet_corners(open_curve, 1.0)
    assert g.is_valid(out)
    assert not g.is_closed_curve(out)
    expected = ((13 - math.sqrt(15)) + math.acos(0.25)
                + 3 * (math.pi / 2 - math.acos(math.sqrt(15) / 4)))
    assert g.curve_length(out) == pytest.approx(expected, rel=1e-6)
    assert g.curve_endpoints(out) == ((0, 0, 0), (13, -3, 0))


def test_fillet_corners_rounds_an_arc_to_arc_corner():
    # the first arc arrives at (4,0) heading down, the second leaves
    # heading right: a 90-degree corner between two arcs
    first = g.make_arc_3pt((0, 0, 0), (2, 2, 0), (4, 0, 0))
    second = g.make_arc_3pt(
        (4, 0, 0), (4 + 3 / math.sqrt(2), -3 + 3 / math.sqrt(2), 0), (7, -3, 0))
    open_curve = g.join_curves([first, second])
    out = g.fillet_corners(open_curve, 0.5)
    assert g.is_valid(out)
    assert g.curve_length(out) < g.curve_length(open_curve)
    assert g.curve_endpoints(out) == ((0, 0, 0), (7, -3, 0))


def test_fillet_corners_refuses_a_radius_that_overlaps_on_an_arc():
    # a shallow arc piece (R=5, 0.785 long) between two corners: both
    # rounds build at r=0.5, but at r=0.6 they want more of the piece
    # than its 0.785 of arc — refused with the piece's number
    phi = 0.785 / 5.0
    center = (4.0, -5.0)
    start = (4.0, 0.0)
    mid_pt = (center[0] + 5 * math.sin(phi / 2),
              center[1] + 5 * math.cos(phi / 2))
    end = (center[0] + 5 * math.sin(phi), center[1] + 5 * math.cos(phi))
    first = g.make_line((4, -10, 0), (4, 0, 0))
    mid = g.make_arc_3pt((start[0], start[1], 0), (mid_pt[0], mid_pt[1], 0),
                         (end[0], end[1], 0))
    # the third piece leaves at 45 degrees off the arc's end tangent
    tangent = (math.cos(phi), -math.sin(phi))
    c, s = math.cos(-math.pi / 4), math.sin(-math.pi / 4)
    heading = (tangent[0] * c - tangent[1] * s,
               tangent[0] * s + tangent[1] * c)
    third = g.make_line((end[0], end[1], 0),
                        (end[0] + 1.5 * heading[0], end[1] + 1.5 * heading[1],
                         0))
    open_curve = g.join_curves([first, mid, third])
    assert g.fillet_corners(open_curve, 0.5) is not None
    with pytest.raises(g.GeometryError, match="overlap on piece 2"):
        g.fillet_corners(open_curve, 0.6)


def test_fillet_corners_rounds_a_closed_path_with_arc_corners():
    # a closed trip of lines and arc corners: everything rounds at once
    # and the path comes back closed
    line_a = g.make_line((0, 0, 0), (10, 0, 0))
    arc_a = g.make_arc_3pt((10, 0, 0), (13, -1.5, 0), (13, -3, 0))
    line_b = g.make_line((13, -3, 0), (13, -13, 0))
    arc_b = g.make_arc_3pt((13, -13, 0), (9, -16, 0), (5, -13, 0))
    line_c = g.make_line((5, -13, 0), (0, -13, 0))
    closing = g.make_line((0, -13, 0), (0, 0, 0))
    closed_path = g.join_curves([line_a, arc_a, line_b, arc_b, line_c,
                                 closing])
    out = g.fillet_corners(closed_path, 0.8)
    assert g.is_valid(out)
    assert g.is_closed_curve(out)
    assert g.curve_length(out) < g.curve_length(closed_path)


def test_fillet_corners_refuses_pieces_that_are_neither_line_nor_arc():
    spline = g.make_interp_curve([(0, 0, 0), (5, 3, 0), (10, 0, 0)])
    line = g.make_line((10, 0, 0), (10, 10, 0))
    with pytest.raises(g.GeometryError, match="straight and arc pieces"):
        g.fillet_corners(g.join_curves([spline, line]), 1.0)


def test_filletedge_command_rounds_every_corner_via_filletcorners(env):
    scene, sel, hist, ctx, proc = env
    rect = scene.add(g.make_rectangle((0, 0, 0), (20, 10, 0)))
    proc.run("filletcorners")
    proc.click_object(rect.id)
    proc.finish_selection()
    proc.provide_text("2")
    shape = scene.all()[0].shape
    assert g.shape_kind(shape) == "curve"
    assert g.curve_length(shape) == pytest.approx(44 + 4 * math.pi, rel=1e-4)


def test_filletedge_variable_law_answers_its_prompts_in_order(env):
    scene, sel, hist, ctx, proc = env
    box = scene.add(g.make_box((0, 0, 0), 10, 10, 10))
    sel.toggle_subobject(box.id, "edge", 0)
    proc.run("filletedge")
    proc.provide_text("No")            # no chain expansion
    proc.provide_text("0:1;1:3")       # the law, straight from text
    proc.provide_text("Smooth")
    assert not proc.busy
    v = g.volume(scene.all()[0].shape)
    # the strip's cross-section is quadratic in the radius, the radius
    # linear from 1 to 3: the mean area sits at 13/3 of the r=1 one
    expected = 1000 - 10 * (1 - 3.14159 / 4) * (1 + 2 + 4.0 / 3)
    assert v == pytest.approx(expected, rel=1e-2)


def test_a_failed_fillet_blames_the_chains_that_cannot_start():
    box = g.make_box((0, 0, 0), 10, 10, 10)
    # all twelve edges of the cube get a chain, and none of them can even
    # begin at this radius: the kernel says so, and the error repeats it
    with pytest.raises(g.GeometryError, match="too big for 12") as ei:
        g.fillet_edges(box, 1000.0)
    # ... and names them, so a caller can highlight the culprits
    assert getattr(ei.value, "blamed", None) == list(range(12))


def test_a_picked_edge_that_failed_stays_selected_for_the_next_try(env):
    scene, sel, hist, ctx, proc = env
    echoes = []
    ctx.add_echo_listener(echoes.append)
    box = scene.add(g.make_box((0, 0, 0), 10, 10, 10))
    sel.toggle_subobject(box.id, "edge", 0)
    proc.run("filletedge")
    proc.provide_text("No")
    proc.provide_text("1000")
    # the processor moves result_subobjects into the selection on finish
    assert sel.subobjects == [(box.id, "edge", 0)]
    assert any("too big" in m for m in echoes)
    assert any("stay selected" in m for m in echoes)


def test_a_failed_fillet_names_the_largest_radius_that_fits():
    box = g.make_box((0, 0, 0), 10, 10, 10)
    with pytest.raises(g.GeometryError):
        g.fillet_edges(box, 1000.0)
    best = g.largest_fillet_radius(box, 1000.0)
    # the kernel swallows nearly the whole face before giving up, so the
    # only honest bound is: something real, and strictly less than asked
    assert best is not None and 0.0 < best < 1000.0
    assert g.shape_kind(g.fillet_edges(box, best)) == "solid"