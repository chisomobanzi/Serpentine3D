"""The Layers list is names and switches; a layer's look is edited in
Properties.

The list used to be a table: name, two columns with blank headers (a check
box and a colour), then Type and Print. Which box was which, and whether a
number was the screen width or the print width, meant reading the header,
the complaint that started the layers study. Now that Properties edits a
picked layer on labelled rows, the list keeps what is used every few
minutes: the name, an eye to show or hide, a lock, and the colour. The
switches draw as an eye and a padlock, so they need no header, and each
says in its tooltip what it is and what a click will do. A click anywhere
in a switch's cell flips it, not just on a box drawn at the cell's edge.

Lock had no switch at all before, only the importers set it.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from serpentine3d.core import geometry as g
from serpentine3d.core.history import History
from serpentine3d.core.scene import Scene
from serpentine3d.ui.layers_panel import LayersPanel

NAME_COL = 0
VISIBLE_COL = 1
LOCK_COL = 2
COLOR_COL = 3


@pytest.fixture(autouse=True)
def _no_colour_dialog(monkeypatch):
    """A click that lands on the swatch opens a modal colour dialog, which
    waits for a person the test run does not have. Stand in for it with a
    cancelled dialog, unless a test says otherwise."""
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QColorDialog
    monkeypatch.setattr(QColorDialog, "getColor",
                        staticmethod(lambda *args: QColor()))


def _panel():
    scene = Scene()
    history = History(scene)
    panel = LayersPanel(scene, history)
    panel.resize(300, 320)
    panel.show()
    ids = [scene.layers.create(name).id for name in "ABC"]
    scene.notify()
    QApplication.processEvents()
    return scene, history, panel, ids


def _item(panel, layer_id):
    for i in range(panel.tree.topLevelItemCount()):
        item = panel.tree.topLevelItem(i)
        if panel._layer_id(item) == layer_id:
            return item
    raise AssertionError(f"no row for {layer_id}")


def _click(panel, layer_id, column):
    """A real click in the middle of the cell, where a hand would aim."""
    tree = panel.tree
    rect = tree.visualItemRect(_item(panel, layer_id))
    x = tree.header().sectionViewportPosition(column) \
        + tree.header().sectionSize(column) // 2
    QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, rect.center().__class__(
                         x, rect.center().y()))
    QTest.qWait(50)
    QApplication.processEvents()


def _select(panel, *layer_ids):
    panel.tree.clearSelection()
    for layer_id in layer_ids:
        _item(panel, layer_id).setSelected(True)
    QApplication.processEvents()


def test_the_list_is_a_name_two_switches_and_a_colour_with_no_header():
    _s, _h, panel, _ids = _panel()

    assert panel.tree.columnCount() == 4
    assert panel.tree.isHeaderHidden()


def test_a_click_on_the_lock_locks_the_layer():
    scene, history, panel, (a, _b, _c) = _panel()

    _click(panel, a, LOCK_COL)

    assert scene.layers.get(a).locked
    history.undo()
    assert not scene.layers.get(a).locked


def test_a_locked_layers_objects_cannot_be_picked():
    scene, _h, panel, (a, _b, _c) = _panel()
    box = scene.add(g.make_box((0, 0, 0), 1, 1, 1), layer_id=a)
    scene.notify()

    _click(panel, a, LOCK_COL)

    assert not scene.is_selectable(box.id)

    _click(panel, a, LOCK_COL)

    assert scene.is_selectable(box.id)


def test_the_lock_on_a_picked_row_locks_every_picked_row_and_keeps_them():
    scene, history, panel, (a, b, c) = _panel()
    _select(panel, a, b)

    _click(panel, b, LOCK_COL)

    assert scene.layers.get(a).locked and scene.layers.get(b).locked
    assert not scene.layers.get(c).locked
    assert panel.picked_layer_ids() == {a, b}
    history.undo()
    assert not scene.layers.get(a).locked and not scene.layers.get(b).locked


def test_the_lock_on_an_unpicked_row_locks_only_that_one():
    scene, _h, panel, (a, _b, c) = _panel()
    _select(panel, a)

    _click(panel, c, LOCK_COL)

    assert scene.layers.get(c).locked
    assert not scene.layers.get(a).locked


def test_a_click_in_the_middle_of_the_eye_hides_the_layer():
    """The old box sat at the cell's left edge, and a click aimed at the
    middle of the cell toggled nothing."""
    scene, _h, panel, (a, _b, _c) = _panel()

    _click(panel, a, VISIBLE_COL)

    assert not scene.layers.get(a).visible

    _click(panel, a, VISIBLE_COL)

    assert scene.layers.get(a).visible


def test_each_switch_says_what_it_is_and_what_a_click_does():
    scene, _h, panel, (a, _b, _c) = _panel()

    assert _item(panel, a).toolTip(VISIBLE_COL) == "Visible: click to hide"
    assert _item(panel, a).toolTip(LOCK_COL) == "Unlocked: click to lock"

    _click(panel, a, VISIBLE_COL)
    _click(panel, a, LOCK_COL)

    assert _item(panel, a).toolTip(VISIBLE_COL) == "Hidden: click to show"
    assert _item(panel, a).toolTip(LOCK_COL) == \
        "Locked: click to unlock. Its objects cannot be picked."


def test_a_layer_under_a_locked_parent_says_so():
    scene, _h, panel, (a, _b, _c) = _panel()
    child = scene.layers.create("Inner", parent=a)
    scene.layers.set_locked(a, True)
    scene.notify()
    QApplication.processEvents()

    row = _item(panel, a).child(0)

    assert panel._layer_id(row) == child.id
    assert row.checkState(LOCK_COL) == Qt.CheckState.Unchecked
    assert row.toolTip(LOCK_COL) == \
        "Locked by A: click to lock this layer as well"


def test_the_colour_still_opens_from_its_swatch(monkeypatch):
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QColorDialog
    scene, _h, panel, (a, _b, _c) = _panel()
    monkeypatch.setattr(QColorDialog, "getColor",
                        staticmethod(lambda *args: QColor(255, 0, 0)))

    _click(panel, a, COLOR_COL)

    assert scene.layers.get(a).color == (1.0, 0.0, 0.0)
