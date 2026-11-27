"""Enter pressed while a viewport has the keyboard answers the running
command, as it does in the command line.

Clicking in a viewport gives it the keyboard. Picking the objects to move
is such a click, so the Enter that ends the picking arrives at the viewport,
which passes it on to the main window. The main window only used Enter to
repeat the last command when none was running, and dropped it otherwise:
Move sat at "Select objects to move" until the user clicked back into the
command line or right-clicked.
"""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from serpentine3d.app import MainWindow
from serpentine3d.commands.base import PointReq, SelectReq
from serpentine3d.core import geometry as g


@pytest.fixture
def window():
    window = MainWindow()
    window.resize(1200, 800)
    QApplication.processEvents()
    yield window
    window.processor.cancel()
    window.mark_saved()
    window.close()


def _enter_in_the_viewport(window, key=Qt.Key.Key_Return):
    pane = window.viewport
    pane.setFocus()
    QTest.keyClick(pane, key)


@pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Enter],
                         ids=["return", "keypad-enter"])
@pytest.mark.parametrize("command", ["move", "copy", "rotate"])
def test_enter_in_the_viewport_ends_the_picking(window, key, command):
    box = window.scene.add(g.make_box((0, 0, 0), 10, 10, 10))
    window.scene.add(g.make_box((20, 0, 0), 5, 5, 5))
    window.command_line.run_command(command)
    assert isinstance(window.processor.request, SelectReq)
    window.processor.click_object(box.id)

    _enter_in_the_viewport(window, key)

    assert window.processor.busy
    assert isinstance(window.processor.request, PointReq), (
        "Enter in the viewport must end the picking, as in the command line")


def test_enter_in_the_viewport_finishes_a_prompt_that_takes_enter(window):
    box = window.scene.add(g.make_box((0, 0, 0), 10, 10, 10))
    window.selection.set([box.id])
    window.command_line.run_command("copy")
    window.processor.provide((0, 0, 0))
    window.processor.provide((30, 0, 0))
    assert "Enter to finish" in window.processor.request.prompt

    _enter_in_the_viewport(window)

    assert not window.processor.busy
    assert len(window.scene.all()) == 2


def test_enter_in_the_viewport_uses_what_was_typed(window):
    box = window.scene.add(g.make_box((0, 0, 0), 10, 10, 10))
    window.selection.set([box.id])
    window.command_line.run_command("move")
    window.processor.provide((0, 0, 0))
    window.command_line.input.setText("5,0,0")

    _enter_in_the_viewport(window)

    assert not window.processor.busy
    lo, _hi = g.bbox(window.scene.get(box.id).shape)
    assert lo == pytest.approx((5, 0, 0), abs=1e-6)


def test_enter_in_the_viewport_still_repeats_the_last_command(window):
    window.command_line.run_command("box")
    window.processor.cancel()
    assert not window.processor.busy

    _enter_in_the_viewport(window)

    assert window.processor.busy
