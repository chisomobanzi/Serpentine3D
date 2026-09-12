"""Paper notes are written where they live, without a blocking dialog.

These tests drive the real MainWindow, layout viewport and Properties panel.
The viewport editor and Properties content field must remain two synchronized
views of the same TextNote, whether editing starts from ``text`` or from the
rendered note itself.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPlainTextEdit, QTextEdit

from serpentine3d.app import MainWindow
from serpentine3d.commands.base import PointReq
from serpentine3d.core.layout import (
    DetailView,
    Layout,
    TextNote,
    annotation_at,
    annotation_bounds,
)
from serpentine3d.ui.text_editor import TextEditorDialog


@pytest.fixture
def sheet():
    window = MainWindow()
    window.resize(1200, 850)
    layout = Layout(name="Direct text sheet")
    window.scene.layouts.append(layout)
    window.switch_space(layout.id)
    window.show()
    window.viewport.layout_view.fit()
    QApplication.processEvents()
    yield window, layout
    window.processor.cancel()
    window.viewport.end_inline_text()
    window.hide()


def _visible_multiline_editors(parent):
    return [
        editor
        for cls in (QPlainTextEdit, QTextEdit)
        for editor in parent.findChildren(cls)
        if editor.isEnabled() and not editor.isReadOnly() and not editor.isHidden()
    ]


def _multiline_editor(parent):
    editors = _visible_multiline_editors(parent)
    assert len(editors) == 1, (
        f"Expected one live multiline text editor in {type(parent).__name__}, "
        f"found {len(editors)}")
    return editors[0]


def _replace_text(editor, lines):
    editor.setFocus()
    QTest.keyClick(editor, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    for index, line in enumerate(lines):
        if index:
            QTest.keyClick(editor, Qt.Key.Key_Return)
        QTest.keyClicks(editor, line)
    QApplication.processEvents()


def _record_modal_attempts(monkeypatch):
    calls = []

    def reject(dialog):
        calls.append(dialog)
        return 0

    monkeypatch.setattr(TextEditorDialog, "exec", reject)
    return calls


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


def _note(layout, note_id):
    return next(note for note in layout.notes if note.id == note_id)


def test_text_places_its_anchor_then_writes_a_live_note_on_the_sheet(
        sheet, monkeypatch):
    window, layout = sheet
    modal_calls = _record_modal_attempts(monkeypatch)

    window.processor.run("text")
    QApplication.processEvents()

    assert not modal_calls, "Paper text opened a blocking TextEditorDialog"
    assert isinstance(window.processor.request, PointReq), (
        "Text must ask for its paper baseline anchor before opening an editor")
    assert not _visible_multiline_editors(window.viewport), (
        "The inline editor must wait until its paper position is known")

    anchor = (68., 82., 0.)
    screen = window.viewport.layout_view.paper_to_screen(*anchor[:2])
    window.processor.provide(anchor)
    QApplication.processEvents()

    inline = _multiline_editor(window.viewport)
    near_editor = inline.geometry().adjusted(-48, -48, 48, 48)
    assert near_editor.contains(QPoint(round(screen[0]), round(screen[1]))), (
        "The inline editor must appear beside the baseline anchor on paper")

    _replace_text(inline, ["Door", "schedule"])
    note, = layout.notes
    note_id = note.id
    assert (note.x, note.y) == pytest.approx(anchor[:2])
    assert note.text == "Door\nschedule", (
        "Typing must create and update the visible TextNote while editing")

    properties = _multiline_editor(window.properties)
    assert properties.toPlainText() == "Door\nschedule", (
        "Properties must follow text typed directly on the sheet")

    QTest.keyClick(inline, Qt.Key.Key_Escape)
    QApplication.processEvents()
    assert not window.processor.busy, "Escape should finish and keep the note"
    assert inline.isHidden(), "Finishing a note should hide its inline editor"
    assert len(layout.notes) == 1
    assert _note(layout, note_id).text == "Door\nschedule"


def test_double_click_edits_a_rendered_note_and_empty_detail_still_opens(
        sheet, monkeypatch):
    window, layout = sheet
    detail = DetailView(x=20., y=20., w=200., h=130.)
    layout.details.append(detail)
    note = TextNote(x=45., y=85., text="Existing note", height=5.)
    layout.notes.append(note)
    window.scene.notify("layouts")
    QApplication.processEvents()
    modal_calls = _record_modal_attempts(monkeypatch)

    bounds = annotation_bounds("note", note)
    paper_hit = ((bounds[0] + bounds[2]) / 2,
                 (bounds[1] + bounds[3]) / 2)
    assert annotation_at(layout, *paper_hit) == ("note", note), (
        "The test must double-click the actual rendered TextNote")
    _double_click(window.viewport,
                  window.viewport.layout_view.paper_to_screen(*paper_hit))

    assert not modal_calls, "Double-clicking a note opened TextEditorDialog"
    inline = _multiline_editor(window.viewport)
    properties = _multiline_editor(window.properties)
    assert inline.toPlainText() == "Existing note"
    assert properties.toPlainText() == "Existing note"
    assert window.viewport.layout_view.entered_detail is None, (
        "A note drawn over a detail must be edited instead of entering the detail")

    _replace_text(inline, ["North", "elevation"])
    assert _note(layout, note.id).text == "North\nelevation"
    assert properties.toPlainText() == "North\nelevation", (
        "Properties must follow direct edits to an existing paper note")

    _replace_text(properties, ["South", "elevation"])
    assert _note(layout, note.id).text == "South\nelevation"
    assert inline.toPlainText() == "South\nelevation", (
        "The sheet editor must follow edits made in Properties")

    QTest.keyClick(inline, Qt.Key.Key_Escape)
    QApplication.processEvents()
    assert inline.isHidden()

    # The ordinary layout gesture is still available wherever no note was hit.
    empty_point = (190., 120.)
    _double_click(window.viewport,
                  window.viewport.layout_view.paper_to_screen(*empty_point))
    assert window.viewport.layout_view.entered_detail == detail.id
    assert not _visible_multiline_editors(window.viewport)


def test_edittext_command_uses_the_same_inline_note_editor(sheet, monkeypatch):
    window, layout = sheet
    note = TextNote(x=45., y=85., text="Existing note", height=5.)
    layout.notes.append(note)
    window.scene.notify("layouts")
    modal_calls = _record_modal_attempts(monkeypatch)

    window.processor.run("edittext")
    window.processor.provide((note.x, note.y, 0.))
    QApplication.processEvents()

    assert not modal_calls
    inline = _multiline_editor(window.viewport)
    assert inline.toPlainText() == "Existing note"
    _replace_text(inline, ["Revised", "note"])
    QTest.keyClick(inline, Qt.Key.Key_Escape)
    QApplication.processEvents()

    assert not window.processor.busy
    assert note.text == "Revised\nnote"
