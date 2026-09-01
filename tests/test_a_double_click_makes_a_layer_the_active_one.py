"""Picking a layer and making it the one you draw on are two gestures.

A plain click on a layer's name used to make it the active layer, so a
user who clicked three layers in turn to switch them off left the last one
active and drew their next curve on it without meaning to: "the active
layer changes when you just happen to select it". Picking a layer is for
saying which rows a button or a box applies to, and it should say nothing
about where new geometry lands.

So the active layer changes on a double-click, the way a Rhino user
expects, and a single click only picks. That takes the name cell's old
double-click, which opened a rename, so renaming moved to the row menu.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractItemDelegate, QApplication, QLineEdit

from serpentine3d.core.history import History
from serpentine3d.core.layers import DEFAULT_LAYER_ID
from serpentine3d.core.scene import Scene
from serpentine3d.ui.layers_panel import LayersPanel

NAME_COL = 0


def _panel():
    scene = Scene()
    panel = LayersPanel(scene, History(scene))
    panel.resize(400, 300)
    panel.show()
    QApplication.processEvents()
    return scene, panel


def _layers(scene, panel):
    """Walls and Roof, on top of the default layer."""
    walls = scene.layers.create("Walls")
    roof = scene.layers.create("Roof")
    scene.notify()
    QApplication.processEvents()
    return walls, roof


def _rows(panel) -> dict:
    out = {}
    stack = [panel.tree.topLevelItem(i)
             for i in range(panel.tree.topLevelItemCount())]
    while stack:
        item = stack.pop()
        out[panel._layer_id(item)] = item
        stack.extend(item.child(i) for i in range(item.childCount()))
    return out


def _point(panel, layer_id, column=NAME_COL):
    index = panel.tree.indexFromItem(_rows(panel)[layer_id], column)
    return panel.tree.visualRect(index).center()


def _click(panel, layer_id, column=NAME_COL):
    QTest.mouseClick(panel.tree.viewport(), Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier,
                     _point(panel, layer_id, column))
    QTest.qWait(50)
    QApplication.processEvents()


def _double_click(panel, layer_id, column=NAME_COL):
    """Two clicks on a cell, delivered the way Qt delivers them.

    Not `QTest.mouseDClick`, which leaves the tree with two plain clicks
    here and no double-click at all: the events go in by hand, as the
    drop-down tests already do it.
    """
    point = QPointF(_point(panel, layer_id, column))
    for typ in (QEvent.Type.MouseButtonPress,
                QEvent.Type.MouseButtonRelease,
                QEvent.Type.MouseButtonDblClick,
                QEvent.Type.MouseButtonRelease):
        QApplication.sendEvent(panel.tree.viewport(), QMouseEvent(
            typ, point, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier))
    QTest.qWait(50)
    QApplication.processEvents()


def _editor(panel):
    return panel.tree.findChild(QLineEdit)


def _close_editor(panel, editor, layer_id):
    """End the edit, the way clicking away from the cell would.

    No test may leave an editor open: the panel is dropped when the test
    returns, but Qt still holds the editor as the widget with focus, and
    the next test to show a panel activates a window, which makes Qt hand
    the focus on and commit an editor that is no longer there.
    """
    index = panel.tree.indexFromItem(_rows(panel)[layer_id], NAME_COL)
    delegate = panel.tree.itemDelegateForIndex(index)
    delegate.closeEditor.emit(editor, QAbstractItemDelegate.EndEditHint.NoHint)
    QApplication.processEvents()


def _menu_texts(menu):
    return [a.text() for a in menu.actions() if not a.isSeparator()]


def _entry(menu, wanted):
    for action in menu.actions():
        if action.text().startswith(wanted):
            return action
    raise AssertionError(
        f"no menu entry starting {wanted!r} in {_menu_texts(menu)}")


# -- picking a layer is not choosing it --

def test_a_plain_click_on_a_name_leaves_the_active_layer_alone():
    scene, panel = _panel()
    walls, _roof = _layers(scene, panel)
    _click(panel, walls.id)
    assert scene.layers.current_id == DEFAULT_LAYER_ID, \
        "clicking a layer to pick it moved the layer new geometry lands on"


def test_picking_several_layers_in_turn_still_leaves_it_alone():
    scene, panel = _panel()
    walls, roof = _layers(scene, panel)
    _click(panel, walls.id)
    _click(panel, roof.id)
    assert scene.layers.current_id == DEFAULT_LAYER_ID


# -- a double-click chooses it --

def test_a_double_click_on_a_name_makes_it_the_active_layer():
    scene, panel = _panel()
    walls, _roof = _layers(scene, panel)
    _double_click(panel, walls.id)
    assert scene.layers.current_id == walls.id, \
        "a double-click on Walls did not make it the active layer"


def test_the_active_layer_is_marked_in_the_panel():
    scene, panel = _panel()
    walls, _roof = _layers(scene, panel)
    _double_click(panel, walls.id)
    assert _rows(panel)[walls.id].text(NAME_COL).startswith("●"), \
        "nothing in the row says which layer is the active one"


def test_a_double_click_no_longer_opens_a_rename():
    scene, panel = _panel()
    walls, _roof = _layers(scene, panel)
    _double_click(panel, walls.id)
    editor = _editor(panel)
    if editor is not None:
        _close_editor(panel, editor, walls.id)
    assert editor is None, \
        "the double-click that chooses a layer also opened its name for edit"


# -- so renaming moved to the menu --

def test_the_row_menu_offers_a_rename():
    scene, panel = _panel()
    walls, _roof = _layers(scene, panel)
    assert any(t.startswith("Rename")
               for t in _menu_texts(panel._menu_for(walls.id))), \
        "with the double-click taken, there is no way left to rename a layer"


def test_the_menu_rename_opens_the_name_for_editing():
    scene, panel = _panel()
    walls, _roof = _layers(scene, panel)
    _entry(panel._menu_for(walls.id), "Rename").trigger()
    QApplication.processEvents()
    editor = _editor(panel)
    assert editor is not None, "Rename opened nothing to type in"
    assert editor.text() == "Walls", \
        "the editor did not start from the layer's own name"
    _close_editor(panel, editor, walls.id)


def test_the_menu_renames_the_row_it_was_opened_on():
    scene, panel = _panel()
    walls, roof = _layers(scene, panel)
    _click(panel, walls.id)
    _entry(panel._menu_for(roof.id), "Rename").trigger()
    QApplication.processEvents()
    editor = _editor(panel)
    assert editor is not None and editor.text() == "Roof", \
        "Rename opened the picked layer instead of the right-clicked one"
    _close_editor(panel, editor, roof.id)
