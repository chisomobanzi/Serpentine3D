"""Text picked out in the command history is what ++ctrl+c++ copies.

You could always drag a selection across the echoed history, and it lit up
like a selection, but nothing would take it. Typing goes to the command
line wherever you clicked, which is what a CAD app should do, so the
history never holds the keyboard focus and never saw the key. ++ctrl+c++
reached the Edit menu's Copy instead, which copies geometry, and with no
object picked it quietly did nothing at all. An error message you can see
but cannot copy is not much use when you are pasting it into a bug report.

Copy now asks the history first and the drawing second, and a selection
left over in the history is dropped the moment you go back to a pane, so
the next ++ctrl+c++ over a picked object copies the object.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from serpentine3d.core import geometry as g


@pytest.fixture
def win(tmp_path, monkeypatch):
    monkeypatch.setenv("SERP3D_CONFIG", str(tmp_path / "settings.json"))
    monkeypatch.setenv("SERP3D_NO_RECOVER", "1")
    from serpentine3d.app import MainWindow
    w = MainWindow()
    QApplication.clipboard().clear()
    yield w
    w.mark_saved()
    w.close()


def _select_history(win, text):
    """Echo a line and leave it picked out, as a drag across it would."""
    win.command_line.echo(text)
    echo = win.command_line.echo_view
    cur = echo.textCursor()
    cur.movePosition(cur.MoveOperation.End)
    cur.movePosition(cur.MoveOperation.StartOfBlock,
                     cur.MoveMode.KeepAnchor)
    echo.setTextCursor(cur)
    return echo


def test_ctrl_c_copies_the_line_you_picked_out_of_the_history(win):
    _select_history(win, "Created Curve 01 (r=25).")
    win._copy_selected()
    assert QApplication.clipboard().text() == "Created Curve 01 (r=25)."


def test_more_than_one_line_comes_back_as_lines(win):
    """A text cursor hands back paragraph separators, not newlines, so
    two copied lines would otherwise paste as one long one."""
    win.command_line.echo("Created Solid 01.")
    echo = _select_history(win, "Created Curve 01 (r=25).")
    cur = echo.textCursor()
    cur.setPosition(0)
    cur.movePosition(cur.MoveOperation.End, cur.MoveMode.KeepAnchor)
    echo.setTextCursor(cur)
    win._copy_selected()
    got = QApplication.clipboard().text()
    assert " " not in got
    assert got.splitlines()[-2:] == ["Created Solid 01.",
                                     "Created Curve 01 (r=25)."]


def test_copying_geometry_still_works_with_nothing_picked_in_the_history(win):
    win.scene.add(g.make_box((0, 0, 0), 1, 1, 1))
    win.selection.select_all()
    win._copy_selected()
    kind, items = win._clipboard
    assert kind == "model" and len(items) == 1
    assert not QApplication.clipboard().text()


def test_a_selection_left_in_the_history_does_not_go_stale(win):
    """Otherwise the one drag you did across the history an hour ago
    would still be what Copy meant, every time, for the rest of the
    session."""
    _select_history(win, "Created Curve 01 (r=25).")
    win.viewport.setFocus()
    QApplication.sendEvent(win.viewport, QMouseEvent(
        QEvent.Type.MouseButtonPress, QPoint(10, 10).toPointF(),
        win.viewport.mapToGlobal(QPoint(10, 10)).toPointF(),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier))
    assert not win.command_line.echo_view.textCursor().hasSelection()

    win.scene.add(g.make_box((0, 0, 0), 1, 1, 1))
    win.selection.select_all()
    win._copy_selected()
    assert win._clipboard[0] == "model"


def test_new_output_drops_the_selection_too(win):
    """The history scrolls to the end as each line lands, which is the
    same thing said another way, but it is worth being sure of."""
    _select_history(win, "Created Curve 01 (r=25).")
    win.command_line.echo("Created Solid 02.")
    assert not win.command_line.echo_view.textCursor().hasSelection()
