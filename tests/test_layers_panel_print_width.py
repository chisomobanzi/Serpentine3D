"""The layers panel edits a layer's print width and its linetype.

The panel already shows a layer's name, whether it is on, and its colour.
Item 6 wants the two attributes a plot is read by as well: the pen width it
prints at, and the dash pattern its lines take. Print width is a number in
millimetres, edited in place, with an empty or "Default" cell meaning the
device default. Linetype is picked from a drop-down of the patterns the
app knows.

Both go through history, so an edit here undoes like any other.
"""

from __future__ import annotations

from serpentine3d.core.history import History
from serpentine3d.core.layers import DEFAULT_LAYER_ID
from serpentine3d.core.scene import Scene
from serpentine3d.ui.layers_panel import LayersPanel

PRINT_COL = 4
TYPE_COL = 3


def _panel():
    scene = Scene()
    return scene, LayersPanel(scene, History(scene))


def _item_for(panel, layer_id):
    for i in range(panel.tree.topLevelItemCount()):
        item = panel.tree.topLevelItem(i)
        if panel._layer_id(item) == layer_id:
            return item
    raise AssertionError("no row for that layer")


def _commit(panel, item, column, text):
    """Set a cell and run the change handler once, the way a finished edit
    does. setText on a live tree fires the handler itself, so signals are
    held while the text is staged and the handler is called by hand."""
    panel.tree.blockSignals(True)
    item.setText(column, text)
    panel.tree.blockSignals(False)
    panel._item_changed(item, column)


def test_the_panel_carries_a_print_column():
    _scene, panel = _panel()
    headers = [panel.tree.headerItem().text(c)
               for c in range(panel.tree.columnCount())]
    assert "Print" in headers
    item = _item_for(panel, DEFAULT_LAYER_ID)
    assert item.text(PRINT_COL) == "Default"


def test_a_set_width_shows_in_millimetres():
    scene, panel = _panel()
    scene.layers.set_print_width(DEFAULT_LAYER_ID, 0.5)
    panel.rebuild()
    assert _item_for(panel, DEFAULT_LAYER_ID).text(PRINT_COL) == "0.5"


def test_editing_the_cell_sets_the_width():
    scene, panel = _panel()
    item = _item_for(panel, DEFAULT_LAYER_ID)
    _commit(panel, item, PRINT_COL, "0.35")
    assert scene.layers.get(DEFAULT_LAYER_ID).print_width == 0.35


def test_default_text_means_the_device_default():
    scene, panel = _panel()
    scene.layers.set_print_width(DEFAULT_LAYER_ID, 0.5)
    panel.rebuild()
    item = _item_for(panel, DEFAULT_LAYER_ID)
    _commit(panel, item, PRINT_COL, "Default")
    assert scene.layers.get(DEFAULT_LAYER_ID).print_width == 0.0


def test_a_value_that_is_not_a_number_is_left_alone():
    scene, panel = _panel()
    scene.layers.set_print_width(DEFAULT_LAYER_ID, 0.5)
    panel.rebuild()
    item = _item_for(panel, DEFAULT_LAYER_ID)
    _commit(panel, item, PRINT_COL, "wide")
    assert scene.layers.get(DEFAULT_LAYER_ID).print_width == 0.5


def test_a_negative_value_falls_to_the_default():
    scene, panel = _panel()
    item = _item_for(panel, DEFAULT_LAYER_ID)
    _commit(panel, item, PRINT_COL, "-3")
    assert scene.layers.get(DEFAULT_LAYER_ID).print_width == 0.0


def test_editing_the_width_can_be_undone():
    scene, panel = _panel()
    history = panel.history
    item = _item_for(panel, DEFAULT_LAYER_ID)
    _commit(panel, item, PRINT_COL, "0.4")
    history.undo()
    assert scene.layers.get(DEFAULT_LAYER_ID).print_width == 0.0


def test_the_type_cell_shows_the_pattern_name():
    scene, panel = _panel()
    scene.layers.set_linetype(DEFAULT_LAYER_ID, "Dashed")
    panel.rebuild()
    assert _item_for(panel, DEFAULT_LAYER_ID).text(TYPE_COL) == "Dashed"
