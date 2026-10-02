"""Pending subobject transforms show the resulting parent geometry (#48).

These exercise the same public preview boundary used for cursor ghosts,
then compare that preview with the actual command completion. A selected
face or segment alone is not an honest preview: its unselected neighbors
must also show how they will meet it.
"""

from __future__ import annotations

import itertools
import json
import math

import numpy as np
import pytest

import serpentine3d.commands  # registers the commands  # noqa: F401
from serpentine3d.commands.base import PointReq
from serpentine3d.core import geometry as g


def _box(scene):
    return scene.add(g.make_box((0, 0, 0), 10, 10, 10), name="Box")


def _rect(scene):
    return scene.add(g.make_polyline(
        [(0, 0, 0), (10, 0, 0), (10, 6, 0), (0, 6, 0)], closed=True))


def _face(shape, normal):
    return next(i for i, f in enumerate(g.faces_of(shape))
                if sum(a * b for a, b in zip(g.face_normal(f), normal)) > 0.9)


def _edge(shape, midpoint):
    return next(i for i, e in enumerate(g.edges_of(shape))
                if math.dist(g.centroid(e), midpoint) < 1e-6)


def _points(shape):
    """Observable corners/endpoints, independent of rebuilt topology order."""
    return sorted({tuple(round(float(v), 6) for v in p)
                   for e in g.edges_of(shape) for p in g.curve_endpoints(e)})


def _assert_points(shape, expected):
    expected = sorted({tuple(round(float(v), 6) for v in p)
                       for p in expected})
    assert _points(shape) == pytest.approx(np.asarray(expected), abs=2e-6)


def _assert_same_geometry(preview, committed):
    assert len(g.faces_of(preview)) == len(g.faces_of(committed))
    assert len(g.edges_of(preview)) == len(g.edges_of(committed))
    _assert_points(preview, _points(committed))
    assert np.asarray(g.bbox(preview)) == pytest.approx(
        np.asarray(g.bbox(committed)), abs=2e-6)
    assert g.volume(preview) == pytest.approx(g.volume(committed), abs=1e-5)


def _start(proc, command, *answers):
    assert proc.run(command)
    for answer in answers:
        proc.provide(answer)
    assert isinstance(proc.request, PointReq)
    assert proc.request.preview_fn is not None


def _preview(proc, cursor):
    ghost = proc.preview_for(cursor)
    assert ghost is not None, "the pending subobject edit has no parent ghost"
    assert g.is_valid(ghost), "the preview must be drawable valid geometry"
    return ghost


_BOX_POINTS = list(itertools.product((0.0, 10.0), repeat=3))
_ANGLE = math.radians(10)


@pytest.mark.parametrize("command,normal,answers,cursor,expected,volume", [
    ("move", (0, 0, 1), [(0., 0., 0.)], (0., 0., 5.),
     [(x, y, 15. if z else 0.) for x, y, z in _BOX_POINTS], 1500.),
    ("rotate", (1, 0, 0), [(5., 5., 5.), (6., 5., 5.)],
     (5. + math.cos(_ANGLE), 5. + math.sin(_ANGLE), 5.),
     [(5. + (x - 5.) * math.cos(_ANGLE) - (y - 5.) * math.sin(_ANGLE),
       5. + (x - 5.) * math.sin(_ANGLE) + (y - 5.) * math.cos(_ANGLE), z)
      if x else (x, y, z) for x, y, z in _BOX_POINTS],
     500. * (1. + math.cos(_ANGLE))),
    # Face scaling uses the face's own center even when the command base
    # point differs; a whole-solid scale would be a misleading ghost.
    ("scale", (0, 0, 1), [(0., 0., 0.), (10., 0., 0.)], (5., 0., 0.),
     [(2.5 + x / 2., 2.5 + y / 2., z) if z else (x, y, z)
      for x, y, z in _BOX_POINTS], 1000. * 1.75 / 3.),
], ids=["push-face", "tilt-face", "taper-face"])
def test_face_cursor_preview_contains_the_deformed_parent_and_matches_commit(
        env, command, normal, answers, cursor, expected, volume):
    scene, sel, _hist, _ctx, proc = env
    box = _box(scene)
    original = box.shape
    sel.toggle_subobject(box.id, "face", _face(box.shape, normal))
    _start(proc, command, *answers)

    ghost = _preview(proc, cursor)

    assert len(g.faces_of(ghost)) == 6, "preview the whole parent, not its face"
    _assert_points(ghost, expected)
    assert g.volume(ghost) == pytest.approx(volume, abs=1e-5)
    assert scene.get(box.id).shape.IsSame(original)
    _assert_points(original, _BOX_POINTS)
    proc.provide(cursor)
    assert not proc.busy
    _assert_same_geometry(ghost, scene.get(box.id).shape)


def test_solid_edge_cursor_preview_includes_stationary_faces_and_matches_commit(env):
    scene, sel, _hist, _ctx, proc = env
    box = _box(scene)
    sel.toggle_subobject(box.id, "edge", _edge(box.shape, (5, 0, 10)))
    _start(proc, "move", (0., 0., 0.))

    ghost = _preview(proc, (0., 0., 5.))

    assert len(g.faces_of(ghost)) == 6
    _assert_points(ghost, [(x, y, 15. if z and y == 0 else z)
                           for x, y, z in _BOX_POINTS])
    assert g.volume(ghost) == pytest.approx(1250., abs=1e-5)
    proc.provide((0., 0., 5.))
    _assert_same_geometry(ghost, scene.get(box.id).shape)


@pytest.mark.parametrize("command,answers,cursor,moved_ends", [
    ("move", [(0., 0., 0.)], (0., -2., 0.), [(0., -2., 0.), (10., -2., 0.)]),
    ("rotate", [(5., 0., 0.), (6., 0., 0.)], (5., 1., 0.),
     [(5., -5., 0.), (5., 5., 0.)]),
    ("rotate3d", [(5., 0., 0.), (5., 10., 0.), (6., 0., 0.)], (5., 0., -1.),
     [(5., 0., 5.), (5., 0., -5.)]),
    ("scale", [(5., 0., 0.), (15., 0., 0.)], (10., 0., 0.),
     [(2.5, 0., 0.), (7.5, 0., 0.)]),
])
def test_curve_segment_cursor_preview_keeps_neighbors_attached_and_matches_commit(
        env, command, answers, cursor, moved_ends):
    scene, sel, _hist, _ctx, proc = env
    rect = _rect(scene)
    sel.toggle_subobject(rect.id, "edge", _edge(rect.shape, (5, 0, 0)))
    _start(proc, command, *answers)

    ghost = _preview(proc, cursor)

    assert len(g.edges_of(ghost)) == 4, "preview every attached parent segment"
    _assert_points(ghost, moved_ends + [(0., 6., 0.), (10., 6., 0.)])
    proc.provide(cursor)
    committed = scene.get(rect.id).shape
    assert g.is_closed_curve(committed)
    _assert_same_geometry(ghost, committed)


@pytest.mark.parametrize("held", ["rim-edges", "face-and-rim", "two-faces"])
def test_parts_of_one_parent_move_once_in_the_preview(env, held):
    scene, sel, _hist, _ctx, proc = env
    box = _box(scene)
    if held != "two-faces":
        for i, edge in enumerate(g.edges_of(box.shape)):
            if abs(g.centroid(edge)[2] - 10.) < 1e-6:
                sel.toggle_subobject(box.id, "edge", i)
    if held != "rim-edges":
        sel.toggle_subobject(box.id, "face", _face(box.shape, (0, 0, 1)))
    if held == "two-faces":
        sel.toggle_subobject(box.id, "face", _face(box.shape, (0, -1, 0)))
    _start(proc, "move", (0., 0., 0.))

    ghost = _preview(proc, (0., 0., 5.))

    expected = [(x, y, 15. if z else
                 (5. if held == "two-faces" and y == 0 else 0.))
                for x, y, z in _BOX_POINTS]
    assert len(g.faces_of(ghost)) == 6, "one parent ghost for the held set"
    _assert_points(ghost, expected)
    assert g.volume(ghost) == pytest.approx(
        1250. if held == "two-faces" else 1500., abs=1e-5)
    proc.provide((0., 0., 5.))
    _assert_same_geometry(ghost, scene.get(box.id).shape)


@pytest.mark.parametrize("command,answers,cursor,expected,volume", [
    ("move", [(0., 0., 0.)], (2., 3., 5.),
     [(x + 2., y + 3., z + 5.) for x, y, z in _BOX_POINTS], 1000.),
    ("rotate", [(0., 0., 0.), (1., 0., 0.)], (0., 1., 0.),
     [(-y, x, z) for x, y, z in _BOX_POINTS], 1000.),
    ("rotate3d", [(0., 0., 0.), (10., 0., 0.), (0., 1., 0.)], (0., 0., 1.),
     [(x, -z, y) for x, y, z in _BOX_POINTS], 1000.),
    ("scale", [(0., 0., 0.), (10., 0., 0.)], (5., 0., 0.),
     [(x / 2., y / 2., z / 2.) for x, y, z in _BOX_POINTS], 125.),
])
def test_every_face_held_previews_the_supported_whole_parent_transform(
        env, command, answers, cursor, expected, volume):
    scene, sel, _hist, _ctx, proc = env
    box = _box(scene)
    for index in range(len(g.faces_of(box.shape))):
        sel.toggle_subobject(box.id, "face", index)
    _start(proc, command, *answers)

    ghost = _preview(proc, cursor)

    assert len(g.faces_of(ghost)) == 6
    _assert_points(ghost, expected)
    assert g.volume(ghost) == pytest.approx(volume, abs=1e-5)
    proc.provide(cursor)
    _assert_same_geometry(ghost, scene.get(box.id).shape)


def test_repeated_cursor_previews_are_pure_and_cancel_leaves_the_original(env):
    scene, sel, hist, ctx, proc = env
    box = _box(scene)
    original = box.shape
    sel.toggle_subobject(box.id, "face", _face(original, (0, 0, 1)))
    before_selection = list(sel.subobjects)
    before_revision = scene.revision
    checkpoints, discards, selection_changes, said = [], [], [], []
    hist.on_checkpoint = checkpoints.append
    hist.on_discard = lambda: discards.append(True)
    sel.add_listener(lambda: selection_changes.append(True))
    ctx.add_echo_listener(said.append)
    _start(proc, "move", (0., 0., 0.))
    before_messages = list(said)

    first = _preview(proc, (0., 0., 2.))
    second = _preview(proc, (0., 0., 5.))
    again = _preview(proc, (0., 0., 2.))

    assert g.volume(first) == pytest.approx(1200., abs=1e-5)
    assert g.volume(second) == pytest.approx(1500., abs=1e-5)
    _assert_same_geometry(first, again)
    assert scene.get(box.id).shape.IsSame(original)
    _assert_points(scene.get(box.id).shape, _BOX_POINTS)
    assert scene.revision == before_revision
    assert sel.subobjects == before_selection
    assert selection_changes == []
    assert checkpoints == ["move"] and discards == []
    assert said == before_messages, "mouse previews must not announce completed edits"
    assert hist.can_undo and not hist.can_redo

    proc.cancel()

    assert not proc.busy
    assert not hist.can_undo and not hist.can_redo
    assert discards == [True]
    assert scene.revision == before_revision
    assert scene.get(box.id).shape.IsSame(original)
    assert sel.subobjects == before_selection


@pytest.mark.parametrize("command,held,answers,cursor", [
    ("rotate", "edge", [(5., 5., 5.), (6., 5., 5.)], (5., 6., 5.)),
    ("scale", "edge", [(0., 0., 0.), (10., 0., 0.)], (5., 0., 0.)),
    ("rotate", "top", [(5., 5., 10.), (6., 5., 10.)], (5., 6., 10.)),
    # Single-face Rotate3D currently refuses at commit; its preview must
    # honor that supported-operation boundary rather than promise a tilt.
    ("rotate3d", "top", [(5., 5., 10.), (15., 5., 10.), (5., 6., 10.)],
     (5., 5., 11.)),
    ("rotate", "two-faces", [(5., 5., 5.), (6., 5., 5.)], (5., 6., 5.)),
    ("scale", "two-faces", [(0., 0., 0.), (10., 0., 0.)], (5., 0., 0.)),
])
def test_refused_subobject_operation_has_no_misleading_transformed_ghost(
        env, command, held, answers, cursor):
    scene, sel, _hist, ctx, proc = env
    box = _box(scene)
    if held == "edge":
        sel.toggle_subobject(box.id, "edge", _edge(box.shape, (5, 0, 10)))
    else:
        sel.toggle_subobject(box.id, "face", _face(box.shape, (0, 0, 1)))
        if held == "two-faces":
            sel.toggle_subobject(box.id, "face", _face(box.shape, (0, -1, 0)))
    original_selection = list(sel.subobjects)
    said = []
    ctx.add_echo_listener(said.append)
    _start(proc, command, *answers)
    messages_before_preview = list(said)

    assert proc.preview_for(cursor) is None
    assert proc.busy, "a refused candidate must not cancel the command"
    assert sel.subobjects == original_selection
    assert said == messages_before_preview
    _assert_points(scene.get(box.id).shape, _BOX_POINTS)

    proc.provide(cursor)
    assert not proc.busy
    _assert_points(scene.get(box.id).shape, _BOX_POINTS)
    assert sel.subobjects == original_selection
    assert len(said) > len(messages_before_preview), "completion explains the refusal"


def test_invalid_candidate_is_quiet_and_a_later_valid_cursor_still_previews(env):
    scene, sel, _hist, _ctx, proc = env
    box = _box(scene)
    sel.toggle_subobject(box.id, "face", _face(box.shape, (0, 0, 1)))
    sel.toggle_subobject(box.id, "face", _face(box.shape, (0, -1, 0)))
    _start(proc, "move", (0., 0., 0.))
    original_selection = list(sel.subobjects)

    # These two faces shifted sideways would bend a planar neighbor.
    assert proc.preview_for((3., 0., 0.)) is None
    assert proc.busy and sel.subobjects == original_selection
    _assert_points(scene.get(box.id).shape, _BOX_POINTS)

    valid = _preview(proc, (0., 0., 5.))
    assert g.volume(valid) == pytest.approx(1250., abs=1e-5)
    proc.provide((0., 0., 5.))
    _assert_same_geometry(valid, scene.get(box.id).shape)


@pytest.mark.parametrize("held", ["whole-object", "control-point"])
def test_existing_whole_object_and_control_point_previews_still_match_commit(env, held):
    scene, sel, _hist, _ctx, proc = env
    if held == "whole-object":
        obj = _box(scene)
        sel.set([obj.id])
        expected = [(x, y, z + 5.) for x, y, z in _BOX_POINTS]
    else:
        obj = scene.add(g.make_line((0, 0, 0), (10, 0, 0)))
        sel.toggle_subobject(obj.id, "cv", 0)
        expected = [(0., 0., 5.), (10., 0., 0.)]
    _start(proc, "move", (0., 0., 0.))

    ghost = _preview(proc, (0., 0., 5.))

    _assert_points(ghost, expected)
    proc.provide((0., 0., 5.))
    _assert_same_geometry(ghost, scene.get(obj.id).shape)


@pytest.fixture
def window(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({}))
    monkeypatch.setenv("SERP3D_CONFIG", str(cfg))
    monkeypatch.setenv("SERP3D_AUTOSAVE_DIR", str(tmp_path / "autosave"))
    from serpentine3d.app import MainWindow
    w = MainWindow()
    yield w
    w.processor.cancel()
    w._saved_revision = w.scene.revision
    w.close()


def test_cursor_movement_delivers_the_full_parent_preview_to_viewports(window):
    box = _box(window.scene)
    window.selection.toggle_subobject(box.id, "face", _face(box.shape, (0, 0, 1)))
    _start(window.processor, "move", (0., 0., 0.))

    for height in (3., 5.):
        window._ghost_timer = None  # each event is beyond the existing 30 Hz cap
        window.viewport.mouseWorldMoved.emit((0., 0., height))
        for viewport in window.all_viewports():
            mesh = viewport._ghost
            assert mesh is not None, "moving the cursor must show a rendered parent ghost"
            assert mesh.has_faces and len(mesh.triangles) >= 12
            assert np.min(mesh.vertices[:, 2]) == pytest.approx(0., abs=1e-5)
            assert np.max(mesh.vertices[:, 2]) == pytest.approx(10. + height, abs=1e-5)
        _assert_points(window.scene.get(box.id).shape, _BOX_POINTS)

    window.processor.cancel()
    assert all(vp._ghost is None for vp in window.all_viewports())
    _assert_points(window.scene.get(box.id).shape, _BOX_POINTS)
