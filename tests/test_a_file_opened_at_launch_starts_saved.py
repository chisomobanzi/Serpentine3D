"""A file opened at launch starts saved, like one opened from File → Open.

Double-clicking a .serp, `serp3d file.serp` and a scale restart all hand
the document over on the command line. That path used to leave the window
dirty, so closing a document nobody had touched asked to save it. A restart
handoff is the one exception: its work really is unsaved, so it stays dirty.
And a handoff no session took up (the restart never got going) is offered
back at the next launch rather than left in the autosave folder.
"""

import pytest
from PySide6.QtWidgets import QMessageBox

from serpentine3d import app as app_mod
from serpentine3d.core import geometry as g
from serpentine3d.fileio import native


@pytest.fixture
def window(monkeypatch):
    monkeypatch.delenv("SERP3D_NO_RECOVER", raising=False)
    from serpentine3d.app import MainWindow
    w = MainWindow()
    yield w
    w.autosave.discard_handoff()
    w.mark_saved()
    w.close()


def _saved_box(window, path):
    window.scene.add(g.make_box((0, 0, 0), 1, 1, 1))
    native.save_scene(window.scene, path)
    window.scene.clear()
    window.mark_saved()
    return path


def _handed_over(window, doc_path):
    """What restart_app leaves behind: one box, handed over."""
    window.scene.add(g.make_box((0, 0, 0), 1, 1, 1))
    path = window.autosave.hand_over(doc_path)
    window.scene.clear()
    window.mark_saved()
    return path


def test_a_file_opened_at_launch_is_not_marked_unsaved(window, tmp_path):
    path = _saved_box(window, str(tmp_path / "doc.serp"))
    app_mod._open_launch_args(window, [path])
    assert len(window.scene.all()) == 1
    assert window.ctx.current_path == path
    assert not window.dirty, "nothing changed since it was opened"


def test_a_restart_handoff_comes_back_unsaved_under_its_old_name(
        window, tmp_path):
    origin = str(tmp_path / "doc.serp")
    handoff = _handed_over(window, origin)
    app_mod._open_launch_args(window, [handoff])
    assert len(window.scene.all()) == 1
    assert window.ctx.current_path == origin
    assert window.dirty, "the handed-over work was never saved"
    assert window.autosave.waiting_handoff() is None, "spent on arrival"


def _answer(monkeypatch, button):
    asked = []

    def question(*args, **kwargs):
        asked.append(args[2])
        return button
    monkeypatch.setattr(app_mod.QMessageBox, "question", question)
    return asked


def test_a_handoff_left_behind_is_offered_back(window, tmp_path, monkeypatch):
    origin = str(tmp_path / "doc.serp")
    _handed_over(window, origin)
    asked = _answer(monkeypatch, QMessageBox.StandardButton.Yes)
    window.offer_handoff()
    assert len(asked) == 1 and origin in asked[0]
    assert len(window.scene.all()) == 1
    assert window.ctx.current_path == origin
    assert window.dirty
    assert window.autosave.waiting_handoff() is None


def test_a_declined_handoff_is_thrown_away(window, tmp_path, monkeypatch):
    _handed_over(window, str(tmp_path / "doc.serp"))
    _answer(monkeypatch, QMessageBox.StandardButton.No)
    window.offer_handoff()
    assert window.scene.all() == []
    assert window.autosave.waiting_handoff() is None, "asked once, not again"


def test_a_restart_that_took_its_handoff_leaves_nothing_to_offer(
        window, tmp_path, monkeypatch):
    handoff = _handed_over(window, str(tmp_path / "doc.serp"))
    app_mod._open_launch_args(window, [handoff])
    asked = _answer(monkeypatch, QMessageBox.StandardButton.Yes)
    window.offer_handoff()
    assert asked == []
