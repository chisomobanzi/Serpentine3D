"""The layers panel draws the tree the model now holds, and can build one.

A layer can sit under another layer, but until the panel shows it that is
a fact about a file and nothing an architect can use. Rhino's layer panel
indents a sublayer under its parent, opens and closes a branch, makes a
new sublayer under the layer you have picked, and moves a layer by
dragging it onto another one. This is that panel.

Two things it must not lose in the process: the panel redraws its whole
tree from the scene on every notify, so an open branch has to stay open
across a redraw the same way the selection already does, and a drop
happens inside Qt's own handling, so the redraw has to wait a turn.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QMimeData, QPointF, Qt
from PySide6.QtGui import QColor, QDropEvent, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from serpentine3d.core.history import History
from serpentine3d.core.scene import Scene
from serpentine3d.ui import theme
from serpentine3d.ui.layers_panel import LayersPanel

_NAME_COL = 0


def _panel():
    scene = Scene()
    panel = LayersPanel(scene, History(scene))
    panel.resize(400, 300)
    panel.show()
    QApplication.processEvents()
    return scene, panel


def _walls_and_roof(scene, panel):
    """Walls with an Interior under it, and a Roof beside them."""
    walls = scene.layers.create("Walls")
    inner = scene.layers.create("Interior", parent=walls.id)
    roof = scene.layers.create("Roof")
    scene.notify()
    QApplication.processEvents()
    return walls, inner, roof


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


def _top_level_ids(panel) -> list:
    return [panel._layer_id(panel.tree.topLevelItem(i))
            for i in range(panel.tree.topLevelItemCount())]


def _settle():
    """Let the redraw a click or a drop defers to the next turn happen."""
    QTest.qWait(50)
    QApplication.processEvents()


# -- the shape of the tree --

def test_a_sublayer_is_drawn_under_its_parent():
    scene, panel = _panel()
    walls, inner, roof = _walls_and_roof(scene, panel)
    rows = _rows(panel)
    assert rows[inner.id].parent() is rows[walls.id], \
        "the sublayer was drawn as a layer of its own"
    assert inner.id not in _top_level_ids(panel)
    assert roof.id in _top_level_ids(panel)


def test_a_layer_two_deep_is_drawn_two_deep():
    scene, panel = _panel()
    walls, inner, _roof = _walls_and_roof(scene, panel)
    trim = scene.layers.create("Trim", parent=inner.id)
    scene.notify()
    QApplication.processEvents()
    rows = _rows(panel)
    assert rows[trim.id].parent() is rows[inner.id]
    assert rows[inner.id].parent() is rows[walls.id]


def test_a_branch_can_be_opened_and_closed():
    scene, panel = _panel()
    walls, _inner, _roof = _walls_and_roof(scene, panel)
    assert _rows(panel)[walls.id].childCount() == 1, \
        "a parent with no expander is a parent nobody can open"


def test_an_open_branch_stays_open_when_the_panel_redraws():
    scene, panel = _panel()
    walls, _inner, _roof = _walls_and_roof(scene, panel)
    _rows(panel)[walls.id].setExpanded(False)
    scene.notify()
    QApplication.processEvents()
    assert _rows(panel)[walls.id].isExpanded() is False, \
        "a closed branch sprang open again on the next redraw"
    _rows(panel)[walls.id].setExpanded(True)
    scene.notify()
    QApplication.processEvents()
    assert _rows(panel)[walls.id].isExpanded() is True


def test_a_picked_sublayer_stays_picked_across_a_redraw():
    scene, panel = _panel()
    _walls, inner, _roof = _walls_and_roof(scene, panel)
    _rows(panel)[inner.id].setSelected(True)
    scene.notify()
    QApplication.processEvents()
    assert _rows(panel)[inner.id].isSelected(), \
        "the redraw only put the top-level rows back"


def test_a_layer_under_a_switched_off_parent_looks_switched_off():
    """Its own switch is still on, and the drawing still shows nothing."""
    scene, panel = _panel()
    walls, inner, roof = _walls_and_roof(scene, panel)
    scene.layers.set_visible(walls.id, False)
    scene.notify()
    QApplication.processEvents()
    rows = _rows(panel)
    assert rows[inner.id].checkState(1) == Qt.CheckState.Checked, \
        "the child's own switch was turned off behind the user's back"
    # Named colour, not "different from the row next to it": a row nobody
    # has dimmed carries no colour of its own at all, so comparing the two
    # passes whatever the dimmed one is - including the palette's disabled
    # grey, which the app's stylesheet paints in the same grey as ordinary
    # text, so nothing looks any different in the shipped window.
    assert rows[inner.id].foreground(_NAME_COL).color() == \
        QColor(theme.TEXT_MUTED), \
        "a layer nobody can see reads the same as one everybody can"
    assert rows[roof.id].foreground(_NAME_COL).color() != \
        QColor(theme.TEXT_MUTED), \
        "a layer everybody can see is dimmed too"


# -- making one --

def test_the_new_sublayer_button_makes_one_under_the_picked_layer():
    scene, panel = _panel()
    walls, _inner, _roof = _walls_and_roof(scene, panel)
    panel.tree.setCurrentItem(_rows(panel)[walls.id])
    panel._new_sublayer()
    QApplication.processEvents()
    names = [la.name for la in scene.layers.children(walls.id)]
    assert len(names) == 2, "no new layer arrived under Walls"


def test_a_new_sublayer_becomes_the_current_layer():
    scene, panel = _panel()
    walls, _inner, _roof = _walls_and_roof(scene, panel)
    panel.tree.setCurrentItem(_rows(panel)[walls.id])
    panel._new_sublayer()
    QApplication.processEvents()
    made = scene.layers.children(walls.id)[-1]
    assert scene.layers.current_id == made.id


def test_a_new_sublayer_is_on_screen_the_moment_it_is_made():
    scene, panel = _panel()
    walls, _inner, _roof = _walls_and_roof(scene, panel)
    _rows(panel)[walls.id].setExpanded(False)
    panel.tree.setCurrentItem(_rows(panel)[walls.id])
    panel._new_sublayer()
    QApplication.processEvents()
    assert _rows(panel)[walls.id].isExpanded(), \
        "the new layer was made inside a closed branch, out of sight"


def test_the_new_sublayer_button_needs_a_layer_to_put_one_under():
    scene, panel = _panel()
    _walls_and_roof(scene, panel)
    panel.tree.setCurrentItem(None)
    before = len(scene.layers.all())
    panel._new_sublayer()
    QApplication.processEvents()
    assert len(scene.layers.all()) == before


# -- moving one --

def _drop_on(panel, moving_id, target_id):
    """Drag a row and let go of it on another row, or on bare tree.

    A drop lands inside Qt's own handling of the mouse, which is the case
    the panel has to defer its redraw for, so this goes through the real
    event rather than calling the panel's own method.
    """
    tree = panel.tree
    rows = _rows(panel)
    tree.setCurrentItem(rows[moving_id])
    rows[moving_id].setSelected(True)
    if target_id is None:
        # below the last row: the bare tree, which means the top level
        pos = QPointF(tree.viewport().rect().center().x(),
                      tree.viewport().rect().bottom() - 2)
    else:
        rect = tree.visualRect(tree.indexFromItem(rows[target_id], _NAME_COL))
        pos = QPointF(rect.center())
    event = QDropEvent(pos, Qt.DropAction.MoveAction, QMimeData(),
                       Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier)
    tree.dropEvent(event)
    _settle()


def test_dropping_a_layer_on_another_puts_it_underneath():
    scene, panel = _panel()
    walls, _inner, roof = _walls_and_roof(scene, panel)
    _drop_on(panel, roof.id, walls.id)
    assert scene.layers.get(roof.id).parent == walls.id
    assert _rows(panel)[roof.id].parent() is _rows(panel)[walls.id]


def test_dropping_a_layer_on_bare_tree_puts_it_back_at_the_top():
    scene, panel = _panel()
    _walls, inner, _roof = _walls_and_roof(scene, panel)
    _drop_on(panel, inner.id, None)
    assert scene.layers.get(inner.id).parent is None
    assert inner.id in _top_level_ids(panel)


def test_a_layer_cannot_be_dropped_onto_its_own_child():
    scene, panel = _panel()
    walls, inner, _roof = _walls_and_roof(scene, panel)
    _drop_on(panel, walls.id, inner.id)
    assert scene.layers.get(walls.id).parent is None, \
        "a layer was moved under itself, and the branch has no top now"
    assert scene.layers.get(inner.id).parent == walls.id


def test_dropping_a_layer_on_itself_changes_nothing():
    scene, panel = _panel()
    _walls, inner, _roof = _walls_and_roof(scene, panel)
    _drop_on(panel, inner.id, inner.id)
    assert scene.layers.get(inner.id).parent is not None


def test_a_move_undoes_in_one_step():
    scene, panel = _panel()
    walls, _inner, roof = _walls_and_roof(scene, panel)
    _drop_on(panel, roof.id, walls.id)
    assert scene.layers.get(roof.id).parent == walls.id
    panel.history.undo()
    assert scene.layers.get(roof.id).parent is None


def test_the_objects_on_a_moved_layer_go_with_it():
    """Moving a layer moves what is drawn on it; nothing changes hands."""
    from serpentine3d.core import geometry as g
    scene, panel = _panel()
    walls, _inner, roof = _walls_and_roof(scene, panel)
    obj = scene.add(g.make_line((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
                    layer_id=roof.id)
    _drop_on(panel, roof.id, walls.id)
    assert scene.get(obj.id).layer_id == roof.id


# -- deleting one --

def test_deleting_a_parent_takes_its_branch_out_of_the_tree():
    scene, panel = _panel()
    walls, inner, roof = _walls_and_roof(scene, panel)
    panel.tree.setCurrentItem(_rows(panel)[walls.id])
    panel._delete_layer()
    QApplication.processEvents()
    rows = _rows(panel)
    assert walls.id not in rows and inner.id not in rows
    assert roof.id in rows


def test_a_double_click_on_a_sublayer_makes_it_the_current_layer():
    """The indent must not put the row out of the pointer's reach."""
    scene, panel = _panel()
    _walls, inner, _roof = _walls_and_roof(scene, panel)
    tree = panel.tree
    rect = tree.visualRect(tree.indexFromItem(_rows(panel)[inner.id],
                                              _NAME_COL))
    point = QPointF(rect.center())
    for typ in (QEvent.Type.MouseButtonPress,
                QEvent.Type.MouseButtonRelease,
                QEvent.Type.MouseButtonDblClick,
                QEvent.Type.MouseButtonRelease):
        QApplication.sendEvent(tree.viewport(), QMouseEvent(
            typ, point, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier))
    _settle()
    assert scene.layers.current_id == inner.id
