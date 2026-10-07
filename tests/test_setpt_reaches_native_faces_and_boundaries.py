"""SetPt reaches valid native open faces and circular solid caps (#62)."""

import math

import pytest
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
from OCP.Geom import Geom_BezierSurface
from OCP.GeomAbs import GeomAbs_CurveType, GeomAbs_SurfaceType
from OCP.GeomConvert import GeomConvert
from OCP.TColgp import TColgp_Array2OfPnt
from OCP.gp import gp_Pnt

from serpentine3d.commands.base import PointReq, SelectReq
from serpentine3d.core import geometry as g


BASE = (2.0, -3.0, 4.0)
TARGET = (91.0, -37.0, 15.0)
SLOPED = [(0, 0, 0), (10, 0, 5), (10, 6, 8), (0, 6, 3)]
RECTANGLE = [(0, 0, 2), (10, 0, 2), (10, 6, 2), (0, 6, 2)]
REFUSAL = ("needs", "unsupported", "collaps", "degener", "invalid",
           "cannot", "can't", "could not", "unable", "fail", "zero")


def _key(point):
    return tuple(round(coordinate, 6) for coordinate in point)


def _corners(shape):
    return {_key(point) for edge in g.edges_of(shape)
            for point in g.curve_endpoints(edge)}


def _current(scene, original):
    obj = scene.get(original.id)
    assert obj is not None, "The original scene object keeps its identity"
    assert obj.name == original.name and obj.layer_id == original.layer_id
    return obj


def _planar_face(corners):
    face = g.planar_face(g.make_polyline(corners, closed=True))
    assert g.is_valid(face) and g.shape_kind(face) == "surface"
    assert g.surface_area(face) > 0
    return face


def _setpt(proc, target=TARGET, axis=2):
    assert proc.run("setpt")
    assert isinstance(proc.request, PointReq), (
        "Held native faces and boundaries must go straight to the target; "
        f"got {getattr(proc.request, 'prompt', None)!r}")
    assert set(proc.request.choices) >= {"X", "Y", "Z"}
    for index, name in enumerate("XYZ"):
        assert proc.set_option(name, "Yes" if index == axis else "No")
    proc.provide(tuple(float(coordinate) for coordinate in target))
    assert not proc.busy


def _nurbs_face():
    poles = TColgp_Array2OfPnt(1, 3, 1, 3)
    heights = [3, 6, 2, 7, 15, 9, 5, 8, 4]
    for i in range(3):
        for j in range(3):
            poles.SetValue(i + 1, j + 1, gp_Pnt(5 * i, 3 * j, heights[3 * i + j]))
    surface = GeomConvert.SurfaceToBSplineSurface_s(Geom_BezierSurface(poles))
    maker = BRepBuilderAPI_MakeFace(surface, 1e-7)
    assert maker.IsDone()
    face = maker.Face()
    assert g.is_valid(face) and g.shape_kind(face) == "surface"
    assert g.surface_control_points(face)[1] == (3, 3)
    return face


def _cap(shape, axis, level):
    matches = [(index, face) for index, face in enumerate(g.faces_of(shape))
               if BRepAdaptor_Surface(face).GetType() == GeomAbs_SurfaceType.GeomAbs_Plane
               and abs(g.centroid(face)[axis] - level) < 1e-6]
    assert len(matches) == 1, "The fixture/result must have one cap at this height"
    return matches[0]


def _hold_cap(selection, obj, held, axis=2, height=10):
    index, cap = _cap(obj.shape, axis, BASE[axis] + height)
    if held == "face":
        selection.toggle_subobject(obj.id, "face", index)
    else:
        boundary = g.edges_of(cap)
        assert len(boundary) == 1, "This is the complete circular rim of a solid cap"
        index = next(index for index, edge in enumerate(g.edges_of(obj.shape))
                     if edge.IsSame(boundary[0]))
        selection.toggle_subobject(obj.id, "edge", index)


def _assert_round_solid(shape, axis=2, height=10, inner=0):
    assert g.is_valid(shape) and g.shape_kind(shape) == "solid"
    assert g.volume(shape) == pytest.approx(math.pi * (4 ** 2 - inner ** 2) * height,
                                           rel=1e-7)
    assert g.free_boundaries(shape) == [], "The cap still closes all curved walls"
    walls, caps = [], []
    for face in g.faces_of(shape):
        adaptor = BRepAdaptor_Surface(face)
        if adaptor.GetType() == GeomAbs_SurfaceType.GeomAbs_Cylinder:
            walls.append(adaptor.Cylinder().Radius())
        else:
            assert adaptor.GetType() == GeomAbs_SurfaceType.GeomAbs_Plane
            caps.append(face)
    assert sorted(walls) == pytest.approx(sorted([4] + ([inner] if inner else [])))
    assert len(caps) == 2, "Unheld cylindrical walls stay curved"
    circles = []
    for edge in g.edges_of(shape):
        adaptor = BRepAdaptor_Curve(edge)
        if adaptor.GetType() == GeomAbs_CurveType.GeomAbs_Circle:
            circle = adaptor.Circle()
            center = g.pnt_tuple(circle.Location())
            assert [center[i] for i in range(3) if i != axis] == pytest.approx(
                [BASE[i] for i in range(3) if i != axis], abs=1e-6)
            assert g.curve_length(edge) == pytest.approx(2 * math.pi * circle.Radius())
            circles.append((round(circle.Radius(), 6), round(center[axis], 6)))
        else:
            assert adaptor.GetType() == GeomAbs_CurveType.GeomAbs_Line
            assert g.curve_length(edge) == pytest.approx(height)
    assert sorted(circles) == sorted((radius, BASE[axis] + z)
                                    for radius in ([4, inner] if inner else [4])
                                    for z in (0, height)), (
        "Both exact circular boundaries retain their radii, without polygonal replacements")
    for level in (BASE[axis], BASE[axis] + height):
        _index, cap = _cap(shape, axis, level)
        assert len(g.face_loops(cap, 32)) == (2 if inner else 1), "The bore remains open"


def _round_solid(scene, axis=2, inner=0):
    direction = tuple(float(index == axis) for index in range(3))
    shape = g.make_cylinder(BASE, 4, 10, direction)
    if inner:
        shape = g.boolean_difference(shape, g.make_cylinder(BASE, inner, 10, direction))
    _assert_round_solid(shape, axis, inner=inner)
    return scene.add(shape, name="Native tube" if inner else "Native cylinder")


@pytest.mark.parametrize("axis", range(3), ids=list("XYZ"))
def test_a_held_open_face_sets_only_the_enabled_coordinate(env, axis):
    scene, selection, _history, _ctx, proc = env
    obj = scene.add(_planar_face(SLOPED), name="Open sloped face")
    expected = [tuple(TARGET[i] if i == axis else p[i] for i in range(3))
                for p in SLOPED]
    _planar_face(expected)  # Each requested projection is a valid, noncollapsed surface.
    selection.toggle_subobject(obj.id, "face", 0)

    _setpt(proc, axis=axis)

    current = _current(scene, obj)
    assert len(scene.all()) == 1
    assert current.kind == "surface" and g.is_valid(current.shape)
    assert len(g.faces_of(current.shape)) == 1
    assert _corners(current.shape) == {_key(p) for p in expected}


def test_a_held_open_boundary_tilts_the_face_and_undo_restores_it(env):
    scene, selection, _history, _ctx, proc = env
    obj = scene.add(_planar_face(RECTANGLE), name="Open rectangle")
    expected = [RECTANGLE[0], RECTANGLE[1], (10, 6, 15), (0, 6, 15)]
    _planar_face(expected)
    index = next(index for index, edge in enumerate(g.edges_of(obj.shape))
                 if all(abs(p[1] - 6) < 1e-6 for p in g.curve_endpoints(edge)))
    selection.toggle_subobject(obj.id, "edge", index)

    _setpt(proc)

    current = _current(scene, obj)
    assert len(scene.all()) == 1
    assert g.is_valid(current.shape) and g.shape_kind(current.shape) == "surface"
    assert _corners(current.shape) == {_key(p) for p in expected}
    assert g.surface_area(current.shape) == pytest.approx(10 * math.hypot(6, 13))
    assert proc.run("undo") and not proc.busy
    restored = scene.get(obj.id)
    assert restored.name == obj.name and g.is_valid(restored.shape)
    assert _corners(restored.shape) == {_key(p) for p in RECTANGLE}


def test_a_held_untrimmed_nurbs_face_flattens_as_whole_surface_setpt(env):
    scene, selection, _history, _ctx, proc = env
    shape = _nurbs_face()
    obj = scene.add(shape, name="Held NURBS surface")
    whole = scene.add(g.copy_shape(shape), name="Whole-object comparison")
    remote = scene.add(g.translate(_nurbs_face(), (30, 0, 0)), name="Unselected curved surface")
    remote_before = g.shape_to_bytes(remote.shape)
    before, grid = g.surface_control_points(obj.shape)

    assert proc.run("setpt") and isinstance(proc.request, SelectReq)
    proc.click_object(whole.id)
    proc.finish_selection()
    assert isinstance(proc.request, PointReq)
    proc.provide(TARGET)
    assert not proc.busy and g.is_valid(_current(scene, whole).shape)
    expected = [(x, y, TARGET[2]) for x, y, _z in before]
    baseline, baseline_grid = g.surface_control_points(_current(scene, whole).shape)
    assert baseline_grid == grid
    for actual, wanted in zip(baseline, expected):
        assert actual == pytest.approx(wanted, abs=1e-6)
    selection.clear()
    selection.toggle_subobject(obj.id, "face", 0)

    _setpt(proc)

    current = _current(scene, obj)
    assert len(scene.all()) == 3
    assert g.is_valid(current.shape) and g.shape_kind(current.shape) == "surface"
    actual, after_grid = g.surface_control_points(current.shape)
    assert after_grid == grid and len(actual) == len(expected)
    for point, wanted in zip(actual, expected):
        assert point == pytest.approx(wanted, abs=1e-6)
    assert g.surface_area(current.shape) == pytest.approx(60)
    assert g.shape_to_bytes(_current(scene, remote).shape) == remote_before, (
        "Unselected curved geometry stays intact")


@pytest.mark.parametrize("axis", range(3), ids=list("XYZ"))
@pytest.mark.parametrize("held", ["face", "rim"])
def test_a_circular_cap_or_complete_rim_sets_the_cylinder_height(env, axis, held):
    scene, selection, _history, _ctx, proc = env
    obj = _round_solid(scene, axis)
    _hold_cap(selection, obj, held, axis)
    target = list(TARGET)
    target[axis] = BASE[axis] + 15

    _setpt(proc, target, axis)

    assert len(scene.all()) == 1
    _assert_round_solid(_current(scene, obj).shape, axis, height=15)
    assert proc.run("undo") and not proc.busy
    restored = scene.get(obj.id)
    assert restored.name == obj.name and restored.layer_id == obj.layer_id
    _assert_round_solid(restored.shape, axis)


def test_an_annular_cap_sets_height_without_filling_the_bore(env):
    scene, selection, _history, _ctx, proc = env
    obj = _round_solid(scene, inner=2)
    _hold_cap(selection, obj, "face")

    _setpt(proc, target=(91, -37, BASE[2] + 15))

    assert len(scene.all()) == 1
    _assert_round_solid(_current(scene, obj).shape, height=15, inner=2)


@pytest.mark.parametrize("held", ["face", "rim"])
def test_a_circular_cap_at_its_existing_height_is_a_valid_noop(env, held):
    scene, selection, _history, ctx, proc = env
    obj = _round_solid(scene)
    _hold_cap(selection, obj, held)
    messages = []
    ctx.add_echo_listener(messages.append)

    _setpt(proc, target=(91, -37, BASE[2] + 10))

    assert len(scene.all()) == 1
    _assert_round_solid(_current(scene, obj).shape)
    assert not any(any(word in message.casefold() for word in REFUSAL)
                   for message in messages), messages


@pytest.mark.parametrize("case", ["collapsed-cap", "collapsed-rim", "curved-wall"])
def test_a_collapsing_native_part_keeps_the_original_curved_solid_and_explains(env, case):
    scene, selection, _history, ctx, proc = env
    obj = _round_solid(scene)
    if case == "curved-wall":
        index = next(index for index, face in enumerate(g.faces_of(obj.shape))
                     if BRepAdaptor_Surface(face).GetType() == GeomAbs_SurfaceType.GeomAbs_Cylinder)
        selection.toggle_subobject(obj.id, "face", index)
        target = TARGET  # Flattening the entire wall leaves no cylindrical solid.
    else:
        _hold_cap(selection, obj, "face" if case == "collapsed-cap" else "rim")
        target = (91, -37, BASE[2])  # Top coincides with the bottom, giving zero height.
    before = g.shape_to_bytes(obj.shape)
    held_before = list(selection.subobjects)
    messages = []
    ctx.add_echo_listener(messages.append)

    _setpt(proc, target)

    current = _current(scene, obj)
    assert len(scene.all()) == 1
    assert g.shape_to_bytes(current.shape) == before
    _assert_round_solid(current.shape)
    assert selection.subobjects == held_before
    assert any(any(word in message.casefold() for word in REFUSAL)
               for message in messages), messages
