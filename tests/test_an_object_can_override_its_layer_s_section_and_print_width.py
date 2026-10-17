"""An object can have a section hatch and a print width of its own (#40).

Colour already worked this way: an object takes its layer's unless it is
given one, and By layer hands it back. Hatching and print width now do
too. One column among the walls can be cut solid, or plot heavier, without
a layer made for it. An object's section hatch is all of a piece, the way
Rhino's section style is: By layer, or its own pattern, angle, spacing
and colour together, starting from the layer's when it is first set.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from serpentine3d.core import geometry as g
from serpentine3d.core.history import History
from serpentine3d.core.layers import section_fill_dict
from serpentine3d.core.layout import SectionFill
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.fileio import native
from serpentine3d.ui.properties import PropertiesPanel


def _scene():
    scene = Scene()
    walls = scene.layers.create("Walls", color=(0.2, 0.4, 0.6))
    scene.layers.set_hatch(walls.id, "cross")
    scene.layers.set_print_width(walls.id, 0.35)
    box = scene.add(g.make_box((0, 0, 0), 5, 5, 5))
    scene.update(box.id, layer_id=walls.id)
    return scene, walls, scene.get(box.id)


# -- the object ---------------------------------------------------------------

def test_an_object_follows_its_layer_until_told_otherwise():
    scene, walls, box = _scene()
    assert box.print_width is None and box.section_fill is None
    assert scene.print_width_of(box) == 0.35
    assert scene.hatch_of(box) == "cross"
    assert scene.section_fill_of(box) == SectionFill("cross", 45.0, 2.5, None)


def test_a_print_width_of_its_own():
    scene, walls, box = _scene()
    box = scene.update(box.id, print_width=0.7)
    assert scene.print_width_of(box) == 0.7
    box = scene.update(box.id, print_width=0.0)
    assert scene.print_width_of(box) == 0.0, "Default is a width of its own"


def test_its_screen_width_follows_its_own_print_width():
    scene, walls, box = _scene()
    box = scene.update(box.id, print_width=0.7)
    assert scene.screen_width_of(box) == pytest.approx(2.8)
    scene.layers.set_lineweight(walls.id, 3.0)       # pinned on the layer
    assert scene.screen_width_of(box) == pytest.approx(3.0), \
        "a screen width set by hand on the layer stopped holding"
    other = scene.add(g.make_box((9, 0, 0), 5, 5, 5))
    assert scene.screen_width_of(other) == \
        scene.layers.get(other.layer_id).lineweight


def test_a_section_fill_of_its_own():
    scene, walls, box = _scene()
    box = scene.update(box.id, section_fill=section_fill_dict(
        "solid", 30.0, 1.5, "#ff0000"))
    assert scene.hatch_of(box) == "solid"
    assert scene.section_fill_of(box) == SectionFill("solid", 30.0, 1.5,
                                                     (1.0, 0.0, 0.0))
    box = scene.update(box.id, section_fill=section_fill_dict(
        "lines", color="layer"))
    assert scene.section_fill_of(box).color == pytest.approx((0.2, 0.4, 0.6))


def test_a_section_fill_is_kept_tidy():
    assert section_fill_dict("Herringbone", 200.0, 0.0, "tartan") == {
        "pattern": "lines", "angle": 20.0, "spacing": 0.2, "color": "ink",
        "cut_line_width": 0.5, "cut_line_color": "ink"}


def test_a_copy_keeps_what_the_original_overrode():
    scene, walls, box = _scene()
    box = scene.update(box.id, print_width=0.5,
                       section_fill=section_fill_dict("solid"))
    copy = scene.add_from(g.make_box((9, 0, 0), 5, 5, 5), box)
    assert copy.print_width == 0.5
    assert copy.section_fill == section_fill_dict("solid")


def test_undo_takes_an_override_back_off():
    scene, walls, box = _scene()
    history = History(scene)
    history.checkpoint("object section")
    scene.update(box.id, section_fill=section_fill_dict("solid"),
                 print_width=1.0)
    history.undo()
    box = scene.get(box.id)
    assert box.section_fill is None and box.print_width is None


# -- the file -----------------------------------------------------------------

def test_both_survive_the_file_and_a_merge(tmp_path):
    scene, walls, box = _scene()
    scene.update(box.id, print_width=0.7,
                 section_fill=section_fill_dict("solid", 30.0, 1.5, "#ff0000"))
    path = str(tmp_path / "doc.serp3d")
    native.save_scene(scene, path)
    for read in (native.load_scene, native.merge_scene):
        out = Scene()
        read(out, path)
        (back,) = [o for o in out.all() if o.kind == "solid"]
        assert back.print_width == 0.7, read.__name__
        assert back.section_fill == section_fill_dict(
            "solid", 30.0, 1.5, "#ff0000"), read.__name__


def test_an_object_from_an_older_file_follows_its_layer(tmp_path):
    scene, walls, box = _scene()
    path = str(tmp_path / "doc.serp3d")
    native.save_scene(scene, path)
    out = Scene()
    native.load_scene(out, path)
    (back,) = [o for o in out.all() if o.kind == "solid"]
    assert back.print_width is None and back.section_fill is None


# -- the object page ----------------------------------------------------------

def _page(kind="solid"):
    scene, walls, box = _scene()
    if kind == "curve":
        box = scene.add(g.make_polyline([(0, 0, 0), (5, 0, 0)]))
    selection = SelectionManager(scene)
    history = History(scene)
    props = PropertiesPanel(scene, selection, history)
    props.show()
    selection.set([box.id])
    QApplication.processEvents()
    return scene, history, props, box


def _type(combo, text):
    combo.setEditText(text)
    combo.lineEdit().editingFinished.emit()
    QApplication.processEvents()


def _choose(combo, data):
    combo.setCurrentIndex(combo.findData(data))
    QApplication.processEvents()


def test_the_page_says_the_object_follows_its_layer():
    _scene_, _h, props, _box = _page()
    assert props.section_hatch.currentText() == "By layer (Cross)"
    assert props.print_width_combo.currentText() == "By layer (0.35)"
    look = props.section_look
    for row in (look.angle, look.spacing, look.color):
        assert not props.form.isRowVisible(row), \
            "the layer's own hatch rows showed on an object that follows it"


def test_choosing_a_pattern_gives_the_object_its_own_from_the_layer():
    scene, history, props, box = _page()
    scene.layers.set_hatch_angle(box.layer_id, 30.0)
    _choose(props.section_hatch, "solid")
    assert scene.get(box.id).section_fill == section_fill_dict(
        "solid", 30.0, 2.5, "ink"), "it did not start from the layer's"
    assert props.form.isRowVisible(props.section_look.color)
    _choose(props.section_hatch, "lines")
    assert props.form.isRowVisible(props.section_look.angle)
    _type(props.section_look.spacing, "4")
    assert scene.get(box.id).section_fill["spacing"] == 4.0

    _choose(props.section_hatch, "bylayer")
    assert scene.get(box.id).section_fill is None
    history.undo()
    assert scene.get(box.id).section_fill["spacing"] == 4.0, \
        "going back to By layer was not one undo step"


def test_a_print_width_typed_or_given_back():
    scene, _h, props, box = _page()
    _type(props.print_width_combo, "0.7")
    assert scene.get(box.id).print_width == 0.7
    _type(props.print_width_combo, "Default")
    assert scene.get(box.id).print_width == 0.0
    props.print_width_combo.setCurrentIndex(0)                 # By layer
    props.print_width_combo.textActivated.emit(
        props.print_width_combo.itemText(0))
    QApplication.processEvents()
    assert scene.get(box.id).print_width is None


def test_a_curve_has_a_print_width_but_no_section():
    """Only something solid leaves a face where it is cut."""
    _scene_, _h, props, _curve = _page("curve")
    assert props.form.isRowVisible(props.print_width_combo)
    assert not props.form.isRowVisible(props.section_hatch)


# -- the commands -------------------------------------------------------------

def test_the_printwidth_command(env):
    scene, selection, _hist, _ctx, proc = env
    box = scene.add(g.make_box((0, 0, 0), 5, 5, 5))
    selection.set([box.id])
    proc.run("printwidth")
    proc.provide_text("0.5")
    assert scene.get(box.id).print_width == 0.5
    selection.set([box.id])          # a command lets go of what it was given
    proc.run("printwidth")
    proc.provide_text("ByLayer")
    assert scene.get(box.id).print_width is None


def test_the_sectionhatch_command(env):
    scene, selection, _hist, _ctx, proc = env
    box = scene.add(g.make_box((0, 0, 0), 5, 5, 5))
    selection.set([box.id])
    proc.run("sectionhatch")
    for text in ("Cross", "60", "4"):
        proc.provide_text(text)
    assert scene.get(box.id).section_fill == section_fill_dict(
        "cross", 60.0, 4.0, "ink")
    selection.set([box.id])
    proc.run("sectionhatch")
    proc.provide_text("ByLayer")
    assert scene.get(box.id).section_fill is None


def test_matchprops_carries_both(env):
    scene, selection, _hist, _ctx, proc = env
    source = scene.add(g.make_box((0, 0, 0), 5, 5, 5))
    target = scene.add(g.make_box((9, 0, 0), 5, 5, 5))
    scene.update(source.id, print_width=0.7,
                 section_fill=section_fill_dict("solid"))
    proc.run("matchprops")
    proc.click_object(source.id)
    proc.click_object(target.id)
    proc.finish_selection()
    target = scene.get(target.id)
    assert target.print_width == 0.7
    assert target.section_fill == section_fill_dict("solid")
