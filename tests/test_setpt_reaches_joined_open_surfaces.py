"""SetPt changes held panels and shared edges of an open polysurface (#62)."""

import pytest

from serpentine3d.commands.base import PointReq
from serpentine3d.core import geometry as g


PANELS = [
    [(0, 0, 2), (10, 0, 2), (10, 6, 5), (0, 6, 5)],
    [(10, 0, 2), (0, 0, 2), (0, -6, 2), (10, -6, 2)],
]
TARGET = (91.0, -37.0, 15.0)
REFUSAL = ("needs", "unsupported", "collaps", "degener", "invalid",
           "cannot", "can't", "could not", "unable", "fail", "zero")


def _key(point):
    return tuple(round(coordinate, 6) for coordinate in point)


def _corners(shape):
    return frozenset(_key(point) for edge in g.edges_of(shape)
                     for point in g.curve_endpoints(edge))


def _assert_shell(shape, panels):
    assert g.is_valid(shape), "Both neighboring panels must remain valid"
    assert g.shape_kind(shape) == "surface"
    assert shape.ShapeType() == g.occ.SHELL and not shape.Closed()
    faces = g.faces_of(shape)
    wanted = [frozenset(_key(point) for point in panel) for panel in panels]
    assert len(faces) == 2
    assert {_corners(face) for face in faces} == set(wanted), (
        "The adjoining panel follows the shared edge; unheld corners stay put")
    assert all(g.surface_area(face) > 0 for face in faces)
    edges = g.edges_of(shape)
    assert len(edges) == 7
    boundaries = [g.edges_of(face) for face in faces]
    shared = [edge for edge in edges
              if sum(any(edge.IsSame(boundary) for boundary in ring)
                     for ring in boundaries) == 2]
    assert len(shared) == 1, "The two faces still share a topological edge"
    assert _corners(shared[0]) == wanted[0] & wanted[1]


def _joined(panels):
    faces = [g.planar_face(g.make_polyline(panel, closed=True))
             for panel in panels]
    assert all(g.is_valid(face) and g.surface_area(face) > 0 for face in faces)
    shape = g.join_surfaces(faces)
    _assert_shell(shape, panels)
    return shape


def _panel_object(scene, name):
    layer = scene.layers.create("Joined panels")
    obj = scene.add(_joined(PANELS), name=name, layer_id=layer.id)
    return obj, (obj.id, obj.name, obj.layer_id)


def _current(scene, identity):
    assert len(scene.all()) == 1
    obj = scene.get(identity[0])
    assert obj is not None, "The joined surface retains its scene identity"
    assert (obj.id, obj.name, obj.layer_id) == identity
    assert obj.kind == "surface"
    return obj


def _hold_panel(selection, obj):
    index = next(index for index, face in enumerate(g.faces_of(obj.shape))
                 if _corners(face) == frozenset(_key(p) for p in PANELS[0]))
    selection.toggle_subobject(obj.id, "face", index)


def _setpt(proc, target=TARGET, axis=2):
    assert proc.run("setpt")
    assert isinstance(proc.request, PointReq), (
        "Held open-polysurface parts go straight to the SetPt target; "
        f"got {getattr(proc.request, 'prompt', None)!r}")
    assert set(proc.request.choices) >= {"X", "Y", "Z"}
    for index, name in enumerate("XYZ"):
        assert proc.set_option(name, "Yes" if index == axis else "No")
    proc.provide(tuple(float(coordinate) for coordinate in target))
    assert not proc.busy


def test_a_held_panel_levels_and_its_neighbor_follows_the_shared_edge(env):
    scene, selection, _history, _ctx, proc = env
    obj, identity = _panel_object(scene, "Joined roof panels")
    expected = [
        [(x, y, TARGET[2]) for x, y, _z in PANELS[0]],
        [(x, y, TARGET[2] if y == 0 else z) for x, y, z in PANELS[1]],
    ]
    _joined(expected)  # The requested level is a valid, connected open shell.
    _hold_panel(selection, obj)

    _setpt(proc)

    _assert_shell(_current(scene, identity).shape, expected)
    assert proc.run("undo") and not proc.busy
    _assert_shell(_current(scene, identity).shape, PANELS)


@pytest.mark.parametrize("height", [15.0, -4.0], ids=["raise", "lower"])
def test_a_held_shared_edge_sets_both_neighbors_and_leaves_other_corners(env, height):
    scene, selection, _history, _ctx, proc = env
    obj, identity = _panel_object(scene, "Joined folded sheet")
    expected = [[(x, y, height if y == 0 else z) for x, y, z in panel]
                for panel in PANELS]
    _joined(expected)
    wanted = frozenset((_key(PANELS[0][0]), _key(PANELS[0][1])))
    index = next(index for index, edge in enumerate(g.edges_of(obj.shape))
                 if _corners(edge) == wanted)
    selection.toggle_subobject(obj.id, "edge", index)

    _setpt(proc, (TARGET[0], TARGET[1], height))

    _assert_shell(_current(scene, identity).shape, expected)


def test_a_collapsing_panel_projection_keeps_the_joined_surface_and_explains(env):
    scene, selection, _history, ctx, proc = env
    obj, identity = _panel_object(scene, "Keep these joined panels")
    # Setting X collapses each pair of panel corners to one point: no face.
    projected = {(TARGET[0], y, z) for _x, y, z in PANELS[0]}
    assert len(projected) == 2
    _hold_panel(selection, obj)
    before = g.shape_to_bytes(obj.shape)
    messages = []
    ctx.add_echo_listener(messages.append)

    _setpt(proc, axis=0)

    current = _current(scene, identity)
    assert g.shape_to_bytes(current.shape) == before
    _assert_shell(current.shape, PANELS)
    assert any(any(word in message.casefold() for word in REFUSAL)
               for message in messages), messages
