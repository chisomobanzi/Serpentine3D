"""Picking a layer shows it in Properties, and the selection stays.

From the layers study (direction D, docs/layers-study.html): Properties edits
a layer as well as objects, so a layer's look is no longer squeezed into the
list's narrow cells. A pick in the list must not throw away what the
viewport had selected, though. The objects stay selected, drawn dimmed so
that full gold still means "this is what Properties edits", and tabs in the
Properties title bar switch between the two.

The rules:

- picking layer rows shows them; the selection is untouched and held;
- a tab goes back to the objects, and the layer's tab stays until let go of;
- selecting different objects lets go of the layer; a command that sets
  the same selection again does not;
- with only one thing live the title just says Properties.
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

from serpentine3d.core import geometry as g
from serpentine3d.core.history import History
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui.layers_panel import LayersPanel
from serpentine3d.ui.properties import PropertiesPanel, SubjectTitleBar


def _setup():
    scene = Scene()
    selection = SelectionManager(scene)
    history = History(scene)
    props = PropertiesPanel(scene, selection, history)
    layers = LayersPanel(scene, history, selection=selection)
    props.follow_layers(layers)
    props.show()
    glazing = scene.layers.create("Glazing")
    box = scene.add(g.make_box((0, 0, 0), 1, 1, 1), name="Box")
    other = scene.add(g.make_box((3, 0, 0), 1, 1, 1), name="Other")
    scene.notify()
    QApplication.processEvents()
    return scene, selection, history, props, layers, glazing, box, other


def _rows(panel):
    out, stack = {}, [panel.tree.topLevelItem(i)
                      for i in range(panel.tree.topLevelItemCount())]
    while stack:
        item = stack.pop()
        out[panel._layer_id(item)] = item
        stack.extend(item.child(i) for i in range(item.childCount()))
    return out


def _pick(panel, *layer_ids):
    """What a click (or a shift-click) on layer rows leaves behind."""
    rows = _rows(panel)
    panel.tree.clearSelection()
    for layer_id in layer_ids:
        rows[layer_id].setSelected(True)
    QApplication.processEvents()


def test_picking_a_layer_shows_it_and_keeps_the_selection():
    scene, selection, _h, props, layers, glazing, box, _o = _setup()
    selection.set([box.id])

    _pick(layers, glazing.id)

    assert props.shown() == "layers"
    assert props.subjects() == ["objects", "layers"]
    assert selection.ids == [box.id]
    assert selection.held


def test_properties_shows_the_layer_page_for_a_layer():
    _s, selection, _h, props, layers, glazing, box, _o = _setup()
    selection.set([box.id])

    _pick(layers, glazing.id)

    assert props.pages.currentWidget() is props.layer_page
    assert props.layer_head.title.text() == "Glazing"

    props.show_subject("objects")

    assert props.pages.currentWidget() is props.object_page
    assert props.header.text() == "Box"


def test_the_objects_tab_goes_back_and_the_layer_stays():
    _s, selection, _h, props, layers, glazing, box, _o = _setup()
    selection.set([box.id])
    _pick(layers, glazing.id)

    props.show_subject("objects")

    assert props.shown() == "objects"
    assert not selection.held
    assert props.subjects() == ["objects", "layers"]
    assert layers.picked_layer_ids() == {glazing.id}

    props.show_subject("layers")

    assert props.shown() == "layers"
    assert selection.held


def test_selecting_something_else_lets_go_of_the_layer():
    _s, selection, _h, props, layers, glazing, box, other = _setup()
    selection.set([box.id])
    _pick(layers, glazing.id)

    selection.set([other.id])
    QApplication.processEvents()

    assert props.shown() == "objects"
    assert props.subjects() == ["objects"]
    assert layers.picked_layer_ids() == set()
    assert not selection.held


def test_setting_the_same_selection_again_keeps_the_layer():
    """Commands often hand back the selection they were given; that is not
    the user moving on from the layer."""
    _s, selection, _h, props, layers, glazing, box, _o = _setup()
    selection.set([box.id])
    _pick(layers, glazing.id)

    selection.set([box.id])
    QApplication.processEvents()

    assert props.shown() == "layers"
    assert layers.picked_layer_ids() == {glazing.id}


def test_a_layer_with_nothing_selected_is_shown_alone():
    _s, selection, _h, props, layers, glazing, _b, _o = _setup()

    _pick(layers, glazing.id)

    assert props.subjects() == ["layers"]
    assert props.shown() == "layers"
    assert not selection.held


def test_letting_go_of_the_layer_rows_goes_back_to_the_objects():
    _s, selection, _h, props, layers, glazing, box, _o = _setup()
    selection.set([box.id])
    _pick(layers, glazing.id)

    _pick(layers)

    assert props.subjects() == ["objects"]
    assert props.shown() == "objects"
    assert not selection.held


def test_clearing_the_selection_leaves_the_layer():
    _s, selection, _h, props, layers, glazing, box, _o = _setup()
    selection.set([box.id])
    _pick(layers, glazing.id)

    selection.clear()
    QApplication.processEvents()

    assert props.subjects() == ["layers"]
    assert props.shown() == "layers"
    assert not selection.held


def test_the_title_has_tabs_only_while_two_things_are_live():
    _s, selection, _h, props, layers, glazing, box, _o = _setup()
    bar = SubjectTitleBar(props)
    selection.set([box.id])

    assert bar.tab_texts() == []
    assert bar.title.text() == "Properties"

    _pick(layers, glazing.id)

    assert bar.tab_texts() == ["Box", "Glazing"]
    assert bar.tabs.currentIndex() == 1

    bar.tabs.setCurrentIndex(0)

    assert props.shown() == "objects"
    assert not selection.held


def test_a_tab_counts_what_it_holds():
    _s, selection, _h, props, layers, glazing, box, other = _setup()
    bar = SubjectTitleBar(props)
    selection.set([box.id, other.id])

    _pick(layers, glazing.id, "default")

    assert bar.tab_texts() == ["2 objects", "2 layers"]


def test_with_properties_closed_the_selection_is_not_dimmed():
    """Nothing on screen would say why it went dim."""
    _s, selection, _h, props, layers, glazing, box, _o = _setup()
    selection.set([box.id])
    props.hide()

    _pick(layers, glazing.id)

    assert not selection.held

    props.show()

    assert selection.held

    props.hide()

    assert not selection.held


# -- saying what is shown ----------------------------------------------------
# A tab reading "Default" could be anything called Default. The page and the
# tab both have to say it is a layer, and the layer page's count must not
# read like the selection tab's "3 objects".


def test_the_layer_page_says_it_is_a_layer():
    _s, _sel, _h, props, layers, glazing, _b, _o = _setup()

    _pick(layers, glazing.id)

    assert props.layer_head.kind.text() == "Layer"

    _pick(layers, glazing.id, "default")

    assert props.layer_head.kind.text() == "Layers"


def test_the_layer_count_says_it_counts_the_layer():
    scene, _sel, _h, props, layers, glazing, box, _o = _setup()

    _pick(layers, "default")

    assert props.layer_head.detail.text() == "2 objects on this layer"

    _pick(layers, glazing.id)

    assert props.layer_head.detail.text() == "Nothing on this layer yet"

    _pick(layers, glazing.id, "default")

    assert props.layer_head.detail.text() == "Default, Glazing · 2 objects on these layers"


def test_a_sublayer_shows_where_it_sits():
    scene, _sel, _h, props, layers, glazing, _b, _o = _setup()
    inner = scene.layers.create("Inner", parent=glazing.id)
    scene.notify()
    QApplication.processEvents()

    _pick(layers, inner.id)

    assert props.layer_head.detail.text() == "Glazing › Inner · Nothing on this layer yet"


def test_each_tab_says_what_it_is_when_pointed_at():
    _s, selection, _h, props, layers, glazing, box, _o = _setup()
    bar = SubjectTitleBar(props)
    selection.set([box.id])

    _pick(layers, glazing.id)

    assert bar.tabs.tabToolTip(0) == "The selection: Box"
    assert bar.tabs.tabToolTip(1) == "Layer: Glazing"


def test_the_layer_tab_is_marked_as_a_layer_not_as_a_swatch():
    """The mark is the Layers panel's own glyph, in the layer's colour, so
    the tab shares its shape with the panel it came from."""
    from serpentine3d.ui import icons
    _s, selection, _h, props, layers, glazing, box, _o = _setup()
    bar = SubjectTitleBar(props)
    selection.set([box.id])

    _pick(layers, glazing.id)

    def image(icon):
        return icon.pixmap(14, 14).toImage()

    assert image(bar.tabs.tabIcon(1)) == image(icons.layer_mark(glazing.color))
    assert image(bar.tabs.tabIcon(0)) == image(icons.selection_mark())


def test_both_panels_carry_their_icon_in_their_title():
    from serpentine3d.app import MainWindow
    win = MainWindow()
    try:
        props_bar = win._prop_dock.titleBarWidget()
        layers_bar = win._layer_dock.titleBarWidget()

        assert not props_bar.icon.pixmap().isNull()
        assert props_bar.title.text() == "Properties"
        assert not layers_bar.icon.pixmap().isNull()
        assert layers_bar.title.text() == "Layers"
        assert (props_bar.icon.pixmap().toImage()
                != layers_bar.icon.pixmap().toImage())
    finally:
        win.mark_saved()
        win.close()
