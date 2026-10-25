"""Alt+A keeps every region, the Rhino chord for CurveBoolean's All.

The word All is on a clickable chip and can be typed, but picking regions is
mouse work and typing would be putting the mouse down. The chord goes
straight to the running command, and only there: it answers the All keyword
when the prompt offers one, and does nothing when no command is asking.
"""

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from serpentine3d.app import MainWindow
from serpentine3d.core import geometry as g


@pytest.fixture
def window():
    win = MainWindow()
    yield win
    win.processor.cancel()
    # closeEvent asks before closing a dirty scene, and a modal question
    # box in a headless run has nobody to answer it
    win.mark_saved()
    win.close()


def _circle(scene, x, y, r):
    return scene.add(g.make_circle((x, y, 0.0), r))


def _alt_a():
    return QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A,
                     Qt.KeyboardModifier.AltModifier, "a")


def test_alt_a_keeps_every_region(window):
    a = _circle(window.scene, 0.0, 0.0, 2.0)
    b = _circle(window.scene, 2.0, 0.0, 2.0)
    window.selection.set([a.id, b.id])
    window.run_command("curveboolean")
    assert window.processor.busy
    window.keyPressEvent(_alt_a())
    window.processor.provide_text("")     # Enter: finish
    curves = [o for o in window.scene.all() if o.kind == "curve"]
    assert len(curves) == 1, "Alt+A kept nothing, or the Enter cancelled"
    assert a.id not in window.scene.objects


def test_alt_a_with_no_command_asking_changes_nothing(window):
    """The chord is the running command's answer, not a global command."""
    a = _circle(window.scene, 0.0, 0.0, 2.0)
    window.selection.set([a.id])
    window.keyPressEvent(_alt_a())
    assert not window.processor.busy
    assert window.scene.get(a.id) is not None


def test_alt_a_reaches_the_command_with_the_command_line_focused(window):
    """The chord works right where the command was just typed from — the
    line edit lets Alt+A bubble to the main window instead of eating it."""
    a = _circle(window.scene, 0.0, 0.0, 2.0)
    b = _circle(window.scene, 2.0, 0.0, 2.0)
    window.selection.set([a.id, b.id])
    window.run_command("curveboolean")
    assert window.processor.busy
    window.command_line.setFocus()
    # deliver the way Qt does: to the focused widget, which ignores it
    # and lets it climb to the main window
    QApplication.instance().notify(window.command_line, _alt_a())
    window.processor.provide_text("")     # Enter: finish
    curves = [o for o in window.scene.all() if o.kind == "curve"]
    assert len(curves) == 1, "Alt+A never reached the command"
    assert a.id not in window.scene.objects
