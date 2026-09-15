"""Dropping a file Serpentine3D cannot open says so instead of nothing.

Reported as "Drag & Drop does not work for DWGs" (#21): DWG is not a format
the program reads at all, so the drag was refused and the drop never
arrived, leaving the window silent. Silence reads as a broken feature. A
drop of local files is now taken and answered: whatever can be imported is,
and anything that cannot gets a line saying why, naming DXF where the file
is a DWG since that is the way out of it.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QApplication

from serpentine3d import fileio


@pytest.fixture
def window():
    from serpentine3d.app import MainWindow

    win = MainWindow()
    try:
        yield win
    finally:
        if win.processor.busy:
            win.processor.cancel()
        win.mark_saved()
        win.close()


def _drag(target, urls):
    mime = QMimeData()
    mime.setUrls(urls)
    actions = Qt.DropAction.CopyAction | Qt.DropAction.MoveAction
    enter = QDragEnterEvent(QPoint(20, 20), actions, mime,
                            Qt.MouseButton.LeftButton,
                            Qt.KeyboardModifier.NoModifier)
    enter._mime = mime
    QApplication.sendEvent(target, enter)
    if not enter.isAccepted():
        return enter, None
    move = QDragMoveEvent(QPoint(25, 25), actions, mime,
                          Qt.MouseButton.LeftButton,
                          Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(target, move)
    drop = QDropEvent(QPointF(25, 25), actions, mime,
                      Qt.MouseButton.LeftButton,
                      Qt.KeyboardModifier.NoModifier)
    drop._mime = mime
    QApplication.sendEvent(target, drop)
    return enter, drop


def _urls(*paths):
    return [QUrl.fromLocalFile(str(path)) for path in paths]


def _said(window):
    """What the window said since the drag began (the banner is not news)."""
    return window.command_line.echo_view.toPlainText().split(
        "type a command to begin (line, circle, box, extrude, loft, ...)")[-1]


def _a_dwg(tmp_path):
    path = tmp_path / "Site plan.dwg"
    path.write_bytes(b"AC1032" + b"\0" * 64)
    return path


def test_a_dropped_dwg_is_answered_and_points_at_dxf(window, tmp_path):
    enter, drop = _drag(window, _urls(_a_dwg(tmp_path)))

    assert enter.isAccepted(), "a dropped file has to arrive to be answered"
    assert drop is not None
    said = _said(window)
    assert ".dwg" in said.lower()
    assert "DXF" in said, "DXF is the way in, so the message has to name it"
    assert not window.history.can_undo, "nothing was imported"


def test_the_message_names_the_file_so_a_mixed_drop_is_clear(window, tmp_path):
    other = tmp_path / "notes.txt"
    other.write_text("notes")

    _drag(window, _urls(_a_dwg(tmp_path), other))

    said = _said(window)
    assert "Site plan.dwg" in said
    assert "notes.txt" in said


def test_an_unknown_format_is_answered_without_the_dxf_advice(window, tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("notes")

    _drag(window, _urls(path))

    said = _said(window)
    assert ".txt" in said.lower()
    assert "Save it as DXF" not in said, "that advice only helps a DWG"


def test_what_can_be_opened_still_is_and_the_rest_is_reported(
        window, tmp_path, monkeypatch):
    good = tmp_path / "triangle.obj"
    good.write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
    seen = []
    original = fileio.import_file

    def record(scene, path, progress=None):
        seen.append(path)
        return original(scene, path, progress=progress)

    monkeypatch.setattr(fileio, "import_file", record)

    _drag(window, _urls(_a_dwg(tmp_path), good))

    assert seen == [str(good)], "the good file still comes in"
    assert "Site plan.dwg" in _said(window)


def test_a_folder_or_a_web_link_is_still_just_refused(window, tmp_path):
    folder = tmp_path / "a folder"
    folder.mkdir()

    enter, drop = _drag(window, _urls(folder) + [QUrl("https://x.test/m.obj")])

    assert not enter.isAccepted(), "there is no file here to answer for"
    assert drop is None
    assert _said(window).strip() == ""


def test_the_supported_formats_are_offered_when_asked_for(window, tmp_path):
    """The message has to leave the user somewhere to go."""
    _drag(window, _urls(_a_dwg(tmp_path)))

    said = _said(window)
    assert "Import" in said or "import" in said
