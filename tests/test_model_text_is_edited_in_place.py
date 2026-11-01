"""Model lettering is written where it lives, without a blocking dialog.

The viewport editor and the Properties content field are two views of the
same editable TextShape.  These tests stay at the MainWindow boundary: they
drive the real command and real Qt input events, while leaving the particular
editor widget implementation open.
"""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QFontDatabase, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QPlainTextEdit, QTextEdit

from serpentine3d.app import MainWindow
from serpentine3d.commands.base import PointReq
from serpentine3d.core.text import TextShape
from serpentine3d.ui.text_editor import InlineTextEditor


@pytest.fixture
def window():
    w = MainWindow()
    w.resize(1200, 850)
    w.show()
    QApplication.processEvents()
    yield w
    w.processor.cancel()
    w.hide()


def _multiline_editor(parent):
    editors = [
        editor
        for cls in (QPlainTextEdit, QTextEdit)
        for editor in parent.findChildren(cls)
        if not editor.isReadOnly() and not editor.isHidden() and editor.isEnabled()
    ]
    assert len(editors) == 1, (
        f"Expected one live multiline text editor in {type(parent).__name__}, "
        f"found {len(editors)}")
    return editors[0]


def _replace_text(editor, lines):
    editor.setFocus()
    QTest.keyClick(editor, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    for index, line in enumerate(lines):
        if index:
            # the viewport popup closes on Enter and breaks on Ctrl+Enter
            QTest.keyClick(editor, Qt.Key.Key_Return,
                           Qt.KeyboardModifier.ControlModifier
                           if isinstance(editor, InlineTextEditor)
                           else Qt.KeyboardModifier.NoModifier)
        QTest.keyClicks(editor, line)
    QApplication.processEvents()


def _forbid_modal_dialog(monkeypatch):
    def modal_was_opened(_dialog):
        pytest.fail("Model text opened a blocking TextEditorDialog")

    monkeypatch.setattr(QDialog, "exec", modal_was_opened)


def _double_click(viewport, point):
    local = QPointF(*point)
    event = QMouseEvent(
        QEvent.Type.MouseButtonDblClick,
        local,
        local,
        viewport.mapToGlobal(local.toPoint()),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(viewport, event)
    QApplication.processEvents()


def _available_font():
    families = set(QFontDatabase.families())
    for family in ("DejaVu Sans", "Liberation Sans", "Arial", "Noto Sans"):
        if family in families:
            return family
    pytest.skip("No installed lettering font")


def test_model_text_is_placed_and_written_directly_in_the_viewport(
        window, monkeypatch):
    _forbid_modal_dialog(monkeypatch)

    window.processor.run("text")
    assert isinstance(window.processor.request, PointReq), (
        "Text should ask for its model-space anchor before asking for content")

    anchor = (25., 35., 0.)
    window.processor.provide(anchor)
    editor = _multiline_editor(window.viewport)

    _replace_text(editor, ["Room", "schedule"])
    obj, = window.scene.all()
    assert isinstance(obj.shape, TextShape)
    assert obj.shape.text == "Room\nschedule", (
        "Typing must rebuild the visible TextShape while editing is active")
    np.testing.assert_allclose(obj.shape.origin, anchor)

    QTest.keyClick(editor, Qt.Key.Key_Escape)
    QApplication.processEvents()
    assert not window.processor.busy, "Escape should finish and keep the text object"
    assert window.scene.get(obj.id).shape.text == "Room\nschedule"
    assert editor.isHidden(), "Finishing text should remove its viewport editor"


def test_enter_closes_the_text_editor_and_ctrl_enter_breaks_the_line(
        window, monkeypatch):
    _forbid_modal_dialog(monkeypatch)
    window.processor.run("text")
    window.processor.provide((0., 0., 0.))
    editor = _multiline_editor(window.viewport)

    editor.setFocus()
    QTest.keyClicks(editor, "Top")
    QTest.keyClick(editor, Qt.Key.Key_Return,
                   Qt.KeyboardModifier.ControlModifier)
    QTest.keyClicks(editor, "line")
    QApplication.processEvents()
    assert not editor.isHidden(), "Ctrl+Enter must keep the editor open"

    QTest.keyClick(editor, Qt.Key.Key_Return)
    QApplication.processEvents()
    assert editor.isHidden(), "Enter should close the text editor"
    assert not window.processor.busy
    obj, = window.scene.all()
    assert obj.shape.text == "Top\nline"


def test_double_click_and_properties_edit_the_same_live_model_text(
        window, monkeypatch):
    _forbid_modal_dialog(monkeypatch)
    original = TextShape(
        "Existing label", 6., _available_font(), origin=(0., 0., 0.))
    obj = window.scene.add(original, name="Room label")

    viewport = window.viewport
    viewport.camera.set_standard_view("top")
    lo, hi = np.asarray(obj.bbox(), float)
    center = (lo + hi) / 2
    viewport.camera.target = center
    viewport.camera.distance = 100.
    QApplication.processEvents()
    screen = viewport.camera.project(
        np.asarray([center]), viewport.width(), viewport.height())[0]
    assert viewport.pick_object(float(screen[0]), float(screen[1])) == obj.id, (
        "The test must double-click the actual visible TextShape")

    _double_click(viewport, (float(screen[0]), float(screen[1])))
    inline = _multiline_editor(viewport)
    assert inline.toPlainText() == "Existing label"
    properties = _multiline_editor(window.properties)
    assert properties.toPlainText() == "Existing label"

    _replace_text(inline, ["North", "elevation"])
    assert window.scene.get(obj.id).shape.text == "North\nelevation"
    assert properties.toPlainText() == "North\nelevation", (
        "Properties must follow direct edits without reopening a dialog")

    _replace_text(properties, ["South", "elevation"])
    assert window.scene.get(obj.id).shape.text == "South\nelevation"
    assert inline.toPlainText() == "South\nelevation", (
        "The viewport editor must follow edits made in Properties")

    QTest.keyClick(inline, Qt.Key.Key_Escape)
    QApplication.processEvents()
    assert inline.isHidden()


def test_text_is_picked_anywhere_inside_its_frame(window):
    text = TextShape("I I", 6., _available_font(), origin=(0., 0., 0.))
    obj = window.scene.add(text, name="Sparse label")
    viewport = window.viewport
    viewport.camera.set_standard_view("top")
    box = text.frame_box()
    viewport.camera.target = box.mean(axis=0)
    viewport.camera.distance = 60.
    QApplication.processEvents()

    corner, opposite = box[0], box[2]
    inside = corner + (opposite - corner) * 0.05
    screen = viewport.camera.project(
        np.asarray([inside]), viewport.width(), viewport.height())[0]
    assert viewport.pick_object(float(screen[0]), float(screen[1])) == obj.id, (
        "A click inside the text's frame but off its letters should pick it")


def test_text_in_the_model_places_model_text(window, monkeypatch):
    _forbid_modal_dialog(monkeypatch)
    window.processor.run("text")
    window.processor.provide((0., 0., 0.))
    editor = _multiline_editor(window.viewport)
    editor.setFocus()
    QTest.keyClicks(editor, "Model")
    QTest.keyClick(editor, Qt.Key.Key_Return)
    QApplication.processEvents()
    obj, = window.scene.all()
    assert isinstance(obj.shape, TextShape)


def test_typing_the_first_text_does_not_shift_the_view(window, monkeypatch):
    """The text fields Properties shows for it must fit the panel as it
    is: a panel that widened pushed the view beside it sideways."""
    _forbid_modal_dialog(monkeypatch)
    viewport = window.viewport
    width = viewport.width()
    window.processor.run("text")
    window.processor.provide((10., 10., 0.))
    editor = _multiline_editor(viewport)
    editor.setFocus()
    QTest.keyClicks(editor, "First")
    QApplication.processEvents()
    assert viewport.width() == width
