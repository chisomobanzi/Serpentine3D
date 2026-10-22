"""Delete in an empty command line deletes what is picked.

Typing a command leaves the keyboard in the command line, and the text box
claimed Delete for itself even with nothing in it, so the window's Delete
never heard it: Ctrl+A then Delete picked everything and deleted nothing.
An empty prompt already handed Home, End and the Ctrl edit keys to the
model, and Delete now goes with them. With text typed, Delete still edits
the text, and the keyboard stays in the command line either way.
"""

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from serpentine3d.core import geometry as g


@pytest.fixture
def window():
    """A shown window, so its Delete shortcut is live. Deleted afterwards,
    not just closed: a closed window keeps the keyboard focus it had, and
    the next test's window takes a field in it for one being typed in."""
    from serpentine3d.app import MainWindow
    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    QApplication.processEvents()
    yield w
    w.mark_saved()
    w.close()
    w.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _typing_in_the_command_line(w):
    w.command_line.focus()
    QApplication.processEvents()
    return w.command_line.input


def test_delete_in_an_empty_command_line_deletes_the_pick(window):
    box = window.scene.add(g.make_box((0, 0, 0), 5, 5, 5))
    window.selection.set([box.id])
    window.command_line.focus()
    QApplication.processEvents()
    QTest.keyClick(window.command_line.input, Qt.Key.Key_Delete)
    QApplication.processEvents()
    assert window.scene.get(box.id) is None


def test_on_a_sheet_it_deletes_the_paper_pick_not_the_model_one(window):
    from serpentine3d.core.layout import Layout, PaperObject
    box = window.scene.add(g.make_box((0, 0, 0), 5, 5, 5))
    window.selection.set([box.id])
    sheet = Layout(name="Sheet1")
    sheet.objects.append(PaperObject(
        shape=g.make_line((10.0, 10.0, 0.0), (90.0, 10.0, 0.0)), name="Rule"))
    window.scene.layouts += [sheet]
    window.switch_space(sheet.id)
    QApplication.processEvents()
    window.viewport.layout_view.selected = [("object", sheet.objects[0])]
    QTest.keyClick(_typing_in_the_command_line(window), Qt.Key.Key_Delete)
    QApplication.processEvents()
    now = next(s for s in window.scene.layouts if s.id == sheet.id)
    assert now.objects == [], "the paper pick is still on the sheet"
    assert window.scene.get(box.id) is not None, "the model pick went too"


def test_with_text_typed_delete_still_edits_the_text(window):
    box = window.scene.add(g.make_box((0, 0, 0), 5, 5, 5))
    window.selection.set([box.id])
    field = _typing_in_the_command_line(window)
    field.setText("circle")
    field.setCursorPosition(0)
    QTest.keyClick(field, Qt.Key.Key_Delete)
    QApplication.processEvents()
    assert field.text() == "ircle"
    assert window.scene.get(box.id) is not None


def test_with_nothing_picked_the_keyboard_stays_in_the_command_line(window):
    window.scene.add(g.make_box((0, 0, 0), 5, 5, 5))
    field = _typing_in_the_command_line(window)
    QTest.keyClick(field, Qt.Key.Key_Delete)
    QApplication.processEvents()
    assert QApplication.focusWidget() is field, (
        f"the keyboard went to {type(QApplication.focusWidget()).__name__}")
