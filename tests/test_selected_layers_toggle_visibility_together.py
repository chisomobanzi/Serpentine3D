"""Turning off one selected layer turns off every selected layer.

An architect reported: "You can't select multiple layers and turn them off
at once; they have to be turned off one by one." With a drawing split across
a dozen layers, hiding the structure to look at the services alone meant a
dozen clicks, and a dozen more to bring it back. The panel should let the
user Ctrl-click or Shift-click several layers, and then a click on any one
of their visibility boxes should switch the whole selection together -
as one undo step, and with one redraw. A lone layer still toggles on its
own, so nobody's single-layer habit changes.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QAbstractItemView, QApplication

from serpentine3d.core.history import History
from serpentine3d.core.scene import Scene
from serpentine3d.ui.layers_panel import LayersPanel

VISIBLE_COL = 1
TYPE_COL = 3   # a single click here selects the row and changes nothing else


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


def _ctrl_click(panel, layer_id, column):
    """A Ctrl-click on a cell, delivered the way Qt delivers it."""
    index = panel.tree.indexFromItem(_item_for(panel, layer_id), column)
    pos = QPointF(panel.tree.visualRect(index).center())
    for typ in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
        QApplication.sendEvent(panel.tree.viewport(), QMouseEvent(
            typ, pos, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.ControlModifier))
    QApplication.processEvents()


def _toggle_visibility(panel, layer_id):
    """Click the layer's visibility box: the view flips the cell's check
    state, which is what the panel hears."""
    item = _item_for(panel, layer_id)
    was_checked = item.checkState(VISIBLE_COL) == Qt.CheckState.Checked
    item.setCheckState(VISIBLE_COL, Qt.CheckState.Unchecked if was_checked
                       else Qt.CheckState.Checked)
    QApplication.processEvents()


def _visible(scene, layer_ids):
    return [scene.layers.get(i).visible for i in layer_ids]


def _selected_ids(panel):
    return {panel._layer_id(item) for item in panel.tree.selectedItems()}


# -- selecting more than one layer --

def test_the_user_can_ctrl_click_several_layers():
    scene, panel = _panel()
    a, b, _c, _d = _four_layers(scene, panel)
    assert panel.tree.selectionMode() in (
        QAbstractItemView.SelectionMode.ExtendedSelection,
        QAbstractItemView.SelectionMode.MultiSelection), \
        "the layers list only lets one layer be picked at a time"
    _ctrl_click(panel, a, TYPE_COL)
    _ctrl_click(panel, b, TYPE_COL)
    assert _selected_ids(panel) == {a, b}


# -- toggling the selection together --

def test_one_click_turns_every_selected_layer_off_and_leaves_the_rest():
    scene, panel = _panel()
    a, b, c, d = _four_layers(scene, panel)
    _select(panel, a, b, c)
    _toggle_visibility(panel, b)
    assert _visible(scene, [a, b, c]) == [False, False, False], \
        "only the clicked layer went off; the other selected ones stayed on"
    assert scene.layers.get(d).visible, "an unselected layer was hidden too"


def test_a_second_click_turns_the_whole_selection_back_on():
    scene, panel = _panel()
    a, b, c, d = _four_layers(scene, panel)
    _select(panel, a, b, c)
    _toggle_visibility(panel, b)
    assert _visible(scene, [a, b, c]) == [False, False, False]
    _toggle_visibility(panel, b)
    assert _visible(scene, [a, b, c, d]) == [True, True, True, True], \
        "the second click did not bring the whole selection back"


# -- a single layer still toggles on its own --

def test_with_only_that_layer_selected_only_it_changes():
    scene, panel = _panel()
    a, b, c, d = _four_layers(scene, panel)
    _select(panel, b)
    _toggle_visibility(panel, b)
    assert _visible(scene, [a, b, c, d]) == [True, False, True, True]


def test_with_nothing_selected_only_the_clicked_layer_changes():
    scene, panel = _panel()
    a, b, c, d = _four_layers(scene, panel)
    _select(panel)
    _toggle_visibility(panel, b)
    assert _visible(scene, [a, b, c, d]) == [True, False, True, True]


# -- one step, one redraw --

def test_the_whole_toggle_undoes_in_one_step():
    scene, panel = _panel()
    a, b, c, _d = _four_layers(scene, panel)
    _select(panel, a, b, c)
    _toggle_visibility(panel, b)
    assert _visible(scene, [a, b, c]) == [False, False, False]
    panel.history.undo()
    assert _visible(scene, [a, b, c]) == [True, True, True], \
        "one undo did not bring back every layer the click hid"


def test_the_scene_is_told_once_for_the_whole_toggle():
    def count_notifies(scene, panel, layer_ids):
        calls = []
        scene.add_listener(lambda *a, **k: calls.append(1), kinds=("layers",))
        _select(panel, *layer_ids)
        _toggle_visibility(panel, layer_ids[0])
        return len(calls)

    scene, panel = _panel()
    _a, b, _c, _d = _four_layers(scene, panel)
    for_one = count_notifies(scene, panel, [b])

    scene, panel = _panel()
    a, b, c, _d = _four_layers(scene, panel)
    for_three = count_notifies(scene, panel, [b, a, c])
    assert _visible(scene, [a, b, c]) == [False, False, False]
    assert for_three == for_one, \
        f"hiding three layers told the scene {for_three} times, one layer {for_one}"
