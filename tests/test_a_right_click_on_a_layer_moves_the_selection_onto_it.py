"""Right-click a layer and move what is selected onto it (issue #27).

Asked for: with objects selected, right-click another layer in the panel
and have the option to move them there. Rhino calls it "Change Object
Layer"; the request itself suggested "Move to layer" reads better, and
the entry goes one further and says what it will do, "Move 3 objects to
Walls", the way the menu's "Move out of Walls" already does.

The entry is always there so it can be found, and is greyed when there is
nothing it could do: nothing selected, or everything selected already on
that layer. It is one undo step, and it leaves the selection as it was.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from serpentine3d.core import geometry as g
from serpentine3d.core.history import History
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui.layers_panel import LayersPanel


@pytest.fixture
def env():
    if not QApplication.instance():
        QApplication([])
    scene = Scene()
    selection = SelectionManager(scene)
    history = History(scene)
    panel = LayersPanel(scene, history, selection=selection)
    panel.resize(400, 300)
    walls = scene.layers.create("Walls")
    roof = scene.layers.create("Roof")
    a = scene.add(g.make_box((0, 0, 0), 1, 1, 1), name="A", layer_id=walls.id)
    b = scene.add(g.make_box((5, 0, 0), 1, 1, 1), name="B", layer_id=walls.id)
    scene.notify()
    QApplication.processEvents()
    try:
        yield scene, selection, history, panel, walls, roof, a, b
    finally:
        panel.deleteLater()
        QApplication.processEvents()


def _row(panel, layer_id):
    """The tree row for a layer, however deep it sits."""
    def walk(item):
        for i in range(item.childCount()):
            child = item.child(i)
            if panel._layer_id(child) == layer_id:
                return child
            found = walk(child)
            if found is not None:
                return found
        return None
    row = walk(panel.tree.invisibleRootItem())
    assert row is not None, layer_id
    return row


def _entry(menu, starts_with="Move"):
    """The move-to-layer entry, whatever count and name it carries."""
    hits = [x for x in menu.actions()
            if not x.isSeparator() and x.text().startswith(starts_with)
            and " to " in x.text() or x.text() == "Move to layer"]
    assert len(hits) == 1, [x.text() for x in menu.actions()]
    return hits[0]


def test_the_entry_says_what_it_will_do(env):
    scene, sel, _h, panel, _walls, roof, a, b = env
    sel.set([a.id, b.id])

    entry = _entry(panel._menu_for(roof.id))

    assert entry.text() == "Move 2 objects to Roof"
    assert entry.isEnabled()


def test_one_object_is_not_plural(env):
    scene, sel, _h, panel, _walls, roof, a, _b = env
    sel.set([a.id])

    assert _entry(panel._menu_for(roof.id)).text() == "Move 1 object to Roof"


def test_triggering_it_moves_the_selection_onto_that_layer(env):
    scene, sel, _h, panel, walls, roof, a, b = env
    sel.set([a.id, b.id])

    _entry(panel._menu_for(roof.id)).trigger()

    assert scene.get(a.id).layer_id == roof.id
    assert scene.get(b.id).layer_id == roof.id


def test_the_selection_is_left_as_it_was(env):
    scene, sel, _h, panel, _walls, roof, a, b = env
    sel.set([a.id, b.id])

    _entry(panel._menu_for(roof.id)).trigger()

    assert sel.ids == [a.id, b.id]


def test_it_is_one_undo_step(env):
    scene, sel, history, panel, walls, roof, a, b = env
    sel.set([a.id, b.id])
    _entry(panel._menu_for(roof.id)).trigger()

    history.undo()

    assert scene.get(a.id).layer_id == walls.id
    assert scene.get(b.id).layer_id == walls.id


def test_with_nothing_selected_it_is_there_but_greyed(env):
    scene, sel, _h, panel, _walls, roof, _a, _b = env
    sel.clear()

    entry = _entry(panel._menu_for(roof.id))

    assert entry.text() == "Move to layer"
    assert not entry.isEnabled()


def test_moving_onto_the_layer_they_are_already_on_is_greyed(env):
    scene, sel, _h, panel, walls, _roof, a, b = env
    sel.set([a.id, b.id])

    entry = _entry(panel._menu_for(walls.id))

    assert not entry.isEnabled()


def test_only_the_ones_elsewhere_are_counted(env):
    """A on Walls, B already on Roof: moving to Roof moves one."""
    scene, sel, _h, panel, _walls, roof, a, b = env
    scene.update(b.id, layer_id=roof.id)
    sel.set([a.id, b.id])

    entry = _entry(panel._menu_for(roof.id))

    assert entry.text() == "Move 1 object to Roof"
    assert entry.isEnabled()


def test_the_target_is_the_row_under_the_pointer_not_the_picked_rows(env):
    """The other entries act on every picked layer; this one has a single
    destination, the layer that was right-clicked."""
    scene, sel, _h, panel, walls, roof, a, b = env
    sel.set([a.id])
    panel.tree.clearSelection()
    for lid in (walls.id, roof.id):
        _row(panel, lid).setSelected(True)
    assert panel._selected_layer_ids() == {walls.id, roof.id}

    _entry(panel._menu_for(roof.id)).trigger()

    assert scene.get(a.id).layer_id == roof.id


def test_a_panel_built_without_a_selection_offers_no_such_entry():
    """Every other caller builds the panel with scene and history alone
    and must go on working; without a selection there is nothing to move."""
    if not QApplication.instance():
        QApplication([])
    scene = Scene()
    panel = LayersPanel(scene, History(scene))
    roof = scene.layers.create("Roof")
    scene.notify()
    QApplication.processEvents()

    texts = [x.text() for x in panel._menu_for(roof.id).actions()]

    assert not any(t.startswith("Move") and " to " in t or t == "Move to layer"
                   for t in texts)
    panel.deleteLater()
    QApplication.processEvents()
