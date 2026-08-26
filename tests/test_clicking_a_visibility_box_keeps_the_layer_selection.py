"""Clicking a layer's visibility box does not change which layers are selected.

Seen in the live app: with layers A, B and C selected, a click on B's
visibility box turns all three off - but the click also collapses the
selection to B alone, so the next click on the same box brings back only B.
The user who hid three layers with one click has to reselect them to show
them again. In Rhino, clicking a layer's on/off bulb never changes the
selection; the same should hold here, while a plain click on a layer's name
still picks that layer on its own.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

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
    """Layers A, B, C and D, on top of the default one."""
    ids = [scene.layers.create(name).id for name in "ABCD"]
    scene.notify()
    QApplication.processEvents()
    return ids


def _item_for(panel, layer_id):
    for i in range(panel.tree.topLevelItemCount()):
        item = panel.tree.topLevelItem(i)
        if panel._layer_id(item) == layer_id:
            return item
    raise AssertionError("no row for that layer")


def _select(panel, *layer_ids):
    panel.tree.clearSelection()
    for layer_id in layer_ids:
        _item_for(panel, layer_id).setSelected(True)
    QApplication.processEvents()


def _click(panel, layer_id, column):
    """A real left click - press and release - on the middle of a cell."""
    tree = panel.tree
    index = tree.indexFromItem(_item_for(panel, layer_id), column)
    rect = tree.visualRect(index)
    assert rect.isValid() and not rect.isEmpty(), "the cell is not on screen"
    QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, rect.center())
    # the panel redraws on a zero-timer after an item change
    QTest.qWait(50)
    QApplication.processEvents()


def _visible(scene, layer_ids):
    return [scene.layers.get(i).visible for i in layer_ids]


def _selected_ids(panel):
    return {panel._layer_id(item) for item in panel.tree.selectedItems()}


# -- the box toggles the group and leaves the selection alone --

def test_a_real_click_on_a_box_hides_the_selection_and_keeps_it_selected():
    scene, panel = _panel()
    a, b, c, d = _four_layers(scene, panel)
    _select(panel, a, b, c)
    _click(panel, b, VISIBLE_COL)
    assert _visible(scene, [a, b, c, d]) == [False, False, False, True], \
        "the click did not hide exactly the three selected layers"
    assert _selected_ids(panel) == {a, b, c}, \
        "clicking the visibility box changed which layers are selected"


def test_a_second_real_click_on_the_same_box_shows_the_whole_selection():
    scene, panel = _panel()
    a, b, c, d = _four_layers(scene, panel)
    _select(panel, a, b, c)
    _click(panel, b, VISIBLE_COL)
    assert _visible(scene, [a, b, c]) == [False, False, False]
    _click(panel, b, VISIBLE_COL)
    assert _visible(scene, [a, b, c, d]) == [True, True, True, True], \
        "the second click brought back only the clicked layer"
    assert _selected_ids(panel) == {a, b, c}


# -- guards --

def test_with_nothing_selected_a_click_toggles_only_that_layer():
    scene, panel = _panel()
    a, b, c, d = _four_layers(scene, panel)
    _select(panel)
    _click(panel, b, VISIBLE_COL)
    assert _visible(scene, [a, b, c, d]) == [True, False, True, True]
    assert _selected_ids(panel) <= {b}, \
        "clicking a visibility box selected other layers"


def test_a_plain_click_on_a_name_still_selects_that_layer_alone():
    scene, panel = _panel()
    a, b, c, d = _four_layers(scene, panel)
    _select(panel, a, b, c)
    _click(panel, d, NAME_COL)
    assert _selected_ids(panel) == {d}, \
        "a plain click on a layer's name no longer picks just that layer"
    assert _visible(scene, [a, b, c, d]) == [True, True, True, True]
