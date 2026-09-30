"""Ctrl+V pastes text into the command line (issue #37).

An empty command line hands Ctrl+C, Ctrl+V and Ctrl+A to the window, so
that they copy, paste and select objects. Paste only knew the program's own
object clipboard, so text on the system clipboard, a command name or a
coordinate copied from anywhere, could not be pasted into an empty command
line with the keyboard at all; right-click Paste worked, and Ctrl+V did too
once something had been typed.

Paste now does what Rhino's does: text on the clipboard goes to the command
line, and objects are pasted when objects were copied last. Copying objects
takes the system clipboard over, in words saying what was copied, so an old
bit of text cannot win against objects copied after it.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
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


def _ctrl(win, key):
    """The keys pressed with the command line holding the keyboard."""
    QTest.keyClick(win.command_line.input, key,
                   Qt.KeyboardModifier.ControlModifier)
    QApplication.processEvents()


def _one_box(win):
    box = win.scene.add(g.make_box((0, 0, 0), 5, 5, 5), name="Box")
    win.selection.set([box.id])
    return box


def test_ctrl_v_pastes_clipboard_text_into_an_empty_command_line(win):
    QApplication.clipboard().setText("circle")
    before = len(win.scene.objects)

    _ctrl(win, Qt.Key.Key_V)

    assert win.command_line.input.text() == "circle"
    assert len(win.scene.objects) == before


def test_objects_copied_after_some_text_still_paste_as_objects(win):
    QApplication.clipboard().setText("text copied earlier")
    _one_box(win)
    _ctrl(win, Qt.Key.Key_C)
    before = len(win.scene.objects)

    _ctrl(win, Qt.Key.Key_V)

    assert len(win.scene.objects) == before + 1
    assert win.command_line.input.text() == ""


def test_text_copied_after_objects_is_what_pastes(win):
    _one_box(win)
    _ctrl(win, Qt.Key.Key_C)
    QApplication.clipboard().setText("10,20,0")
    before = len(win.scene.objects)

    _ctrl(win, Qt.Key.Key_V)

    assert win.command_line.input.text() == "10,20,0"
    assert len(win.scene.objects) == before


def test_the_edit_menu_paste_follows_the_same_rule(win):
    QApplication.clipboard().setText("line")

    win._paste()

    assert win.command_line.input.text() == "line"


def test_in_assistant_mode_the_text_goes_to_the_assistant(win):
    win.command_workspace.set_mode("ai")
    QApplication.clipboard().setText("make a box")

    win._paste()

    assert win.command_workspace.assistant.input.toPlainText() == "make a box"
    assert win.command_line.input.text() == ""


def test_a_clipboard_manager_keeping_only_the_words_still_pastes_objects(win):
    """Linux clipboard managers can take a copy over and keep only its
    text; the words a copy of objects leaves are what is recognised."""
    _one_box(win)
    _ctrl(win, Qt.Key.Key_C)
    words = QApplication.clipboard().text()
    QApplication.clipboard().setText(words)     # as a manager re-owns it
    before = len(win.scene.objects)

    _ctrl(win, Qt.Key.Key_V)

    assert len(win.scene.objects) == before + 1
    assert win.command_line.input.text() == ""


def test_quitting_after_copying_objects_does_not_crash(tmp_path):
    """A QMimeData made in Python and left on the clipboard segfaults
    PySide6 as the interpreter shuts down, which took CI's whole test run
    down with exit 139 and would have crashed the program on the way out
    every time objects had been copied. Run in its own process, since the
    crash only comes at the very end."""
    import os
    import subprocess
    import sys
    script = tmp_path / "copy_and_quit.py"
    script.write_text(
        "from PySide6.QtWidgets import QApplication\n"
        "app = QApplication([])\n"
        "from serpentine3d.app import MainWindow\n"
        "from serpentine3d.core import geometry as g\n"
        "w = MainWindow()\n"
        "box = w.scene.add(g.make_box((0, 0, 0), 1, 1, 1), name='Box')\n"
        "w.selection.set([box.id])\n"
        "w._copy_selected()\n"
        "assert 'copied in Serpentine3D' in QApplication.clipboard().text()\n"
        "w.mark_saved()\n"
        "w.close()\n")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen",
               SERP3D_CONFIG=str(tmp_path / "settings.json"),
               SERP3D_NO_RECOVER="1", SERP3D_RPC_PORT="0",
               PYTHONPATH=os.pathsep.join(
                   [os.getcwd(), os.environ.get("PYTHONPATH", "")]))
    done = subprocess.run([sys.executable, str(script)], env=env,
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, (done.returncode, done.stderr[-2000:])
