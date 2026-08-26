"""Pressing Space at the command line does what Enter does.

Rhino users keep one hand on the mouse and hit the Spacebar with the other
to run the command they typed, commit a value, or repeat the last command.
The one place Space must stay a space is a prompt asking for free text —
a layer called "Ground floor" needs the space between its words.
"""

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from serpentine3d.app import MainWindow
from serpentine3d.commands.base import PointReq, TextReq


def _window():
    w = MainWindow()
    w.resize(1200, 800)
    QApplication.processEvents()
    w.command_line.focus()
    return w


def _space(w):
    QTest.keyClick(w.command_line.input, Qt.Key.Key_Space)


def _start_line_with_enter(w):
    """Set-up only: Enter is the way that already works."""
    QTest.keyClicks(w.command_line.input, "line")
    QTest.keyClick(w.command_line.input, Qt.Key.Key_Return)
    assert w.processor.busy and w.processor.active.name == "line"


def test_space_after_a_command_name_runs_it():
    w = _window()
    QTest.keyClicks(w.command_line.input, "line")
    _space(w)
    assert w.processor.busy, "the command should have started"
    assert w.processor.active.name == "line"
    assert isinstance(w.processor.request, PointReq), \
        "line should now be asking for its first point"
    assert w.command_line.input.text() == "", \
        "no space character should be left behind in the input"


def test_space_commits_a_typed_point_mid_command():
    w = _window()
    _start_line_with_enter(w)
    QTest.keyClicks(w.command_line.input, "0,0,0")
    _space(w)
    assert len(w.processor.picked_points) == 1, \
        "the typed point should have been taken as the first point"
    assert w.command_line.input.text() == ""


def test_space_on_an_empty_prompt_repeats_the_last_command():
    w = _window()
    _start_line_with_enter(w)
    QTest.keyClick(w.command_line.input, Qt.Key.Key_Escape)   # give it up
    assert not w.processor.busy
    assert w.processor.last_command == "line"
    _space(w)
    assert w.processor.busy and w.processor.active.name == "line", \
        "Space on an idle prompt should repeat the last command, like Enter"


def test_space_is_a_space_when_a_command_asks_for_text():
    """`layer` > New asks for a name; a two-word name has to be typeable."""
    w = _window()
    w.processor.run("layer")
    w.processor.provide_text("New")
    assert isinstance(w.processor.request, TextReq), \
        "the test proves nothing unless a free-text prompt is up"
    QTest.keyClicks(w.command_line.input, "Ground")
    _space(w)
    QTest.keyClicks(w.command_line.input, "floor")
    assert w.command_line.input.text() == "Ground floor"
    assert isinstance(w.processor.request, TextReq), \
        "Space must not have submitted the half-typed name"
    QTest.keyClick(w.command_line.input, Qt.Key.Key_Return)
    assert w.scene.layers.find_by_name("Ground floor") is not None
