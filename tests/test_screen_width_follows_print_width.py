"""A layer's screen width follows its print width until you set it.

A layer had two widths that knew nothing of each other: pixels on screen
and millimetres on the plot (#40's thread). Set a 0.7 mm pen for the walls
and the screen still drew them as thin as everything else. Now the screen
width comes from the print width, at 4 px a millimetre so a 0.35 mm pen
draws at the 1.4 px every layer has always had, and never thinner than a
pixel. Set a screen width yourself and it stays put whatever the print
width does, until you ask for From print again.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from serpentine3d.core.history import History
from serpentine3d.core.layers import (DEFAULT_LAYER_ID, LayerManager,
                                      screen_width_for)
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.fileio import native
from serpentine3d.ui.layers_panel import LayersPanel
from serpentine3d.ui.properties import PropertiesPanel


# -- the rule ----------------------------------------------------------------

@pytest.mark.parametrize("print_mm, px", [
    (0.35, 1.4), (0.5, 2.0), (0.7, 2.8), (1.0, 4.0),
    (0.25, 1.0), (0.13, 1.0),          # never thinner than a pixel
    (0.0, 1.4),                        # Default draws as layers always did
])
def test_a_pen_draws_at_four_pixels_a_millimetre(print_mm, px):
    assert screen_width_for(print_mm) == pytest.approx(px)


# -- the layer ---------------------------------------------------------------

def test_a_new_layer_follows_its_print_width():
    lm = LayerManager()
    assert not lm.get(DEFAULT_LAYER_ID).screen_pinned
    lm.set_print_width(DEFAULT_LAYER_ID, 0.7)
    assert lm.get(DEFAULT_LAYER_ID).lineweight == pytest.approx(2.8)
    lm.set_print_width(DEFAULT_LAYER_ID, 0.0)
    assert lm.get(DEFAULT_LAYER_ID).lineweight == pytest.approx(1.4)


def test_a_screen_width_you_set_stays_put():
    lm = LayerManager()
    lm.set_lineweight(DEFAULT_LAYER_ID, 3.0)
    assert lm.get(DEFAULT_LAYER_ID).screen_pinned
    lm.set_print_width(DEFAULT_LAYER_ID, 0.5)
    assert lm.get(DEFAULT_LAYER_ID).lineweight == pytest.approx(3.0), \
        "a print width overwrote the screen width somebody chose"


def test_from_print_lets_go_of_it_again():
    lm = LayerManager()
    lm.set_print_width(DEFAULT_LAYER_ID, 0.5)
    lm.set_lineweight(DEFAULT_LAYER_ID, 3.0)
    lm.follow_print(DEFAULT_LAYER_ID)
    layer = lm.get(DEFAULT_LAYER_ID)
    assert not layer.screen_pinned
    assert layer.lineweight == pytest.approx(2.0)


# -- the file ------------------------------------------------------------------

def _round_trip(scene, tmp_path):
    path = str(tmp_path / "doc.serp3d")
    native.save_scene(scene, path)
    out = Scene()
    native.load_scene(out, path)
    return out


def test_following_and_pinned_both_survive_the_file(tmp_path):
    scene = Scene()
    walls = scene.layers.create("Walls").id
    glass = scene.layers.create("Glass").id
    scene.layers.set_print_width(walls, 0.5)
    scene.layers.set_print_width(glass, 0.5)
    scene.layers.set_lineweight(glass, 3.0)

    out = _round_trip(scene, tmp_path)
    walls, glass = (out.layers.find_by_name(n) for n in ("Walls", "Glass"))
    assert not walls.screen_pinned and walls.lineweight == pytest.approx(2.0)
    assert glass.screen_pinned and glass.lineweight == pytest.approx(3.0)


def _old_file(**layer):
    scene = Scene()
    native._load_doc(scene, {
        "format": "serpentine3d",
        "layers": [{"id": "default", "name": "Default",
                    "color": [0.85, 0.85, 0.85]},
                   {"id": "walls", "name": "Walls",
                    "color": [0.5, 0.5, 0.5], **layer}]})
    return scene.layers.find_by_name("Walls")


def test_an_old_layer_left_at_the_default_follows_its_print_width():
    walls = _old_file(lineweight=1.4, print_width=0.7)
    assert not walls.screen_pinned
    assert walls.lineweight == pytest.approx(2.8)


def test_an_old_layer_somebody_set_keeps_its_screen_width():
    walls = _old_file(lineweight=2.5, print_width=0.7)
    assert walls.screen_pinned
    assert walls.lineweight == pytest.approx(2.5)


def test_a_layer_brought_in_from_another_file_keeps_its_choice(tmp_path):
    other = Scene()
    lid = other.layers.create("Steel").id
    other.layers.set_print_width(lid, 0.5)
    other.layers.set_lineweight(lid, 3.0)
    path = str(tmp_path / "other.serp3d")
    native.save_scene(other, path)

    scene = Scene()
    native.merge_scene(scene, path)
    steel = scene.layers.find_by_name("Steel")
    assert steel is not None and steel.screen_pinned
    assert steel.lineweight == pytest.approx(3.0)


# -- the layer page --------------------------------------------------------------

def _page(*names):
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
    ids = {la.id for la in made}
    for i in range(panel.tree.topLevelItemCount()):
        item = panel.tree.topLevelItem(i)
        item.setSelected(panel._layer_id(item) in ids)
    QApplication.processEvents()
    return scene, history, props, made


def _type(combo, text):
    combo.setEditText(text)
    combo.lineEdit().editingFinished.emit()
    QApplication.processEvents()


def test_the_page_says_the_screen_width_comes_from_print():
    _scene, _h, props, _made = _page("Walls")
    assert props.layer_screen.currentText() == "From print (1.4)"


def test_a_print_width_moves_the_screen_width_on_the_page():
    scene, _h, props, (walls,) = _page("Walls")
    _type(props.layer_print, "0.7")
    assert scene.layers.get(walls.id).lineweight == pytest.approx(2.8)
    assert props.layer_screen.currentText() == "From print (2.8)"


def test_typing_a_screen_width_pins_it():
    scene, _h, props, (walls,) = _page("Walls")
    _type(props.layer_screen, "3")
    layer = scene.layers.get(walls.id)
    assert layer.screen_pinned and layer.lineweight == pytest.approx(3.0)
    assert props.layer_screen.currentText() == "3"


def test_choosing_from_print_lets_go():
    scene, history, props, (walls,) = _page("Walls")
    _type(props.layer_print, "0.5")
    _type(props.layer_screen, "3")
    props.layer_screen.setCurrentIndex(0)       # what a click on it does
    props.layer_screen.textActivated.emit("From print")
    QApplication.processEvents()
    layer = scene.layers.get(walls.id)
    assert not layer.screen_pinned
    assert layer.lineweight == pytest.approx(2.0)

    history.undo()
    assert scene.layers.get(walls.id).screen_pinned, \
        "letting go of the screen width was not one undo step"


def test_from_print_is_the_first_choice_offered():
    _scene, _h, props, _made = _page("Walls")
    assert props.layer_screen.itemText(0) == "From print"


def test_picked_layers_that_disagree_show_nothing():
    scene, _h, props, (walls, glass) = _page("Walls", "Glass")
    scene.layers.set_lineweight(glass.id, 3.0)
    scene.notify()
    QApplication.processEvents()
    assert props.layer_screen.currentText() == ""


# -- the layer command -------------------------------------------------------------

def test_the_layer_command_s_weight_pins_the_screen_width(env):
    scene, _sel, _hist, _ctx, proc = env
    layer = scene.layers.create("Walls")
    proc.run("layer")
    proc.provide_text("Weight")
    proc.provide_text("Walls")
    proc.provide_text("3")
    layer = scene.layers.get(layer.id)
    assert layer.screen_pinned and layer.lineweight == pytest.approx(3.0)
