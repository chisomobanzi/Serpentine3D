"""SetPt acts on Ctrl+Shift-held segments without flattening their parent (#62)."""

import math

import pytest

from serpentine3d.commands.base import PointReq
from serpentine3d.core import geometry as g


CORNERS = [(0, 0, 1), (10, 5, 3), (20, 8, 7),
           (30, -3, 11), (40, 6, 13), (50, 2, 17)]
TARGET = (73.0, -29.0, 23.0)


def _edge_between(shape, a, b):
    for index, edge in enumerate(g.edges_of(shape)):
        p, q = g.curve_endpoints(edge)
        if ((math.dist(p, a) < 1e-6 and math.dist(q, b) < 1e-6)
                or (math.dist(p, b) < 1e-6 and math.dist(q, a) < 1e-6)):
            return index, edge
    raise AssertionError(f"No segment connects {a} to {b}")


def _hold(selection, obj, corners, indices):
    for index in indices:
        edge_index, _edge = _edge_between(
            obj.shape, corners[index], corners[index + 1])
        selection.toggle_subobject(obj.id, "edge", edge_index)


def _start(proc):
    assert proc.run("setpt")
    assert isinstance(proc.request, PointReq), (
        "SetPt must use the held curve segments and ask for the target point; "
        f"it instead asks {getattr(proc.request, 'prompt', None)!r}")


def _assert_chain(scene, obj, corners, closed=False):
    current = scene.get(obj.id)
    assert current is not None, "The segments remain in the original object"
    assert current.kind == "curve"
    assert current.name == obj.name
    shape = current.shape
    pairs = list(zip(corners, corners[1:]))
    if closed:
        pairs.append((corners[-1], corners[0]))
    assert len(g.edges_of(shape)) == len(pairs)
    assert g.is_closed_curve(shape) == closed
    for a, b in pairs:
        _index, edge = _edge_between(shape, a, b)
        assert g.curve_length(edge) == pytest.approx(math.dist(a, b), abs=1e-6)


@pytest.mark.parametrize("held", [(1,), (1, 2)])
def test_a_held_segment_goes_straight_to_the_target_and_axis_choices(env, held):
    scene, selection, _history, _ctx, proc = env
    obj = scene.add(g.make_polyline(CORNERS), name="Survey line")
    _hold(selection, obj, CORNERS, held)

    _start(proc)

    assert set(proc.request.choices) >= {"X", "Y", "Z"}
    for axis in "XYZ":
        assert set(proc.request.choices[axis]) == {"Yes", "No"}
    assert proc.option("X", "No") == "No"
    assert proc.option("Y", "No") == "No"
    assert proc.option("Z", "Yes") == "Yes"


@pytest.mark.parametrize("options, axes", [
    ({}, (False, False, True)),
    ({"X": "Yes", "Z": "No"}, (True, False, False)),
    ({"Y": "Yes", "Z": "No"}, (False, True, False)),
    ({"X": "Yes", "Y": "Yes", "Z": "No"}, (True, True, False)),
    ({"X": "Yes"}, (True, False, True)),
    ({"Y": "Yes"}, (False, True, True)),
], ids=["default-z", "x-only", "y-only", "xy", "xz", "yz"])
def test_only_enabled_coordinates_of_the_held_segment_are_set(env, options, axes):
    scene, selection, _history, _ctx, proc = env
    obj = scene.add(g.make_polyline(CORNERS), name="Survey line")
    other = scene.add(g.make_line((80, 1, 4), (90, 2, 8)), name="Other curve")
    _hold(selection, obj, CORNERS, [1])

    _start(proc)
    for axis, value in options.items():
        assert proc.set_option(axis, value)
    proc.provide(TARGET)

    assert not proc.busy
    expected = list(CORNERS)
    for index in (1, 2):
        expected[index] = tuple(TARGET[axis] if enabled else CORNERS[index][axis]
                                for axis, enabled in enumerate(axes))
    _assert_chain(scene, obj, expected)
    _assert_chain(scene, other, [(80, 1, 4), (90, 2, 8)])
    assert {o.id for o in scene.all()} == {obj.id, other.id}


@pytest.mark.parametrize("held", [(0, 1), (1, 3)], ids=["adjacent", "separate"])
def test_several_held_segments_on_several_curves_share_one_target(env, held):
    scene, selection, _history, _ctx, proc = env
    first = scene.add(g.make_polyline(CORNERS), name="First curve")
    shifted = [(x + 100, y + 20, z + 2) for x, y, z in CORNERS]
    second = scene.add(g.make_polyline(shifted), name="Second curve")
    _hold(selection, first, CORNERS, held)
    _hold(selection, second, shifted, [2])

    _start(proc)
    proc.provide(TARGET)

    assert not proc.busy
    changed = {point for index in held for point in (index, index + 1)}
    expected_first = [(x, y, TARGET[2] if index in changed else z)
                      for index, (x, y, z) in enumerate(CORNERS)]
    expected_second = [(x, y, TARGET[2] if index in (2, 3) else z)
                       for index, (x, y, z) in enumerate(shifted)]
    _assert_chain(scene, first, expected_first)
    _assert_chain(scene, second, expected_second)
    assert {o.id for o in scene.all()} == {first.id, second.id}


def test_a_closed_curve_keeps_both_neighbours_attached_to_its_held_side(env):
    scene, selection, _history, _ctx, proc = env
    corners = [(0, 0, 1), (10, 3, 2), (10, 10, 3), (0, 10, 4)]
    obj = scene.add(g.make_polyline(corners, closed=True), name="Closed curve")
    _hold(selection, obj, corners, [0])

    _start(proc)
    proc.provide((99.0, 88.0, 9.0))

    assert not proc.busy
    _assert_chain(scene, obj, [(0, 0, 9), (10, 3, 9), corners[2], corners[3]],
                  closed=True)
    assert len(scene.all()) == 1


def test_a_held_spline_is_flattened_throughout_and_a_remote_spline_stays_curved(env):
    scene, selection, _history, _ctx, proc = env
    poles = [(10, 5, 3), (13, 12, 14), (17, -2, 9), (20, 8, 7)]
    remote_poles = [(30, -3, 11), (34, 7, 16), (38, -8, 19), (40, 6, 13)]
    joined = g.join_curves([
        g.make_line(CORNERS[0], poles[0]),
        g.make_control_curve(poles),
        g.make_line(poles[-1], remote_poles[0]),
        g.make_control_curve(remote_poles),
    ])
    obj = scene.add(joined, name="Polycurve")
    index, _edge = _edge_between(obj.shape, poles[0], poles[-1])
    selection.toggle_subobject(obj.id, "edge", index)
    _remote_index, remote_before = _edge_between(
        obj.shape, remote_poles[0], remote_poles[-1])
    before_samples = g.sample_curve(remote_before, 17)

    _start(proc)
    proc.provide(TARGET)

    assert not proc.busy
    shape = scene.get(obj.id).shape
    assert len(scene.all()) == 1 and len(g.edges_of(shape)) == 4
    a, b = (poles[0][0], poles[0][1], TARGET[2]), (
        poles[-1][0], poles[-1][1], TARGET[2])
    _index, held_after = _edge_between(shape, a, b)
    after_poles = g.get_control_points(held_after)
    assert len(after_poles) == len(poles)
    for got, (x, y, _z) in zip(after_poles, poles):
        assert got == pytest.approx((x, y, TARGET[2]), abs=1e-6)
    assert all(p[2] == pytest.approx(TARGET[2], abs=1e-6)
               for p in g.sample_curve(held_after, 17))
    assert g.curve_length(held_after) > math.dist(a, b), "The spline stays curved"
    _edge_between(shape, CORNERS[0], a)
    _edge_between(shape, b, remote_poles[0])
    _index, remote_after = _edge_between(shape, remote_poles[0], remote_poles[-1])
    after_samples = g.sample_curve(remote_after, 17)
    forward = max(math.dist(a, b) for a, b in zip(before_samples, after_samples))
    backward = max(math.dist(a, b) for a, b in zip(before_samples, reversed(after_samples)))
    assert min(forward, backward) < 1e-6, "The unheld remote spline is unchanged"


def test_undo_restores_every_segment_and_shared_corner(env):
    scene, selection, history, _ctx, proc = env
    obj = scene.add(g.make_polyline(CORNERS), name="Survey line")
    _hold(selection, obj, CORNERS, [1, 2])

    _start(proc)
    proc.provide(TARGET)
    assert not proc.busy and history.can_undo
    expected = [(x, y, TARGET[2] if index in (1, 2, 3) else z)
                for index, (x, y, z) in enumerate(CORNERS)]
    _assert_chain(scene, obj, expected)

    proc.run("undo")

    _assert_chain(scene, obj, CORNERS)
    assert len(scene.all()) == 1
    assert not history.can_undo


@pytest.mark.parametrize("change_options", [False, True])
def test_cancelling_setpt_leaves_the_original_curve_and_no_undo_entry(env, change_options):
    scene, selection, history, _ctx, proc = env
    obj = scene.add(g.make_polyline(CORNERS), name="Survey line")
    _hold(selection, obj, CORNERS, [1, 3])

    _start(proc)
    if change_options:
        assert proc.set_option("X", "Yes")
        assert proc.set_option("Z", "No")
    proc.cancel()

    assert not proc.busy
    _assert_chain(scene, obj, CORNERS)
    assert len(scene.all()) == 1
    assert not history.can_undo


def test_switching_all_axes_off_leaves_the_held_segments_unchanged(env):
    scene, selection, _history, _ctx, proc = env
    obj = scene.add(g.make_polyline(CORNERS), name="Survey line")
    _hold(selection, obj, CORNERS, [1, 2])

    _start(proc)
    for axis in "XYZ":
        assert proc.set_option(axis, "No")
    proc.provide(TARGET)

    assert not proc.busy
    _assert_chain(scene, obj, CORNERS)
    assert len(scene.all()) == 1
