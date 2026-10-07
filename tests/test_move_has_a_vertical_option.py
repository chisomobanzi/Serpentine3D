"""Move's Vertical option holds the base CPlane normal, including its preview (#49)."""

from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest

from serpentine3d.app import MainWindow
from serpentine3d.commands.base import PointReq, SelectReq
from serpentine3d.core import cplane as cp
from serpentine3d.core import geometry as g
from serpentine3d.core.tessellate import tessellate


BASE = (4.0, 7.0, 3.0)
TARGET = (19.0, -6.0, 11.0)
CURVE = [(0, 0, 1), (4, 2, 3), (9, 6, 4), (14, 0, 2)]
BOTTOM = [(0, 0, 0), (12, 0, 0), (12, 8, 0), (0, 8, 0)]
TOP = [(x, y, 10) for x, y, _z in BOTTOM]


def _key(point):
    return tuple(round(float(c), 6) for c in point)


def _corners(shape):
    return {_key(point) for edge in g.edges_of(shape)
            for point in g.curve_endpoints(edge)}


def _geometry(shape):
    """A ghost compound and the committed object may wrap the same geometry."""
    return (sorted(tuple(sorted(_key(p) for p in g.sample_curve(edge, 5)))
                   for edge in g.edges_of(shape)),
            sorted((_key(g.centroid(face)), round(g.surface_area(face), 6))
                   for face in g.faces_of(shape)))


def _state(scene, selection, history):
    return (scene.revision,
            tuple((obj.id, g.shape_to_bytes(obj.shape)) for obj in scene.all()),
            tuple(selection.ids), tuple(selection.subobjects),
            len(history._undo), len(history._redo))


def _plane(ctx, plane):
    viewport = SimpleNamespace(space="model", cplane=plane)
    viewport.active_cplane = lambda: viewport.cplane
    ctx.viewport = viewport
    return viewport


def _box(scene):
    return scene.add(g.make_box((0, 0, 0), 12, 8, 10), name="Move this")


def _start(scene, selection, proc, base=BASE):
    obj = _box(scene)
    selection.set([obj.id])
    assert proc.run("move")
    assert isinstance(proc.request, PointReq)
    if base is not None:
        proc.provide(base)
        assert isinstance(proc.request, PointReq)
    return obj


def _vertical(proc, value="Yes"):
    """Use the existing public option input, without assuming a new helper."""
    request = proc.request
    proc.provide_text(f"Vertical={value}")
    assert proc.busy and proc.request is request


def _assert_translated(shape, original, offset):
    for actual, before in zip(g.bbox(shape), g.bbox(original)):
        expected = tuple(float(c) for c in np.asarray(before) + offset)
        assert actual == pytest.approx(expected, abs=1e-6)


@pytest.mark.parametrize("stage", ["selection", "base", "target"])
@pytest.mark.parametrize("entry", ["v", "Vertical"])
def test_vertical_is_an_option_at_each_move_prompt_without_answering_it(env, stage, entry):
    scene, selection, history, _ctx, proc = env
    obj = _box(scene)
    if stage != "selection":
        selection.set([obj.id])
    assert proc.run("move")
    if stage == "target":
        proc.provide(BASE)
    request = proc.request
    assert isinstance(request, SelectReq if stage == "selection" else PointReq)
    assert dict(proc.option_chips()).get("Vertical") == "No", (
        "Move must offer a Vertical=No chip at selection and both point prompts")
    before = _state(scene, selection, history)
    points = tuple(proc.picked_points)

    proc.provide_text(entry)

    assert proc.busy and proc.request is request, "V changes the option, not the point"
    assert proc.option("Vertical", "No") == "Yes"
    assert _state(scene, selection, history) == before
    assert tuple(proc.picked_points) == points
    proc.provide_text(entry)
    assert proc.option("Vertical", "Yes") == "No", "The option can be turned off"
    assert proc.request is request


@pytest.mark.parametrize("plane", [
    cp.CPlane(),
    cp.PRESETS["front"](),
    cp.CPlane(origin=(61, -22, 17), normal=(2, -3, 6), xdir=(3, 2, 0)),
], ids=["top", "front", "translated-tilted"])
@pytest.mark.parametrize("input_mode", ["mouse-point", "typed-coordinates"])
@pytest.mark.parametrize("enable_at", ["base", "target"])
def test_vertical_projects_targets_onto_the_base_planes_normal(env, plane, input_mode, enable_at):
    scene, selection, history, ctx, proc = env
    _plane(ctx, plane)
    obj = _start(scene, selection, proc, base=None)
    original = obj.shape
    if enable_at == "base":
        _vertical(proc)
    proc.provide(BASE)
    if enable_at == "target":
        _vertical(proc)
    offset = np.dot(np.subtract(TARGET, BASE), plane.normal) * plane.normal
    request = proc.request
    before = _state(scene, selection, history)
    ghost = (proc.preview_for(TARGET) if input_mode == "mouse-point"
             else proc.preview_shape("19,-6,11"))

    assert ghost is not None, "A Vertical move shows its result before committing"
    _assert_translated(ghost, original, offset)
    assert _state(scene, selection, history) == before
    assert proc.busy and proc.request is request
    if input_mode == "mouse-point":
        proc.provide(TARGET)
    else:
        proc.provide_text("19,-6,11")
    assert not proc.busy
    _assert_translated(scene.get(obj.id).shape, original, offset)
    assert _geometry(scene.get(obj.id).shape) == _geometry(ghost)


@pytest.mark.parametrize("normal", [(0, 0, 1), (2, -3, 6)], ids=["top", "tilted"])
@pytest.mark.parametrize("text,distance", [("5", 5), ("-2.5", -2.5), ("0", 0), ("3cm", 30)])
def test_vertical_accepts_signed_zero_and_unit_distances_without_a_cursor(env, normal, text, distance):
    scene, selection, history, ctx, proc = env
    plane = cp.CPlane(origin=(61, -22, 17), normal=normal)
    _plane(ctx, plane)
    obj = _start(scene, selection, proc)
    original = obj.shape
    _vertical(proc)
    before = _state(scene, selection, history)

    ghost = proc.preview_shape(text)

    assert ghost is not None, "A typed height works even without a mouse direction"
    _assert_translated(ghost, original, distance * plane.normal)
    assert _state(scene, selection, history) == before
    proc.provide_text(text)
    assert not proc.busy, "The height must finish Move instead of asking for coordinates"
    _assert_translated(scene.get(obj.id).shape, original, distance * plane.normal)
    assert _geometry(scene.get(obj.id).shape) == _geometry(ghost)


def test_vertical_turns_off_and_another_move_starts_unconstrained(env):
    scene, selection, _history, _ctx, proc = env
    obj = _start(scene, selection, proc)
    original = obj.shape
    _vertical(proc)
    _assert_translated(proc.preview_for(TARGET), original, np.asarray((0, 0, 8)))

    _vertical(proc, "No")

    ordinary = np.subtract(TARGET, BASE)
    ghost = proc.preview_for(TARGET)
    _assert_translated(ghost, original, ordinary)
    proc.provide(TARGET)
    _assert_translated(scene.get(obj.id).shape, original, ordinary)
    selection.set([obj.id])
    assert proc.run("move")
    proc.provide((0, 0, 0))
    assert dict(proc.option_chips())["Vertical"] == "No"
    second = scene.get(obj.id).shape
    proc.provide((1, 2, 3))
    _assert_translated(scene.get(obj.id).shape, second, np.asarray((1, 2, 3)))


def test_vertical_chosen_during_selection_carries_into_the_target(env):
    scene, selection, _history, _ctx, proc = env
    obj = _box(scene)
    original = obj.shape
    assert proc.run("move")
    assert isinstance(proc.request, SelectReq)
    proc.provide_text("v")
    proc.click_object(obj.id)
    proc.finish_selection()
    assert isinstance(proc.request, PointReq)
    proc.provide(BASE)

    proc.provide(TARGET)

    assert not proc.busy
    _assert_translated(scene.get(obj.id).shape, original, np.asarray((0, 0, 8)))


def test_vertical_off_keeps_zero_as_the_world_origin(env):
    scene, selection, _history, _ctx, proc = env
    obj = _start(scene, selection, proc)
    original = obj.shape

    proc.provide_text("0")

    assert not proc.busy
    _assert_translated(scene.get(obj.id).shape, original, -np.asarray(BASE))


def test_vertical_keeps_the_base_normal_when_the_active_pane_changes(env):
    scene, selection, _history, ctx, proc = env
    plane = cp.CPlane(origin=(8, 9, 10), normal=(2, -3, 6))
    viewport = _plane(ctx, plane)
    obj = _start(scene, selection, proc)
    original = obj.shape
    _vertical(proc)
    offset = np.dot(np.subtract(TARGET, BASE), plane.normal) * plane.normal

    viewport.cplane = cp.PRESETS["right"]()

    _assert_translated(proc.preview_for(TARGET), original, offset)
    proc.provide(TARGET)
    _assert_translated(scene.get(obj.id).shape, original, offset)


def test_multiple_selected_objects_move_vertically_together_and_undo_as_one(env):
    scene, selection, history, _ctx, proc = env
    box = _box(scene)
    curve = scene.add(g.make_polyline(CURVE), name="Move this too")
    untouched = scene.add(g.make_box((50, 40, 30), 2, 3, 4), name="Leave this")
    originals = {obj.id: obj.shape for obj in scene.all()}
    selection.set([box.id, curve.id])
    assert proc.run("move")
    proc.provide(BASE)
    _vertical(proc)
    before = _state(scene, selection, history)
    request = proc.request

    ghost = proc.preview_for(TARGET)

    expected = g.make_compound([g.translate(originals[obj.id], (0, 0, 8))
                                for obj in (box, curve)])
    assert _geometry(ghost) == _geometry(expected), "The ghost contains only selected objects"
    assert _state(scene, selection, history) == before
    assert proc.request is request
    proc.provide(TARGET)
    assert not proc.busy
    for obj in (box, curve):
        _assert_translated(scene.get(obj.id).shape, originals[obj.id], np.asarray((0, 0, 8)))
    assert g.shape_to_bytes(scene.get(untouched.id).shape) == g.shape_to_bytes(originals[untouched.id])
    committed = {obj.id: _geometry(obj.shape) for obj in scene.all()}
    assert history.undo() is not None
    assert {obj.id: _geometry(obj.shape) for obj in scene.all()} == {
        obj_id: _geometry(shape) for obj_id, shape in originals.items()}
    assert history.redo() is not None
    assert {obj.id: _geometry(obj.shape) for obj in scene.all()} == committed


def _hold(scene, selection, kind):
    if kind == "control-point":
        obj = scene.add(g.make_line((0, 0, 0), (12, 0, 0)))
        selection.toggle_subobject(obj.id, "cv", 0)
        expected = {(0, 0, 5), (12, 0, 0)}
    elif kind == "segment":
        obj = scene.add(g.make_polyline(CURVE))
        index = next(i for i, edge in enumerate(g.edges_of(obj.shape))
                     if {_key(p) for p in g.curve_endpoints(edge)} == set(CURVE[1:3]))
        selection.toggle_subobject(obj.id, "edge", index)
        expected = {_key((x, y, z + (5 if i in (1, 2) else 0)))
                    for i, (x, y, z) in enumerate(CURVE)}
    else:
        obj = _box(scene)
        if kind == "solid-face":
            index = next(i for i, face in enumerate(g.faces_of(obj.shape))
                         if g.face_normal(face)[2] > 0.9)
            selection.toggle_subobject(obj.id, "face", index)
            lifted = range(4)
        else:
            index = next(i for i, edge in enumerate(g.edges_of(obj.shape))
                         if {_key(p) for p in g.curve_endpoints(edge)} == set(TOP[:2]))
            selection.toggle_subobject(obj.id, "edge", index)
            lifted = (0, 1)
        expected = set(BOTTOM) | {(x, y, z + (5 if i in lifted else 0))
                                  for i, (x, y, z) in enumerate(TOP)}
    assert g.is_valid(obj.shape), "Held-part fixtures start with valid geometry"
    return obj, expected


@pytest.mark.parametrize("kind", ["control-point", "segment", "solid-face", "solid-edge"])
def test_vertical_moves_only_held_parts_with_an_accurate_pure_preview_and_undo(env, kind):
    scene, selection, history, _ctx, proc = env
    obj, expected = _hold(scene, selection, kind)
    original = _geometry(obj.shape)
    untouched = scene.add(g.make_line((50, 40, 30), (60, 40, 30)))
    untouched_geometry = _geometry(untouched.shape)
    assert proc.run("move")
    assert isinstance(proc.request, PointReq), "Held parts skip whole-object selection"
    proc.provide((0, 0, 0))
    _vertical(proc)
    before = _state(scene, selection, history)
    request = proc.request

    ghost = proc.preview_for((20, -30, 5))

    assert ghost is not None, f"The held {kind} needs a visible Vertical preview"
    assert _corners(ghost) == expected, "Only held corners travel; adjoining geometry stays connected"
    assert g.is_valid(ghost)
    assert _state(scene, selection, history) == before
    assert proc.request is request
    proc.provide((20, -30, 5))
    assert not proc.busy
    result = scene.get(obj.id).shape
    assert _corners(result) == expected
    assert _geometry(result) == _geometry(ghost)
    assert g.is_valid(result)
    if kind.startswith("solid"):
        assert len(g.faces_of(result)) == 6 and len(g.edges_of(result)) == 12
        assert g.volume(result) == pytest.approx(1440 if kind == "solid-face" else 1200, abs=1e-6)
    assert _geometry(scene.get(untouched.id).shape) == untouched_geometry
    assert history.undo() is not None
    assert _geometry(scene.get(obj.id).shape) == original


@pytest.fixture
def window():
    window = MainWindow()
    window.set_view_layout("quad")
    for pane in window.all_viewports():
        pane.resize(800, 600)
        pane.grid_snap = False
        pane.ortho = False
        pane.snaps.enabled = False
    yield window
    window.processor.cancel()
    window.mark_saved()
    window.close()


def _type(window, text):
    window.command_line.input.clear()
    QTest.keyClicks(window.command_line.input, text)


def _start_window(window):
    top = next(vp for vp in window.all_viewports() if vp._view_name == "top")
    window._set_active_viewport(top)
    obj = _box(window.scene)
    window.selection.set([obj.id])
    window.command_line.run_command("move")
    window.processor.provide(BASE)
    return obj


def _assert_all_panes_show(window, expected):
    mesh = tessellate(expected)
    panes = list(window.all_viewports())
    assert len(panes) == 4
    for pane in panes:
        assert pane._ghost is not None, f"{pane._view_name} must show the pending move"
        triangles, segments = pane._ghost_geometry()
        np.testing.assert_allclose(segments, mesh.edge_segments.reshape(-1, 3), rtol=0, atol=1e-5)
        np.testing.assert_allclose(triangles, mesh.vertices[mesh.triangles.ravel()], rtol=0, atol=1e-5)


@pytest.mark.parametrize("finish", ["commit", "cancel"])
def test_v_enter_and_a_typed_height_preview_reach_all_panes_and_clear_at_finish(window, finish):
    obj = _start_window(window)
    original = obj.shape
    before = _state(window.scene, window.selection, window.history)
    request = window.processor.request
    _type(window, "v")
    QTest.keyClick(window.command_line.input, Qt.Key.Key_Return)
    assert window.processor.request is request and window.processor.busy

    _type(window, "3cm")

    expected = g.translate(original, (0, 0, 30))
    _assert_all_panes_show(window, expected)
    assert _state(window.scene, window.selection, window.history) == before
    if finish == "commit":
        QTest.keyClick(window.command_line.input, Qt.Key.Key_Return)
        assert _geometry(window.scene.get(obj.id).shape) == _geometry(expected)
    else:
        window.processor.cancel()
        assert _geometry(window.scene.get(obj.id).shape) == _geometry(original)
        assert not window.history.can_undo
    assert not window.processor.busy
    assert all(pane._ghost is None and pane.point_axis is None
               and not pane.point_mode for pane in window.all_viewports())


def test_the_vertical_chip_updates_an_existing_typed_preview_in_every_pane(window):
    obj = _start_window(window)
    original = obj.shape
    _type(window, "19,-6,11")
    _assert_all_panes_show(window, g.translate(original, np.subtract(TARGET, BASE)))
    before = _state(window.scene, window.selection, window.history)
    request = window.processor.request

    window.command_line.optionClicked.emit("Vertical")

    _assert_all_panes_show(window, g.translate(original, (0, 0, 8)))
    assert window.processor.request is request
    assert _state(window.scene, window.selection, window.history) == before
    window.command_line.optionClicked.emit("Vertical")
    _assert_all_panes_show(window, g.translate(original, np.subtract(TARGET, BASE)))


@pytest.mark.parametrize("view", ["perspective", "front"])
def test_the_mouse_can_move_along_the_vertical_from_another_pane(window, view):
    obj = _start_window(window)
    original = obj.shape
    _type(window, "v")
    QTest.keyClick(window.command_line.input, Qt.Key.Key_Return)
    pane = next(vp for vp in window.all_viewports() if vp._view_name == view)
    upper = pane.world_point_at(400, 200)
    lower = pane.world_point_at(400, 400)
    assert upper is not None and lower is not None
    assert upper[:2] == pytest.approx(BASE[:2], abs=1e-6), (
        "Vertical must solve the cursor against the normal through the base")
    assert lower[:2] == pytest.approx(BASE[:2], abs=1e-6)
    assert abs(upper[2] - lower[2]) > 1, "Moving the cursor must change elevation"
    before = _state(window.scene, window.selection, window.history)
    event = QMouseEvent(QEvent.Type.MouseMove, QPointF(400, 200),
                        Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                        Qt.KeyboardModifier.NoModifier)
    pane.mouseMoveEvent(event)
    expected = g.translate(original, (0, 0, upper[2] - BASE[2]))
    _assert_all_panes_show(window, expected)
    assert _state(window.scene, window.selection, window.history) == before

    QTest.mouseClick(pane, Qt.MouseButton.LeftButton, pos=QPoint(400, 200))

    assert not window.processor.busy
    assert _geometry(window.scene.get(obj.id).shape) == _geometry(expected)
    assert all(vp._ghost is None and vp.point_axis is None for vp in window.all_viewports())


def test_move_on_paper_keeps_its_two_dimensional_input(window):
    from serpentine3d.core.layout import DetailView, Layout
    model = _box(window.scene)
    original = _geometry(model.shape)
    layout = Layout(name="Sheet")
    detail = DetailView(x=10, y=20, w=100, h=80)
    layout.details.append(detail)
    window.scene.layouts.append(layout)
    pane = window.viewport
    pane.space = layout.id
    window._set_active_viewport(pane)
    lv = pane.layout_view
    lv.fit()
    lv._fitted_for = layout.id
    lv.press(*lv.paper_to_screen(detail.x + detail.w / 2,
                                 detail.y + detail.h / 2))
    lv.release_drag()
    assert lv.selected == [("detail", detail)]

    assert window.processor.run("move")
    assert "Vertical" not in dict(window.processor.option_chips())
    window.processor.provide_text("0,0,0")
    window.processor.provide_text("15,-4,90")

    assert not window.processor.busy
    assert (detail.x, detail.y, detail.w, detail.h) == pytest.approx((25, 16, 100, 80))
    assert _geometry(window.scene.get(model.id).shape) == original
