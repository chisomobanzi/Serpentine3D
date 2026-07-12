import math

import pytest

from serpentine.core import geometry as g


def test_line():
    line = g.make_line((0, 0, 0), (10, 0, 0))
    assert g.shape_kind(line) == "curve"
    assert g.curve_length(line) == pytest.approx(10.0)


def test_line_coincident_points_rejected():
    with pytest.raises(g.GeometryError):
        g.make_line((1, 2, 3), (1, 2, 3))


def test_polyline():
    pl = g.make_polyline([(0, 0, 0), (10, 0, 0), (10, 10, 0)])
    assert g.curve_length(pl) == pytest.approx(20.0)
    closed = g.make_polyline([(0, 0, 0), (10, 0, 0), (10, 10, 0)], closed=True)
    assert g.is_closed_curve(closed)


def test_circle():
    c = g.make_circle((0, 0, 0), 5.0)
    assert g.curve_length(c) == pytest.approx(2 * math.pi * 5.0)
    assert g.is_closed_curve(c)


def test_arc_3pt():
    # half circle radius 5 through (5,0),(0,5),(-5,0)
    arc = g.make_arc_3pt((5, 0, 0), (0, 5, 0), (-5, 0, 0))
    assert g.curve_length(arc) == pytest.approx(math.pi * 5.0, rel=1e-6)


def test_ellipse():
    e = g.make_ellipse((0, 0, 0), 10, 5)
    assert g.is_closed_curve(e)


def test_rectangle():
    r = g.make_rectangle((0, 0, 0), (10, 5, 0))
    assert g.is_closed_curve(r)
    assert g.curve_length(r) == pytest.approx(30.0)


def test_interp_curve_passes_through_points():
    pts = [(0, 0, 0), (5, 5, 0), (10, 0, 0), (15, -5, 0)]
    curve = g.make_interp_curve(pts)
    assert g.shape_kind(curve) == "curve"
    (mn, mx) = g.bbox(curve)
    assert mn[0] == pytest.approx(0, abs=0.2)
    assert mx[0] == pytest.approx(15, abs=0.2)


def test_control_curve():
    curve = g.make_control_curve([(0, 0, 0), (5, 10, 0), (10, 0, 0)], degree=2)
    assert g.shape_kind(curve) == "curve"


def test_extrude_curve_to_surface():
    line = g.make_line((0, 0, 0), (10, 0, 0))
    srf = g.extrude(line, (0, 0, 1), 5.0)
    assert g.shape_kind(srf) == "surface"
    assert g.surface_area(srf) == pytest.approx(50.0)


def test_extrude_closed_capped_gives_solid():
    rect = g.make_rectangle((0, 0, 0), (10, 10, 0))
    solid = g.extrude(rect, (0, 0, 1), 10.0, cap=True)
    assert g.shape_kind(solid) == "solid"
    assert g.volume(solid) == pytest.approx(1000.0)


def test_revolve():
    line = g.make_line((5, 0, 0), (5, 0, 10))
    srf = g.revolve(line, (0, 0, 0), (0, 0, 1), 360)
    assert g.shape_kind(srf) in ("surface", "solid")
    assert g.surface_area(srf) == pytest.approx(2 * math.pi * 5 * 10, rel=1e-4)


def test_loft():
    c1 = g.make_circle((0, 0, 0), 5)
    c2 = g.make_circle((0, 0, 10), 3)
    srf = g.loft([c1, c2])
    assert g.shape_kind(srf) in ("surface", "solid")
    (mn, mx) = g.bbox(srf)
    assert mx[2] == pytest.approx(10, abs=0.1)


def test_planar_face():
    circle = g.make_circle((0, 0, 0), 5)
    face = g.planar_face(circle)
    assert g.shape_kind(face) == "surface"
    assert g.surface_area(face) == pytest.approx(math.pi * 25, rel=1e-4)


def test_planar_face_open_curve_rejected():
    line = g.make_line((0, 0, 0), (1, 0, 0))
    with pytest.raises(g.GeometryError):
        g.planar_face(line)


def test_solids():
    box = g.make_box((0, 0, 0), 2, 3, 4)
    assert g.volume(box) == pytest.approx(24.0)
    sph = g.make_sphere((0, 0, 0), 3)
    assert g.volume(sph) == pytest.approx(4 / 3 * math.pi * 27, rel=1e-4)
    cyl = g.make_cylinder((0, 0, 0), 2, 5)
    assert g.volume(cyl) == pytest.approx(math.pi * 4 * 5, rel=1e-4)


def test_boolean_union_difference_intersection():
    a = g.make_box((0, 0, 0), 10, 10, 10)
    b = g.make_box((5, 5, 5), 10, 10, 10)
    union = g.boolean_union(a, b)
    assert g.volume(union) == pytest.approx(2000 - 125)
    diff = g.boolean_difference(a, b)
    assert g.volume(diff) == pytest.approx(1000 - 125)
    inter = g.boolean_intersection(a, b)
    assert g.volume(inter) == pytest.approx(125)


def test_boolean_disjoint_intersection_is_empty_or_fails():
    a = g.make_box((0, 0, 0), 1, 1, 1)
    b = g.make_box((10, 10, 10), 1, 1, 1)
    try:
        inter = g.boolean_intersection(a, b)
        assert g.volume(inter) == pytest.approx(0, abs=1e-9)
    except g.GeometryError:
        pass


def test_translate():
    box = g.make_box((0, 0, 0), 1, 1, 1)
    moved = g.translate(box, (10, 0, 0))
    (mn, mx) = g.bbox(moved)
    assert mn[0] == pytest.approx(10, abs=1e-6)


def test_rotate():
    line = g.make_line((10, 0, 0), (20, 0, 0))
    rot = g.rotate(line, (0, 0, 0), (0, 0, 1), 90)
    (mn, mx) = g.bbox(rot)
    assert mx[1] == pytest.approx(20, abs=1e-6)
    assert abs(mx[0]) < 1e-6


def test_scale_uniform_and_nonuniform():
    box = g.make_box((0, 0, 0), 1, 1, 1)
    big = g.scale(box, (0, 0, 0), 2.0)
    assert g.volume(big) == pytest.approx(8.0)
    stretched = g.scale(box, (0, 0, 0), 1.0, factors=(2, 1, 3))
    assert g.volume(stretched) == pytest.approx(6.0, rel=1e-5)


def test_mirror():
    box = g.make_box((1, 0, 0), 1, 1, 1)
    m = g.mirror(box, (0, 0, 0), (1, 0, 0))
    (mn, mx) = g.bbox(m)
    assert mx[0] == pytest.approx(-1, abs=1e-6)
    assert mn[0] == pytest.approx(-2, abs=1e-6)


def test_join_curves():
    l1 = g.make_line((0, 0, 0), (10, 0, 0))
    l2 = g.make_line((10, 0, 0), (10, 10, 0))
    joined = g.join_curves([l1, l2])
    assert g.curve_length(joined) == pytest.approx(20.0)


def test_brep_roundtrip():
    box = g.make_box((0, 0, 0), 2, 2, 2)
    data = g.shape_to_bytes(box)
    assert len(data) > 0
    back = g.shape_from_bytes(data)
    assert g.volume(back) == pytest.approx(8.0)


def test_measure():
    box = g.make_box((0, 0, 0), 2, 2, 2)
    assert g.centroid(box) == pytest.approx((1, 1, 1))
    assert g.is_valid(box)


def test_offset_curve():
    circle = g.make_circle((0, 0, 0), 5)
    off = g.offset_curve(circle, 2.0)
    assert g.curve_length(off) == pytest.approx(2 * math.pi * 7, rel=1e-3)


def test_offset_open_curve():
    line = g.make_polyline([(0, 0, 0), (10, 0, 0), (10, 10, 0)])
    off = g.offset_curve(line, 1.0)
    assert g.shape_kind(off) == "curve"


def test_fillet_curves():
    l1 = g.make_line((0, 0, 0), (10, 0, 0))
    l2 = g.make_line((10, 0, 0), (10, 10, 0))
    ea, arc, eb = g.fillet_curves(l1, l2, 2.0, (10, 0, 0))
    joined = g.join_curves([ea, arc, eb])
    # 8 + 8 straight + quarter circle r=2
    assert g.curve_length(joined) == pytest.approx(16 + math.pi, rel=1e-4)


def test_explode_wire_and_solid():
    pl = g.make_polyline([(0, 0, 0), (5, 0, 0), (5, 5, 0)])
    parts = g.explode(pl)
    assert len(parts) == 2
    box = g.make_box((0, 0, 0), 1, 1, 1)
    faces = g.explode(box)
    assert len(faces) == 6


def test_snap_points():
    from serpentine.core.snaps import snap_points_for
    line = g.make_line((0, 0, 0), (10, 0, 0))
    pts = snap_points_for(line)
    kinds = {k for _, k in pts}
    assert kinds == {"end", "mid"}
    assert ((5.0, 0.0, 0.0), "mid") in [(p, k) for p, k in pts]
    circle = g.make_circle((3, 3, 0), 2)
    kinds = {k for _, k in snap_points_for(circle)}
    assert "center" in kinds


def test_split_curve_by_curve():
    line = g.make_line((0, 0, 0), (10, 0, 0))
    cutter = g.make_line((5, -5, 0), (5, 5, 0))
    pieces = g.split_shape(line, [cutter])
    assert len(pieces) == 2
    lengths = sorted(g.curve_length(p) for p in pieces)
    assert lengths == pytest.approx([5, 5])


def test_split_circle_by_line():
    circle = g.make_circle((0, 0, 0), 5)
    cutter = g.make_line((-10, 0, 0), (10, 0, 0))
    pieces = g.split_shape(circle, [cutter])
    assert len(pieces) == 2
    for p in pieces:
        assert g.curve_length(p) == pytest.approx(math.pi * 5, rel=1e-3)


def test_split_surface_by_curve():
    rect = g.make_rectangle((0, 0, 0), (10, 10, 0))
    face = g.planar_face(rect)
    cutter = g.make_line((5, -2, 0), (5, 12, 0))
    pieces = g.split_shape(face, [cutter])
    assert len(pieces) == 2
    areas = sorted(g.surface_area(p) for p in pieces)
    assert areas == pytest.approx([50, 50], rel=1e-4)


def test_split_no_intersection_raises():
    line = g.make_line((0, 0, 0), (10, 0, 0))
    cutter = g.make_line((0, 5, 0), (10, 5, 0))
    with pytest.raises(g.GeometryError):
        g.split_shape(line, [cutter])


def test_sweep2():
    profile = g.make_line((0, 0, 0), (0, 0, 3))
    rail1 = g.make_line((0, 0, 0), (20, 0, 0))
    rail2 = g.make_line((0, 5, 0), (20, 5, 0))
    srf = g.sweep2(profile, rail1, rail2)
    assert g.shape_kind(srf) in ("surface", "solid")
    assert g.surface_area(srf) == pytest.approx(60, rel=1e-3)


def test_control_points_roundtrip():
    pts = [(0, 0, 0), (5, 5, 0), (10, 0, 0)]
    curve = g.make_control_curve(pts, degree=2)
    cvs = g.get_control_points(curve)
    assert len(cvs) == 3
    assert cvs[1] == pytest.approx((5, 5, 0))

    moved = g.move_control_point(curve, 1, (5, 10, 0))
    cvs2 = g.get_control_points(moved)
    assert cvs2[1] == pytest.approx((5, 10, 0))
    # ends unchanged
    assert cvs2[0] == pytest.approx((0, 0, 0))


def test_control_points_of_circle_via_conversion():
    circle = g.make_circle((0, 0, 0), 5)
    cvs = g.get_control_points(circle)
    assert len(cvs) >= 7    # rational bspline circle representation
    moved = g.move_control_point(circle, 0, (8, 0, 0))
    assert g.shape_kind(moved) == "curve"


def test_sample_curve():
    line = g.make_line((0, 0, 0), (10, 0, 0))
    pts = g.sample_curve(line, 5)
    assert len(pts) == 5
    assert pts[2] == pytest.approx((5, 0, 0), abs=1e-6)
    # works on wires too
    pl = g.make_polyline([(0, 0, 0), (10, 0, 0), (10, 10, 0)])
    pts = g.sample_curve(pl, 3)
    assert pts[1] == pytest.approx((10, 0, 0), abs=1e-6)


def test_rebuild_curve():
    curve = g.make_interp_curve(
        [(0, 0, 0), (3, 4, 0), (6, -2, 0), (10, 1, 0), (14, 5, 0)])
    rebuilt = g.rebuild_curve(curve, point_count=8, degree=3)
    assert g.shape_kind(rebuilt) == "curve"
    # length approximately preserved (rebuild smooths, so allow a few %)
    assert g.curve_length(rebuilt) == pytest.approx(
        g.curve_length(curve), rel=0.05)
    # rebuild with degree 2 fit
    rebuilt2 = g.rebuild_curve(curve, point_count=12, degree=2)
    assert g.curve_length(rebuilt2) == pytest.approx(
        g.curve_length(curve), rel=0.08)
    # closed curves stay closed
    circle = g.make_circle((0, 0, 0), 5)
    rc = g.rebuild_curve(circle, point_count=12)
    assert g.is_closed_curve(rc)
    assert g.curve_length(rc) == pytest.approx(2 * math.pi * 5, rel=0.01)


def test_curvature_at():
    circle = g.make_circle((0, 0, 0), 5)
    info = g.curvature_at(circle, (5.2, 0, 0))
    assert info["curvature"] == pytest.approx(1 / 5, rel=1e-4)
    assert info["radius"] == pytest.approx(5, rel=1e-4)
    line = g.make_line((0, 0, 0), (10, 0, 0))
    info = g.curvature_at(line, (5, 1, 0))
    assert info["radius"] == float("inf")
