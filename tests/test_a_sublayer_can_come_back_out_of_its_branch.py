"""A sublayer can be taken back out to the level above it.

A layer could be dragged into another one from the day sublayers landed,
but the only way back out was to let go of it over the blank space under
the last row, which the tree reads as "no target" and so as the top level.
Nothing said so, and the first user to try it asked outright: "i cant see
how i would be able to take a sublayer back to the level of a parent
layer? is there somewhere i drag it?". Worse, that blank space is gone as
soon as the layers fill the panel, so the one way out disappears exactly
when a drawing has enough layers to need it.

So the way out is a button beside the one that makes a sublayer, and a
right-click menu that names the branch it would leave. Out means one level
at a time - a layer that comes out of Walls::Exterior lands in Walls,
beside the parent it left - with the top level a second entry for anything
buried deeper.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import QApplication, QPushButton

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


def _house(scene):
    """Walls, with an Interior and an Exterior under it, and a Roof beside.

    Cladding sits under Exterior, three deep, which is the case that tells
    "out one level" apart from "out to the top".
    """
    walls = scene.layers.create("Walls")
    inner = scene.layers.create("Interior", parent=walls.id)
    outer = scene.layers.create("Exterior", parent=walls.id)
    clad = scene.layers.create("Cladding", parent=outer.id)
    roof = scene.layers.create("Roof")
    scene.notify()
    QApplication.processEvents()
    return walls, inner, outer, clad, roof


def _rows(panel) -> dict:
    """Every row in the tree, by layer id, however deep it sits."""
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


def _select(panel, *layer_ids):
    rows = _rows(panel)
    panel.tree.clearSelection()
    # Current first, then the selection: setting the current row is itself
    # a selection gesture, and in extended selection it shrinks the
    # selection to that one row, which is not what a ctrl-click does.
    if layer_ids:
        panel.tree.setCurrentItem(rows[layer_ids[0]])
    for layer_id in layer_ids:
        rows[layer_id].setSelected(True)
    QApplication.processEvents()


def _selected_ids(panel):
    return {panel._layer_id(item) for item in panel.tree.selectedItems()}


def _out_button(panel):
    """The button that takes the picked layer out of its branch."""
    for btn in panel.findChildren(QPushButton):
        if "out of" in (btn.toolTip() or "").lower():
            return btn
    raise AssertionError(
        "the panel has no button for taking a layer out of its branch")


def _click_out(panel):
    _out_button(panel).click()
    QApplication.processEvents()


def _path(scene, layer_id):
    return scene.layers.full_path(layer_id)


def _menu_texts(menu):
    return [a.text() for a in menu.actions() if not a.isSeparator()]


def _entry(menu, wanted):
    """The menu entry whose text starts with the given words."""
    for action in menu.actions():
        if action.text().startswith(wanted):
            return action
    raise AssertionError(
        f"no menu entry starting {wanted!r} in {_menu_texts(menu)}")


# -- the button --

def test_the_panel_offers_a_button_for_taking_a_layer_out_of_its_branch():
    _scene, panel = _panel()
    btn = _out_button(panel)
    assert btn.isVisible(), "the way out is there but the user cannot see it"


def test_the_button_lifts_a_sublayer_out_to_the_top_level():
    scene, panel = _panel()
    _walls, inner, _outer, _clad, _roof = _house(scene)
    _select(panel, inner.id)
    _click_out(panel)
    assert scene.layers.get(inner.id).parent is None, \
        "Interior is still stuck under Walls"
    assert inner.id in {panel._layer_id(panel.tree.topLevelItem(i))
                        for i in range(panel.tree.topLevelItemCount())}, \
        "the layer came out in the scene but the tree still draws it inside"


def test_a_layer_three_deep_comes_out_one_level_at_a_time():
    scene, panel = _panel()
    walls, _inner, _outer, clad, _roof = _house(scene)
    _select(panel, clad.id)
    _click_out(panel)
    assert scene.layers.get(clad.id).parent == walls.id, \
        f"Cladding went to {_path(scene, clad.id)}, not beside the Exterior " \
        "it came out of"


def test_a_layer_already_at_the_top_level_has_nowhere_to_come_out_to():
    scene, panel = _panel()
    walls, inner, _outer, _clad, roof = _house(scene)
    _select(panel, inner.id)
    _click_out(panel)
    _select(panel, roof.id)
    _click_out(panel)
    assert scene.layers.get(roof.id).parent is None
    panel.history.undo()
    assert scene.layers.get(inner.id).parent == walls.id, \
        "the press that could move nothing still cost the user an undo"


def test_every_picked_sublayer_comes_out_together():
    scene, panel = _panel()
    walls, inner, outer, _clad, _roof = _house(scene)
    _select(panel, inner.id, outer.id)
    _click_out(panel)
    assert scene.layers.get(inner.id).parent is None
    assert scene.layers.get(outer.id).parent is None
    panel.history.undo()
    assert scene.layers.get(inner.id).parent == walls.id
    assert scene.layers.get(outer.id).parent == walls.id, \
        "two layers moved by one press take two undos to put back"


def test_the_layer_stays_picked_after_it_comes_out():
    scene, panel = _panel()
    _walls, _inner, _outer, clad, _roof = _house(scene)
    _select(panel, clad.id)
    _click_out(panel)
    assert clad.id in _selected_ids(panel), \
        "the layer lost its selection, so a second press moves something else"


def _right_click(panel, layer_id):
    """A real right-click on a row, and the menu it puts up.

    The menu is opened with exec, which would sit in its own event loop
    until somebody clicked it, so the one this raises is stubbed to go up
    and come straight back down.
    """
    tree = panel.tree
    pos = tree.visualItemRect(_rows(panel)[layer_id]).center()
    opened = []
    build = panel._menu_for

    def spy(clicked_id):
        menu = build(clicked_id)
        menu.exec = lambda *a, **kw: None
        opened.append((clicked_id, menu))
        return menu

    panel._menu_for = spy
    try:
        QApplication.sendEvent(tree.viewport(), QContextMenuEvent(
            QContextMenuEvent.Reason.Mouse, pos,
            tree.viewport().mapToGlobal(pos)))
        QApplication.processEvents()
    finally:
        panel._menu_for = build
    assert opened, "a right-click on a layer row put up no menu at all"
    return opened[-1]


# -- the right-click menu --

def test_a_right_click_on_the_tree_opens_the_panels_own_menu():
    _scene, panel = _panel()
    assert panel.tree.contextMenuPolicy() == \
        Qt.ContextMenuPolicy.CustomContextMenu, \
        "a right-click on a layer offers nothing"


def test_a_right_click_lands_on_the_row_under_the_pointer():
    scene, panel = _panel()
    _walls, _inner, _outer, clad, _roof = _house(scene)
    clicked, menu = _right_click(panel, clad.id)
    assert clicked == clad.id, \
        "the menu came up for a different layer than the one right-clicked"
    assert any(t.startswith("Move out of Exterior")
               for t in _menu_texts(menu)), _menu_texts(menu)


def test_the_menu_on_a_sublayer_names_the_branch_it_would_leave():
    scene, panel = _panel()
    _walls, inner, _outer, _clad, _roof = _house(scene)
    menu = panel._menu_for(inner.id)
    assert any(t.startswith("Move out of Walls") for t in _menu_texts(menu)), \
        f"the menu says nothing about getting out: {_menu_texts(menu)}"


def test_the_menu_entry_takes_the_layer_out_of_its_branch():
    scene, panel = _panel()
    walls, _inner, _outer, clad, _roof = _house(scene)
    _select(panel, clad.id)
    _entry(panel._menu_for(clad.id), "Move out of Exterior").trigger()
    QApplication.processEvents()
    assert scene.layers.get(clad.id).parent == walls.id


def test_a_deep_layer_can_go_straight_to_the_top_level():
    scene, panel = _panel()
    _walls, _inner, _outer, clad, _roof = _house(scene)
    _select(panel, clad.id)
    _entry(panel._menu_for(clad.id), "Move to the top level").trigger()
    QApplication.processEvents()
    assert scene.layers.get(clad.id).parent is None, \
        f"Cladding only got as far as {_path(scene, clad.id)}"


def test_one_level_down_is_not_offered_the_top_level_twice():
    scene, panel = _panel()
    _walls, inner, _outer, _clad, _roof = _house(scene)
    texts = _menu_texts(panel._menu_for(inner.id))
    assert "Move to the top level" not in texts, \
        "a layer one level down is offered the same move under two names"


def test_a_top_level_layer_is_not_offered_a_way_out():
    scene, panel = _panel()
    _walls, _inner, _outer, _clad, roof = _house(scene)
    for action in panel._menu_for(roof.id).actions():
        assert not (action.text().startswith("Move out")
                    and action.isEnabled()), \
            "a layer at the top level is offered a way out of nothing"


def test_the_menu_acts_on_the_row_under_the_pointer_when_it_is_not_picked():
    scene, panel = _panel()
    walls, inner, _outer, clad, _roof = _house(scene)
    _select(panel, inner.id)
    _entry(panel._menu_for(clad.id), "Move out of Exterior").trigger()
    QApplication.processEvents()
    assert scene.layers.get(clad.id).parent == walls.id, \
        "the right-clicked layer stayed put"
    assert scene.layers.get(inner.id).parent == walls.id, \
        "the menu moved the selection instead of the row it was opened on"


def test_the_menu_moves_the_whole_selection_when_it_is_opened_on_one_of_them():
    scene, panel = _panel()
    walls, inner, outer, _clad, _roof = _house(scene)
    _select(panel, inner.id, outer.id)
    _entry(panel._menu_for(outer.id), "Move out of Walls").trigger()
    QApplication.processEvents()
    assert scene.layers.get(inner.id).parent is None
    assert scene.layers.get(outer.id).parent is None, \
        "only the right-clicked one of the picked layers came out"
    assert scene.layers.get(walls.id).parent is None
