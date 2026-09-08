"""Close Python documents through their tabs without losing source or geometry."""

from contextlib import contextmanager

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QTabBar, QTabWidget

from serpentine3d.api import SerpApi
from tests.test_scripts_are_editable_scene_previews import (
    BOX, _click, _control, _editor, _example, _history, _layout, _open,
    _pane, _preview, _save, _state, _wait, win, windows,
)


def _tabs(win):
    tabs = _pane(win).findChild(QTabWidget)
    assert tabs is not None, "Python documents need independently closable tabs"
    return tabs


def _sources(win):
    tabs = _tabs(win)
    return [tabs.widget(i).toPlainText() for i in range(tabs.count())]


def _close(win, editor):
    tabs = _tabs(win)
    index = tabs.indexOf(editor)
    assert index >= 0
    _layout(win)
    bar = tabs.tabBar()
    buttons = [bar.tabButton(index, side) for side in
               (QTabBar.ButtonPosition.LeftSide, QTabBar.ButtonPosition.RightSide)]
    buttons = [button for button in buttons if button is not None]
    assert tabs.tabsClosable() and buttons, (
        "Each Python document tab needs a visible close button")
    button = buttons[0]
    assert button.isVisibleTo(bar) and button.isEnabled()
    button.click()
    QApplication.processEvents()


@contextmanager
def _answer_dialogs(choice=QMessageBox.StandardButton.Cancel):
    """Exercise real native message boxes; also dismiss an optional error notice."""
    seen = []
    timer = QTimer()

    def answer():
        for dialog in QApplication.topLevelWidgets():
            if not isinstance(dialog, QMessageBox) or not dialog.isVisible():
                continue
            buttons = dialog.standardButtons()
            seen.append((dialog.text() + " " + dialog.informativeText(), buttons))
            for candidate in (choice, QMessageBox.StandardButton.Ok,
                              QMessageBox.StandardButton.Cancel,
                              QMessageBox.StandardButton.Discard):
                button = dialog.button(candidate)
                if button is not None:
                    button.click()
                    break
            else:
                dialog.reject()

    timer.timeout.connect(answer)
    timer.start(5)
    try:
        yield seen
    finally:
        timer.stop()


def _assert_save_choice(seen):
    required = (QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel)
    assert any(buttons & required == required for _, buttons in seen), (
        "Closing unsaved Python must offer Save, Discard and Cancel")


def test_closing_clean_and_empty_tabs_preserves_other_source_scene_and_undo(win, tmp_path, monkeypatch):
    _preview(win, BOX)
    _click(win, "Keep")
    _save(win, tmp_path / "kept.py", monkeypatch)
    clean = _editor(win)
    before = _state(win)
    _click(win, "New")
    empty = _editor(win)
    _click(win, "New")
    survivor = "# Keep this draft\nlength = 31\n"
    _editor(win).insertPlainText(survivor)

    with _answer_dialogs() as seen:
        _close(win, clean)
        _close(win, empty)

    assert not seen, "Unmodified saved files and empty drafts need no discard prompt"
    assert _sources(win) == [survivor]
    assert _editor(win).toPlainText() == survivor
    assert _state(win) == before and win.history.can_undo
    win.history.undo()
    assert win.scene.all() == []
    win.history.redo()
    assert _state(win) == before


def test_closing_the_last_blank_tab_leaves_a_usable_python_editor(win):
    with _answer_dialogs() as seen:
        _close(win, _editor(win))

    assert not seen and _sources(win) == [""]
    _preview(win, BOX)
    _click(win, "Keep")
    assert win.scene.find_by_name("Script box") is not None


@pytest.mark.parametrize("origin", ["typed", "example", "assistant", "modified_file"])
def test_cancel_keeps_unsaved_source_from_every_document_origin(win, tmp_path, monkeypatch, origin):
    if origin == "example":
        _example(win, "box")
    elif origin == "assistant":
        SerpApi(win).prepare_script(BOX, "Assistant box")
    elif origin == "modified_file":
        path = tmp_path / "existing.py"
        path.write_text(BOX, encoding="utf-8")
        _open(win, path, monkeypatch)
        _editor(win).insertPlainText("# Unsaved revision\n")
    else:
        _editor(win).insertPlainText(BOX)
    original = _sources(win)
    active = _editor(win)

    with _answer_dialogs(QMessageBox.StandardButton.Cancel) as seen:
        _close(win, active)

    _assert_save_choice(seen)
    assert _sources(win) == original and _editor(win) is active
    assert win.scene.all() == [] and not win.history.can_undo
    if origin == "modified_file":
        assert path.read_text(encoding="utf-8") == BOX


def test_save_on_close_writes_the_requested_tab_and_preserves_current_draft(win, tmp_path, monkeypatch):
    path = tmp_path / "edited.py"
    path.write_text(BOX, encoding="utf-8")
    _open(win, path, monkeypatch)
    target = _editor(win)
    target.insertPlainText("# Precise Unicode source: π\n")
    source = target.toPlainText()
    _click(win, "New")
    survivor = "# A different current draft\n"
    _editor(win).insertPlainText(survivor)

    with _answer_dialogs(QMessageBox.StandardButton.Save) as seen:
        _close(win, target)

    _assert_save_choice(seen)
    assert path.read_text(encoding="utf-8") == source
    assert source not in _sources(win)
    assert _editor(win).toPlainText() == survivor
    assert win.scene.all() == [] and not win.history.can_undo


@pytest.mark.parametrize("save_result", ["cancel", "failure"])
def test_canceled_or_failed_save_keeps_the_tab_and_exact_unsaved_source(win, tmp_path, monkeypatch, save_result):
    from PySide6.QtWidgets import QFileDialog

    source = "# My only copy\nsize = 14\n"
    _editor(win).insertPlainText(source)
    original = _editor(win)
    # A nonexistent parent gives a deterministic OSError even when running as root.
    path = "" if save_result == "cancel" else str(tmp_path / "missing" / "draft.py")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *args, **kwargs: (path, "Python (*.py)"))
    with _answer_dialogs(QMessageBox.StandardButton.Save) as seen:
        _close(win, original)

    _assert_save_choice(seen)
    assert _sources(win) == [source] and _editor(win) is original
    assert win.scene.all() == [] and not win.history.can_undo
    if save_result == "failure":
        notices = _history(win) + " ".join(text for text, _ in seen)
        assert "fail" in notices.lower() or "error" in notices.lower()


def test_discard_closes_only_source_and_closed_draft_stays_out_of_recovery(windows):
    first = windows()
    _preview(first, BOX)
    _click(first, "Keep")
    target = _editor(first)
    before = _state(first)
    _click(first, "New")
    survivor = "# Recover this remaining draft\nheight = 42\n"
    _editor(first).insertPlainText(survivor)

    with _answer_dialogs(QMessageBox.StandardButton.Discard) as seen:
        _close(first, target)

    _assert_save_choice(seen)
    assert _sources(first) == [survivor]
    assert _state(first) == before and first.history.can_undo
    first.mark_saved()
    first.close()
    reopened = windows()
    assert _sources(reopened) == [survivor], "Closed drafts must not return on recovery"


@pytest.mark.parametrize("activity", ["run", "preview"])
def test_run_or_preview_origin_cannot_close_but_an_unrelated_idle_tab_can(win, activity):
    if activity == "run":
        _editor(win).setPlainText(
            "import time\ndeadline = time.monotonic() + 4\n"
            "while time.monotonic() < deadline:\n    pass\n" + BOX)
        _click(win, "Run")
        assert _control(_pane(win), "Stop").isEnabled()
    else:
        _preview(win, BOX)
    origin = _editor(win)
    source = origin.toPlainText()
    before = _state(win)
    _click(win, "New")
    idle = _editor(win)
    with _answer_dialogs() as idle_notices:
        _close(win, idle)
    assert not idle_notices
    assert _sources(win) == [source]

    previous_history = _history(win)
    with _answer_dialogs(QMessageBox.StandardButton.Discard) as notices:
        _close(win, origin)

    assert _sources(win) == [source], "Resolve the draft's active run/preview before closing it"
    assert _state(win) == before and not win.history.can_undo
    pane = _pane(win)
    visible_labels = " ".join(label.text() for label in pane.findChildren(QLabel)
                              if label.isVisibleTo(pane))
    text = (_history(win)[len(previous_history):] + " " + visible_labels
            + " ".join(message for message, _ in notices)).lower()
    if activity == "run":
        assert "stop" in text, "Explain that the running script must be stopped first"
        assert _control(_pane(win), "Stop").isEnabled()
        _click(win, "Stop")
        _wait(lambda: not _control(_pane(win), "Stop").isEnabled(), "Stop did not finish")
    else:
        assert "keep" in text and "discard" in text, "Explain how to resolve the preview first"
        assert _control(_pane(win), "Keep").isEnabled()
        _click(win, "Keep")
        assert win.scene.find_by_name("Script box") is not None

    with _answer_dialogs(QMessageBox.StandardButton.Discard) as resolved_notices:
        _close(win, origin)
    _assert_save_choice(resolved_notices)
    assert _sources(win) == [""]
