"""A layer's linetype and print width are chosen from a list, not rolled.

An architect setting up a sheet reported that the Type cell was a "rolling
option": every click advanced to the next dash pattern, so getting from
Continuous to Phantom meant seven clicks and one too many put you back at
the start. Print was a bare text cell that asked you to remember the pen
widths by heart. Both should open a drop-down when edited - Type lists the
linetypes the app knows, Print lists the standard pen widths but still
takes a typed value - and a single click on Type should no longer change
anything by itself.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QAbstractItemDelegate, QApplication, QComboBox

from serpentine3d.core.history import History
from serpentine3d.core.layers import DEFAULT_LAYER_ID
from serpentine3d.core.linetype import LINETYPES
from serpentine3d.core.scene import Scene
from serpentine3d.ui.layers_panel import LayersPanel

TYPE_COL = 3
PRINT_COL = 4
STANDARD_PEN_WIDTHS = ["0.13", "0.18", "0.25", "0.35", "0.5", "0.7", "1.0"]


def _panel():
    scene = Scene()
    panel = LayersPanel(scene, History(scene))
    panel.resize(400, 300)
    panel.show()
    QApplication.processEvents()
    return scene, panel


def _item_for(panel, layer_id):
    for i in range(panel.tree.topLevelItemCount()):
        item = panel.tree.topLevelItem(i)
        if panel._layer_id(item) == layer_id:
            return item
    raise AssertionError("no row for that layer")


def _mouse(panel, item, column, *types):
    """Mouse events on a cell, delivered the way Qt delivers them."""
    index = panel.tree.indexFromItem(item, column)
    pos = QPointF(panel.tree.visualRect(index).center())
    for typ in types:
        QApplication.sendEvent(panel.tree.viewport(), QMouseEvent(
            typ, pos, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier))
    QApplication.processEvents()


def _click(panel, item, column):
    _mouse(panel, item, column,
           QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease)


def _open_editor(panel, item, column):
    """Double-click the cell, the way the panel starts an edit, and hand
    back the drop-down it opens."""
    _mouse(panel, item, column,
           QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
           QEvent.Type.MouseButtonDblClick, QEvent.Type.MouseButtonRelease)
    combo = panel.tree.findChild(QComboBox)
    assert combo is not None, "editing the cell opened no drop-down"
    return combo


def _close_editor(panel, layer_id, column, combo):
    """End the edit, the way clicking away from the cell would.

    No test may leave an editor open. The panel is dropped when the test
    returns, but Qt still holds the drop-down as the widget with focus, and
    the next test to show a panel activates a window, which makes Qt hand
    the focus on and commit an editor that is no longer there. That crash
    lands in whichever test opened the next panel, nowhere near the test
    that actually left the door open.
    """
    index = panel.tree.indexFromItem(_item_for(panel, layer_id), column)
    delegate = panel.tree.itemDelegateForIndex(index)
    delegate.closeEditor.emit(combo, QAbstractItemDelegate.EndEditHint.NoHint)
    QApplication.processEvents()


def _choose(panel, layer_id, column, combo, text):
    """Pick (or type) a value in the open drop-down and finish the edit."""
    combo.setCurrentText(text)
    QApplication.processEvents()
    index = panel.tree.indexFromItem(_item_for(panel, layer_id), column)
    delegate = panel.tree.itemDelegateForIndex(index)
    delegate.commitData.emit(combo)
    _close_editor(panel, layer_id, column, combo)


def _entries(combo):
    return [combo.itemText(i) for i in range(combo.count())]


# -- Type --

def test_the_type_cell_lists_every_linetype_with_the_current_one_chosen():
    scene, panel = _panel()
    scene.layers.set_linetype(DEFAULT_LAYER_ID, "Hidden")
    panel.rebuild()
    combo = _open_editor(panel, _item_for(panel, DEFAULT_LAYER_ID), TYPE_COL)
    assert _entries(combo) == list(LINETYPES)
    assert combo.currentText() == "Hidden"
    _close_editor(panel, DEFAULT_LAYER_ID, TYPE_COL, combo)


def test_choosing_a_linetype_sets_it_on_the_layer():
    scene, panel = _panel()
    item = _item_for(panel, DEFAULT_LAYER_ID)
    combo = _open_editor(panel, item, TYPE_COL)
    _choose(panel, DEFAULT_LAYER_ID, TYPE_COL, combo, "Phantom")
    assert scene.layers.get(DEFAULT_LAYER_ID).linetype == "Phantom"


def test_a_chosen_linetype_undoes_in_one_step():
    scene, panel = _panel()
    scene.layers.set_linetype(DEFAULT_LAYER_ID, "Dashed")
    panel.rebuild()
    item = _item_for(panel, DEFAULT_LAYER_ID)
    combo = _open_editor(panel, item, TYPE_COL)
    _choose(panel, DEFAULT_LAYER_ID, TYPE_COL, combo, "Center")
    assert scene.layers.get(DEFAULT_LAYER_ID).linetype == "Center"
    panel.history.undo()
    assert scene.layers.get(DEFAULT_LAYER_ID).linetype == "Dashed"


def test_a_single_click_on_the_type_cell_changes_nothing():
    scene, panel = _panel()
    scene.layers.set_linetype(DEFAULT_LAYER_ID, "Dashed")
    panel.rebuild()
    _click(panel, _item_for(panel, DEFAULT_LAYER_ID), TYPE_COL)
    assert scene.layers.get(DEFAULT_LAYER_ID).linetype == "Dashed", \
        "one click still rolled the linetype on to the next one"


# -- Print --

def test_the_print_cell_lists_default_and_the_standard_pen_widths():
    _scene, panel = _panel()
    combo = _open_editor(panel, _item_for(panel, DEFAULT_LAYER_ID), PRINT_COL)
    assert _entries(combo) == ["Default"] + STANDARD_PEN_WIDTHS
    assert combo.isEditable(), "a custom width has to be typeable"
    _close_editor(panel, DEFAULT_LAYER_ID, PRINT_COL, combo)


def test_choosing_a_standard_width_sets_it_on_the_layer():
    scene, panel = _panel()
    item = _item_for(panel, DEFAULT_LAYER_ID)
    combo = _open_editor(panel, item, PRINT_COL)
    _choose(panel, DEFAULT_LAYER_ID, PRINT_COL, combo, "0.35")
    assert scene.layers.get(DEFAULT_LAYER_ID).print_width == 0.35


def test_choosing_default_returns_the_layer_to_the_device_default():
    scene, panel = _panel()
    scene.layers.set_print_width(DEFAULT_LAYER_ID, 0.5)
    panel.rebuild()
    item = _item_for(panel, DEFAULT_LAYER_ID)
    combo = _open_editor(panel, item, PRINT_COL)
    _choose(panel, DEFAULT_LAYER_ID, PRINT_COL, combo, "Default")
    assert scene.layers.get(DEFAULT_LAYER_ID).print_width == 0.0


def test_a_typed_custom_width_is_kept():
    scene, panel = _panel()
    item = _item_for(panel, DEFAULT_LAYER_ID)
    combo = _open_editor(panel, item, PRINT_COL)
    _choose(panel, DEFAULT_LAYER_ID, PRINT_COL, combo, "0.42")
    assert scene.layers.get(DEFAULT_LAYER_ID).print_width == 0.42
