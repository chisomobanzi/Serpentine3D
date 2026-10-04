"""SetPt shows its pending result without editing the selected originals.

These use the public cursor/typed preview boundary and compare the complete
ghost with independently constructed geometry and with command completion.
"""

from __future__ import annotations

import numpy as np
import pytest

from serpentine3d.commands.base import PointReq, SelectReq
from serpentine3d.core import geometry as g
from serpentine3d.core import occ


TARGET = (40.0, 50.0, 12.0)
KINDS = ("point", "control-curve", "polyline", "surface")


def _shape(kind, z=None):
    points = {
        "point": [(1.0, 2.0, 3.0)],
        "control-curve": [(5.0, 0.0, 2.0), (8.0, 8.0, 9.0),
                          (12.0, -4.0, 5.0), (15.0, 6.0, 7.0)],
        "polyline": [(0.0, 10.0, 1.0), (4.0, 12.0, 6.0),
                     (8.0, 10.0, 4.0)],
        # A planar face that leans in Z, with finite trimmed bounds.
        "surface": [(20.0, 2.0, 1.0), (24.0, 2.0, 5.0),
                    (24.0, 8.0, 5.0), (20.0, 8.0, 1.0)],
    }[kind]
    if z is not None:
        points = [(x, y, z) for x, y, _ in points]
    if kind == "point":
        return g.make_point(points[0])
    if kind == "control-curve":
        return g.make_control_curve(points, degree=3)
    wire = g.make_polyline(points, closed=kind == "surface")
    return g.planar_face(wire) if kind == "surface" else wire


def _vertices(shape):
    vertices = occ.map_shapes(shape, occ.VERTEX)
    return sorted(g.point_coords(vertices.FindKey(i))
                  for i in range(1, vertices.Extent() + 1))


def _edge_samples(shape):
    # Interior samples distinguish the entire curved result from a band
    # between endpoints; sorted positions ignore topology traversal order.
    return sorted(tuple(round(float(v), 6) for v in point)
                  for edge in g.edges_of(shape)
                  for point in g.sample_curve(edge, 11))


def _assert_geometry(actual, expected):
    assert actual is not None, "SetPt has no result preview while picking its target"
    assert g.is_valid(actual), "SetPt's preview must be drawable geometry"
    assert len(g.faces_of(actual)) == len(g.faces_of(expected))
    assert len(g.edges_of(actual)) == len(g.edges_of(expected))
    assert np.asarray(_vertices(actual)) == pytest.approx(
        np.asarray(_vertices(expected)), abs=2e-6)
    assert np.asarray(_edge_samples(actual)) == pytest.approx(
        np.asarray(_edge_samples(expected)), abs=2e-6)
    assert np.asarray(g.bbox(actual)) == pytest.approx(
        np.asarray(g.bbox(expected)), abs=2e-6)
    assert occ.surface_properties(actual).Mass() == pytest.approx(
        occ.surface_properties(expected).Mass(), abs=1e-5)


def _start(proc, selection, objects):
    selection.set([obj.id for obj in objects])
    assert proc.run("setpt")
    assert isinstance(proc.request, PointReq)


def _preview(proc, input_kind, target=TARGET):
    if input_kind == "typed":
        return proc.preview_shape(",".join(str(v) for v in target))
    return proc.preview_for(target)


@pytest.mark.parametrize("input_kind", ("cursor", "typed"))
@pytest.mark.parametrize("kind", KINDS)
def test_supported_geometry_previews_the_default_z_result_and_matches_commit(
        env, kind, input_kind):
    scene, selection, _history, _ctx, proc = env
    obj = scene.add(_shape(kind), name=kind)
    _start(proc, selection, [obj])

    ghost = _preview(proc, input_kind)

    _assert_geometry(ghost, _shape(kind, z=TARGET[2]))
    proc.provide(TARGET)
    assert not proc.busy
    _assert_geometry(ghost, scene.get(obj.id).shape)


@pytest.mark.parametrize("input_kind", ("cursor", "typed"))
def test_preview_contains_every_selected_object_and_excludes_unselected_geometry(
        env, input_kind):
    scene, selection, _history, _ctx, proc = env
    objects = [scene.add(_shape(kind), name=kind) for kind in KINDS]
    unselected = scene.add(g.make_point((100.0, 100.0, 100.0)))
    original_unselected = unselected.shape
    _start(proc, selection, objects)

    ghost = _preview(proc, input_kind)

    _assert_geometry(ghost, g.make_compound(
        [_shape(kind, z=TARGET[2]) for kind in KINDS]))
    proc.provide(TARGET)
    _assert_geometry(ghost, g.make_compound(
        [scene.get(obj.id).shape for obj in objects]))
    assert scene.get(unselected.id).shape.IsSame(original_unselected)


@pytest.mark.parametrize("input_kind", ("cursor", "typed"))
def test_preview_tracks_live_axis_options_and_all_axes_off_is_honest(
        env, input_kind):
    scene, selection, _history, _ctx, proc = env
    obj = scene.add(g.make_point((1.0, 2.0, 3.0)))
    original = obj.shape
    _start(proc, selection, [obj])
    request = proc.request

    _assert_geometry(_preview(proc, input_kind), g.make_point((1.0, 2.0, 12.0)))
    proc.provide_text("X=Yes")
    proc.provide_text("Z=No")
    assert proc.request is request
    _assert_geometry(_preview(proc, input_kind), g.make_point((40.0, 2.0, 3.0)))
    proc.provide_text("Y=Yes")
    _assert_geometry(_preview(proc, input_kind), g.make_point((40.0, 50.0, 3.0)))

    proc.provide_text("X=No")
    proc.provide_text("Y=No")
    no_change = _preview(proc, input_kind)
    if no_change is not None:
        _assert_geometry(no_change, original)
    assert scene.get(obj.id).shape.IsSame(original)

    proc.provide_text("Z=Yes")
    final_ghost = _preview(proc, input_kind)
    _assert_geometry(final_ghost, g.make_point((1.0, 2.0, 12.0)))
    proc.provide(TARGET)
    _assert_geometry(final_ghost, scene.get(obj.id).shape)


def test_repeated_previews_are_pure_and_cancel_preserves_originals_and_prior_undo(env):
    scene, selection, history, ctx, proc = env
    objects = [scene.add(_shape(kind), name=kind) for kind in KINDS]
    originals = [obj.shape for obj in objects]
    history.checkpoint("earlier edit")
    sentinel = scene.add(g.make_point((100.0, 100.0, 100.0)))
    _start(proc, selection, objects)
    revision = scene.revision
    selected_ids = list(selection.ids)
    subobjects = list(selection.subobjects)
    object_ids = [obj.id for obj in scene.all()]
    checkpoints, discards, selection_changes, messages = [], [], [], []
    history.on_checkpoint = checkpoints.append
    history.on_discard = lambda: discards.append(True)
    selection.add_listener(lambda: selection_changes.append(True))
    ctx.add_echo_listener(messages.append)

    first = proc.preview_for((40.0, 50.0, 2.0))
    second = proc.preview_for(TARGET)
    again = proc.preview_shape("40,50,2")

    _assert_geometry(first, g.make_compound([_shape(kind, z=2.0) for kind in KINDS]))
    _assert_geometry(second, g.make_compound(
        [_shape(kind, z=TARGET[2]) for kind in KINDS]))
    _assert_geometry(again, first)
    assert [obj.id for obj in scene.all()] == object_ids
    for obj, original, kind in zip(objects, originals, KINDS):
        assert scene.get(obj.id) is obj
        assert obj.shape.IsSame(original)
        _assert_geometry(obj.shape, _shape(kind))
    assert scene.revision == revision
    assert selection.ids == selected_ids and selection.subobjects == subobjects
    assert selection_changes == [] and checkpoints == [] and discards == []
    assert messages == [], "Previewing must not announce completed SetPt edits"
    assert history.can_undo and not history.can_redo

    proc.cancel()

    assert not proc.busy
    assert discards == [True] and checkpoints == []
    assert scene.revision == revision
    assert selection.ids == selected_ids and selection.subobjects == subobjects
    for obj, original, kind in zip(objects, originals, KINDS):
        assert scene.get(obj.id) is obj
        assert obj.shape.IsSame(original)
        _assert_geometry(obj.shape, _shape(kind))
    assert history.undo() == "earlier edit", "Cancel must preserve the preceding undo"
    assert scene.get(sentinel.id) is None
    assert not history.can_undo


def test_malformed_candidates_are_quiet_and_later_valid_input_still_previews(env):
    scene, selection, _history, ctx, proc = env
    obj = scene.add(_shape("control-curve"))
    original = obj.shape
    _start(proc, selection, [obj])
    selected_ids = list(selection.ids)
    messages = []
    ctx.add_echo_listener(messages.append)
    for candidate in (None, 5.0, "not a point", (1.0, 2.0), (1.0, 2.0, "bad")):
        assert proc.preview_for(candidate) is None
    for text in ("", "not a point", "1,", "1,2,bad"):
        assert proc.preview_shape(text) is None
    assert messages == []
    assert proc.busy and scene.get(obj.id).shape.IsSame(original)
    assert selection.ids == selected_ids

    ghost = proc.preview_shape("40,50,12")

    _assert_geometry(ghost, _shape("control-curve", z=TARGET[2]))
    proc.provide(TARGET)
    _assert_geometry(ghost, scene.get(obj.id).shape)


def test_unsupported_solid_is_refused_and_never_enters_the_result_preview(env):
    scene, selection, _history, _ctx, proc = env
    solid = scene.add(g.make_box((100.0, 100.0, 100.0), 2.0, 3.0, 4.0))
    original_solid = solid.shape
    point = scene.add(_shape("point"))
    assert proc.run("setpt")
    proc.click_object(solid.id)
    assert isinstance(proc.request, SelectReq)
    assert proc.preview_for(TARGET) is None
    assert scene.get(solid.id).shape.IsSame(original_solid)

    proc.click_object(point.id)
    proc.finish_selection()
    assert isinstance(proc.request, PointReq)
    ghost = proc.preview_for(TARGET)

    _assert_geometry(ghost, _shape("point", z=TARGET[2]))
    proc.provide(TARGET)
    assert scene.get(solid.id).shape.IsSame(original_solid)
    _assert_geometry(ghost, scene.get(point.id).shape)
