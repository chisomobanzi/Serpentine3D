"""Copy's Vertical option holds its original base and CPlane normal (#49)."""

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


def _key(point):
    return tuple(round(float(c), 6) for c in point)


def _geometry(shape):
    """Compare the visible geometry of a ghost compound and its duplicates."""
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
    return scene.add(g.make_box((0, 0, 0), 12, 8, 10), name="Copy this")


def _start(scene, selection, proc, base=BASE):
    obj = _box(scene)
    selection.set([obj.id])
    assert proc.run("copy")
    assert isinstance(proc.request, PointReq)
    if base is not None:
        proc.provide(base)
        assert isinstance(proc.request, PointReq)
    return obj


def _vertical(proc, value="Yes"):
    request = proc.request
    proc.provide_text(f"Vertical={value}")
    assert proc.busy and proc.request is request, "Changing Vertical must not answer the prompt"


def _copies(scene, originals):
    return [obj for obj in scene.all() if obj.id not in originals]


def _assert_translated(shape, original, offset):
    for actual, before in zip(g.bbox(shape), g.bbox(original)):
        expected = tuple(float(c) for c in np.asarray(before) + offset)
        assert actual == pytest.approx(expected, abs=1e-6)


@pytest.mark.parametrize("stage", ["selection", "base", "target", "repeated-target"])
@pytest.mark.parametrize("entry", ["v", "Vertical", "Vertical=Yes"])
def test_vertical_is_offered_at_every_copy_prompt_without_answering_it(env, stage, entry):
    scene, selection, history, _ctx, proc = env
    obj = _box(scene)
    if stage != "selection":
        selection.set([obj.id])
    assert proc.run("copy")
    if stage in ("target", "repeated-target"):
        proc.provide(BASE)
    if stage == "repeated-target":
        proc.provide(TARGET)
        assert len(scene.all()) == 2
    request = proc.request
    assert isinstance(request, SelectReq if stage == "selection" else PointReq)
    assert dict(proc.option_chips()).get("Vertical") == "No", (
        "Copy must offer Vertical=No during selection, at its base, and at every target")
    before = _state(scene, selection, history)
    points = tuple(proc.picked_points)

    proc.provide_text(entry)

    assert proc.busy and proc.request is request
    assert proc.option("Vertical", "No") == "Yes"
    assert _state(scene, selection, history) == before
    assert tuple(proc.picked_points) == points
    proc.provide_text("Vertical=No" if "=" in entry else entry)
    assert proc.option("Vertical", "Yes") == "No"
    assert proc.request is request
    assert _state(scene, selection, history) == before
    assert tuple(proc.picked_points) == points


@pytest.mark.parametrize("plane", [
    cp.CPlane(),
    cp.PRESETS["front"](),
    cp.CPlane(origin=(61, -22, 17), normal=(2, -3, 6), xdir=(3, 2, 0)),
], ids=["top", "front", "translated-tilted"])
@pytest.mark.parametrize("input_mode", ["mouse-point", "typed-coordinates"])
@pytest.mark.parametrize("enable_at", ["base", "target"])
def test_vertical_projects_a_copy_and_its_pure_preview_onto_the_base_normal(
        env, plane, input_mode, enable_at):
    scene, selection, history, ctx, proc = env
    _plane(ctx, plane)
    untouched = scene.add(g.make_box((50, 40, 30), 2, 3, 4), name="Leave this")
    obj = _start(scene, selection, proc, base=None)
    originals = {o.id: g.shape_to_bytes(o.shape) for o in scene.all()}
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

    assert ghost is not None, "Vertical Copy must show the pending duplicate"
    _assert_translated(ghost, original, offset)
    assert _state(scene, selection, history) == before
    assert proc.busy and proc.request is request
    if input_mode == "mouse-point":
        proc.provide(TARGET)
    else:
        proc.provide_text("19,-6,11")
    made = _copies(scene, originals)
    assert len(made) == 1 and made[0].id != obj.id
    _assert_translated(made[0].shape, original, offset)
    assert _geometry(made[0].shape) == _geometry(ghost)
    assert proc.busy and isinstance(proc.request, PointReq), "Copy waits for another target"
    assert dict(proc.option_chips())["Vertical"] == "Yes"
    assert g.shape_to_bytes(scene.get(obj.id).shape) == originals[obj.id]
    assert g.shape_to_bytes(scene.get(untouched.id).shape) == originals[untouched.id]
    proc.provide_text("")
    assert not proc.busy


@pytest.mark.parametrize("normal", [(0, 0, 1), (2, -3, 6)], ids=["top", "tilted"])
@pytest.mark.parametrize("text,distance", [
    ("5", 5), ("-2.5", -2.5), ("0", 0), ("3cm", 30), ("-1in", -25.4),
])
def test_vertical_copies_accept_signed_zero_and_unit_distances_without_mouse_aim(
        env, normal, text, distance):
    scene, selection, history, ctx, proc = env
    plane = cp.CPlane(origin=(61, -22, 17), normal=normal)
    _plane(ctx, plane)
    obj = _start(scene, selection, proc)
    original = obj.shape
    _vertical(proc)
    before = _state(scene, selection, history)

    ghost = proc.preview_shape(text)

    assert ghost is not None, "A typed Vertical distance must work without a mouse direction"
    _assert_translated(ghost, original, distance * plane.normal)
    assert _state(scene, selection, history) == before
    proc.provide_text(text)
    made = _copies(scene, [obj.id])
    assert len(made) == 1, "The distance must create a copy instead of requesting coordinates"
    _assert_translated(made[0].shape, original, distance * plane.normal)
    assert _geometry(made[0].shape) == _geometry(ghost)
    assert _geometry(scene.get(obj.id).shape) == _geometry(original)
    assert proc.busy
    proc.provide_text("")
    assert not proc.busy


def test_vertical_chosen_during_selection_carries_into_copy_targets(env):
    scene, selection, _history, _ctx, proc = env
    obj = _box(scene)
    original = obj.shape
    assert proc.run("copy")
    assert isinstance(proc.request, SelectReq)
    proc.provide_text("v")
    proc.click_object(obj.id)
    proc.finish_selection()
    assert isinstance(proc.request, PointReq)
    proc.provide(BASE)

    proc.provide(TARGET)

    made = _copies(scene, [obj.id])
    assert len(made) == 1
    _assert_translated(made[0].shape, original, np.asarray((0, 0, 8)))
    proc.provide_text("")
    assert not proc.busy


def test_turning_vertical_off_restores_copy_and_a_new_copy_starts_off(env):
    scene, selection, _history, _ctx, proc = env
    obj = _start(scene, selection, proc)
    original = obj.shape
    _vertical(proc)
    _assert_translated(proc.preview_for(TARGET), original, np.asarray((0, 0, 8)))
    proc.provide(TARGET)
    vertical_copy = _copies(scene, [obj.id])[0]

    _vertical(proc, "No")

    ordinary = np.subtract(TARGET, BASE)
    _assert_translated(proc.preview_for(TARGET), original, ordinary)
    proc.provide(TARGET)
    made = _copies(scene, [obj.id, vertical_copy.id])
    assert len(made) == 1
    _assert_translated(made[0].shape, original, ordinary)
    proc.provide_text("")
    selection.set([obj.id])
    assert proc.run("copy")
    assert dict(proc.option_chips())["Vertical"] == "No"
    proc.provide((0, 0, 0))
    previous = {o.id for o in scene.all()}
    proc.provide((1, 2, 3))
    made = _copies(scene, previous)
    assert len(made) == 1
    _assert_translated(made[0].shape, original, np.asarray((1, 2, 3)))
    proc.provide_text("")


def test_ordinary_copy_keeps_zero_as_the_world_origin(env):
    scene, selection, history, _ctx, proc = env
    obj = _start(scene, selection, proc)
    original = obj.shape
    before = _state(scene, selection, history)
    ghost = proc.preview_shape("0")
    _assert_translated(ghost, original, -np.asarray(BASE))
    assert _state(scene, selection, history) == before

    proc.provide_text("0")

    made = _copies(scene, [obj.id])
    assert len(made) == 1
    _assert_translated(made[0].shape, original, -np.asarray(BASE))
    assert _geometry(scene.get(obj.id).shape) == _geometry(original)
    proc.provide_text("")
    assert not proc.busy


def test_vertical_copy_keeps_the_base_normal_across_viewport_changes_and_repeats(env):
    scene, selection, _history, ctx, proc = env
    plane = cp.CPlane(origin=(8, 9, 10), normal=(2, -3, 6))
    _plane(ctx, plane)
    obj = _start(scene, selection, proc)
    original = obj.shape
    _plane(ctx, cp.PRESETS["front"]())
    _vertical(proc)
    offset = np.dot(np.subtract(TARGET, BASE), plane.normal) * plane.normal

    _assert_translated(proc.preview_for(TARGET), original, offset)
    proc.provide(TARGET)
    first = _copies(scene, [obj.id])[0]
    _assert_translated(first.shape, original, offset)
    _plane(ctx, cp.PRESETS["right"]())
    _assert_translated(proc.preview_shape("-4"), original, -4 * plane.normal)
    proc.provide_text("-4")
    second = _copies(scene, [obj.id, first.id])
    assert len(second) == 1
    _assert_translated(second[0].shape, original, -4 * plane.normal)
    assert _geometry(scene.get(obj.id).shape) == _geometry(original)
    proc.provide_text("")


@pytest.mark.parametrize("vertical", [False, True], ids=["ordinary-guard", "vertical"])
def test_repeated_copies_keep_original_sources_metadata_and_undo_redo(env, vertical):
    scene, selection, history, _ctx, proc = env
    layer = scene.layers.create("Copy layer")
    box = _box(scene)
    box = scene.update(box.id, layer_id=layer.id, color=(0.2, 0.4, 0.7),
                       material={"roughness": 0.25}, annotation={"kind": "label", "text": "A"},
                       group_id="copy-group")
    curve = scene.add(g.make_polyline(CURVE), name="Copy this too")
    untouched = scene.add(g.make_box((50, 40, 30), 2, 3, 4), name="Leave this")
    sources = [box, curve]
    originals = {obj.id: obj.shape for obj in scene.all()}
    original_bytes = {obj.id: g.shape_to_bytes(obj.shape) for obj in scene.all()}
    selection.set([obj.id for obj in sources])
    assert proc.run("copy")
    proc.provide(BASE)
    if vertical:
        _vertical(proc)
    for target in (TARGET, (7, 100, -4)):
        offset = np.subtract(target, BASE)
        if vertical:
            offset = np.asarray((0, 0, offset[2]))
        before = _state(scene, selection, history)
        previous = {obj.id for obj in scene.all()}
        request = proc.request
        ghost = proc.preview_for(target)
        expected = g.make_compound([g.translate(originals[obj.id], offset) for obj in sources])
        assert _geometry(ghost) == _geometry(expected), "Only the original selection is previewed"
        assert _state(scene, selection, history) == before
        assert proc.request is request

        proc.provide(target)

        made = _copies(scene, previous)
        assert len(made) == 2, "Every target copies both original sources exactly once"
        assert _geometry(g.make_compound([obj.shape for obj in made])) == _geometry(ghost)
        for copy, source in zip(made, sources):
            _assert_translated(copy.shape, originals[source.id], offset)
            for field in ("layer_id", "color", "material", "annotation", "group_id"):
                assert getattr(copy, field) == getattr(source, field)
        for obj_id, shape_bytes in original_bytes.items():
            assert g.shape_to_bytes(scene.get(obj_id).shape) == shape_bytes
        assert proc.busy
    proc.provide_text("")
    assert not proc.busy
    assert len(scene.all()) == 7
    assert _geometry(scene.get(untouched.id).shape) == _geometry(originals[untouched.id])
    committed = {obj.id: _geometry(obj.shape) for obj in scene.all()}
    assert history.undo() is not None
    assert {obj.id: _geometry(obj.shape) for obj in scene.all()} == {
        obj_id: _geometry(shape) for obj_id, shape in originals.items()}
    assert history.redo() is not None
    assert {obj.id: _geometry(obj.shape) for obj in scene.all()} == committed


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
    window.command_line.run_command("copy")
    window.processor.provide(BASE)
    return obj


def _assert_all_panes_show(window, expected):
    mesh = tessellate(expected)
    panes = list(window.all_viewports())
    assert len(panes) == 4
    for pane in panes:
        assert pane._ghost is not None, f"{pane._view_name} must show the pending copy"
        triangles, segments = pane._ghost_geometry()
        np.testing.assert_allclose(segments, mesh.edge_segments.reshape(-1, 3), rtol=0, atol=1e-5)
        np.testing.assert_allclose(triangles, mesh.vertices[mesh.triangles.ravel()], rtol=0, atol=1e-5)


@pytest.mark.parametrize("finish", ["enter", "cancel-before-first", "cancel-after-first"])
def test_v_enter_and_typed_copy_previews_reach_all_panes_and_clear_at_finish(window, finish):
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
    if finish == "cancel-before-first":
        window.processor.cancel()
        assert len(window.scene.all()) == 1
        assert not window.history.can_undo
    else:
        QTest.keyClick(window.command_line.input, Qt.Key.Key_Return)
        assert window.processor.busy, "A committed copy leaves the next target available"
        made = _copies(window.scene, [obj.id])
        assert len(made) == 1
        assert _geometry(made[0].shape) == _geometry(expected)
        before = _state(window.scene, window.selection, window.history)
        _type(window, "-2.5")
        _assert_all_panes_show(window, g.translate(original, (0, 0, -2.5)))
        assert _state(window.scene, window.selection, window.history) == before
        if finish == "enter":
            _type(window, "")
            QTest.keyClick(window.command_line.input, Qt.Key.Key_Return)
        else:
            window.processor.cancel()
        made = _copies(window.scene, [obj.id])
        assert len(made) == 1, "Finishing clears the pending preview and keeps the committed copy"
        assert _geometry(made[0].shape) == _geometry(expected)
        committed = {o.id: _geometry(o.shape) for o in window.scene.all()}
        assert window.history.undo() is not None
        assert len(window.scene.all()) == 1
        assert window.history.redo() is not None
        assert {o.id: _geometry(o.shape) for o in window.scene.all()} == committed
    assert _geometry(window.scene.get(obj.id).shape) == _geometry(original)
    assert not window.processor.busy
    assert all(pane._ghost is None and pane.point_axis is None
               and not pane.point_mode for pane in window.all_viewports())


def test_the_vertical_copy_chip_updates_current_typed_preview_and_cursor_in_all_panes(window):
    obj = _start_window(window)
    original = obj.shape
    front = next(vp for vp in window.all_viewports() if vp._view_name == "front")
    ordinary_cursor = front.world_point_at(400, 200)
    _type(window, "19,-6,11")
    _assert_all_panes_show(window, g.translate(original, np.subtract(TARGET, BASE)))
    before = _state(window.scene, window.selection, window.history)
    request = window.processor.request

    window.command_line.optionClicked.emit("Vertical")

    _assert_all_panes_show(window, g.translate(original, (0, 0, 8)))
    assert window.processor.request is request
    assert _state(window.scene, window.selection, window.history) == before
    assert front.world_point_at(400, 200)[:2] == pytest.approx(BASE[:2], abs=1e-6)
    window.command_line.optionClicked.emit("Vertical")
    _assert_all_panes_show(window, g.translate(original, np.subtract(TARGET, BASE)))
    assert front.world_point_at(400, 200) == pytest.approx(ordinary_cursor, abs=1e-6)


@pytest.mark.parametrize("view", ["perspective", "front"])
def test_the_mouse_can_copy_along_the_vertical_from_another_pane(window, view):
    obj = _start_window(window)
    original = obj.shape
    _type(window, "v")
    QTest.keyClick(window.command_line.input, Qt.Key.Key_Return)
    pane = next(vp for vp in window.all_viewports() if vp._view_name == view)
    upper = pane.world_point_at(400, 200)
    lower = pane.world_point_at(400, 400)
    assert upper is not None and lower is not None
    assert upper[:2] == pytest.approx(BASE[:2], abs=1e-6), (
        "Vertical must solve the cursor against the normal through the copy base")
    assert lower[:2] == pytest.approx(BASE[:2], abs=1e-6)
    assert abs(upper[2] - lower[2]) > 1
    before = _state(window.scene, window.selection, window.history)
    event = QMouseEvent(QEvent.Type.MouseMove, QPointF(400, 200),
                        Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                        Qt.KeyboardModifier.NoModifier)
    pane.mouseMoveEvent(event)
    expected = g.translate(original, (0, 0, upper[2] - BASE[2]))
    _assert_all_panes_show(window, expected)
    assert _state(window.scene, window.selection, window.history) == before

    QTest.mouseClick(pane, Qt.MouseButton.LeftButton, pos=QPoint(400, 200))

    assert window.processor.busy
    made = _copies(window.scene, [obj.id])
    assert len(made) == 1
    assert _geometry(made[0].shape) == _geometry(expected)
    event = QMouseEvent(QEvent.Type.MouseMove, QPointF(400, 400),
                        Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                        Qt.KeyboardModifier.NoModifier)
    pane.mouseMoveEvent(event)
    _assert_all_panes_show(window, g.translate(original, (0, 0, lower[2] - BASE[2])))
    QTest.mouseClick(pane, Qt.MouseButton.LeftButton, pos=QPoint(400, 400))
    made = _copies(window.scene, [obj.id])
    assert len(made) == 2
    assert _geometry(made[1].shape) == _geometry(g.translate(original, (0, 0, lower[2] - BASE[2])))
    _type(window, "")
    QTest.keyClick(window.command_line.input, Qt.Key.Key_Return)
    assert not window.processor.busy
    assert all(vp._ghost is None and vp.point_axis is None for vp in window.all_viewports())


def test_copy_on_paper_keeps_two_dimensional_repeated_targets_and_has_no_vertical(window):
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

    assert window.processor.run("copy")
    assert "Vertical" not in dict(window.processor.option_chips())
    window.processor.provide_text("0,0,0")
    assert "Vertical" not in dict(window.processor.option_chips())
    window.processor.provide_text("15,-4,90")
    assert window.processor.busy
    assert "Vertical" not in dict(window.processor.option_chips())
    window.processor.provide_text("0,10,5")
    window.processor.provide_text("")

    assert not window.processor.busy
    assert len(layout.details) == 3
    assert (detail.x, detail.y, detail.w, detail.h) == pytest.approx((10, 20, 100, 80))
    assert (layout.details[1].x, layout.details[1].y) == pytest.approx((25, 16))
    assert (layout.details[2].x, layout.details[2].y) == pytest.approx((10, 30))
    assert _geometry(window.scene.get(model.id).shape) == original
