"""Hard morphology cases for the edge fillet: the blends SolidWorks
survives — concave corners, chains meeting at a vertex, closed rims,
fillets next to fillets, space-curve intersection edges, extreme model
scales — plus the guard against a blend that builds but breaks."""

import math

import pytest

from serpentine3d.core import geometry as g


def vertex_edges(box, at=(0.0, 0.0, 0.0), eps=1e-4):
    """The straight edges of an axis-aligned box incident to a corner."""
    picked = []
    for e in g.edges_of(box):
        (mn, mx) = g.bbox(e)
        axes = [i for i in range(3) if mx[i] - mn[i] > 1e-3]
        if len(axes) != 1:
            continue
        if all(mn[i] - eps <= at[i] <= mx[i] + eps for i in range(3)):
            picked.append(e)
    return picked


def vertical_edges(shape, eps=1e-3):
    out = []
    for e in g.edges_of(shape):
        (mn, mx) = g.bbox(e)
        if mx[2] - mn[2] > eps and mx[0] - mn[0] < eps and mx[1] - mn[1] < eps:
            out.append(e)
    return out


def concave_edge(lblock):
    """The inner vertical edge of an L-block cut from a box."""
    for e in vertical_edges(lblock):
        (mn, mx) = g.bbox(e)
        if abs(mn[0] - 5.0) < 1e-4 and abs(mx[1] - 5.0) < 1e-4:
            return e
    raise AssertionError("concave edge not found")


def cylinder_rim(cyl, height, eps=1e-4):
    rims = [e for e in g.edges_of(cyl)
            if abs(g.bbox(e)[0][2] - height) < eps
            and abs(g.bbox(e)[1][2] - height) < eps]
    assert len(rims) == 1
    return rims[0]


def test_a_concave_inner_edge_fillets_adding_material():
    base = g.make_box((0, 0, 0), 10, 10, 10)
    notch = g.make_box((5, 0, 0), 5, 5, 10)
    lblock = g.boolean_difference(base, notch)
    out = g.fillet_edges(lblock, 1.0, edges=[concave_edge(lblock)])
    assert g.is_valid(out)
    # an inner corner gains the material a constant radius rolls into it
    assert g.volume(out) == pytest.approx(
        750 + (1 - math.pi / 4) * 10, rel=1e-5)


def test_three_edges_meeting_at_a_vertex_fillets_together():
    box = g.make_box((0, 0, 0), 10, 10, 10)
    picked = vertex_edges(box)
    assert len(picked) == 3
    out = g.fillet_edges(box, 1.0, edges=picked)
    assert g.is_valid(out)
    # the corner patch closes the vertex where the three blends meet
    assert g.volume(out) == pytest.approx(993.7293, abs=0.01)


def test_different_radii_meeting_at_one_vertex_still_close():
    box = g.make_box((0, 0, 0), 10, 10, 10)
    picked = vertex_edges(box)
    out = g.fillet_edges(box, radii=[1.0, 1.0, 3.0], edges=picked)
    assert g.is_valid(out)
    even = g.fillet_edges(box, 1.0, edges=picked)
    assert g.volume(out) < g.volume(even)


def test_a_closed_rim_fillets_by_the_pappus_bounds():
    cyl = g.make_cylinder((0, 0, 0), 5.0, 10.0)
    out = g.fillet_edges(cyl, 1.0, edges=[cylinder_rim(cyl, 10.0)])
    assert g.is_valid(out)
    # the removed ring's swept area lies between rolling it at r and at
    # r inward from the rim: Pappus bounds the volume on both sides
    area = (1 - math.pi / 4)
    v = g.volume(out)
    assert 250 * math.pi - area * 2 * math.pi * 5 < v
    assert v < 250 * math.pi - area * 2 * math.pi * 4


def test_a_variable_law_runs_over_a_closed_edge():
    cyl = g.make_cylinder((0, 0, 0), 5.0, 10.0)
    rim = cylinder_rim(cyl, 10.0)
    law = g.fillet_edges(cyl, [(0.0, 0.5), (0.5, 2.5), (1.0, 0.5)],
                         edges=[rim])
    thin = g.fillet_edges(cyl, 0.5, edges=[rim])
    thick = g.fillet_edges(cyl, 2.5, edges=[rim])
    assert g.is_valid(law)
    assert g.volume(thin) > g.volume(law) > g.volume(thick)


def test_a_fillet_next_to_a_fillet_keeps_the_solid_valid():
    box = g.make_box((0, 0, 0), 10, 10, 10)
    once = g.fillet_edges(box, 1.0, edges=[g.edges_of(box)[0]])
    assert g.is_valid(once)
    # the edge now runs against the blend's tangent face — a G1 seam
    for e in g.edges_of(once):
        (mn, mx) = g.bbox(e)
        if (abs(mn[2]) < 1e-4 and abs(mx[2]) < 1e-4
                and abs(mn[1]) < 1e-4 and abs(mx[1]) < 1e-4
                and mx[0] - mn[0] > 5.0):
            twice = g.fillet_edges(once, 0.5, edges=[e])
            assert g.is_valid(twice)
            assert g.volume(twice) < g.volume(once)
            return
    raise AssertionError("the edge beside the fillet was not found")


def test_a_blend_that_builds_but_breaks_is_refused():
    # a 1mm plate: r=0.6 eats past mid-thickness, and the kernel hands
    # back a solid that fails its own checks — refuse it, never return it
    plate = g.make_box((0, 0, 0), 20, 20, 1)
    with pytest.raises(g.GeometryError, match="fails its own solid checks"):
        g.fillet_edges(plate, 0.6)


def test_a_radius_that_meets_the_opposite_side_reports_the_blend():
    box = g.make_box((0, 0, 0), 10, 10, 10)
    with pytest.raises(g.GeometryError, match="failed the blend"):
        g.fillet_edges(box, 5.0)


def test_a_law_may_taper_to_zero_at_its_ends():
    box = g.make_box((0, 0, 0), 10, 10, 10)
    e = g.edges_of(box)[0]
    tapered = g.fillet_edges(box, [(0.0, 0.0), (0.5, 6.0), (1.0, 0.5)],
                             edges=[e])
    assert g.is_valid(tapered)
    # tapering the ends removes less than a full-strength constant blend
    even = g.fillet_edges(box, 6.0, edges=[e])
    assert g.volume(tapered) > g.volume(even)


def test_a_space_curve_intersection_edge_fillets():
    # a T of two cylinders: the seam is a genuine space curve between two
    # curved faces, the kind of edge a box-only test never sees
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    v = g.make_cylinder((0, 0, 0), 5.0, 20.0)
    h = BRepPrimAPI_MakeCylinder(
        gp_Ax2(gp_Pnt(-5, 4, 10), gp_Dir(1, 0, 0)), 3.0, 20.0).Shape()
    body = g.boolean_union(v, h)
    cands = []
    for e in g.edges_of(body):
        (mn, mx) = g.bbox(e)
        spans = [mx[i] - mn[i] for i in range(3)]
        if all(d > 0.3 for d in spans) and spans[2] < 8.0:
            cands.append(e)
    assert len(cands) == 1
    out = g.fillet_edges(body, 0.8, edges=cands)
    assert g.is_valid(out)


def test_extreme_model_scales_keep_their_blends_valid():
    tiny = g.fillet_edges(g.make_box((0, 0, 0), 0.01, 0.01, 0.01), 0.001)
    assert g.is_valid(tiny)
    huge = g.fillet_edges(
        g.make_box((0, 0, 0), 10000, 10000, 10000), 1000.0)
    assert g.is_valid(huge)
    assert g.volume(huge) < 10000 ** 3


def test_a_repair_retry_re_resolves_the_picked_edges(monkeypatch):
    box = g.make_box((0, 0, 0), 10, 10, 10)
    e = g.edges_of(box)[0]
    repaired = g.copy_shape(box)
    monkeypatch.setattr(g, "_repaired_input", lambda shape: repaired)
    calls = []

    def fake_build(shape, radius, radii, r_pair, law, edges, chamfer,
                   transition, verb):
        calls.append((shape, edges))
        if len(calls) == 1:
            raise g._FilletBuildError("boom", [0])
        # the second attempt feeds the REPAIRED shape its own edges, not
        # the original shape's handles
        assert shape is repaired
        assert len(edges) == 1 and not edges[0].IsSame(e)
        assert g.curve_endpoints(edges[0]) == g.curve_endpoints(e)
        return g.make_box((0, 0, 0), 10, 10, 10)

    monkeypatch.setattr(g, "_fillet_edges_build", fake_build)
    out = g.fillet_edges(box, 1.0, edges=[e])
    assert g.shape_kind(out) == "solid"
    assert len(calls) == 2


def test_a_repair_that_rebuilds_the_wire_layout_skips_the_retry(monkeypatch):
    box = g.make_box((0, 0, 0), 10, 10, 10)
    e = g.edges_of(box)[0]
    # a repair that moved the wire layout: no edge of this stand-in
    # matches the picked edge, so the retry must not happen at all
    unrelated = g.make_box((100, 100, 100), 10, 10, 10)
    monkeypatch.setattr(g, "_repaired_input", lambda shape: unrelated)
    calls = []

    def failing_build(shape, radius, radii, r_pair, law, edges, chamfer,
                      transition, verb):
        calls.append(edges)
        raise g._FilletBuildError("boom", [0])

    monkeypatch.setattr(g, "_fillet_edges_build", failing_build)
    with pytest.raises(g.GeometryError, match="boom"):
        g.fillet_edges(box, 1.0, edges=[e])
    assert len(calls) == 1          # the original failure stands, honest


def test_filletcorners_says_which_piece_is_not_roundable(env):
    scene, sel, hist, ctx, proc = env
    echoes = []
    ctx.add_echo_listener(echoes.append)
    spline = scene.add(g.make_control_curve(
        [(0, 0, 0), (5, 5, 0), (10, 0, 0)], degree=2))
    proc.run("filletcorners")
    proc.click_object(spline.id)
    proc.finish_selection()
    proc.provide_text("2")
    assert not proc.busy
    # the command names the piece, instead of a generic framework error
    assert any("piece 1 is neither" in m for m in echoes)
    assert not any(m.startswith("Error:") for m in echoes)
