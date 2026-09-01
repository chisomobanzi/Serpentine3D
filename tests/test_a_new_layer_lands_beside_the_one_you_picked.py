"""The + button makes a layer where the one you picked is, not at the top.

Picking a sublayer and pressing + used to make a top-level layer at the
end of the list: an uncle of the layer that was picked, not a sibling of
it, and nowhere near the row that was being looked at. Rhino's panel puts
the new layer beside the picked one, which is also what the button beside
this one is for: `↳` makes a layer *inside* the picked one, so `+` making
one *beside* it is the pair of them.

The new layer goes directly under the picked layer's branch, so it reads
as the next row at that level rather than turning up at the bottom of the
panel.
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

from serpentine3d.core.history import History
from serpentine3d.core.scene import Scene
from serpentine3d.ui.layers_panel import LayersPanel


def _panel():
    scene = Scene()
    panel = LayersPanel(scene, History(scene))
    panel.resize(400, 300)
    panel.show()
    QApplication.processEvents()
    return scene, panel


def _house(scene, panel):
    """Walls, holding Interior and Exterior, then Roof."""
    layers = scene.layers
    walls = layers.create("Walls")
    inner = layers.create("Interior", parent=walls.id)
    outer = layers.create("Exterior", parent=walls.id)
    roof = layers.create("Roof")
    scene.notify()
    panel.tree.expandAll()
    QApplication.processEvents()
    return walls, inner, outer, roof


def _rows(panel) -> dict:
    out = {}

    def walk(item):
        for i in range(item.childCount()):
            child = item.child(i)
            out[panel._layer_id(child)] = child
            walk(child)

    for i in range(panel.tree.topLevelItemCount()):
        top = panel.tree.topLevelItem(i)
        out[panel._layer_id(top)] = top
        walk(top)
    return out


def _pick(panel, layer_id):
    panel.tree.setCurrentItem(_rows(panel)[layer_id])
    QApplication.processEvents()


def _names(layers):
    return [la.name for la in layers.all()]


def test_a_new_layer_made_beside_a_sublayer_is_a_sublayer_too():
    scene, panel = _panel()
    walls, inner, _outer, _roof = _house(scene, panel)
    _pick(panel, inner.id)
    panel._new_layer()
    made = scene.layers.get(scene.layers.current_id)
    assert made.parent == walls.id, \
        "the new layer is an uncle of the picked one, not a sibling"


def test_the_new_layer_lands_right_under_the_one_it_was_made_beside():
    scene, panel = _panel()
    _walls, inner, _outer, _roof = _house(scene, panel)
    _pick(panel, inner.id)
    panel._new_layer()
    made = scene.layers.get(scene.layers.current_id)
    assert _names(scene.layers) == ["Default", "Walls", "Interior", made.name,
                                    "Exterior", "Roof"], _names(scene.layers)


def test_a_new_layer_made_beside_a_top_level_layer_stays_at_the_top_level():
    scene, panel = _panel()
    walls, _inner, _outer, _roof = _house(scene, panel)
    _pick(panel, walls.id)
    panel._new_layer()
    made = scene.layers.get(scene.layers.current_id)
    assert made.parent is None
    assert _names(scene.layers) == ["Default", "Walls", "Interior",
                                    "Exterior", made.name, "Roof"], \
        "the new layer landed inside the branch it was made beside"


def test_a_new_layer_with_nothing_picked_goes_at_the_end():
    scene, panel = _panel()
    _house(scene, panel)
    panel.tree.setCurrentItem(None)
    panel.tree.clearSelection()
    QApplication.processEvents()
    panel._new_layer()
    made = scene.layers.get(scene.layers.current_id)
    assert made.parent is None
    assert _names(scene.layers)[-1] == made.name, _names(scene.layers)


def test_the_new_layer_is_the_one_being_drawn_on():
    scene, panel = _panel()
    _walls, inner, _outer, _roof = _house(scene, panel)
    _pick(panel, inner.id)
    panel._new_layer()
    assert scene.layers.current_id not in (inner.id, "default")


def test_making_a_layer_beside_a_sublayer_is_one_undo():
    scene, panel = _panel()
    _walls, inner, _outer, _roof = _house(scene, panel)
    before = _names(scene.layers)
    _pick(panel, inner.id)
    panel._new_layer()
    panel.history.undo()
    assert _names(scene.layers) == before, \
        "putting the new layer in its place cost a second undo"


def test_the_new_row_is_the_picked_one_afterwards():
    """So the next + is beside the layer just made, and typing a name
    lands on the row that was just added rather than the one above it."""
    scene, panel = _panel()
    _walls, inner, _outer, _roof = _house(scene, panel)
    _pick(panel, inner.id)
    panel._new_layer()
    made = scene.layers.current_id
    assert panel._layer_id(panel.tree.currentItem()) == made
    panel._new_layer()
    assert _names(scene.layers)[3:5] == [scene.layers.get(made).name,
                                         scene.layers.get(
                                             scene.layers.current_id).name], \
        "the second + went above the layer the first one made"


def test_a_new_sublayer_is_the_picked_row_too():
    scene, panel = _panel()
    walls, _inner, _outer, _roof = _house(scene, panel)
    _pick(panel, walls.id)
    panel._new_sublayer()
    assert panel._layer_id(panel.tree.currentItem()) == scene.layers.current_id
