"""The layer list is the drawing's contents page, so its order is the
user's to set.

Layers come out in the order they were made, which is the order the work
happened in, not the order anyone wants to read: a site plan drawn last
sits under the furniture. Rhino's panel has a pair of arrows for this and
the first-use report asked for them ("layer reorder (move up/down)").

A layer moves among its own siblings and nowhere else. Up out of a branch
is what the `↰` button is for, and a layer that holds a branch takes the
whole branch with it, so the tree the user reads never changes shape from
an arrow press.
"""

from __future__ import annotations

import os
import tempfile

from PySide6.QtWidgets import QApplication, QPushButton

from serpentine3d.core.history import History
from serpentine3d.core.layers import LayerManager
from serpentine3d.core.scene import Scene
from serpentine3d.ui.layers_panel import LayersPanel


def _house(layers):
    """Walls (holding Interior and Exterior), then Roof, then Site."""
    walls = layers.create("Walls")
    inner = layers.create("Interior", parent=walls.id)
    outer = layers.create("Exterior", parent=walls.id)
    roof = layers.create("Roof")
    site = layers.create("Site")
    return walls, inner, outer, roof, site


def _names(layers):
    return [la.name for la in layers.all()]


def _child_names(layers, layer_id):
    return [la.name for la in layers.children(layer_id)]


# -- the model --

def test_a_layer_moves_above_the_one_before_it():
    layers = LayerManager()
    _walls, _inner, _outer, roof, _site = _house(layers)
    assert layers.move_up(roof.id) is True
    assert _names(layers) == ["Default", "Roof", "Walls", "Interior",
                              "Exterior", "Site"], _names(layers)


def test_a_layer_moves_below_the_one_after_it():
    layers = LayerManager()
    _walls, _inner, _outer, roof, _site = _house(layers)
    assert layers.move_down(roof.id) is True
    assert _names(layers) == ["Default", "Walls", "Interior", "Exterior",
                              "Site", "Roof"], _names(layers)


def test_the_layer_at_the_top_has_nowhere_above_it_to_go():
    layers = LayerManager()
    _house(layers)
    before = _names(layers)
    assert layers.move_up("default") is False, \
        "the first layer claims to have moved"
    assert _names(layers) == before


def test_the_layer_at_the_bottom_has_nowhere_below_it_to_go():
    layers = LayerManager()
    _walls, _inner, _outer, _roof, site = _house(layers)
    before = _names(layers)
    assert layers.move_down(site.id) is False
    assert _names(layers) == before


def test_a_sublayer_moves_among_its_own_siblings():
    layers = LayerManager()
    walls, _inner, outer, _roof, _site = _house(layers)
    assert layers.move_up(outer.id) is True
    assert _child_names(layers, walls.id) == ["Exterior", "Interior"]
    assert layers.get(outer.id).parent == walls.id, \
        "the arrow took the layer out of its branch"


def test_the_first_sublayer_cannot_climb_out_of_its_branch():
    layers = LayerManager()
    walls, inner, _outer, _roof, _site = _house(layers)
    assert layers.move_up(inner.id) is False, \
        "the top sublayer moved somewhere, and out of Walls is the only way"
    assert layers.get(inner.id).parent == walls.id
    assert _child_names(layers, walls.id) == ["Interior", "Exterior"]


def test_a_layer_carries_its_whole_branch_with_it():
    layers = LayerManager()
    walls, _inner, _outer, _roof, _site = _house(layers)
    layers.move_down(walls.id)
    assert _names(layers) == ["Default", "Roof", "Walls", "Interior",
                              "Exterior", "Site"], _names(layers)
    assert _child_names(layers, walls.id) == ["Interior", "Exterior"], \
        "the branch was left behind where the layer used to be"


def test_a_layer_passes_a_whole_branch_in_one_press():
    """Walls holds two layers, so one press over it is one press, not three."""
    layers = LayerManager()
    walls, _inner, _outer, roof, _site = _house(layers)
    layers.move_up(roof.id)
    assert _names(layers).index("Roof") < _names(layers).index("Walls")
    assert layers.get(roof.id).parent is None
    assert _child_names(layers, walls.id) == ["Interior", "Exterior"]


def test_the_order_survives_an_undo():
    scene = Scene()
    history = History(scene)
    layers = scene.layers
    _walls, _inner, _outer, roof, _site = _house(layers)
    before = _names(layers)
    history.checkpoint("move layer")
    layers.move_up(roof.id)
    history.undo()
    assert _names(scene.layers) == before


def test_the_order_comes_back_from_a_saved_file():
    from serpentine3d.fileio.native import load_scene, save_scene

    scene = Scene()
    _walls, _inner, _outer, roof, _site = _house(scene.layers)
    # Default is not nailed to the top: it moves like any other layer, and
    # the file has to say so or the order is only half kept.
    scene.layers.move_up(roof.id)
    scene.layers.move_up(roof.id)
    scene.layers.move_up(roof.id)
    written = _names(scene.layers)
    assert written[0] == "Roof", written

    path = os.path.join(tempfile.mkdtemp(), "order.s3d")
    save_scene(scene, path)
    other = Scene()
    load_scene(other, path)
    assert _names(other.layers) == written, \
        "the file brought the layers back in the order they were made"


# -- the panel --

def _panel():
    scene = Scene()
    panel = LayersPanel(scene, History(scene))
    panel.resize(400, 300)
    panel.show()
    QApplication.processEvents()
    return scene, panel


def _rows(panel) -> dict:
    out = {}
    stack = [panel.tree.topLevelItem(i)
             for i in range(panel.tree.topLevelItemCount())]
    while stack:
        item = stack.pop()
        out[panel._layer_id(item)] = item
        stack.extend(item.child(i) for i in range(item.childCount()))
    return out


def _select(panel, *layer_ids):
    rows = _rows(panel)
    panel.tree.clearSelection()
    # Current first, then the selection: setting the current row shrinks an
    # extended selection to that one row.
    if layer_ids:
        panel.tree.setCurrentItem(rows[layer_ids[0]])
    for layer_id in layer_ids:
        rows[layer_id].setSelected(True)
    QApplication.processEvents()


def _selected_ids(panel):
    return {panel._layer_id(item) for item in panel.tree.selectedItems()}


def _button(panel, wanted):
    for btn in panel.findChildren(QPushButton):
        if wanted in (btn.toolTip() or "").lower():
            return btn
    raise AssertionError(f"the panel has no button for {wanted!r}")


def _press(panel, wanted):
    _button(panel, wanted).click()
    QApplication.processEvents()


def _drawn(panel):
    """The names in the tree, top to bottom, as the user reads them."""
    out = []

    def walk(item):
        for i in range(item.childCount()):
            child = item.child(i)
            out.append(child.text(0).strip("● ").split("  (")[0])
            walk(child)

    for i in range(panel.tree.topLevelItemCount()):
        top = panel.tree.topLevelItem(i)
        out.append(top.text(0).strip("● ").split("  (")[0])
        walk(top)
    return out


def test_the_panel_offers_a_button_for_each_direction():
    _scene, panel = _panel()
    assert _button(panel, "up").isVisible()
    assert _button(panel, "down").isVisible()


def test_the_button_moves_the_picked_layer_up_the_list():
    scene, panel = _panel()
    _walls, _inner, _outer, roof, _site = _house(scene.layers)
    scene.notify()
    QApplication.processEvents()
    _select(panel, roof.id)
    _press(panel, "up")
    assert _drawn(panel) == ["Default", "Roof", "Walls", "Interior",
                             "Exterior", "Site"], _drawn(panel)


def test_one_press_is_one_undo():
    scene, panel = _panel()
    _walls, _inner, _outer, roof, _site = _house(scene.layers)
    scene.notify()
    QApplication.processEvents()
    before = _names(scene.layers)
    _select(panel, roof.id)
    _press(panel, "down")
    panel.history.undo()
    assert _names(scene.layers) == before


def test_a_press_that_moves_nothing_costs_no_undo():
    scene, panel = _panel()
    _walls, _inner, _outer, roof, _site = _house(scene.layers)
    scene.notify()
    QApplication.processEvents()
    _select(panel, roof.id)
    _press(panel, "up")
    _select(panel, "default")
    _press(panel, "up")
    panel.history.undo()
    assert _names(scene.layers)[1] == "Walls", \
        "the press that could move nothing still cost the user an undo"


def test_the_layer_stays_picked_after_it_moves():
    scene, panel = _panel()
    _walls, _inner, _outer, roof, _site = _house(scene.layers)
    scene.notify()
    QApplication.processEvents()
    _select(panel, roof.id)
    _press(panel, "up")
    assert roof.id in _selected_ids(panel), \
        "the layer lost its selection, so a second press moves something else"


def test_picked_layers_move_together():
    scene, panel = _panel()
    _walls, _inner, _outer, roof, site = _house(scene.layers)
    scene.notify()
    QApplication.processEvents()
    _select(panel, roof.id, site.id)
    _press(panel, "up")
    assert _drawn(panel) == ["Default", "Roof", "Site", "Walls", "Interior",
                             "Exterior"], _drawn(panel)


def test_picked_layers_stop_together_at_the_top():
    """The pair keeps its order when the one in front runs out of room."""
    scene, panel = _panel()
    _walls, _inner, _outer, roof, site = _house(scene.layers)
    scene.notify()
    QApplication.processEvents()
    _select(panel, roof.id, site.id)
    for _ in range(4):
        _press(panel, "up")
    assert _drawn(panel) == ["Roof", "Site", "Default", "Walls", "Interior",
                             "Exterior"], _drawn(panel)
