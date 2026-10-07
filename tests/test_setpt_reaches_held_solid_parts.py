"""SetPt levels Ctrl+Shift-held solid parts without moving unheld corners (#62)."""

import math

import pytest

from serpentine3d.commands.base import PointReq
from serpentine3d.core import geometry as g


BASE = [(0, 0, 0), (10, 0, 0), (10, 6, 0), (0, 6, 0)]
TOP = [(0, 0, 10), (10, 0, 10), (10, 6, 10), (0, 6, 10)]
SLOPED_TOP = [(0, 0, 8), (10, 0, 14), (10, 6, 14), (0, 6, 8)]
TARGET = (14.0, 9.0, 15.0)


def _key(point):
    return tuple(round(coordinate, 6) for coordinate in point)


def _corners(shape):
    return frozenset(_key(point) for edge in g.edges_of(shape)
                     for point in g.curve_endpoints(edge))


def _face_with(shape, corners):
    wanted = frozenset(_key(point) for point in corners)
    for index, face in enumerate(g.faces_of(shape)):
        if _corners(face) == wanted:
            return index
    raise AssertionError(f"No face has corners {wanted}")


def _edge_between(shape, a, b):
    for index, edge in enumerate(g.edges_of(shape)):
        p, q = g.curve_endpoints(edge)
        if ((math.dist(p, a) < 1e-6 and math.dist(q, b) < 1e-6)
                or (math.dist(p, b) < 1e-6 and math.dist(q, a) < 1e-6)):
            return index
    raise AssertionError(f"No edge connects {a} to {b}")


def _face_rings(bottom, top):
    return [bottom, top] + [
        [bottom[index], bottom[(index + 1) % 4],
         top[(index + 1) % 4], top[index]]
        for index in range(4)
    ]


def _assert_solid(scene, obj, bottom, top, volume):
    current = scene.get(obj.id)
    assert current is not None, "The solid keeps its scene object identity"
    assert current.kind == "solid"
    assert current.name == obj.name
    assert current.layer_id == obj.layer_id
    shape = current.shape
    assert g.shape_kind(shape) == "solid"
    assert g.is_valid(shape), "The neighboring faces must still form a valid solid"
    assert g.volume(shape) == pytest.approx(volume, abs=1e-6)

    faces = g.faces_of(shape)
    expected_faces = {frozenset(_key(point) for point in ring)
                      for ring in _face_rings(bottom, top)}
    assert len(faces) == len(expected_faces) == 6
    assert {_corners(face) for face in faces} == expected_faces, (
        "Every adjacent face meets the changed corners; unheld corners stay put")

    expected_pairs = [(ring[index], ring[(index + 1) % 4])
                      for ring in (bottom, top) for index in range(4)]
    expected_pairs += list(zip(bottom, top))
    edges = g.edges_of(shape)
    assert len(edges) == len(expected_pairs) == 12
    face_edges = [g.edges_of(face) for face in faces]
    for a, b in expected_pairs:
        edge = edges[_edge_between(shape, a, b)]
        assert g.curve_length(edge) == pytest.approx(math.dist(a, b), abs=1e-6)
        assert sum(any(edge.IsSame(boundary) for boundary in boundaries)
                   for boundaries in face_edges) == 2, (
            "Each edge is shared by its two neighbors, with no detached faces")


def _box(scene, name="Box"):
    obj = scene.add(g.make_box((0, 0, 0), 10, 6, 10), name=name)
    _assert_solid(scene, obj, BASE, TOP, 600)
    return obj


def _wedge(scene):
    section = g.make_polyline([BASE[0], BASE[1], SLOPED_TOP[1], SLOPED_TOP[0]],
                              closed=True)
    obj = scene.add(g.extrude(section, (0, 1, 0), 6, cap=True), name="Sloped roof")
    _assert_solid(scene, obj, BASE, SLOPED_TOP, 660)
    return obj


def _hold_top(selection, obj, mode, top=TOP):
    if mode in ("face", "face-and-rim"):
        selection.toggle_subobject(obj.id, "face", _face_with(obj.shape, top))
    if mode in ("rim", "face-and-rim", "opposite-rim"):
        indices = (0, 2) if mode == "opposite-rim" else range(4)
        for index in indices:
            selection.toggle_subobject(
                obj.id, "edge", _edge_between(obj.shape, top[index],
                                               top[(index + 1) % 4]))


def _start(proc):
    assert proc.run("setpt")
    assert isinstance(proc.request, PointReq), (
        "SetPt must use the held faces or solid edges and ask for the target; "
        f"it instead asks {getattr(proc.request, 'prompt', None)!r}")
    assert set(proc.request.choices) >= {"X", "Y", "Z"}
    for axis in "XYZ":
        assert set(proc.request.choices[axis]) == {"Yes", "No"}


def _setpt(proc, target=TARGET, options=None):
    _start(proc)
    for axis, value in (options or {}).items():
        assert proc.set_option(axis, value)
    proc.provide(tuple(float(coordinate) for coordinate in target))
    assert not proc.busy


@pytest.mark.parametrize("held", ["face", "rim", "face-and-rim"])
def test_held_solid_parts_go_straight_to_the_target_and_axis_choices(env, held):
    scene, selection, _history, _ctx, proc = env
    obj = _box(scene)
    _hold_top(selection, obj, held)

    _start(proc)

    assert proc.option("X", "No") == "No"
    assert proc.option("Y", "No") == "No"
    assert proc.option("Z", "Yes") == "Yes"


@pytest.mark.parametrize("held", ["face", "rim", "opposite-rim", "face-and-rim"])
def test_the_top_and_its_rim_are_set_once_and_the_bottom_stays_put(env, held):
    scene, selection, _history, _ctx, proc = env
    obj = _box(scene)
    other = scene.add(g.make_box((40, 20, 2), 10, 6, 10), name="Unheld solid")
    other_bottom = [(x + 40, y + 20, z + 2) for x, y, z in BASE]
    other_top = [(x + 40, y + 20, z + 2) for x, y, z in TOP]
    _hold_top(selection, obj, held)

    _setpt(proc, target=(91.0, -37.0, 15.0))

    _assert_solid(scene, obj, BASE, [(x, y, 15) for x, y, _z in TOP], 900)
    _assert_solid(scene, other, other_bottom, other_top, 600)
    assert {item.id for item in scene.all()} == {obj.id, other.id}


@pytest.mark.parametrize("held", ["face", "rim"])
def test_a_sloped_top_is_leveled_to_one_z_rather_than_translated(env, held):
    scene, selection, _history, _ctx, proc = env
    obj = _wedge(scene)
    _hold_top(selection, obj, held, SLOPED_TOP)

    _setpt(proc)

    _assert_solid(scene, obj, BASE,
                  [(x, y, 15) for x, y, _z in SLOPED_TOP], 900)
    assert {item.id for item in scene.all()} == {obj.id}


@pytest.mark.parametrize("kind, corner_indices, options, axes, volume", [
    ("face", (1, 2, 5, 6), {"X": "Yes", "Z": "No"},
     (True, False, False), 840),
    ("face", (2, 3, 6, 7), {"Y": "Yes", "Z": "No"},
     (False, True, False), 900),
    ("edge", (5, 6), {"X": "Yes", "Z": "No"},
     (True, False, False), 720),
    ("edge", (6, 7), {"Y": "Yes", "Z": "No"},
     (False, True, False), 750),
    ("edge", (2, 6), {"X": "Yes", "Y": "Yes", "Z": "No"},
     (True, True, False), 870),
    ("edge", (5, 6), {"X": "Yes"}, (True, False, True), 870),
    ("edge", (6, 7), {"Y": "Yes"}, (False, True, True), 900),
], ids=["face-x", "face-y", "edge-x", "edge-y", "edge-xy", "edge-xz", "edge-yz"])
def test_only_enabled_coordinates_of_the_held_part_are_set(
        env, kind, corner_indices, options, axes, volume):
    scene, selection, _history, _ctx, proc = env
    obj = _box(scene)
    corners = BASE + TOP
    held_corners = [corners[index] for index in corner_indices]
    if kind == "face":
        index = _face_with(obj.shape, held_corners)
    else:
        index = _edge_between(obj.shape, *held_corners)
    selection.toggle_subobject(obj.id, kind, index)

    _setpt(proc, options=options)

    expected = list(corners)
    for index in corner_indices:
        expected[index] = tuple(TARGET[axis] if enabled else corners[index][axis]
                                for axis, enabled in enumerate(axes))
    _assert_solid(scene, obj, expected[:4], expected[4:], volume)
    assert {item.id for item in scene.all()} == {obj.id}


def test_faces_and_edges_on_several_solids_share_the_target(env):
    scene, selection, _history, _ctx, proc = env
    first = _box(scene, name="First solid")
    second = scene.add(g.make_box((30, 20, 2), 10, 6, 10), name="Second solid")
    second_bottom = [(x + 30, y + 20, z + 2) for x, y, z in BASE]
    second_top = [(x + 30, y + 20, z + 2) for x, y, z in TOP]
    _assert_solid(scene, second, second_bottom, second_top, 600)
    _hold_top(selection, first, "face-and-rim")
    _hold_top(selection, second, "opposite-rim", second_top)

    _setpt(proc)

    _assert_solid(scene, first, BASE, [(x, y, 15) for x, y, _z in TOP], 900)
    _assert_solid(scene, second, second_bottom,
                  [(x, y, 15) for x, y, _z in second_top], 780)
    assert {item.id for item in scene.all()} == {first.id, second.id}


def test_undo_restores_the_solid_and_all_shared_corners(env):
    scene, selection, history, _ctx, proc = env
    obj = _wedge(scene)
    _hold_top(selection, obj, "face-and-rim", SLOPED_TOP)

    _setpt(proc)
    _assert_solid(scene, obj, BASE, [(x, y, 15) for x, y, _z in SLOPED_TOP], 900)
    assert history.can_undo

    assert proc.run("undo")

    _assert_solid(scene, obj, BASE, SLOPED_TOP, 660)
    assert {item.id for item in scene.all()} == {obj.id}
    assert not history.can_undo


@pytest.mark.parametrize("change_options", [False, True])
def test_cancelling_setpt_keeps_the_original_solid_without_an_undo_entry(
        env, change_options):
    scene, selection, history, _ctx, proc = env
    obj = _wedge(scene)
    _hold_top(selection, obj, "face-and-rim", SLOPED_TOP)

    _start(proc)
    if change_options:
        assert proc.set_option("X", "Yes")
        assert proc.set_option("Z", "No")
    proc.cancel()

    assert not proc.busy
    _assert_solid(scene, obj, BASE, SLOPED_TOP, 660)
    assert {item.id for item in scene.all()} == {obj.id}
    assert not history.can_undo


@pytest.mark.parametrize("held, target, options", [
    ("face", TARGET, {"X": "Yes", "Z": "No"}),
    ("vertical-edge", (20.0, 30.0, 5.0), {}),
    ("face-and-rim", (20.0, 30.0, 0.0), {}),
], ids=["face-collapse", "edge-collapse", "solid-collapse"])
def test_a_collapsing_projection_reports_why_and_keeps_the_solid_and_selection(
        env, held, target, options):
    scene, selection, _history, ctx, proc = env
    obj = _box(scene)
    if held == "vertical-edge":
        selection.toggle_subobject(obj.id, "edge",
                                   _edge_between(obj.shape, BASE[2], TOP[2]))
    else:
        _hold_top(selection, obj, held)
    held_before = list(selection.subobjects)
    messages = []
    ctx.add_echo_listener(messages.append)

    _setpt(proc, target=target, options=options)

    _assert_solid(scene, obj, BASE, TOP, 600)
    assert {item.id for item in scene.all()} == {obj.id}
    assert selection.subobjects == held_before
    diagnostic_words = ("collaps", "degener", "invalid", "cannot", "can't",
                        "could not", "unable", "fail", "zero", "flatten")
    assert any(any(word in message.casefold() for word in diagnostic_words)
               for message in messages), messages


def test_switching_all_axes_off_keeps_the_held_solid_parts_unchanged(env):
    scene, selection, _history, _ctx, proc = env
    obj = _box(scene)
    _hold_top(selection, obj, "face-and-rim")

    _setpt(proc, options={axis: "No" for axis in "XYZ"})

    _assert_solid(scene, obj, BASE, TOP, 600)
    assert {item.id for item in scene.all()} == {obj.id}
