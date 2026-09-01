"""Shift-clicking a layer's name selects the range from the name clicked
before it, and nothing more.

Seen in the live app: with layers Default, A, B and C, a user clicks A's
name, then Shift-clicks C's name expecting A, B and C to be selected. What
they get is Default, A, B and C - and a click on B's visibility box then
switches Default off too, which nobody asked for. Clicking a name used to
make that layer current, so the scene notified and the panel redrew its
tree in the middle of the click, and the tree forgot which row the user
clicked last; a click that lands right after such a redraw can even be
swallowed entirely. The tree should remember the row the user clicked,
just as it does in any other list, and a plain click should pick the layer
and nothing else: choosing the layer to draw on is a double-click.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (QApplication, QStyle,
                               QStyleOptionViewItem)

from serpentine3d.core.history import History
from serpentine3d.core.scene import Scene
from serpentine3d.ui.layers_panel import LayersPanel

NAME_COL = 0
VISIBLE_COL = 1


def _panel():
    scene = Scene()
    panel = LayersPanel(scene, History(scene))
    panel.resize(400, 300)
    panel.show()
    QApplication.processEvents()
    return scene, panel


def _four_layers(scene, panel):
    """The default layer, then A, B and C; returns their ids in that order."""
    default = scene.layers.current_id
    ids = [scene.layers.create(name).id for name in "ABC"]
    scene.notify()
    QApplication.processEvents()
    return [default, *ids]


def _item_for(panel, layer_id):
    for i in range(panel.tree.topLevelItemCount()):
        item = panel.tree.topLevelItem(i)
        if panel._layer_id(item) == layer_id:
            return item
    raise AssertionError("no row for that layer")


def _click_point(tree, index):
    """Where a hand would land in a cell.

    A check box is drawn hard against the left edge of its cell, not in the
    middle of it, and how much of the cell it covers is the style's business:
    on Fusion the box stops two pixels short of the centre, so a click aimed
    at the centre lands on bare cell and toggles nothing. Aim at the box when
    the cell has one, at the middle of the cell when it does not.
    """
    rect = tree.visualRect(index)
    assert rect.isValid() and not rect.isEmpty(), "the cell is not on screen"
    item = tree.itemFromIndex(index)
    if item.data(index.column(), Qt.ItemDataRole.CheckStateRole) is None:
        return rect.center()
    option = QStyleOptionViewItem()
    option.rect = rect
    option.features |= QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
    box = tree.style().subElementRect(
        QStyle.SubElement.SE_ItemViewItemCheckIndicator, option, tree)
    return box.center()


def _click(panel, layer_id, column,
           modifier=Qt.KeyboardModifier.NoModifier, wait=True):
    """A real left click - press and release - where a hand would land."""
    tree = panel.tree
    index = tree.indexFromItem(_item_for(panel, layer_id), column)
    QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton,
                     modifier, _click_point(tree, index))
    if wait:
        # the panel redraws on a zero-timer after an item change
        QTest.qWait(50)
    QApplication.processEvents()


def _shift_click(panel, layer_id, column):
    _click(panel, layer_id, column, Qt.KeyboardModifier.ShiftModifier)


def _visible(scene, layer_ids):
    return [scene.layers.get(i).visible for i in layer_ids]


def _selected_ids(panel):
    return {panel._layer_id(item) for item in panel.tree.selectedItems()}


# -- a shift-click picks the range from the last clicked name --

def test_clicking_a_name_then_shift_clicking_another_selects_just_that_range():
    scene, panel = _panel()
    default, a, b, c = _four_layers(scene, panel)
    _click(panel, a, NAME_COL)
    _shift_click(panel, c, NAME_COL)
    assert _selected_ids(panel) == {a, b, c}, \
        "the shift-click did not select exactly the range A..C"
    assert default not in _selected_ids(panel), \
        "the default layer was pulled into the selection"
    assert scene.layers.current_id == default, \
        "picking A moved the layer new geometry lands on"


def test_hiding_the_shift_selected_range_leaves_the_default_layer_on():
    scene, panel = _panel()
    default, a, b, c = _four_layers(scene, panel)
    _click(panel, a, NAME_COL)
    _shift_click(panel, c, NAME_COL)
    _click(panel, b, VISIBLE_COL)
    assert _visible(scene, [default, a, b, c]) == [True, False, False, False], \
        "hiding the range A..C did not hide exactly A, B and C"


# -- a click right after a redraw is not swallowed --

def test_a_click_on_a_box_right_after_clicking_its_name_still_lands():
    scene, panel = _panel()
    default, a, b, c = _four_layers(scene, panel)
    _click(panel, a, NAME_COL, wait=False)
    _click(panel, a, VISIBLE_COL)
    assert _visible(scene, [default, a, b, c]) == [True, False, True, True], \
        "the click on A's visibility box was swallowed"


# -- guard --

def test_clicking_one_name_then_another_selects_only_the_second():
    scene, panel = _panel()
    default, a, b, c = _four_layers(scene, panel)
    _click(panel, a, NAME_COL)
    _click(panel, c, NAME_COL)
    assert _selected_ids(panel) == {c}, \
        "a plain click on a second name did not pick just that layer"
    assert scene.layers.current_id == default
