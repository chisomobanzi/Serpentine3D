"""A layer carries the hatch its material is drawn with.

A section drawing is read by its fills. Walls hatched one way and
insulation another tell you what the thing is made of at a glance, and
that is a property of the material rather than of the afternoon it was
drawn on. The material is what a layer stands for, so the pattern sits
on the layer: set Concrete to cross once and every hatch drawn while
Concrete is current comes out crossed.

A layer that says nothing leaves the app as it was, offering lines and
letting you say otherwise. Only the patterns the app can actually draw
mean anything, so a file naming one it cannot is a layer with no hatch
rather than a prompt with a word in it nothing can fill.
"""

from __future__ import annotations

from serpentine3d.core.layers import DEFAULT_LAYER_ID, Layer, LayerManager
from serpentine3d.core.layout import HATCH_PATTERNS
from serpentine3d.core.scene import Scene
from serpentine3d.fileio import native


# -- the field --

def test_a_new_layer_has_no_hatch_of_its_own():
    assert Layer("l", "L", (1.0, 1.0, 1.0)).hatch == ""
    assert LayerManager().get(DEFAULT_LAYER_ID).hatch == ""


def test_a_layer_keeps_the_pattern_it_is_given():
    lm = LayerManager()
    lm.set_hatch(DEFAULT_LAYER_ID, "cross")
    assert lm.get(DEFAULT_LAYER_ID).hatch == "cross"


def test_every_pattern_a_hatch_can_be_drawn_with_can_sit_on_a_layer():
    """The layer's list and the hatch command's list are one list."""
    lm = LayerManager()
    for pattern in HATCH_PATTERNS:
        lm.set_hatch(DEFAULT_LAYER_ID, pattern)
        assert lm.get(DEFAULT_LAYER_ID).hatch == pattern


def test_the_case_it_is_written_in_does_not_matter():
    """A menu offers "Cross"; a hatch and a file both say "cross"."""
    lm = LayerManager()
    lm.set_hatch(DEFAULT_LAYER_ID, "Cross")
    assert lm.get(DEFAULT_LAYER_ID).hatch == "cross"


def test_a_pattern_the_app_cannot_draw_is_no_pattern_at_all():
    lm = LayerManager()
    lm.set_hatch(DEFAULT_LAYER_ID, "cross")
    lm.set_hatch(DEFAULT_LAYER_ID, "herringbone")
    assert lm.get(DEFAULT_LAYER_ID).hatch == "", \
        "a pattern nothing can draw was kept, so the prompt offers a word " \
        "that fills nothing"


def test_a_layer_can_be_put_back_to_having_no_hatch():
    lm = LayerManager()
    lm.set_hatch(DEFAULT_LAYER_ID, "solid")
    lm.set_hatch(DEFAULT_LAYER_ID, "None")
    assert lm.get(DEFAULT_LAYER_ID).hatch == ""


def test_the_hatch_is_the_layer_s_own_and_not_its_parent_s():
    """Sublayers came later than this idea and inherit nothing here.

    A branch called Concrete with Reinforcement under it is two
    materials, not one drawn twice.
    """
    lm = LayerManager()
    parent = lm.create("Concrete")
    child = lm.create("Reinforcement", parent=parent.id)
    lm.set_hatch(parent.id, "cross")
    assert lm.get(child.id).hatch == ""


# -- and it outlives the file --

def test_the_hatch_survives_a_save_and_an_open(tmp_path):
    scene = Scene()
    lid = scene.layers.create("Concrete").id
    scene.layers.set_hatch(lid, "cross")
    path = str(tmp_path / "doc.serp3d")
    native.save_scene(scene, path)
    out = Scene()
    native.load_scene(out, path)
    assert out.layers.find_by_name("Concrete").hatch == "cross", \
        "the layer's hatch was lost on the way through the file"


def test_a_file_written_before_layers_had_a_hatch_still_opens():
    """The field is younger than the format, so a file predating it is
    legal and its layers simply have no hatch."""
    scene = Scene()
    native._load_doc(scene, {
        "format": "serpentine3d",
        "layers": [{"id": "default", "name": "Default",
                    "color": [0.85, 0.85, 0.85]}]})
    assert scene.layers.get(DEFAULT_LAYER_ID).hatch == ""
