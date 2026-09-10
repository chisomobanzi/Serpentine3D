"""Closed outlines must survive Join; Cap must not duplicate existing walls."""
import itertools
import math
import pytest
from OCP.BRepCheck import BRepCheck_Analyzer
from serpentine3d.core import geometry as g


def profiles():
    # The same selection order as curve, offset, line, line. The offset
    # wire is initially disconnected from the first curve.
    a = g.make_control_curve([(0, 0, 0), (6, 8, 0), (6, 16, 0), (0, 24, 0)])
    b = g.make_polyline([(-4, 0, 0), (-6, 8, 0), (-6, 16, 0), (-4, 24, 0)])
    return [a, b, g.make_line((-4, 0, 0), (0, 0, 0)),
            g.make_line((-4, 24, 0), (0, 24, 0))]


@pytest.mark.parametrize("order", list(itertools.permutations(range(4))))
def test_join_retains_all_edges_regardless_of_selection_order(order):
    curves = profiles()
    joined = g.join_curves([curves[i] for i in order])
    assert len(g.edges_of(joined)) == 6
    assert g.is_closed_curve(joined)
    assert g.curve_length(joined) == pytest.approx(sum(g.curve_length(c) for c in curves))
    result = g.extrude(joined, (0, 0, 1), 10, cap=True)
    assert g.shape_kind(result) == "solid"
    assert len(g.faces_of(result)) == 8
    assert BRepCheck_Analyzer(result).IsValid()


def test_disconnected_curve_cannot_disappear_from_a_partially_successful_join():
    curves = [g.make_line((0, 0, 0), (10, 0, 0)),
              g.make_line((100, 100, 0), (110, 100, 0)),
              g.make_line((10, 0, 0), (10, 10, 0))]
    with pytest.raises(g.GeometryError):
        g.join_curves(curves)


@pytest.mark.parametrize("split", [False, True])
def test_cap_does_not_double_an_already_filled_flat_wall(split):
    wall = g.planar_face(g.make_rectangle((0, 0, 0), (10, 10, 0)))
    if split:
        wall = g.join_surfaces([g.planar_face(g.make_rectangle((0, 0, 0), (5, 10, 0))),
                                g.planar_face(g.make_rectangle((5, 0, 0), (10, 10, 0)))])
    with pytest.raises(g.GeometryError, match="No closable planar openings"):
        g.cap_holes(wall)


def test_joined_extrusion_walls_cap_to_one_valid_closed_solid():
    walls = [g.extrude(c, (0, 0, 1), 10, cap=False) for c in profiles()]
    joined = g.join_surfaces(walls)
    result = g.cap_holes(joined)
    assert g.shape_kind(result) == "solid"
    assert len(g.faces_of(result)) == 8
    assert BRepCheck_Analyzer(result).IsValid()
    assert g.volume(result) > 0


def test_capping_a_compound_keeps_both_closed_tubes():
    tube = g.extrude(g.make_circle((0, 0, 0), 5), (0, 0, 1), 10, cap=False)
    other = g.translate(tube, (30, 0, 0))
    result = g.cap_holes(g.make_compound([tube, other]))
    assert len(g.faces_of(result)) == 6
    assert g.volume(result) == pytest.approx(2 * math.pi * 25 * 10, rel=1e-3)
    assert BRepCheck_Analyzer(result).IsValid()


def test_cap_reports_no_change_for_separate_walls_then_join_cap_succeeds(env):
    scene, selection, history, ctx, proc = env
    messages = []
    ctx.echo = messages.append
    objects = [scene.add(g.extrude(c, (0, 0, 1), 10, cap=False)) for c in profiles()]
    original = {o.id: o.shape for o in objects}
    selection.set([o.id for o in objects])
    proc.run("cap")
    assert not proc.busy
    assert all(scene.get(oid).shape.IsSame(shape) for oid, shape in original.items())
    assert not any(m.startswith("Capped ") for m in messages)
    assert any("join" in m.lower() for m in messages)
    selection.set([o.id for o in objects])
    proc.run("join")
    selection.set([o.id for o in scene.all()])
    proc.run("cap")
    assert len(scene.all()) == 1
    result = scene.all()[0]
    assert result.kind == "solid" and BRepCheck_Analyzer(result.shape).IsValid()
    history.undo()
    assert scene.all()[0].kind == "surface"
