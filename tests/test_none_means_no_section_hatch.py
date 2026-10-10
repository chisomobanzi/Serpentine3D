"""A layer's section hatch says what its cuts are filled with, and None
means no fill.

A layer nobody had set showed "None" on its page and in the layer command,
yet every cut through it was hatched with lines, which is what cuts had
always looked like. So choosing None changed nothing on the sheet (#40).
Now an unset layer says Lines, the fill it has always had, and None is a
choice of its own: the cut keeps its outline and nothing else.
"""

from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtWidgets import QApplication

from serpentine3d.commands.drafting import _layer_pattern
from serpentine3d.core.history import History
from serpentine3d.core.layers import DEFAULT_LAYER_ID, Layer, LayerManager
from serpentine3d.core.layout import cut_hatching
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.fileio import native
from serpentine3d.ui.layers_panel import LayersPanel
from serpentine3d.ui.properties import PropertiesPanel

SQUARE = [(-10.0, -10.0), (10.0, -10.0), (10.0, 10.0), (-10.0, 10.0)]
HOLE = [(-4.0, -4.0), (4.0, -4.0), (4.0, 4.0), (-4.0, 4.0)]


# -- the layer -------------------------------------------------------------

def test_a_layer_nobody_has_set_is_hatched_with_lines():
    assert Layer("l", "L", (1.0, 1.0, 1.0)).hatch == "lines"
    assert LayerManager().get(DEFAULT_LAYER_ID).hatch == "lines"


def test_a_file_that_says_nothing_about_hatches_opens_on_lines():
    """Written before layers had a hatch, or by a build that wrote "" for
    one it had not been told: both were drawn with lines, so both are."""
    scene = Scene()
    native._load_doc(scene, {
        "format": "serpentine3d",
        "layers": [{"id": "default", "name": "Default",
                    "color": [0.85, 0.85, 0.85]},
                   {"id": "walls", "name": "Walls",
                    "color": [0.5, 0.5, 0.5], "hatch": ""}]})
    assert scene.layers.get(DEFAULT_LAYER_ID).hatch == "lines"
    assert scene.layers.find_by_name("Walls").hatch == "lines"


def test_none_is_a_choice_of_its_own(tmp_path):
    scene = Scene()
    lid = scene.layers.create("Insulation").id
    scene.layers.set_hatch(lid, "None")
    assert scene.layers.get(lid).hatch == "none"

    path = str(tmp_path / "doc.serp3d")
    native.save_scene(scene, path)
    out = Scene()
    native.load_scene(out, path)
    assert out.layers.find_by_name("Insulation").hatch == "none", \
        "None came back from the file as a fill"


# -- the cut ---------------------------------------------------------------

def test_a_cut_through_none_keeps_its_outline_and_nothing_else():
    fill, loops, solid = cut_hatching([[SQUARE, HOLE]], 0.0, 0.0, 1.0,
                                      patterns=["none"])
    assert fill == [], "None was hatched anyway"
    assert solid == [], "None was flooded"
    assert len(loops) == 2, "the cut lost the line round one of its rings"


# -- what offers it --------------------------------------------------------

def _layer_page():
    scene = Scene()
    selection = SelectionManager(scene)
    history = History(scene)
    props = PropertiesPanel(scene, selection, history)
    panel = LayersPanel(scene, history, selection=selection)
    props.follow_layers(panel)
    props.show()
    walls = scene.layers.create("Walls")
    scene.notify()
    QApplication.processEvents()
    item = next(panel.tree.topLevelItem(i)
                for i in range(panel.tree.topLevelItemCount())
                if panel._layer_id(panel.tree.topLevelItem(i)) == walls.id)
    item.setSelected(True)
    QApplication.processEvents()
    return scene, props, walls


def test_the_layer_page_shows_what_an_unset_layer_is_hatched_with():
    _scene, props, _walls = _layer_page()
    assert props.layer_hatch.currentText() == "Lines"


def test_the_layer_page_offers_none_first_and_stores_it():
    scene, props, walls = _layer_page()
    assert props.layer_hatch.itemText(0) == "None"
    props.layer_hatch.setCurrentIndex(0)
    assert scene.layers.get(walls.id).hatch == "none"


def test_a_hatch_drawn_on_a_none_layer_starts_from_lines():
    """None says the material has no fill; a hatch drawn by hand still
    needs a pattern, and lines is the one it has always started on."""
    scene = Scene()
    lid = scene.layers.create("Insulation").id
    scene.layers.set_hatch(lid, "none")
    scene.layers.current_id = lid
    assert _layer_pattern(SimpleNamespace(scene=scene)) == "Lines"
