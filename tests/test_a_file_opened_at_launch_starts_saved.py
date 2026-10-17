"""A file opened at launch starts saved, like one opened from File → Open.

Double-clicking a .serp, `serp3d file.serp` and a scale restart all hand
the document over on the command line. That path used to leave the window
dirty, so closing a document nobody had touched asked to save it. A restart
handoff is the one exception: its work really is unsaved, so it stays dirty.
"""

import os

import pytest

from serpentine3d import app as app_mod
from serpentine3d.core import geometry as g
from serpentine3d.fileio import native
from serpentine3d.utils import autosave as autosave_mod


@pytest.fixture
def window():
    from serpentine3d.app import MainWindow
    w = MainWindow()
    yield w
    w.mark_saved()
    w.close()


def _saved_box(window, path):
    window.scene.add(g.make_box((0, 0, 0), 1, 1, 1))
    native.save_scene(window.scene, path)
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
        window, tmp_path, monkeypatch):
    handoff = str(tmp_path / "restart-handoff.serp")
    monkeypatch.setattr(autosave_mod, "HANDOFF_PATH", handoff)
    _saved_box(window, handoff)
    origin = str(tmp_path / "doc.serp")
    app_mod._open_launch_args(window, [handoff, "--restart-origin", origin])
    assert len(window.scene.all()) == 1
    assert window.ctx.current_path == origin
    assert window.dirty, "the handed-over work was never saved"
    assert not os.path.exists(handoff), "the handoff is spent on arrival"
