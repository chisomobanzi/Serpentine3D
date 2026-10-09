"""Every page of Properties opens the same way: what kind of thing, which one,
and a line of what and where.

The layer page got a gold "LAYER" heading so it could not be mistaken for
the selection; the object page had only a name, so a tab reading "Default"
or a header reading "Box" said nothing about what sort of thing either was.
Now both pages, and any later one (a sheet, say), share one header: a mark
and the kind in gold capitals, the name, and a muted line. The mark is the
same one the page's tab carries, because both are drawn from one
description of the subject, so a tab and its page cannot disagree.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from serpentine3d.core import geometry as g
from serpentine3d.core.history import History
from serpentine3d.core.layout import DetailView, Layout, TextNote
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui import icons
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
    scene.notify()
    QApplication.processEvents()
    return scene, selection, props, layers, glazing


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


def _image(pixmap):
    return pixmap.toImage()


def _head(head):
    return (head.kind.text(), head.title.text(), head.detail.text())


# -- the selection ------------------------------------------------------------

def test_one_object_says_object_its_name_and_what_and_where():
    scene, selection, props, _l, _g = _setup()
    box = scene.add(g.make_box((0, 0, 0), 1, 1, 1), name="Wall block")

    selection.set([box.id])

    assert _head(props.object_head) == ("Object", "Wall block",
                                        "Solid on Default")
    assert props.object_head.kind.isVisibleTo(props)
    assert props.header.text() == "Wall block"


def test_the_object_mark_is_the_selection_pointer():
    scene, selection, props, _l, _g = _setup()
    box = scene.add(g.make_box((0, 0, 0), 1, 1, 1))

    selection.set([box.id])

    assert (_image(props.object_head.mark.pixmap())
            == _image(icons.selection_mark().pixmap(14, 14)))


def test_several_objects_of_one_kind():
    scene, selection, props, _l, _g = _setup()
    a = scene.add(g.make_box((0, 0, 0), 1, 1, 1))
    b = scene.add(g.make_box((3, 0, 0), 1, 1, 1))

    selection.set([a.id, b.id])

    assert _head(props.object_head) == ("Objects", "2 objects selected",
                                        "Solids on Default")


def test_mixed_kinds_on_several_layers_are_counted():
    scene, selection, props, _l, glazing = _setup()
    a = scene.add(g.make_box((0, 0, 0), 1, 1, 1))
    b = scene.add(g.make_box((3, 0, 0), 1, 1, 1))
    c = scene.add(g.make_line((0, 0, 0), (5, 0, 0)), layer_id=glazing.id)

    selection.set([c.id, a.id, b.id])

    assert _head(props.object_head) == ("Objects", "3 objects selected",
                                        "2 solids, 1 curve on 2 layers")


def test_many_kinds_are_summed_up_after_three():
    from serpentine3d.ui import properties

    assert properties._kinds_text(
        ["Solid", "Solid", "Curve", "Mesh", "Surface", "Point"]) == \
        "2 solids, 1 curve, 1 mesh, 2 others"
    assert properties._kinds_text(["Mesh", "Mesh"]) == "Meshes"
    assert properties._kinds_text(["Hatch", "Point cloud", "Hatch"]) == \
        "2 hatches, 1 point cloud"


def test_nothing_selected_says_so_and_where_to_look():
    _s, _sel, props, _l, _g = _setup()

    assert props.header.text() == "No selection"
    assert not props.object_head.kind.isVisibleTo(props)
    assert props.object_head.detail.text() == \
        "Select objects, or pick a layer in Layers."


def test_the_type_row_is_gone_because_the_header_says_it():
    scene, selection, props, _l, _g = _setup()
    box = scene.add(g.make_box((0, 0, 0), 1, 1, 1))
    selection.set([box.id])

    labels = [props.form.itemAt(i, props.form.ItemRole.LabelRole)
              for i in range(props.form.rowCount())]
    texts = [w.widget().text() for w in labels if w is not None
             and w.widget() is not None and hasattr(w.widget(), "text")]

    assert "Type" not in texts
    assert "Info" in texts


# -- the two pages and their tabs agree ---------------------------------------

def test_each_tab_carries_the_mark_and_name_of_its_page():
    scene, selection, props, layers, glazing = _setup()
    bar = SubjectTitleBar(props)
    box = scene.add(g.make_box((0, 0, 0), 1, 1, 1), name="Wall block")
    selection.set([box.id])
    _pick(layers, glazing.id)

    assert (_image(bar.tabs.tabIcon(1).pixmap(14, 14))
            == _image(props.layer_head.mark.pixmap()))
    assert bar.tabs.tabText(1) == props.layer_head.title.text()

    props.show_subject("objects")

    assert (_image(bar.tabs.tabIcon(0).pixmap(14, 14))
            == _image(props.object_head.mark.pixmap()))
    assert bar.tabs.tabText(0) == props.object_head.title.text()


def test_the_layer_page_uses_the_same_header():
    _s, _sel, props, layers, glazing = _setup()

    _pick(layers, glazing.id)

    assert _head(props.layer_head) == ("Layer", "Glazing",
                                       "Nothing on this layer yet")
    assert type(props.layer_head) is type(props.object_head)


# -- on a sheet ---------------------------------------------------------------

DET = {"x": 200.0, "y": 30.0, "w": 160.0, "h": 120.0, "scale_denom": 2.0,
       "target": [400.0, 250.0, 0.0]}


@pytest.fixture
def sheet():
    from serpentine3d.app import MainWindow
    w = MainWindow()
    w.resize(1200, 800)
    lay = Layout(name="Sheet1")
    detail = DetailView(**DET)
    lay.details.append(detail)
    border = lay.add(g.make_rectangle((20.0, 20.0, 0.0), (120.0, 80.0, 0.0)),
                     name="Border")
    note = TextNote(x=30.0, y=30.0, text="\nGround floor plan\nScale 1:50")
    lay.notes.append(note)
    w.scene.layouts.append(lay)
    w.switch_space(lay.id)
    yield w, lay, border, detail, note
    w.mark_saved()
    w.close()


def _pick_on_sheet(w, *picks):
    lv = w.viewport.layout_view
    lv.selected = list(picks)
    w.viewport.layoutSelectionChanged.emit()


def test_a_curve_on_paper(sheet):
    w, _lay, border, _d, _n = sheet

    _pick_on_sheet(w, ("object", border))

    assert _head(w.properties.object_head) == ("Object", "Border",
                                               "Curve on paper")


def test_a_detail_says_which_view_at_what_scale(sheet):
    w, _lay, _b, detail, _n = sheet

    _pick_on_sheet(w, ("detail", detail))

    assert _head(w.properties.object_head) == (
        "Detail", "Top view", "1:2 · frame 160 × 120 mm")


def test_two_details(sheet):
    w, lay, _b, detail, _n = sheet
    other = DetailView(**{**DET, "x": 20.0})
    lay.details.append(other)

    _pick_on_sheet(w, ("detail", detail), ("detail", other))

    assert _head(w.properties.object_head) == (
        "Details", "2 details selected", "On paper")


def test_a_text_note_is_named_by_its_first_line(sheet):
    w, _lay, _b, _d, note = sheet

    _pick_on_sheet(w, ("note", note))

    assert _head(w.properties.object_head) == (
        "Text note", "Ground floor plan", "Text on paper")
