"""Model shortcuts belong to an empty CAD prompt, text keys to editors."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit

from tests.test_default_shortcuts import _lines, open_window  # noqa: F401


def focus_press(field, sequence):
    field.setFocus(Qt.FocusReason.OtherFocusReason)
    QApplication.processEvents()
    assert QApplication.focusWidget() is field
    QTest.keySequence(field, QKeySequence(sequence))
    QApplication.processEvents()


@pytest.mark.parametrize("sequence,command", [
    ("Home", "undoview"), ("End", "redoview"), ("Ctrl+H", "hide"),
])
def test_empty_command_prompt_dispatches_factory_key_once(
        open_window, monkeypatch, sequence, command):
    window = open_window()
    fired = []
    monkeypatch.setattr(window, "run_command", fired.append)
    field = window.command_line.input
    assert not field.text()
    focus_press(field, sequence)
    assert fired == [command]


def test_command_text_owns_editing_until_prompt_is_empty(open_window):
    window = open_window()
    first, _ = _lines(window)
    window.selection.set([first])
    vp = window.viewport
    vp.camera.azimuth += 0.25
    vp.note_view_change(now=vp._view_moved_at + 5.0)
    camera = vp.camera.state()
    field = window.command_line.input
    field.setText("abc")
    field.setCursorPosition(1)
    focus_press(field, "Home")
    assert field.cursorPosition() == 0
    focus_press(field, "End")
    assert field.cursorPosition() == 3
    native = QLineEdit(field.text())
    native.setCursorPosition(field.cursorPosition())
    native.show()
    native.activateWindow()
    QApplication.processEvents()
    assert QApplication.activeWindow() is native
    focus_press(native, "Ctrl+H")
    native.close()
    window.activateWindow()
    QApplication.processEvents()
    assert QApplication.activeWindow() is window
    focus_press(field, "Ctrl+H")
    assert field.text() == native.text()
    assert field.cursorPosition() == native.cursorPosition()
    assert vp.camera.state() == camera
    assert window.scene.get(first).visible
    field.clear()
    focus_press(field, "Ctrl+H")
    assert not window.scene.get(first).visible
    focus_press(window.viewport, "Ctrl+Shift+H")
    assert window.scene.get(first).visible


def test_empty_prompt_retains_model_copy_paste_and_select_all(open_window):
    window = open_window()
    first, _ = _lines(window)
    window.selection.set([first])
    field = window.command_line.input
    focus_press(field, "Ctrl+C")
    window.selection.clear()
    focus_press(field, "Ctrl+V")
    assert len(window.scene.all()) == 3
    focus_press(field, "Ctrl+A")
    assert set(window.selection.ids) == {obj.id for obj in window.scene.all()}
    assert field.text() == ""


def test_command_typing_submission_and_history_remain_available(open_window):
    window = open_window()
    field = window.command_line.input
    field.setFocus()
    QApplication.processEvents()
    QTest.keyClicks(field, "line")
    QApplication.processEvents()
    assert field.text() == "line"
    submitted = []
    window.command_line.submitted.connect(submitted.append)
    focus_press(field, "Return")
    assert submitted == ["line"]
    assert field.text() == ""
    window.processor.cancel()
    focus_press(field, "Up")
    assert field.text() == "line"
    focus_press(field, "Down")
    assert field.text() == ""


def script_field(window):
    workspace = window.command_workspace
    workspace.set_pane_visible("script", True)
    script = workspace._ensure_script()
    script.new_draft("alpha", "Shortcuts.py")
    return script.editor


def test_python_editor_retains_navigation_clipboard_and_undo(
        open_window, monkeypatch):
    window = open_window()
    field = script_field(window)
    fired = []
    monkeypatch.setattr(window, "run_command", fired.append)
    field.moveCursor(QTextCursor.MoveOperation.End)
    focus_press(field, "Home")
    assert field.textCursor().position() == 0
    focus_press(field, "End")
    assert field.textCursor().position() == 5
    field.selectAll()
    focus_press(field, "Ctrl+C")
    assert QApplication.clipboard().text() == "alpha"
    field.moveCursor(QTextCursor.MoveOperation.End)
    QApplication.clipboard().setText(" beta")
    focus_press(field, "Ctrl+V")
    assert field.toPlainText() == "alpha beta"
    focus_press(field, "Ctrl+Z")
    assert field.toPlainText() == "alpha"
    assert fired == []


@pytest.mark.parametrize("sequence,attribute", [
    ("F8", "ortho"), ("F9", "grid_snap"),
])
def test_python_editor_unhandled_keys_do_not_toggle_the_model(
        open_window, sequence, attribute):
    window = open_window()
    field = script_field(window)
    before = getattr(window.viewport, attribute)
    focus_press(field, sequence)
    assert getattr(window.viewport, attribute) is before
    assert field.toPlainText() == "alpha"
    focus_press(window.viewport, sequence)
    assert getattr(window.viewport, attribute) is not before


@pytest.mark.parametrize("sequence,attribute", [
    ("F8", "ortho"), ("F9", "grid_snap"),
])
def test_drawing_control_keys_preserve_a_line_waiting_for_its_next_point(
        open_window, sequence, attribute):
    from serpentine3d.core import geometry as g

    window = open_window()
    window.run_command("line")
    window.processor.provide_text("0,0,0")
    processor = window.processor
    active = processor.active
    picked = list(processor.picked_points)
    repeat_target = processor.last_command
    assert processor.busy and len(picked) == 1
    before = getattr(window.viewport, attribute)
    focus_press(window.command_line.input, sequence)
    assert getattr(window.viewport, attribute) is not before
    assert processor.busy and processor.active is active
    assert processor.picked_points == picked
    assert processor.last_command == repeat_target
    processor.provide_text("10,0,0")
    objects = window.scene.all()
    assert len(objects) == 1
    assert g.curve_length(objects[0].shape) == pytest.approx(10.0)


@pytest.mark.parametrize("destination", ["assistant", "properties"])
def test_other_text_fields_keep_home_and_end_for_editing(
        open_window, monkeypatch, destination):
    window = open_window()
    if destination == "assistant":
        workspace = window.command_workspace
        workspace.set_mode("ai")
        field = workspace.assistant.input
        field.setPlainText("alpha")
        field.moveCursor(QTextCursor.MoveOperation.End)
        cursor_position = lambda: field.textCursor().position()
    else:
        first, _ = _lines(window)
        window.selection.set([first])
        field = window.properties.name_edit
        field.setText("alpha")
        field.setCursorPosition(5)
        cursor_position = field.cursorPosition
    fired = []
    monkeypatch.setattr(window, "run_command", fired.append)
    focus_press(field, "Home")
    assert cursor_position() == 0
    focus_press(field, "End")
    assert cursor_position() == 5
    assert fired == []
