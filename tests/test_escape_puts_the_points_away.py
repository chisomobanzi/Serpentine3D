"""Escape backs out of point editing, the way it backs out of everything else.

Escape gave up whatever was in hand: a running command, or the selection. It
had nothing to say about control points, which only F11 could put away, so a
drawing covered in markers stayed covered until you remembered the key.

One rung at a time, most recent first: a running command, then the points,
then the selection. And putting the points away lets go of the ones being
held, because a held point is what `move` moves and what the gumball stands
on, and neither should be working on markers nobody can see.
"""

import pytest

from serpentine3d.core import geometry as g

CORNERS = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 10.0, 0.0)]


@pytest.fixture
def win(monkeypatch, tmp_path):
    monkeypatch.setenv("SERP3D_CONFIG", str(tmp_path / "s.json"))
    monkeypatch.setenv("SERP3D_NO_RECOVER", "1")
    from serpentine3d.app import MainWindow
    w = MainWindow()
    yield w
    w.mark_saved()
    w.close()


def _points_on(w):
    """A curve with its control points showing, as F10 leaves things."""
    obj = w.scene.add(g.make_polyline(CORNERS))
    w.selection.set([obj.id])
    w.processor.run("pointson")
    assert obj.id in w.scene.cv_enabled
    return obj


# ------------------------------------------------------------- the ladder

def test_escape_puts_the_control_points_away(win):
    _points_on(win)
    win._cancel()
    assert not win.scene.cv_enabled


def test_the_escape_key_in_a_pane_is_what_does_it(win):
    """The key itself, not only the handler it is wired to."""
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    _points_on(win)
    win.viewport.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress,
                                         Qt.Key.Key_Escape,
                                         Qt.KeyboardModifier.NoModifier))
    assert not win.scene.cv_enabled


def test_escape_keeps_the_selection_while_the_points_are_showing(win):
    """One rung per press: the points go first, what is selected stays."""
    obj = _points_on(win)
    win.selection.set([obj.id])
    win._cancel()
    assert win.selection.ids == [obj.id]


def test_a_second_escape_lets_go_of_the_object(win):
    obj = _points_on(win)
    win.selection.set([obj.id])
    win._cancel()
    win._cancel()
    assert win.selection.ids == []


def test_escape_still_clears_the_selection_with_no_points_showing(win):
    obj = win.scene.add(g.make_polyline(CORNERS))
    win.selection.set([obj.id])
    win._cancel()
    assert win.selection.ids == []


def test_a_running_command_is_given_up_first(win):
    """The command is the newer thing in hand, and the points outlive it."""
    _points_on(win)
    win.processor.run("move")
    assert win.processor.busy
    win._cancel()
    assert not win.processor.busy
    assert win.scene.cv_enabled, "it threw the points away as well"


# ------------------------------------------------- and lets go of the points

def test_the_points_it_hides_are_no_longer_held(win):
    """F11 as much as Escape: hiding a point is letting go of it."""
    obj = _points_on(win)
    win.selection.set_subobjects([(obj.id, "cv", 1)])
    win.processor.run("pointsoff")
    assert win.selection.subobjects == []


def test_move_asks_which_objects_again_once_the_points_are_away(win):
    """Otherwise it would quietly move corners nobody can see."""
    obj = _points_on(win)
    win.selection.set_subobjects([(obj.id, "cv", 1)])
    win._cancel()
    win.processor.run("move")
    assert "object" in win.processor.request.prompt.lower()


def test_sub_objects_that_are_not_points_are_left_alone(win):
    """A held face is not a marker, and nothing was hidden from it."""
    obj = _points_on(win)
    win.selection.set_subobjects([(obj.id, "face", 0)])
    win._cancel()
    assert win.selection.subobjects == [(obj.id, "face", 0)]
