"""A layer carries two widths, the way Rhino does.

`lineweight` is how heavy the edge looks on screen, in pixels. It is a
drawing aid and says nothing about the plot. `print_width` is the pen the
layout, the PDF and the DXF put the layer's geometry down with, in
millimetres, and it is what a printed drawing is actually measured by.

Rhino's PlotWeight is the same field, in the same unit, with the same
default: 0 means "let the device decide", which prints as a thin default
line. So print_width defaults to 0.0 and never goes negative, and the two
widths move independently: setting one leaves the other where it was.
"""

from __future__ import annotations

from serpentine3d.core import geometry as g
from serpentine3d.core.layers import DEFAULT_LAYER_ID, Layer, LayerManager
from serpentine3d.core.scene import Scene


def test_a_new_layer_prints_at_the_device_default():
    assert Layer("l", "L", (1.0, 1.0, 1.0)).print_width == 0.0
    assert LayerManager().get(DEFAULT_LAYER_ID).print_width == 0.0


def test_set_print_width_takes_millimetres():
    lm = LayerManager()
    lm.set_print_width(DEFAULT_LAYER_ID, 0.5)
    assert lm.get(DEFAULT_LAYER_ID).print_width == 0.5


def test_a_print_width_is_never_negative():
    """Rhino's -1 is 'default'; we say that with 0, so nothing below it."""
    lm = LayerManager()
    lm.set_print_width(DEFAULT_LAYER_ID, -2.0)
    assert lm.get(DEFAULT_LAYER_ID).print_width == 0.0


def test_the_two_widths_are_independent():
    lm = LayerManager()
    lm.set_lineweight(DEFAULT_LAYER_ID, 3.0)
    lm.set_print_width(DEFAULT_LAYER_ID, 0.7)
    assert lm.get(DEFAULT_LAYER_ID).lineweight == 3.0
    lm.set_lineweight(DEFAULT_LAYER_ID, 5.0)
    assert lm.get(DEFAULT_LAYER_ID).print_width == 0.7


def test_the_scene_reads_the_objects_print_width_off_its_layer():
    scene = Scene()
    lid = scene.layers.create("Heavy").id
    scene.layers.set_print_width(lid, 1.2)
    obj = scene.add(g.make_line((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
                    layer_id=lid)
    assert scene.print_width_of(obj) == 1.2
