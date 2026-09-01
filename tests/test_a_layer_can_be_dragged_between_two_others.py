"""A layer lands where it was dropped: inside a layer, or between two.

Dropping a layer onto another one has put it inside since sublayers
landed, which is half of what a hand expects from a list it can drag.
The other half is dropping between two rows: that is how a layer is put
in its place without stepping it there one arrow press at a time, how it
goes to either end of the list, and how it comes back out of a branch,
which is what the first user to try it asked for ("you should be able to
just drag it back").

Qt offers two pixels at the top and bottom of a row for this, which no
hand can hit, so a row is read in three bands instead: a quarter at each
edge means beside it, and the half in between means inside it.
"""

from __future__ import annotations

from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt
from PySide6.QtGui import QDragLeaveEvent, QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from serpentine3d.core.history import History
from serpentine3d.core.layers import LayerManager
from serpentine3d.core.scene import Scene
from serpentine3d.ui.layers_panel import LayersPanel


def _house(layers):
    """Walls, holding Interior and Exterior, then Roof, then Site."""
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

def test_a_layer_lands_in_front_of_the_one_it_was_dropped_above():
    layers = LayerManager()
    _walls, _inner, _outer, roof, _site = _house(layers)
    assert layers.place(roof.id, None, before_id="default") is True
    assert _names(layers) == ["Roof", "Default", "Walls", "Interior",
                              "Exterior", "Site"], _names(layers)


def test_a_layer_dropped_with_nothing_in_front_of_it_goes_last():
    layers = LayerManager()
    walls, _inner, _outer, _roof, _site = _house(layers)
    assert layers.place(walls.id, None) is True
    assert _names(layers) == ["Default", "Roof", "Site", "Walls",
                              "Interior", "Exterior"], _names(layers)


def test_a_layer_dropped_between_two_sublayers_joins_them():
    layers = LayerManager()
    walls, _inner, outer, roof, _site = _house(layers)
    layers.place(roof.id, walls.id, before_id=outer.id)
    assert _child_names(layers, walls.id) == ["Interior", "Roof", "Exterior"]
    assert layers.get(roof.id).parent == walls.id


def test_a_sublayer_dropped_among_the_top_layers_leaves_its_branch():
    layers = LayerManager()
    walls, inner, _outer, roof, _site = _house(layers)
    layers.place(inner.id, None, before_id=roof.id)
    assert layers.get(inner.id).parent is None, \
        "the layer is still stuck in the branch it was dragged out of"
    assert _names(layers) == ["Default", "Walls", "Exterior", "Interior",
                              "Roof", "Site"], _names(layers)
    assert _child_names(layers, walls.id) == ["Exterior"]


def test_a_layer_takes_its_branch_where_it_is_dropped():
    layers = LayerManager()
    walls, _inner, _outer, _roof, site = _house(layers)
    layers.place(walls.id, None, before_id=site.id)
    assert _names(layers) == ["Default", "Roof", "Walls", "Interior",
                              "Exterior", "Site"], _names(layers)
    assert _child_names(layers, walls.id) == ["Interior", "Exterior"], \
        "the branch was left behind where the layer used to be"


def test_a_layer_cannot_be_dropped_inside_its_own_branch():
    layers = LayerManager()
    walls, inner, _outer, _roof, _site = _house(layers)
    for parent, before in ((walls.id, None),        # inside itself
                           (inner.id, None),        # inside its own child
                           (walls.id, inner.id)):   # in front of that child
        try:
            layers.place(walls.id, parent, before_id=before)
        except ValueError:
            pass
        else:
            raise AssertionError(
                "a layer was moved under itself, and that branch has no top")
    assert layers.get(walls.id).parent is None
    assert _child_names(layers, walls.id) == ["Interior", "Exterior"]


def test_it_can_only_land_in_front_of_a_layer_in_the_branch_it_joins():
    """Otherwise the caller is asking for two different places at once."""
    layers = LayerManager()
    _walls, inner, _outer, roof, _site = _house(layers)
    try:
        layers.place(roof.id, None, before_id=inner.id)
    except ValueError:
        return
    raise AssertionError("a layer landed in front of another layer's sublayer")


def test_a_drop_that_puts_a_layer_back_where_it_was_says_nothing_moved():
    layers = LayerManager()
    _walls, _inner, _outer, roof, site = _house(layers)
    assert layers.place(roof.id, None, before_id=site.id) is False, \
        "a drop that moved nothing still claims a move, so it costs an undo"


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


def _point(panel, target_id, where):
    """A point in a row: on its top edge, in its middle, on its bottom."""
    tree = panel.tree
    if target_id is None:
        # the bare tree under the last row
        return QPoint(tree.viewport().rect().center().x(),
                      tree.viewport().rect().bottom() - 2)
    rect = tree.visualItemRect(_rows(panel)[target_id])
    return QPoint(rect.center().x(), {
        "above": rect.top() + 1,
        "on": rect.center().y(),
        "below": rect.bottom() - 1}[where])


def _drop(panel, moving_ids, target_id, where="on"):
    """Pick up one or more rows and let go of them over a point."""
    tree = panel.tree
    rows = _rows(panel)
    tree.clearSelection()
    tree.setCurrentItem(rows[moving_ids[0]])
    for layer_id in moving_ids:
        rows[layer_id].setSelected(True)
    event = QDropEvent(QPointF(_point(panel, target_id, where)),
                       Qt.DropAction.MoveAction, QMimeData(),
                       Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier)
    tree.dropEvent(event)
    QTest.qWait(50)
    QApplication.processEvents()


def _house_panel():
    scene, panel = _panel()
    layers = _house(scene.layers)
    scene.notify()
    QApplication.processEvents()
    return scene, panel, layers


def test_a_drop_on_the_middle_of_a_row_still_puts_the_layer_inside_it():
    scene, panel, (walls, _inner, _outer, roof, _site) = _house_panel()
    _drop(panel, [roof.id], walls.id, "on")
    assert scene.layers.get(roof.id).parent == walls.id, \
        "the drop that has always meant 'inside this one' stopped meaning it"


def test_a_drop_on_the_top_of_a_row_puts_the_layer_in_front_of_it():
    scene, panel, (walls, _inner, _outer, _roof, site) = _house_panel()
    _drop(panel, [site.id], walls.id, "above")
    assert scene.layers.get(site.id).parent is None, \
        "a drop between two layers put the layer inside one of them"
    assert _drawn(panel) == ["Default", "Site", "Walls", "Interior",
                             "Exterior", "Roof"], _drawn(panel)


def test_a_drop_on_the_bottom_of_a_row_puts_the_layer_after_it():
    scene, panel, (_walls, _inner, _outer, _roof, site) = _house_panel()
    _drop(panel, [site.id], "default", "below")
    assert scene.layers.get(site.id).parent is None, \
        "a drop under a layer put the layer inside it"
    assert _drawn(panel) == ["Default", "Site", "Walls", "Interior",
                             "Exterior", "Roof"], _drawn(panel)


def test_a_drop_under_the_open_layer_makes_the_layer_its_first_sublayer():
    """The line drawn there sits over the first sublayer, so that is where
    it goes: the row under an open branch belongs to the branch."""
    scene, panel, (walls, inner, _outer, roof, _site) = _house_panel()
    panel.tree.expandAll()
    QApplication.processEvents()
    _drop(panel, [roof.id], walls.id, "below")
    assert scene.layers.get(roof.id).parent == walls.id
    assert _child_names(scene.layers, walls.id) == ["Roof", "Interior",
                                                    "Exterior"]


def test_a_sublayer_dragged_between_two_top_layers_comes_out_of_its_branch():
    """The way back out, without going near a button."""
    scene, panel, (walls, inner, _outer, roof, _site) = _house_panel()
    _drop(panel, [inner.id], roof.id, "above")
    assert scene.layers.get(inner.id).parent is None, \
        "Interior is still stuck under Walls"
    assert _drawn(panel) == ["Default", "Walls", "Exterior", "Interior",
                             "Roof", "Site"], _drawn(panel)


def test_a_drop_above_the_first_row_puts_the_layer_at_the_top():
    scene, panel, (_walls, _inner, _outer, _roof, site) = _house_panel()
    _drop(panel, [site.id], "default", "above")
    assert _drawn(panel)[0] == "Site", _drawn(panel)


def test_a_drop_below_the_last_row_puts_the_layer_at_the_end():
    scene, panel, (walls, _inner, _outer, _roof, _site) = _house_panel()
    _drop(panel, [walls.id], None)
    assert _drawn(panel) == ["Default", "Roof", "Site", "Walls", "Interior",
                             "Exterior"], _drawn(panel)


def test_dragged_layers_land_in_the_order_they_were_in():
    scene, panel, (walls, _inner, _outer, roof, site) = _house_panel()
    _drop(panel, [roof.id, site.id], walls.id, "above")
    assert _drawn(panel) == ["Default", "Roof", "Site", "Walls", "Interior",
                             "Exterior"], _drawn(panel)


def test_a_drop_is_one_undo():
    scene, panel, (walls, _inner, _outer, roof, site) = _house_panel()
    before = _names(scene.layers)
    _drop(panel, [roof.id, site.id], walls.id, "above")
    panel.history.undo()
    assert _names(scene.layers) == before, \
        "one drop of two layers takes two undos to put back"


def test_a_drop_that_moves_nothing_costs_no_undo():
    scene, panel, (walls, _inner, _outer, roof, site) = _house_panel()
    _drop(panel, [site.id], walls.id, "above")
    _drop(panel, [site.id], walls.id, "above")
    panel.history.undo()
    assert _drawn(panel)[1] == "Walls", \
        "the drop that moved nothing still cost the user an undo"


# -- and the panel says where it would land --

def test_the_tree_marks_the_row_a_layer_would_drop_into():
    _scene, panel, (walls, _inner, _outer, _roof, _site) = _house_panel()
    spot = panel.tree._drop_spot(_point(panel, walls.id, "on"))
    assert (spot.parent, spot.before, spot.where) == (walls.id, None, "on")


def test_the_tree_marks_the_gap_a_layer_would_drop_between():
    _scene, panel, (walls, _inner, _outer, _roof, _site) = _house_panel()
    spot = panel.tree._drop_spot(_point(panel, walls.id, "above"))
    assert (spot.parent, spot.before, spot.where) == (None, walls.id, "above")


def test_the_mark_is_dropped_when_the_layer_is_dragged_back_out():
    _scene, panel, (walls, _inner, _outer, _roof, _site) = _house_panel()
    panel.tree._drop_at = panel.tree._drop_spot(
        _point(panel, walls.id, "above"))
    panel.tree.dragLeaveEvent(QDragLeaveEvent())
    assert panel.tree._drop_at is None, \
        "the line stays on the tree after the drag has left it"
