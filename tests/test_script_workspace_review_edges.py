"""Integration regressions found while reviewing the native script workspace."""

import pytest
from PySide6.QtWidgets import QApplication

from tests.test_scripts_are_editable_scene_previews import (
    BOX, _click, _editor, _find_draft, _preview, _save, win, windows,
)


def test_a_completed_ai_reply_does_not_take_focus_from_python(win):
    win.cfg.set("ai", "api_key", "test-key")
    workspace = win.command_workspace
    workspace.set_mode("ai")
    win.show()
    win.activateWindow()
    QApplication.processEvents()
    editor = _editor(win)
    editor.setFocus()
    assert QApplication.focusWidget() is editor

    workspace.assistant._on_finished("end_turn")

    assert QApplication.focusWidget() is editor
    assert workspace.mode == "ai"


def test_saving_a_pending_preview_keeps_its_output_identity(win, tmp_path, monkeypatch):
    _preview(win, BOX)
    _save(win, tmp_path / "box.py", monkeypatch)
    _click(win, "Keep")
    assert len(win.scene.all()) == 1

    _preview(win, BOX.replace("2, 3, 4", "5, 3, 4"))
    _click(win, "Keep")

    assert len(win.scene.all()) == 1, "Saving between Run and Keep must not duplicate later outputs"
    from serpentine3d.core import geometry
    assert round(geometry.volume(win.scene.all()[0].shape), 5) == 60


@pytest.mark.parametrize("restore", ["undo", "redo"])
def test_save_keeps_identity_when_undo_and_redo_restore_an_earlier_run(win, tmp_path, monkeypatch, restore):
    _preview(win, BOX)
    _click(win, "Keep")
    _preview(win, BOX)
    _click(win, "Keep")
    if restore == "redo":
        win.history.undo()
    _save(win, tmp_path / "box.py", monkeypatch)
    getattr(win.history, restore)()
    _preview(win, BOX)
    _click(win, "Keep")

    assert len(win.scene.all()) == 1


def test_normal_close_recovers_unsaved_python_and_file_identity(windows, tmp_path, monkeypatch):
    first = windows()
    _editor(first).setPlainText(BOX)
    path = tmp_path / "saved.py"
    _save(first, path, monkeypatch)
    saved_draft = BOX + "# Unsaved edits to an existing file\n"
    _editor(first).setPlainText(saved_draft)
    _click(first, "New")
    new_draft = "# An unsaved new script\nwidth = 27\n"
    _editor(first).setPlainText(new_draft)
    first.mark_saved()
    first.close()

    reopened = windows()

    assert _find_draft(reopened, new_draft).toPlainText() == new_draft
    _find_draft(reopened, saved_draft)
    _click(reopened, "Save")
    assert path.read_text(encoding="utf-8") == saved_draft

def test_saving_an_untitled_kept_script_marks_its_new_ownership_unsaved(win, tmp_path, monkeypatch):
    _preview(win, BOX)
    _click(win, "Keep")
    win.mark_saved()
    assert not win.dirty

    _save(win, tmp_path / "box.py", monkeypatch)

    assert win.dirty, "The drawing must save its changed link to the Python file"
    _preview(win, BOX)
    _click(win, "Keep")
    assert len(win.scene.all()) == 1
