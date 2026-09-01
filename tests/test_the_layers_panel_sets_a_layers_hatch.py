"""The Layers panel is where a layer's hatch gets set: in the row menu.

The panel's five columns already fill the 280px dock a fresh window gives
it exactly, with the layer name two pixels wider than the name needs, so
a sixth column would push the name of the layer everything is drawn on
back to reading "Defa...". The row menu costs no width, and it is where
the panel already keeps the moves that have no room of their own.

It follows the rest of that menu: it acts on every picked layer when the
row belongs to the selection, so a dozen layers become concrete in one
go, and it goes through history like any other edit.
"""

from __future__ import annotations

from serpentine3d.core.history import History
from serpentine3d.core.layers import DEFAULT_LAYER_ID
from serpentine3d.core.scene import Scene
from serpentine3d.ui.layers_panel import LayersPanel


def _panel():
    scene = Scene()
    return scene, LayersPanel(scene, History(scene))


def _rows(panel):
    return {panel._layer_id(panel.tree.topLevelItem(i)):
            panel.tree.topLevelItem(i)
            for i in range(panel.tree.topLevelItemCount())}


def _hatch_entries(panel, layer_id):
    """The Hatch submenu's entries, and the menu they hang off.

    The menu comes back with them because it has to be held onto: it is
    built for one click, and Qt takes it away again the moment nothing
    names it, entries and all.
    """
    menu = panel._menu_for(layer_id)
    for action in menu.actions():
        if action.text() == "Hatch":
            return menu, action.menu().actions()
    entries = [a.text() for a in menu.actions()]
    raise AssertionError(f"no Hatch entry in the row menu: {entries}")


def _pick(panel, layer_id, text):
    """Choose one of the patterns, the way a click on it does."""
    _menu, entries = _hatch_entries(panel, layer_id)
    for action in entries:
        if action.text() == text:
            action.trigger()
            return
    raise AssertionError(f"no {text!r} pattern to pick")


def test_the_row_menu_offers_every_pattern_and_a_way_out_of_them():
    _scene, panel = _panel()
    _menu, entries = _hatch_entries(panel, DEFAULT_LAYER_ID)
    assert [a.text() for a in entries] == ["None", "Lines", "Cross", "Solid"]


def test_picking_a_pattern_sets_it_on_the_layer():
    scene, panel = _panel()
    _pick(panel, DEFAULT_LAYER_ID, "Cross")
    assert scene.layers.get(DEFAULT_LAYER_ID).hatch == "cross"


def test_the_pattern_the_layer_already_has_is_ticked():
    """The menu is the only place the value shows, so it has to show it."""
    scene, panel = _panel()
    scene.layers.set_hatch(DEFAULT_LAYER_ID, "solid")
    _menu, entries = _hatch_entries(panel, DEFAULT_LAYER_ID)
    assert [a.text() for a in entries if a.isChecked()] == ["Solid"]


def test_a_layer_with_no_hatch_has_none_ticked():
    _scene, panel = _panel()
    _menu, entries = _hatch_entries(panel, DEFAULT_LAYER_ID)
    assert [a.text() for a in entries if a.isChecked()] == ["None"]


def test_none_takes_the_hatch_back_off_the_layer():
    scene, panel = _panel()
    scene.layers.set_hatch(DEFAULT_LAYER_ID, "cross")
    panel.rebuild()
    _pick(panel, DEFAULT_LAYER_ID, "None")
    assert scene.layers.get(DEFAULT_LAYER_ID).hatch == ""


def test_a_pattern_lands_on_every_picked_layer():
    scene, panel = _panel()
    walls = scene.layers.create("Walls").id
    slab = scene.layers.create("Slab").id
    panel.rebuild()
    rows = _rows(panel)
    rows[walls].setSelected(True)
    rows[slab].setSelected(True)
    _pick(panel, walls, "Cross")
    assert scene.layers.get(walls).hatch == "cross"
    assert scene.layers.get(slab).hatch == "cross", \
        "only the row under the pointer took the pattern"
    assert scene.layers.get(DEFAULT_LAYER_ID).hatch == "", \
        "a layer nobody picked was hatched too"


def test_picking_a_pattern_can_be_undone():
    scene, panel = _panel()
    scene.layers.set_hatch(DEFAULT_LAYER_ID, "lines")
    panel.rebuild()
    _pick(panel, DEFAULT_LAYER_ID, "Solid")
    panel.history.undo()
    assert scene.layers.get(DEFAULT_LAYER_ID).hatch == "lines"


def test_layers_that_disagree_have_nothing_ticked():
    """Two materials picked at once are not one material."""
    scene, panel = _panel()
    walls = scene.layers.create("Walls").id
    slab = scene.layers.create("Slab").id
    scene.layers.set_hatch(walls, "cross")
    scene.layers.set_hatch(slab, "solid")
    panel.rebuild()
    rows = _rows(panel)
    rows[walls].setSelected(True)
    rows[slab].setSelected(True)
    _menu, entries = _hatch_entries(panel, walls)
    assert [a.text() for a in entries if a.isChecked()] == []
