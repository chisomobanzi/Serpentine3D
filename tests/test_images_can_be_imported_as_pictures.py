"""Issue #17: choosing or dropping an image starts portable picture placement."""

from __future__ import annotations

import math

import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from serpentine3d.commands.base import PointReq
from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene
from serpentine3d.fileio import native


IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


@pytest.fixture
def window(monkeypatch):
    from serpentine3d.app import MainWindow

    win = MainWindow()
    win.test_messages = []
    win.ctx.add_echo_listener(win.test_messages.append)
    monkeypatch.setattr(win.command_line, "echo", win.test_messages.append)
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda parent, title, text:
                        win.test_messages.append(f"{title}: {text}"))
    try:
        yield win
    finally:
        if win.processor.busy:
            win.processor.cancel()
        win.mark_saved()
        win.close()


def _image(path, colour="tomato"):
    image = QImage(12, 8, QImage.Format.Format_RGB32)
    image.fill(QColor(colour))
    fmt = "JPEG" if path.suffix.lower() in (".jpg", ".jpeg") else path.suffix[1:].upper()
    assert image.save(str(path), fmt), f"Test image encoder unavailable: {fmt}"
    return path


def _chooser(monkeypatch, path):
    """Keep the real dialog/filter wiring; replace only user file selection."""
    from serpentine3d import app as app_mod

    calls = []

    class ChosenDialog(QFileDialog):
        def __init__(self, parent, title, directory, filters):
            super().__init__(parent, title, directory, filters)
            calls.append((title, filters))

        def exec(self):
            return 1 if path else 0

        def selectedFiles(self):
            return [str(path)] if path else []

    monkeypatch.setattr(app_mod, "QFileDialog", ChosenDialog)
    return calls


def _menu_import(window):
    file_menu = next(action.menu() for action in window.menuBar().actions()
                     if action.text().replace("&", "").lower() == "file")
    action = next(action for action in file_menu.actions()
                  if action.text().replace("&", "").startswith("Import"))
    action.trigger()
    QApplication.processEvents()


def _drop(window, paths):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
    enter = QDragEnterEvent(QPoint(20, 20), Qt.DropAction.CopyAction, mime,
                            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(window.viewport, enter)
    assert enter.isAccepted(), "A supported image must be accepted over the viewport"
    drop = QDropEvent(QPointF(20, 20), Qt.DropAction.CopyAction, mime,
                      Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(window.viewport, drop)
    assert drop.isAccepted()
    assert drop.dropAction() == Qt.DropAction.CopyAction
    QApplication.processEvents()


def _start(window, monkeypatch, path, entry):
    calls = _chooser(monkeypatch, path if entry == "menu" else None)
    if entry == "menu":
        _menu_import(window)
    else:
        _drop(window, [path])
    assert len(calls) == (1 if entry == "menu" else 0), \
        "An already chosen/dropped image must not open another file chooser"
    return calls


def _place(window, first=(1.0, 2.0, 0.0), opposite=(13.0, 4.0, 0.0)):
    assert window.processor.busy, "Importing an image must start interactive picture placement"
    assert isinstance(window.processor.request, PointReq), \
        "The source is known already; request the first corner directly"
    window.processor.provide(first)
    assert isinstance(window.processor.request, PointReq)
    window.processor.provide(opposite)
    QApplication.processEvents()


def _encoded_image(plane):
    pending = [plane]
    while pending:
        value = pending.pop()
        if isinstance(value, (bytes, bytearray, memoryview)):
            return bytes(value)
        if isinstance(value, dict):
            pending.extend(value.values())
        elif isinstance(value, (list, tuple)):
            pending.extend(value)
    pytest.fail("The placed picture must embed image content, not depend on a path")


def test_file_import_offers_all_requested_picture_formats(window, monkeypatch):
    calls = _chooser(monkeypatch, None)
    _menu_import(window)
    assert len(calls) == 1
    filters = calls[0][1].lower()
    assert all(f"*{extension}" in filters for extension in IMAGE_EXTENSIONS), filters


@pytest.mark.parametrize("entry", ["menu", "drop"])
@pytest.mark.parametrize("extension", IMAGE_EXTENSIONS)
@pytest.mark.parametrize("uppercase", [False, True], ids=["lowercase", "uppercase"])
def test_images_join_the_current_drawing_as_portable_undoable_pictures(
        window, monkeypatch, tmp_path, entry, extension, uppercase):
    existing = window.scene.add(g.make_box((30, 0, 0), 2, 3, 4), name="Existing work")
    document = str(tmp_path / "Working drawing.serp")
    window.ctx.current_path = document
    window.mark_saved()
    source = _image(tmp_path / ("Reference with spaces" +
                                (extension.upper() if uppercase else extension)))

    _start(window, monkeypatch, source, entry)
    assert not window.scene.image_planes, "Placement must wait for the user's corners"
    _place(window)

    assert not window.processor.busy
    assert len(window.scene.image_planes) == 1
    assert window.scene.get(existing.id) is not None
    pictures = [obj for obj in window.scene.all() if obj.kind == "picture"]
    assert len(pictures) == 1 and window.scene.is_selectable(pictures[0].id)
    assert window.ctx.current_path == document
    assert window.dirty
    assert source.exists(), "Dropping copies image content and must retain the source"
    plane = window.scene.image_planes[0]
    assert plane["origin"] == pytest.approx([1, 2, 0])
    assert math.dist([0, 0, 0], plane["u"]) == pytest.approx(12)
    assert math.dist([0, 0, 0], plane["v"]) == pytest.approx(8), \
        "Height follows the image's 12:8 aspect ratio, not the second corner's height"
    encoded = _encoded_image(plane)
    image = QImage.fromData(encoded)
    assert not image.isNull() and image.width() == 12 and image.height() == 8

    saved = tmp_path / "Portable drawing.serp"
    native.save_scene(window.scene, str(saved))
    source.unlink()
    loaded = Scene()
    native.load_scene(loaded, str(saved))
    assert _encoded_image(loaded.image_planes[0]) == encoded
    assert not QImage.fromData(_encoded_image(loaded.image_planes[0])).isNull()

    assert window.history.can_undo
    window.history.undo()
    assert not window.scene.image_planes
    assert [obj.id for obj in window.scene.all()] == [existing.id]
    assert window.ctx.current_path == document
    assert not window.history.can_undo, "One picture must have exactly one undo step"


@pytest.mark.parametrize("entry", ["menu", "drop"])
@pytest.mark.parametrize("after_first_corner", [False, True])
def test_escape_cancels_unfinished_picture_without_empty_undo(
        window, monkeypatch, tmp_path, entry, after_first_corner):
    existing = window.scene.add(g.make_box((0, 0, 0), 2, 3, 4))
    window.mark_saved()
    source = _image(tmp_path / "cancel me.png")
    _start(window, monkeypatch, source, entry)
    assert isinstance(window.processor.request, PointReq)
    if after_first_corner:
        window.processor.provide((0.0, 0.0, 0.0))
    QTest.keyClick(window.command_line.input, Qt.Key.Key_Escape)
    QApplication.processEvents()
    assert not window.processor.busy
    assert not window.scene.image_planes
    assert [obj.id for obj in window.scene.all()] == [existing.id]
    assert not window.history.can_undo
    assert not window.dirty


@pytest.mark.parametrize("entry", ["menu", "drop"])
def test_corrupt_images_report_the_problem_without_changing_the_drawing(
        window, monkeypatch, tmp_path, entry):
    source = tmp_path / "broken picture.png"
    source.write_bytes(b"not image data")
    window.mark_saved()
    _start(window, monkeypatch, source, entry)
    assert not window.processor.busy
    assert not window.scene.image_planes
    assert not window.history.can_undo
    assert not window.dirty
    feedback = " ".join(window.test_messages).lower()
    assert "image" in feedback and any(word in feedback for word in
                                      ("read", "decode", "invalid", "corrupt")), feedback


def test_the_picture_command_chooser_also_offers_webp(window, monkeypatch, tmp_path):
    source = _image(tmp_path / "Picture.webp")
    calls = _chooser(monkeypatch, source)
    window.run_command("picture")
    assert len(calls) == 1
    assert "*.webp" in calls[0][1].lower()
    _place(window)
    assert len(window.scene.image_planes) == 1


@pytest.mark.parametrize("cancel_second", [False, True])
def test_multiple_dropped_images_get_placed_in_order_and_keep_completed_work(
        window, monkeypatch, tmp_path, cancel_second):
    first = _image(tmp_path / "First.png", "red")
    second = _image(tmp_path / "Second.webp", "blue")
    calls = _chooser(monkeypatch, None)
    _drop(window, [first, second])
    _place(window)
    assert len(window.scene.image_planes) == 1
    assert _encoded_image(window.scene.image_planes[0]) == first.read_bytes()
    assert isinstance(window.processor.request, PointReq), \
        "The next dropped image must be offered for placement, not silently lost"
    if cancel_second:
        QTest.keyClick(window.command_line.input, Qt.Key.Key_Escape)
        QApplication.processEvents()
        assert not window.processor.busy
        assert len(window.scene.image_planes) == 1
    else:
        _place(window, first=(20.0, 0.0, 0.0), opposite=(32.0, 4.0, 0.0))
        assert not window.processor.busy
        assert len(window.scene.image_planes) == 2
        assert _encoded_image(window.scene.image_planes[1]) == second.read_bytes()
    assert not calls, "Dropping multiple known paths must not ask the user to choose again"
    assert window.dirty
    undo_count = 0
    while window.history.can_undo:
        window.history.undo()
        undo_count += 1
    assert not window.scene.image_planes
    assert undo_count <= (1 if cancel_second else 2), "Cancellation added an empty undo step"
