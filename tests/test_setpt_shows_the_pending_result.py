"""SetPt shows the result of its pending target without editing the scene (#62)."""

import math

import numpy as np
import pytest
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_SurfaceType
from PySide6.QtTest import QTest

from serpentine3d.app import MainWindow
from serpentine3d.commands.base import PointReq, SelectReq
from serpentine3d.core import geometry as g
from serpentine3d.core.tessellate import tessellate


CORNERS = [(0, 0, 1), (10, 5, 3), (20, 8, 7), (30, -3, 11)]
BOTTOM = [(0, 0, 0), (10, 0, 0), (10, 6, 0), (0, 6, 0)]
TOP = [(x, y, 10) for x, y, _z in BOTTOM]
SLOPED = [(0, 0, 0), (10, 0, 5), (10, 6, 8), (0, 6, 3)]
TARGET = (73.0, -29.0, 15.0)


def _key(point):
    return tuple(round(float(coordinate), 6) for coordinate in point)


def _corners(shape):
    return {_key(point) for edge in g.edges_of(shape)
            for point in g.curve_endpoints(edge)}


def _edge_between(shape, a, b):
    wanted = {_key(a), _key(b)}
    return next(index for index, edge in enumerate(g.edges_of(shape))
                if {_key(point) for point in g.curve_endpoints(edge)} == wanted)


def _held(scene, selection, kind):
    if kind == "segment":
        shape = g.make_polyline(CORNERS)
    elif kind == "open-face":
        shape = g.planar_face(g.make_polyline(SLOPED, closed=True))
    elif kind == "circular-cap":
        shape = g.make_cylinder((0, 0, 0), 4, 10)
    else:
        shape = g.make_box((0, 0, 0), 10, 6, 10)
    assert g.is_valid(shape), "The preview fixture starts with valid geometry"
    obj = scene.add(shape, name=kind)
    if kind in ("segment", "solid-edge"):
        ends = CORNERS[1:3] if kind == "segment" else TOP[:2]
        selection.toggle_subobject(obj.id, "edge", _edge_between(shape, *ends))
    else:
        face = (0 if kind == "open-face" else
                next(index for index, face in enumerate(g.faces_of(shape))
                     if abs(g.bbox(face)[0][2] - 10) < 1e-6
                     and abs(g.bbox(face)[1][2] - 10) < 1e-6))
        selection.toggle_subobject(obj.id, "face", face)
    return obj


def _start(proc):
    assert proc.run("setpt")
    assert isinstance(proc.request, PointReq)
    assert set(proc.request.choices) >= {"X", "Y", "Z"}


def _state(scene, selection, history):
    return (scene.revision,
            tuple((obj.id, g.shape_to_bytes(obj.shape)) for obj in scene.all()),
            tuple(selection.ids), tuple(selection.subobjects),
            len(history._undo), len(history._redo))


def _geometry(shape):
    """Compare the complete result, allowing a ghost to wrap it in a compound."""
    edges = sorted(tuple(sorted(_key(point) for point in g.sample_curve(edge, 5)))
                   for edge in g.edges_of(shape))
    faces = sorted((_key(g.centroid(face)), round(g.surface_area(face), 6))
                   for face in g.faces_of(shape))
    return edges, faces


def _project(points, indices, target, axes):
    return [tuple(target[axis] if index in indices and enabled else point[axis]
                  for axis, enabled in enumerate(axes))
            for index, point in enumerate(points)]


def _assert_result(ghost, kind, target=TARGET):
    assert ghost is not None, f"SetPt must preview the pending {kind} result"
    assert g.is_valid(ghost)
    if kind == "segment":
        assert _corners(ghost) == set(_project(CORNERS, (1, 2), target,
                                              (False, False, True)))
        assert len(g.edges_of(ghost)) == 3
    elif kind in ("solid-face", "solid-edge"):
        held = range(4) if kind == "solid-face" else (0, 1)
        expected = BOTTOM + _project(TOP, held, target, (False, False, True))
        assert _corners(ghost) == set(expected), "Unheld corners stay in the ghost"
        assert len(g.faces_of(ghost)) == 6 and len(g.edges_of(ghost)) == 12
        volume = 60 * (target[2] if kind == "solid-face" else (10 + target[2]) / 2)
        assert g.volume(ghost) == pytest.approx(volume, abs=1e-6)
    elif kind == "open-face":
        assert _corners(ghost) == {(x, y, target[2]) for x, y, _z in SLOPED}
        assert len(g.faces_of(ghost)) == 1
        assert g.surface_area(ghost) == pytest.approx(60, abs=1e-6)
    else:
        low, high = g.bbox(ghost)
        assert low == pytest.approx((-4, -4, 0), abs=1e-6)
        assert high == pytest.approx((4, 4, target[2]), abs=1e-6)
        assert g.volume(ghost) == pytest.approx(math.pi * 16 * target[2], abs=1e-6)
        assert len(g.faces_of(ghost)) == 3
        assert any(BRepAdaptor_Surface(face).GetType()
                   == GeomAbs_SurfaceType.GeomAbs_Cylinder
                   for face in g.faces_of(ghost)), "The cap preview retains its curved wall"


@pytest.mark.parametrize("kind", ["segment", "solid-face", "solid-edge",
                                  "open-face", "circular-cap"])
@pytest.mark.parametrize("input_mode", ["cursor", "typed"])
def test_the_pending_target_previews_only_the_held_geometry(env, kind, input_mode):
    scene, selection, history, _ctx, proc = env
    obj = _held(scene, selection, kind)
    scene.add(g.make_line((80, 1, 4), (90, 2, 8)), name="Unselected curve")
    _start(proc)
    request = proc.request
    before = _state(scene, selection, history)

    ghost = (proc.preview_for(TARGET) if input_mode == "cursor"
             else proc.preview_shape("73,-29,15"))

    _assert_result(ghost, kind)
    assert _state(scene, selection, history) == before
    assert proc.busy and proc.request is request, "A preview does not accept its target"
    proc.provide(TARGET)
    assert not proc.busy
    assert _geometry(scene.get(obj.id).shape) == _geometry(ghost), (
        "Accepting the target must produce the geometry shown by its ghost")
    assert proc.preview_for(TARGET) is None


def test_new_targets_and_axis_choices_update_the_segment_preview(env):
    scene, selection, history, _ctx, proc = env
    _held(scene, selection, "segment")
    _start(proc)
    request = proc.request
    before = _state(scene, selection, history)

    _assert_result(proc.preview_for(TARGET), "segment")
    _assert_result(proc.preview_shape("73,-29,23"), "segment", (73, -29, 23))
    for axis in (0, 1):
        for index, name in enumerate("XYZ"):
            assert proc.set_option(name, "Yes" if index == axis else "No")
        ghost = proc.preview_for(TARGET)
        assert ghost is not None, f"The {'XYZ'[axis]} choice must update the ghost"
        axes = tuple(index == axis for index in range(3))
        assert _corners(ghost) == set(_project(CORNERS, (1, 2), TARGET, axes))
        assert _state(scene, selection, history) == before
        assert proc.busy and proc.request is request


def test_whole_object_setpt_keeps_selection_then_previews_its_target(env):
    scene, selection, history, _ctx, proc = env
    obj = scene.add(g.make_polyline(CORNERS), name="Whole curve")
    assert proc.run("setpt") and isinstance(proc.request, SelectReq)
    proc.click_object(obj.id)
    proc.finish_selection()
    assert isinstance(proc.request, PointReq)
    before = _state(scene, selection, history)

    ghost = proc.preview_shape("73,-29,15")

    assert ghost is not None, "Whole-object SetPt must also preview its target"
    assert _corners(ghost) == {(x, y, 15) for x, y, _z in CORNERS}
    assert _state(scene, selection, history) == before
    proc.provide(TARGET)
    assert not proc.busy
    assert _geometry(scene.get(obj.id).shape) == _geometry(ghost)


@pytest.fixture
def window():
    window = MainWindow()
    window.set_view_layout("quad")
    yield window
    window.processor.cancel()
    window.mark_saved()
    window.close()


def _type_target(window, text):
    field = window.command_line.input
    field.clear()
    QTest.keyClicks(field, text)


def _assert_panes_show(window, kind):
    preview = window.processor.preview_shape(window.command_line.input.text())
    _assert_result(preview, kind)
    expected = tessellate(preview)
    panes = list(window.all_viewports())
    assert len(panes) == 4
    for pane in panes:
        assert pane._ghost is not None, f"{pane._view_name} must display the result"
        triangles, segments = pane._ghost_geometry()
        assert segments is not None and len(segments)
        np.testing.assert_allclose(segments, expected.edge_segments.reshape(-1, 3),
                                   rtol=0, atol=1e-5)
        if kind == "segment":
            assert triangles is None
        else:
            assert triangles is not None and len(triangles)
            np.testing.assert_allclose(triangles,
                                       expected.vertices[expected.triangles.ravel()],
                                       rtol=0, atol=1e-5)
    return preview


@pytest.mark.parametrize("finish", ["commit", "cancel"])
def test_typing_the_target_reaches_every_pane_and_finishing_clears_it(window, finish):
    obj = _held(window.scene, window.selection, "segment")
    _start(window.processor)
    before = _state(window.scene, window.selection, window.history)

    _type_target(window, "73,-29,15")

    ghost = _assert_panes_show(window, "segment")
    assert _state(window.scene, window.selection, window.history) == before
    if finish == "commit":
        window.processor.provide_text(window.command_line.input.text())
        assert _geometry(window.scene.get(obj.id).shape) == _geometry(ghost)
    else:
        window.processor.cancel()
        assert g.shape_to_bytes(window.scene.get(obj.id).shape) == before[1][0][1]
        assert not window.history.can_undo
    assert not window.processor.busy
    assert all(pane._ghost is None for pane in window.all_viewports())


@pytest.mark.parametrize("kind", ["solid-face", "circular-cap"])
def test_collapsing_targets_and_all_axes_no_clear_the_previous_ghost(window, kind):
    _held(window.scene, window.selection, kind)
    _start(window.processor)
    request = window.processor.request
    before = _state(window.scene, window.selection, window.history)
    _type_target(window, "73,-29,15")
    _assert_panes_show(window, kind)

    _type_target(window, "73,-29,0")

    assert all(pane._ghost is None for pane in window.all_viewports()), (
        "A collapsing target must remove the earlier valid result ghost")
    assert _state(window.scene, window.selection, window.history) == before
    assert window.processor.busy and window.processor.request is request
    _type_target(window, "73,-29,15")
    _assert_panes_show(window, kind)
    window._on_option_chip("Z")
    assert all(window.processor.option(axis, "No") == "No" for axis in "XYZ")
    assert all(pane._ghost is None for pane in window.all_viewports()), (
        "Turning off the last axis must clear the previously valid result ghost")
    assert _state(window.scene, window.selection, window.history) == before
    assert window.processor.busy and window.processor.request is request
