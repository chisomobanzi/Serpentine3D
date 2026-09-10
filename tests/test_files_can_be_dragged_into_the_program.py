"""Dropping supported local files is another way to use File > Import."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from serpentine3d import fileio
from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene


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


def _drag(target, urls, *, modifiers=Qt.KeyboardModifier.NoModifier):
    """Deliver the same event sequence Qt sends for a file-manager drop.

    Sending to the viewport also tests Qt's delivery to its accepting parent;
    directly invoking a window handler would miss that user-facing boundary.
    """
    mime = QMimeData()
    mime.setUrls(urls)
    actions = Qt.DropAction.CopyAction | Qt.DropAction.MoveAction
    enter = QDragEnterEvent(QPoint(20, 20), actions, mime,
                            Qt.MouseButton.LeftButton, modifiers)
    # Qt events borrow their MIME data; retain it while callers inspect them
    # (including pytest's failure repr).
    enter._mime = mime
    QApplication.sendEvent(target, enter)
    if not enter.isAccepted():
        return enter, None
    move = QDragMoveEvent(QPoint(25, 25), actions, mime,
                          Qt.MouseButton.LeftButton, modifiers)
    QApplication.sendEvent(target, move)
    assert move.isAccepted(), "A supported file must remain accepted over the pane"
    drop = QDropEvent(QPointF(25, 25), actions, mime,
                      Qt.MouseButton.LeftButton, modifiers)
    drop._mime = mime
    QApplication.sendEvent(target, drop)
    return enter, drop


def _urls(*paths):
    return [QUrl.fromLocalFile(str(path)) for path in paths]


def _obj(path):
    path.write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
    return path


@pytest.mark.parametrize("target_name", ["window", "viewport"])
def test_dropped_geometry_joins_existing_work_and_can_be_undone(
        window, tmp_path, monkeypatch, target_name):
    existing = window.scene.add(g.make_box((30, 0, 0), 2, 3, 4),
                                name="Existing work")
    current_path = str(tmp_path / "My working document.serp")
    window.ctx.current_path = current_path
    window.mark_saved()
    obj = _obj(tmp_path / "A triangle.OBJ")
    step = tmp_path / "A solid.STEP"
    source = Scene()
    source.add(g.make_box((0, 0, 0), 5, 6, 7))
    fileio.export_file(source, str(step))
    messages = []
    monkeypatch.setattr(window.command_line, "echo", messages.append)
    target = window if target_name == "window" else window.viewport

    enter, drop = _drag(target, _urls(obj, step))

    assert enter.isAccepted(), "Dragging supported files must advertise an import"
    assert drop is not None and drop.isAccepted()
    assert drop.dropAction() == Qt.DropAction.CopyAction
    assert len(window.scene.all()) == 3
    assert window.scene.find_by_name("Existing work").id == existing.id
    assert g.volume(window.scene.find_by_name("Existing work").shape) == pytest.approx(24)
    assert any(o.kind == "mesh" for o in window.scene.all())
    assert any(g.volume(o.shape) == pytest.approx(210)
               for o in window.scene.all() if o.kind == "solid")
    assert window.ctx.current_path == current_path
    assert window.dirty
    assert any("Imported" in text for text in messages)
    assert obj.exists() and step.exists()

    # The UI may group a drop or checkpoint individual files. Both must undo
    # all added geometry without sacrificing the model already being edited.
    while window.history.can_undo:
        window.history.undo()
    assert [o.id for o in window.scene.all()] == [existing.id]
    assert window.ctx.current_path == current_path


@pytest.mark.parametrize("extension", sorted(
    fileio.IMPORT_EXTS - {".jpg", ".jpeg", ".png", ".webp"}))
@pytest.mark.parametrize("uppercase", [False, True], ids=["lowercase", "uppercase"])
def test_every_import_format_reaches_the_importer_with_its_local_path(
        window, tmp_path, monkeypatch, extension, uppercase):
    # Pictures need interactive placement; their dialog/drop behavior is
    # exercised in test_images_can_be_imported_as_pictures.py.
    suffix = extension.upper() if uppercase else extension
    path = tmp_path / ("Model with spaces" + suffix)
    path.write_bytes(b"format dispatch is checked at the import boundary")
    seen = []

    def record_import(scene, local_path, progress=None):
        seen.append((scene, local_path, progress))
        return 0

    monkeypatch.setattr(fileio, "import_file", record_import)
    enter, drop = _drag(window, _urls(path))

    assert enter.isAccepted(), f"File > Import supports {extension}; dragging must too"
    assert drop is not None and drop.isAccepted()
    assert len(seen) == 1
    assert seen[0][0] is window.scene
    assert seen[0][1] == str(path)
    assert callable(seen[0][2]), "Dropped imports need the usual progress/cancel feedback"


@pytest.mark.parametrize("kind", ["remote", "directory", "unsupported", "missing"])
def test_non_importable_drags_are_rejected(window, tmp_path, monkeypatch, kind):
    path = tmp_path / "not a model.obj"
    if kind == "remote":
        urls = [QUrl("https://example.com/model.obj")]
    elif kind == "directory":
        path.mkdir()
        urls = _urls(path)
    elif kind == "unsupported":
        path = tmp_path / "notes.txt"
        path.write_text("notes")
        urls = _urls(path)
    else:
        urls = _urls(path)
    seen = []
    monkeypatch.setattr(fileio, "import_file", lambda *args, **kwargs: seen.append(args))

    enter, drop = _drag(window, urls)

    assert not enter.isAccepted()
    assert drop is None
    assert not seen
    assert not window.history.can_undo


def test_a_mixed_drop_imports_local_supported_files_only(window, tmp_path, monkeypatch):
    valid = _obj(tmp_path / "triangle.obj")
    unsupported = tmp_path / "notes.txt"
    unsupported.write_text("notes")
    directory = tmp_path / "directory.obj"
    directory.mkdir()
    seen = []
    original = fileio.import_file

    def record_import(scene, path, progress=None):
        seen.append(path)
        return original(scene, path, progress=progress)

    monkeypatch.setattr(fileio, "import_file", record_import)
    enter, drop = _drag(window.viewport, [QUrl("https://example.com/remote.obj")]
                        + _urls(unsupported, directory, valid))

    assert enter.isAccepted()
    assert drop is not None and drop.isAccepted()
    assert seen == [str(valid)]
    assert len(window.scene.all()) == 1


def test_an_import_error_is_reported_and_does_not_lose_other_dropped_files(
        window, tmp_path, monkeypatch):
    broken = tmp_path / "broken.step"
    broken.write_text("broken file")
    valid = _obj(tmp_path / "good.obj")
    original = fileio.import_file
    warnings = []

    def import_with_one_error(scene, path, progress=None):
        if path == str(broken):
            raise ValueError("Cannot read broken.step")
        return original(scene, path, progress=progress)

    monkeypatch.setattr(fileio, "import_file", import_with_one_error)
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda parent, title, text: warnings.append((title, text)))
    enter, drop = _drag(window, _urls(broken, valid))

    assert enter.isAccepted()
    assert drop is not None and drop.isAccepted()
    assert len(window.scene.all()) == 1
    assert warnings and "Import" in warnings[0][0]
    assert "Cannot read broken.step" in warnings[0][1]
    assert window.history.can_undo
    window.history.undo()
    assert not window.scene.all()
    assert not window.history.can_undo, "Failed imports must not leave empty undo steps"


def test_a_drop_offering_move_still_copies_the_source(window, tmp_path):
    path = _obj(tmp_path / "keep me.obj")
    enter, drop = _drag(window, _urls(path),
                        modifiers=Qt.KeyboardModifier.ShiftModifier)

    assert enter.isAccepted()
    assert drop is not None and drop.isAccepted()
    assert drop.proposedAction() == Qt.DropAction.MoveAction
    assert drop.dropAction() == Qt.DropAction.CopyAction
    assert path.exists()
    assert len(window.scene.all()) == 1
