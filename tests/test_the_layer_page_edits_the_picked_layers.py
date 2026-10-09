"""Properties edits a picked layer: one labelled row per thing.

Rhino's layer table makes you read a column header to know whether 0.25 is
the screen width or the print width (#40's thread). Here each value is a
row whose label carries its unit, every change is one undo step, and with
several layers picked a value they disagree on shows blank and setting it
sets it on all of them.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from serpentine3d.core import geometry as g
from serpentine3d.core.history import History
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui.layers_panel import LayersPanel
from serpentine3d.ui.properties import PropertiesPanel


def _setup(*names):
    scene = Scene()
    selection = SelectionManager(scene)
    history = History(scene)
    props = PropertiesPanel(scene, selection, history)
    panel = LayersPanel(scene, history, selection=selection)
    props.follow_layers(panel)
    props.show()
    made = [scene.layers.create(n) for n in names]
    scene.notify()
    QApplication.processEvents()
    return scene, selection, history, props, panel, made


def _pick(panel, *layer_ids):
    stack = [panel.tree.topLevelItem(i)
             for i in range(panel.tree.topLevelItemCount())]
    panel.tree.clearSelection()
    while stack:
        item = stack.pop()
        if panel._layer_id(item) in layer_ids:
            item.setSelected(True)
        stack.extend(item.child(i) for i in range(item.childCount()))
    QApplication.processEvents()


def _type(combo, text):
    combo.setEditText(text)
    combo.lineEdit().editingFinished.emit()
    QApplication.processEvents()


def test_print_width_is_its_own_row_in_millimetres():
    scene, _sel, history, props, panel, (walls,) = _setup("Walls")
    _pick(panel, walls.id)

    _type(props.layer_print, "0.35")

    assert scene.layers.get(walls.id).print_width == 0.35
    assert scene.layers.get(walls.id).lineweight == 1.4
    history.undo()
    assert scene.layers.get(walls.id).print_width == 0.0


def test_a_width_can_be_typed_with_its_unit():
    scene, _sel, _h, props, panel, (walls,) = _setup("Walls")
    _pick(panel, walls.id)

    _type(props.layer_print, "0.5 mm")
    _type(props.layer_screen, "2px")

    assert scene.layers.get(walls.id).print_width == 0.5
    assert scene.layers.get(walls.id).lineweight == 2.0


def test_nonsense_leaves_the_width_and_puts_it_back():
    scene, _sel, history, props, panel, (walls,) = _setup("Walls")
    scene.layers.set_print_width(walls.id, 0.25)
    _pick(panel, walls.id)

    _type(props.layer_print, "thick")

    assert scene.layers.get(walls.id).print_width == 0.25
    assert props.layer_print.currentText() == "0.25"
    assert not history.can_undo


def test_default_print_width_is_the_printer_default():
    scene, _sel, _h, props, panel, (walls,) = _setup("Walls")
    scene.layers.set_print_width(walls.id, 0.5)
    _pick(panel, walls.id)

    _type(props.layer_print, "Default")

    assert scene.layers.get(walls.id).print_width == 0.0


def test_section_hatch_and_linetype():
    scene, _sel, _h, props, panel, (walls,) = _setup("Walls")
    _pick(panel, walls.id)

    props.layer_hatch.setCurrentIndex(props.layer_hatch.findData("cross"))
    props.layer_linetype.setCurrentText("Dashed")

    assert scene.layers.get(walls.id).hatch == "cross"
    assert scene.layers.get(walls.id).linetype == "Dashed"

    props.layer_hatch.setCurrentIndex(props.layer_hatch.findData(""))

    assert scene.layers.get(walls.id).hatch == ""


def test_renaming_from_properties():
    scene, _sel, _h, props, panel, (walls,) = _setup("Walls")
    _pick(panel, walls.id)

    props.layer_name.setText("Concrete walls")
    props.layer_name.editingFinished.emit()

    assert scene.layers.get(walls.id).name == "Concrete walls"
    assert props.layer_head.title.text() == "Concrete walls"


def test_visible_and_locked():
    scene, _sel, _h, props, panel, (walls,) = _setup("Walls")
    _pick(panel, walls.id)

    props.layer_visible.click()
    props.layer_locked.click()

    assert not scene.layers.get(walls.id).visible
    assert scene.layers.get(walls.id).locked


def test_two_layers_that_differ_show_blank_and_take_one_value():
    scene, _sel, history, props, panel, (a, b) = _setup("A", "B")
    scene.layers.set_print_width(a.id, 0.25)
    scene.layers.set_print_width(b.id, 0.5)
    _pick(panel, a.id, b.id)

    assert props.layer_head.title.text() == "2 layers"
    assert props.layer_print.currentText() == ""
    assert not props.layer_name.isEnabled()

    _type(props.layer_print, "0.35")

    assert scene.layers.get(a.id).print_width == 0.35
    assert scene.layers.get(b.id).print_width == 0.35
    history.undo()
    assert scene.layers.get(a.id).print_width == 0.25
    assert scene.layers.get(b.id).print_width == 0.5


def test_mixed_visibility_shows_partly_checked():
    scene, _sel, _h, props, panel, (a, b) = _setup("A", "B")
    scene.layers.set_visible(b.id, False)
    _pick(panel, a.id, b.id)

    assert props.layer_visible.checkState() == Qt.CheckState.PartiallyChecked

    props.layer_visible.click()

    assert scene.layers.get(a.id).visible and scene.layers.get(b.id).visible
    assert props.layer_visible.checkState() == Qt.CheckState.Checked


def test_the_held_selection_can_be_moved_onto_the_layer():
    scene, selection, history, props, panel, (walls,) = _setup("Walls")
    box = scene.add(g.make_box((0, 0, 0), 1, 1, 1))
    selection.set([box.id])
    _pick(panel, walls.id)

    assert props.layer_move_here.isVisibleTo(props)

    props.layer_move_here.click()

    assert scene.get(box.id).layer_id == walls.id
    assert selection.ids == [box.id]
    assert props.shown() == "layers"
    assert not props.layer_move_here.isVisibleTo(props)
    history.undo()
    assert scene.get(box.id).layer_id != walls.id


def test_select_objects_moves_on_to_them():
    scene, selection, _h, props, panel, (walls,) = _setup("Walls")
    on = scene.add(g.make_box((0, 0, 0), 1, 1, 1), layer_id=walls.id)
    scene.add(g.make_box((3, 0, 0), 1, 1, 1))
    _pick(panel, walls.id)

    props.layer_select.click()
    QApplication.processEvents()

    assert selection.ids == [on.id]
    assert props.shown() == "objects"
    assert not selection.held


def test_an_edit_made_elsewhere_shows_on_the_page():
    scene, _sel, _h, props, panel, (walls,) = _setup("Walls")
    _pick(panel, walls.id)

    scene.layers.set_print_width(walls.id, 0.7)
    scene.notify()

    assert props.layer_print.currentText() == "0.7"


def test_an_empty_layer_offers_nothing_to_select():
    """The theme draws a disabled button like any other, so one with
    nothing to do is hidden rather than greyed."""
    scene, _sel, _h, props, panel, (walls,) = _setup("Walls")
    _pick(panel, walls.id)

    assert not props.layer_select.isVisibleTo(props)

    scene.add(g.make_box((0, 0, 0), 1, 1, 1), layer_id=walls.id)
    scene.notify()

    assert props.layer_select.isVisibleTo(props)
