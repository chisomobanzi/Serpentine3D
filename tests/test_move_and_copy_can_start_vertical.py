"""Vertical Move/Copy presets work as commands, aliases, and shortcuts (#49)."""

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QShortcut
from PySide6.QtTest import QTest

from serpentine3d.app import MainWindow
from serpentine3d.commands import base as commands
from serpentine3d.commands.base import PointReq, SelectReq, TextReq
from serpentine3d.core import geometry as g
from serpentine3d.core.tessellate import tessellate


BASE = (4.0, 7.0, 3.0)
PRESETS = [
    "{command} Vertical",
    "  {command}   vErTiCaL  ",
    "! _{command} _Vertical",
    "  !  _{command}\t_vErTiCaL  ",
    "!_{command} _Vertical",
]


def _box(scene):
    return scene.add(g.make_box((0, 0, 0), 12, 8, 10), name="Preset source")


def _assert_base_prompt(proc, command):
    assert proc.busy and proc.active.name == command
    assert isinstance(proc.request, PointReq)
    assert "from" in proc.request.prompt.lower(), "The preset must still ask for a base point"
    assert proc.picked_points == [], "Vertical is an option, not a supplied point"
    assert dict(proc.option_chips())["Vertical"] == "Yes"


def _assert_offset(shape, original, offset):
    for actual, before in zip(g.bbox(shape), g.bbox(original)):
        assert actual == pytest.approx(np.asarray(before) + offset, abs=1e-6)


def _state(scene, selection, history):
    return (scene.revision,
            tuple((obj.id, g.shape_to_bytes(obj.shape)) for obj in scene.all()),
            tuple(selection.ids), tuple(selection.subobjects),
            history.can_undo, history.can_redo)


@pytest.mark.parametrize("command", ["Move", "Copy"])
@pytest.mark.parametrize("template", PRESETS,
                         ids=["native", "native-case-spacing", "rhino",
                              "rhino-case-spacing", "adjacent-cancel"])
@pytest.mark.parametrize("preselected", [False, True], ids=["pick-after", "preselected"])
def test_presets_set_vertical_without_answering_selection_or_the_base(
        env, command, template, preselected):
    scene, selection, _history, ctx, proc = env
    obj = _box(scene)
    original = g.shape_to_bytes(obj.shape)
    revision = scene.revision
    said = []
    ctx.add_echo_listener(said.append)
    if preselected:
        selection.set([obj.id])

    assert proc.run(template.format(command=command.swapcase())), said
    assert proc.busy and proc.active.name == command.lower()
    assert dict(proc.option_chips())["Vertical"] == "Yes", said
    if not preselected:
        assert isinstance(proc.request, SelectReq), "Vertical must not finish object selection"
        assert selection.ids == []
        proc.click_object(obj.id)
        proc.finish_selection()
    _assert_base_prompt(proc, command.lower())
    assert scene.revision == revision
    assert g.shape_to_bytes(scene.get(obj.id).shape) == original
    assert not any("Unknown command" in message for message in said)
    proc.provide_text("4,7,3")
    assert isinstance(proc.request, PointReq)
    assert proc.request.rubber_from == BASE
    assert dict(proc.option_chips())["Vertical"] == "Yes"
    proc.cancel()


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
    window.cfg.set("aliases", {})
    window.apply_user_aliases()
    window.mark_saved()
    window.close()


def _type(window, text):
    window.command_line.input.clear()
    QTest.keyClicks(window.command_line.input, text)


def _enter(window, text=""):
    _type(window, text)
    QTest.keyClick(window.command_line.input, Qt.Key.Key_Return)


@pytest.mark.parametrize("command", ["move", "copy"])
@pytest.mark.parametrize("template", ["{command} Vertical", "! _{command} _Vertical"],
                         ids=["native", "rhino"])
@pytest.mark.parametrize("preselected", [False, True], ids=["pick-after", "preselected"])
@pytest.mark.parametrize("entry", ["shortcut", "alias"])
def test_configured_presets_offer_the_next_prompt_and_keep_the_vertical_result(
        window, command, template, preselected, entry):
    top = next(pane for pane in window.all_viewports() if pane._view_name == "top")
    front = next(pane for pane in window.all_viewports() if pane._view_name == "front")
    window._set_active_viewport(top)
    obj = _box(window.scene)
    original = obj.shape
    original_bytes = g.shape_to_bytes(original)
    if preselected:
        window.selection.set([obj.id])
    preset = template.format(command=command.capitalize())
    if entry == "shortcut":
        window.cfg.set("shortcuts", {"Ctrl+Alt+F6": preset})
        window.apply_user_shortcuts()
        shortcuts = [shortcut for shortcut in window.findChildren(QShortcut)
                     if shortcut.key().toString() == "Ctrl+Alt+F6"]
        assert len(shortcuts) == 1
        QTest.keyClick(window, Qt.Key.Key_F6,
                       Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
    else:
        alias = f"{command}verticalpresettest"
        window.cfg.set("aliases", {alias: preset})
        window.apply_user_aliases()
        window.command_line.run_command(alias)

    proc = window.processor
    assert proc.busy and proc.active.name == command, window.command_line.echo_view.toPlainText()
    assert "Vertical=Yes" in [chip.text() for chip in window.command_line._chips]
    assert proc.request.prompt in window.command_line.prompt_label.text()
    if not preselected:
        assert isinstance(proc.request, SelectReq), "The preset must let the user choose objects"
        proc.click_object(obj.id)
        _enter(window)
    _assert_base_prompt(proc, command)
    assert "from" in window.command_line.prompt_label.text().lower()
    _enter(window, "4,7,3")
    assert isinstance(proc.request, PointReq)
    assert proc.request.rubber_from == BASE
    normal = np.asarray(top.active_cplane().normal, float)
    np.testing.assert_allclose(proc.request.axis_lock[1], normal)
    window._set_active_viewport(front)
    before = _state(window.scene, window.selection, window.history)

    _type(window, "-3cm")

    mesh = tessellate(g.translate(original, tuple(-30 * normal)))
    for pane in window.all_viewports():
        assert pane._ghost is not None, "A preset must preview its signed height in every pane"
        triangles, segments = pane._ghost_geometry()
        np.testing.assert_allclose(segments, mesh.edge_segments.reshape(-1, 3),
                                   rtol=0, atol=1e-5)
        np.testing.assert_allclose(triangles, mesh.vertices[mesh.triangles.ravel()],
                                   rtol=0, atol=1e-5)
    assert _state(window.scene, window.selection, window.history) == before
    QTest.keyClick(window.command_line.input, Qt.Key.Key_Return)
    if command == "move":
        _assert_offset(window.scene.get(obj.id).shape, original, -30 * normal)
    else:
        copies = [made for made in window.scene.all() if made.id != obj.id]
        assert len(copies) == 1
        _assert_offset(copies[0].shape, original, -30 * normal)
        assert dict(proc.option_chips())["Vertical"] == "Yes"
        _enter(window, "+2cm")
        copies = [made for made in window.scene.all() if made.id != obj.id]
        assert len(copies) == 2
        _assert_offset(copies[1].shape, original, 20 * normal)
        assert g.shape_to_bytes(window.scene.get(obj.id).shape) == original_bytes
        _enter(window)
    assert not proc.busy
    assert all(pane._ghost is None and pane.point_axis is None and not pane.point_mode
               for pane in window.all_viewports())
    window.selection.set([obj.id])
    window.command_line.run_command(command)
    assert dict(proc.option_chips())["Vertical"] == "No", "A preset must not change the next command's default"


@pytest.mark.parametrize("command", ["move", "copy"])
@pytest.mark.parametrize("template", ["! _{command} _Vertical", "!_{command} _Vertical"],
                         ids=["spaced-cancel", "adjacent-cancel"])
def test_leading_cancel_prefix_replaces_an_in_flight_command(env, command, template):
    scene, selection, _history, ctx, proc = env
    obj = _box(scene)
    original = g.shape_to_bytes(obj.shape)
    said = []
    ctx.add_echo_listener(said.append)
    assert proc.run("line")
    proc.provide(BASE)
    selection.set([obj.id])

    assert proc.run(template.format(command=command)), said

    _assert_base_prompt(proc, command)
    assert not any("Unknown command" in message for message in said)
    assert len(scene.all()) == 1 and g.shape_to_bytes(scene.get(obj.id).shape) == original
    proc.cancel()


@pytest.mark.parametrize("command", ["move", "copy"])
@pytest.mark.parametrize("template", ["! _{command} _Vertical", "!_{command} _Vertical"],
                         ids=["spaced-cancel", "adjacent-cancel"])
def test_leading_cancel_prefix_can_replace_a_command_from_the_gui_prompt(window, command, template):
    obj = _box(window.scene)
    window.command_line.run_command("line")
    window.processor.provide(BASE)
    window.selection.set([obj.id])

    window.command_line.run_command(template.format(command=command))

    _assert_base_prompt(window.processor, command)
    assert "Vertical=Yes" in [chip.text() for chip in window.command_line._chips]
    assert "Unknown command" not in window.command_line.echo_view.toPlainText()
    assert len(window.scene.all()) == 1


@pytest.mark.parametrize("macro,bounds", [
    ("line 1,2,3 5,2,3", ((1, 2, 3), (5, 2, 3))),
    ("line BothSides 2,3,4 5,3,4", ((-1, 3, 4), (5, 3, 4))),
], ids=["ordinary-points", "construction-keyword"])
@pytest.mark.parametrize("alias", [False, True], ids=["direct", "alias"])
def test_native_point_macros_and_construction_keywords_keep_their_meaning(env, macro, bounds, alias):
    scene, _selection, _history, _ctx, proc = env
    name = "nativepointpresetguard"
    if alias:
        commands.add_alias(name, macro)
    try:
        assert proc.run(name if alias else macro)
        assert not proc.busy
        assert len(scene.all()) == 1
        for actual, expected in zip(g.bbox(scene.all()[0].shape), bounds):
            assert actual == pytest.approx(expected, abs=1e-6)
    finally:
        if alias:
            commands.remove_alias(name)


@pytest.mark.parametrize("alias", [False, True], ids=["direct", "alias"])
def test_native_macro_text_keeps_literal_bang_and_underscore_characters(env, alias):
    scene, selection, _history, _ctx, proc = env
    obj = _box(scene)
    selection.set([obj.id])
    name = "nativetextpresetguard"
    macro = "block !_vertical"
    if alias:
        commands.add_alias(name, macro)
    try:
        assert proc.run(name if alias else macro)
        assert not proc.busy
        assert [definition["name"] for definition in scene.block_defs.values()] == ["!_vertical"]
    finally:
        if alias:
            commands.remove_alias(name)


def test_a_gui_text_answer_keeps_literal_bang_and_underscore_characters(window):
    obj = _box(window.scene)
    window.selection.set([obj.id])
    window.command_line.run_command("block")
    assert isinstance(window.processor.request, TextReq)

    window.command_line.run_command("!_vertical")

    assert not window.processor.busy
    assert [definition["name"] for definition in window.scene.block_defs.values()] == ["!_vertical"]
    assert "Unknown command" not in window.command_line.echo_view.toPlainText()
