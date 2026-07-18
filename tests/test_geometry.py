import math

import numpy as np

import pytest

from serpentine3d.core import geometry as g


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
    from serpentine3d.core.snaps import snap_points_for
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


def test_dash_segments_bounded():
    import numpy as np
    from serpentine3d.core.hlr import dash_segments
    # exact boundary alignment used to loop forever
    line = np.array([[0, 0, 0], [10, 0, 0]], float)
    d = dash_segments(line, dash=2.0, gap=1.2)
    total = sum(np.linalg.norm(s[1] - s[0]) for s in d)
    assert 5.0 < total < 8.0
    # pathological: period exactly divides length, tiny segments
    poly = np.array([[0, 0, 0], [3.2, 0, 0], [3.2, 6.4, 0]], float)
    d2 = dash_segments(poly, dash=1.6, gap=1.6)
    assert len(d2) >= 2
    # zero-length segments skipped
    d3 = dash_segments(np.array([[1, 1, 0], [1, 1, 0]], float))
    assert len(d3) == 0


def test_fillet_edges_solid():
    box = g.make_box((0, 0, 0), 10, 10, 10)
    filleted = g.fillet_edges(box, 1.0)
    # rounded box: volume less than sharp box, more than r=1 inset
    v = g.volume(filleted)
    assert 900 < v < 1000


def test_chamfer_edges_solid():
    box = g.make_box((0, 0, 0), 10, 10, 10)
    chamfered = g.fillet_edges(box, 1.0, chamfer=True)
    assert 900 < g.volume(chamfered) < 1000


def test_cap_holes():
    # an open cylinder (surface of revolution) capped into a solid
    line = g.make_line((5, 0, 0), (5, 0, 10))
    tube = g.revolve(line, (0, 0, 0), (0, 0, 1), 360)
    capped = g.cap_holes(tube)
    assert g.shape_kind(capped) == "solid"
    assert g.volume(capped) == pytest.approx(math.pi * 25 * 10, rel=1e-3)


def test_intersect_shapes():
    a = g.make_box((0, 0, 0), 10, 10, 10)
    b = g.make_sphere((10, 5, 5), 3)
    curves = g.intersect_shapes(a, b)
    assert len(curves) >= 1
    total = sum(g.curve_length(c) for c in curves)
    assert total == pytest.approx(2 * math.pi * 3, rel=1e-2)


def test_contour():
    box = g.make_box((0, 0, 0), 10, 10, 30)
    levels = g.contour(box, (0, 0, 1), 10.0)
    assert len(levels) == 2
    for _, curves in levels:
        total = sum(g.curve_length(c) for c in curves)
        assert total == pytest.approx(40, rel=1e-6)


def test_patch_surface():
    c1 = g.make_interp_curve([(0, 0, 0), (5, 0, 2), (10, 0, 0)])
    c2 = g.make_interp_curve([(10, 0, 0), (10, 5, 3), (10, 10, 0)])
    c3 = g.make_interp_curve([(10, 10, 0), (5, 10, 2), (0, 10, 0)])
    c4 = g.make_interp_curve([(0, 10, 0), (0, 5, 3), (0, 0, 0)])
    srf = g.patch_surface([c1, c2, c3, c4])
    assert g.shape_kind(srf) == "surface"
    assert g.surface_area(srf) > 100


def test_blend_curves_tangent():
    a = g.make_line((0, 0, 0), (10, 0, 0))
    b = g.make_line((20, 5, 0), (30, 5, 0))
    blend = g.blend_curves(a, b)
    assert g.shape_kind(blend) == "curve"
    # blend connects (10,0,0) to (20,5,0)
    mn, mx = g.bbox(blend)
    assert mn[0] == pytest.approx(10, abs=0.1)
    assert mx[0] == pytest.approx(20, abs=0.1)


def test_project_and_pull():
    srf = g.extrude(g.make_line((0, 0, 5), (10, 0, 5)), (0, 1, 0), 10)
    circle = g.make_circle((5, 5, 20), 2)
    projected = g.project_curve(circle, srf, (0, 0, -1))
    assert len(projected) >= 1
    pulled = g.pull_curve(circle, srf)
    assert len(pulled) >= 1


def test_helix():
    h = g.make_helix((0, 0, 0), 5, 2, 3)
    mn, mx = g.bbox(h)
    assert mx[2] == pytest.approx(6, rel=1e-3)      # 3 turns * pitch 2
    expected = math.hypot(2 * math.pi * 5, 2) * 3
    assert g.curve_length(h) == pytest.approx(expected, rel=1e-3)


def test_unroll_cylinder():
    line = g.make_line((5, 0, 0), (5, 0, 10))
    cyl_face = g.faces_of(g.revolve(line, (0, 0, 0), (0, 0, 1), 360))[0]
    curves = g.unroll_face(cyl_face)
    assert len(curves) >= 2
    import numpy as np
    mins = np.full(3, np.inf); maxs = np.full(3, -np.inf)
    for c in curves:
        mn, mx = g.bbox(c)
        mins = np.minimum(mins, mn); maxs = np.maximum(maxs, mx)
    w = maxs[0] - mins[0]
    h = maxs[1] - mins[1]
    assert sorted([w, h])[1] == pytest.approx(2 * math.pi * 5, rel=1e-3)
    assert sorted([w, h])[0] == pytest.approx(10, rel=1e-3)


def test_text_curves():
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    if not QFontDatabase.families():
        pytest.skip("no fonts in the Qt font database (headless Windows "
                    "uses the freetype backend, which ships no fonts)")
    from serpentine3d.core.text import text_curves
    curves = text_curves("AB", height=10)
    assert len(curves) >= 3        # A outer, A hole, B outer, B holes
    import numpy as np
    maxs = np.full(3, -np.inf); mins = np.full(3, np.inf)
    for c in curves:
        mn, mx = g.bbox(c)
        mins = np.minimum(mins, mn); maxs = np.maximum(maxs, mx)
    assert 7 < (maxs[1] - mins[1]) < 14     # roughly requested height


def test_deform_twist_curve():
    from serpentine3d.core import deform
    line = g.make_line((5, 0, 0), (5, 0, 10))
    fn = deform.twist_fn((0, 0, 0), (0, 0, 1), 90.0, 10.0)
    twisted = deform.deform_shape(line, fn)
    mn, mx = g.bbox(twisted)
    # the top of the line rotates 90 degrees: x=5 -> y=5
    assert mx[1] == pytest.approx(5, abs=0.15)
    assert g.curve_length(twisted) > 10


def test_deform_taper_surface():
    from serpentine3d.core import deform
    rect = g.make_rectangle((-5, -5, 0), (5, 5, 0))
    solidish = g.extrude(rect, (0, 0, 1), 10, cap=False)
    fn = deform.taper_fn((0, 0, 0), (0, 0, 1), 0.5, 10.0)
    tapered = deform.deform_shape(solidish, fn)
    mn, mx = g.bbox(tapered)
    assert mx[0] == pytest.approx(5, abs=0.1)     # base stays
    # top width should be ~5 (half of 10): probe with a section
    levels = g.contour(tapered, (0, 0, 1), 9.0)
    top_curves = levels[-1][1]
    tmn = np.array([np.inf] * 3); tmx = -tmn
    for c in top_curves:
        cmn, cmx = g.bbox(c)
        tmn = np.minimum(tmn, cmn); tmx = np.maximum(tmx, cmx)
    assert (tmx[0] - tmn[0]) == pytest.approx(5.5, abs=0.4)


def test_deform_bend_curve():
    from serpentine3d.core import deform
    line = g.make_line((0, 0, 0), (10, 0, 0))
    fn = deform.bend_fn((0, 0, 0), (1, 0, 0), 90.0, 10.0)
    bent = deform.deform_shape(line, fn)
    # arc length preserved-ish
    assert g.curve_length(bent) == pytest.approx(10, rel=0.02)
    mn, mx = g.bbox(bent)
    assert mx[2] > 2      # curls upward


def test_flow_along_curve():
    from serpentine3d.core import deform
    target = g.make_arc_3pt((0, 0, 0), (10, 6, 0), (20, 0, 0))
    box_curve = g.make_rectangle((0, -1, 0), (20, 1, 0))
    fn = deform.flow_fn((0, 0, 0), (20, 0, 0), target)
    flowed = deform.deform_shape(box_curve, fn)
    mn, mx = g.bbox(flowed)
    assert mx[1] > 5      # follows the arc upward


def test_extend_and_match():
    line = g.make_line((0, 0, 0), (10, 0, 0))
    longer = g.extend_curve(line, 5.0, "end")
    assert g.curve_length(longer) == pytest.approx(15, rel=1e-3)
    both = g.extend_curve(longer, 2.0, "start")
    assert g.curve_length(both) == pytest.approx(17, rel=1e-3)

    a = g.make_interp_curve([(0, 0, 0), (5, 2, 0), (9, 1, 0)])
    b = g.make_line((10, 0, 0), (20, 0, 0))
    matched = g.match_curve(a, b, "tangent")
    # end of a now touches start of b
    import numpy as np
    pts = g.sample_curve(matched, 32)
    end = np.asarray(pts[-1])
    assert np.linalg.norm(end - np.array([10, 0, 0])) < 1e-6


def test_edge_chain_and_variable_fillet():
    # a rounded-rect extrusion: side edges form tangent chains
    rect = g.make_rectangle((0, 0, 0), (20, 10, 0))
    l1 = g.make_line((0, 0, 0), (10, 0, 0))
    l2 = g.make_line((10, 0, 0), (10, 10, 0))
    ea, arc, eb = g.fillet_curves(l1, l2, 3.0, (10, 0, 0))
    joined = g.join_curves([ea, arc, eb])
    # chain from the arc should include both lines (tangent continuation)
    idx_arc = 1
    chain = g.edge_chain(joined, idx_arc)
    assert len(chain) == 3

    box = g.make_box((0, 0, 0), 10, 10, 10)
    var = g.fillet_edges(box, (1.0, 3.0), edges=[g.edges_of(box)[0]])
    assert g.shape_kind(var) == "solid"
    assert 900 < g.volume(var) < 1000


# --------------------------------------------------------- offset_faces


def _box_faces_by_z():
    box = g.make_box((0, 0, 0), 10, 10, 10)
    faces = g.faces_of(box)
    top = next(i for i, f in enumerate(faces) if g.face_normal(f)[2] > 0.9)
    bot = next(i for i, f in enumerate(faces) if g.face_normal(f)[2] < -0.9)
    sides = [i for i in range(len(faces)) if i not in (top, bot)]
    return box, top, bot, sides


def test_offset_faces_grows_two_opposite_faces():
    box, top, bot, _ = _box_faces_by_z()
    out = g.offset_faces(box, {top: 5.0, bot: 5.0})   # height 10 -> 20
    assert g.volume(out) == pytest.approx(2000.0, abs=1)


def test_offset_faces_grows_footprint():
    box, _, _, sides = _box_faces_by_z()
    out = g.offset_faces(box, {s: 2.0 for s in sides})   # 10x10 -> 14x14
    assert g.volume(out) == pytest.approx(1960.0, abs=1)


def test_offset_faces_single_entry_matches_push():
    box, top, _, _ = _box_faces_by_z()
    out = g.offset_faces(box, {top: 5.0})
    assert g.volume(out) == pytest.approx(1500.0, abs=1)


def test_offset_faces_rejects_carve_through():
    box, top, _, _ = _box_faces_by_z()
    with pytest.raises(g.GeometryError):
        g.offset_faces(box, {top: -20.0})


def test_offset_faces_rejects_bad_index():
    box, _, _, _ = _box_faces_by_z()
    with pytest.raises(g.GeometryError):
        g.offset_faces(box, {999: 2.0})


def test_offset_faces_rejects_empty():
    box, _, _, _ = _box_faces_by_z()
    with pytest.raises(g.GeometryError):
        g.offset_faces(box, {})
