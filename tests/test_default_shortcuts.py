"""Factory keyboard presets work immediately, including on old settings."""

import json

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


PRESETS = {
    "Ctrl+G": "group",
    "Ctrl+Shift+G": "ungroup",
    "Ctrl+H": "hide",
    "Ctrl+Shift+H": "show",
    "Ctrl+L": "lock",
    "Ctrl+Shift+L": "unlockall",
    "Ctrl+T": "trim",
    "Ctrl+J": "join",
    "F8": "ortho",
    "F9": "gridsnap",
    "Ctrl+W": "zoomwindow",
    "Home": "undoview",
    "End": "redoview",
    "Ctrl+Shift+E": "zoomextents",
}


@pytest.fixture
def open_window(tmp_path, monkeypatch):
    """Create an active real window without reading the developer's data."""
    from serpentine3d.app import MainWindow

    windows = []

    def create(settings=None):
        path = tmp_path / f"settings-{len(windows)}.json"
        if settings is not None:
            path.write_text(json.dumps(settings), encoding="utf-8")
        monkeypatch.setenv("SERP3D_CONFIG", str(path))
        window = MainWindow()
        windows.append(window)
        window.set_view_layout("single")
        window.show()
        window.activateWindow()
        window.viewport.setFocus(Qt.FocusReason.OtherFocusReason)
        QApplication.processEvents()
        return window

    yield create
    for window in windows:
        window.processor.cancel()
        window.mark_saved()
        window.close()
    QApplication.processEvents()


def press(window, sequence):
    """Use Qt's normal shortcut path from the modelling viewport."""
    window.viewport.setFocus(Qt.FocusReason.OtherFocusReason)
    QApplication.processEvents()
    QTest.keySequence(window.viewport, QKeySequence(sequence))
    QApplication.processEvents()


@pytest.mark.parametrize("settings", [None, {"shortcuts": {}}],
                         ids=["fresh-settings", "legacy-empty-shortcuts"])
def test_factory_keys_dispatch_the_expected_command_once(
        open_window, monkeypatch, settings):
    window = open_window(settings)
    fired = []
    monkeypatch.setattr(window, "run_command", fired.append)
    failures = {}
    for sequence, command in PRESETS.items():
        fired.clear()
        window.command_line.input.clear()
        press(window, sequence)
        if fired != [command]:
            failures[sequence] = {"expected": command, "fired": list(fired)}
    assert not failures, failures


def test_custom_equivalent_key_spellings_take_precedence_over_presets(
        open_window, monkeypatch):
    window = open_window({"shortcuts": {
        "ctrl+g": "line",
        "CTRL+SHIFT+G": "circle",
        "F8": "grid",
        "ctrl+e": "top",
    }})
    fired = []
    monkeypatch.setattr(window, "run_command", fired.append)
    for sequence, command in [
        ("Ctrl+G", "line"), ("Ctrl+Shift+G", "circle"),
        ("F8", "grid"), ("Ctrl+E", "top"),
        ("F9", "gridsnap"), ("Ctrl+H", "hide"),
    ]:
        fired.clear()
        window.command_line.input.clear()
        press(window, sequence)
        assert fired == [command], (sequence, fired)


def test_existing_shortcuts_remain_usable(open_window, monkeypatch):
    window = open_window()
    fired = []
    monkeypatch.setattr(window, "run_command", fired.append)
    for sequence, command in [
        ("Ctrl+E", "zoomextents"), ("Ctrl+A", "selall"),
        ("Ctrl+Z", "undo"), ("Ctrl+Y", "redo"),
        ("F2", "front"), ("F7", "grid"),
        ("F10", "pointson"), ("F11", "pointsoff"),
    ]:
        fired.clear()
        press(window, sequence)
        assert fired == [command], (sequence, fired)


def _lines(window):
    from serpentine3d.core import geometry as g
    first = window.scene.add(g.make_line((0, 0, 0), (10, 0, 0)))
    second = window.scene.add(g.make_line((10, 0, 0), (20, 0, 0)))
    return [first.id, second.id]


def test_group_and_ungroup_keys_change_the_selected_objects(open_window):
    window = open_window()
    ids = _lines(window)
    window.selection.set(ids)
    press(window, "Ctrl+G")
    groups = [window.scene.get(oid).group_id for oid in ids]
    assert groups[0] and groups[0] == groups[1]
    window.selection.set(ids)
    press(window, "Ctrl+Shift+G")
    assert all(window.scene.get(oid).group_id is None for oid in ids)


def test_hide_and_show_all_keys_reveal_unselected_hidden_objects(open_window):
    window = open_window()
    first, second = _lines(window)
    window.scene.update(second, visible=False)
    window.selection.set([first])
    press(window, "Ctrl+H")
    assert not window.scene.get(first).visible
    window.selection.clear()
    press(window, "Ctrl+Shift+H")
    assert all(window.scene.get(oid).visible for oid in (first, second))


def test_lock_and_unlock_all_keys_release_unselected_objects(open_window):
    window = open_window()
    first, second = _lines(window)
    window.scene.update(second, locked=True)
    window.selection.set([first])
    press(window, "Ctrl+L")
    assert window.scene.get(first).locked
    assert window.selection.ids == []
    press(window, "Ctrl+Shift+L")
    assert all(not window.scene.get(oid).locked for oid in (first, second))


@pytest.mark.parametrize("sequence,attribute", [
    ("F8", "ortho"), ("F9", "grid_snap"),
])
def test_drawing_control_keys_toggle_once_per_press(
        open_window, sequence, attribute):
    window = open_window()
    before = getattr(window.viewport, attribute)
    press(window, sequence)
    assert getattr(window.viewport, attribute) is not before
    press(window, sequence)
    assert getattr(window.viewport, attribute) is before


def test_home_and_end_restore_camera_history_without_editing_objects(open_window):
    window = open_window()
    _lines(window)
    vp = window.viewport
    start = vp.camera.state()
    revision = window.scene.revision
    vp.camera.azimuth += 0.25
    vp.note_view_change(now=vp._view_moved_at + 5.0)
    moved = vp.camera.state()
    assert moved != start
    press(window, "Home")
    assert vp.camera.state() == start
    press(window, "End")
    assert vp.camera.state() == moved
    assert window.scene.revision == revision


def test_join_key_joins_preselected_curves(open_window):
    from serpentine3d.core import geometry as g
    window = open_window()
    window.selection.set(_lines(window))
    press(window, "Ctrl+J")
    objects = window.scene.all()
    assert len(objects) == 1
    assert g.curve_length(objects[0].shape) == pytest.approx(20.0)


@pytest.mark.parametrize("sequence", ["Ctrl+T", "Ctrl+W"])
def test_interactive_keys_start_a_command(open_window, sequence):
    window = open_window()
    press(window, sequence)
    assert window.processor.busy, f"{sequence} did not start a command"


@pytest.mark.parametrize("sequence", ["Ctrl+E", "Ctrl+Shift+E"])
def test_both_zoom_extents_keys_frame_the_model(open_window, sequence):
    window = open_window()
    _lines(window)
    window.viewport.camera.distance = 10000.0
    press(window, sequence)
    assert window.viewport.camera.distance < 10000.0
