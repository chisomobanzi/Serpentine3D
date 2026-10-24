"""A cut's hatch lies on a background its layer says (#91).

Reported: the hatch colour can be set, but the colour of the object still
shows as the background of the hatch where a clipping plane cuts it. A
layer, and an object with a section style of its own, now say what a cut
shows under its hatch: None, the darker shade of the object it always
was on screen and bare paper on a sheet, or a colour, the layer's or one
of its own, which fills the cut on screen and on paper alike.
"""

from __future__ import annotations

import numpy as np
import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.layers import (DEFAULT_LAYER_ID, LayerManager,
                                      section_fill_dict)
from serpentine3d.core.layout import SectionFill, section_drawing
from serpentine3d.core.scene import Scene
from serpentine3d.ui import section_caps as caps

SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]


def _scene():
    scene = Scene()
    walls = scene.layers.create("Walls", color=(0.2, 0.4, 0.6))
    box = scene.add(g.make_box((0, 0, 0), 5, 5, 5))
    scene.update(box.id, layer_id=walls.id)
    return scene, walls, scene.get(box.id)


@pytest.mark.parametrize("given, kept", [
    ("none", "none"), ("object", "none"), ("Layer", "layer"), ("#FFFFFF", "#ffffff"),
    ((1.0, 1.0, 1.0), "#ffffff"), ("tartan", "none"), (None, "none"),
    ("ink", "none"),
])
def test_the_background_is_none_the_layer_s_or_its_own(given, kept):
    lm = LayerManager()
    lm.set_hatch_background(DEFAULT_LAYER_ID, given)

    assert lm.get(DEFAULT_LAYER_ID).hatch_background == kept


def test_a_layer_starts_with_no_background():
    assert LayerManager().get(DEFAULT_LAYER_ID).hatch_background == "none"


def test_a_cut_reads_its_background_off_its_layer():
    scene, walls, box = _scene()

    assert scene.section_fill_of(box).background is None
    scene.layers.set_hatch_background(walls.id, "#ffffff")
    assert scene.section_fill_of(box).background == pytest.approx((1, 1, 1))
    scene.layers.set_hatch_background(walls.id, "layer")
    assert scene.section_fill_of(box).background == \
        pytest.approx((0.2, 0.4, 0.6))


def test_an_object_s_own_style_has_a_background_of_its_own():
    scene, walls, box = _scene()
    scene.layers.set_hatch_background(walls.id, "#ffffff")
    box = scene.update(box.id, section_fill=section_fill_dict(
        "cross", background="#00ff00"))

    assert scene.section_fill_of(box).background == pytest.approx((0, 1, 0))


# --- on screen --------------------------------------------------------------

def test_the_cap_lies_on_the_background_rather_than_the_object():
    shade = caps.cap_style(SectionFill("lines"), (1.0, 0.0, 0.0))
    white = caps.cap_style(SectionFill("lines", background=(1.0, 1.0, 1.0)),
                           (1.0, 0.0, 0.0))

    assert shade.fill == pytest.approx((caps.CUT_SHADE, 0.0, 0.0))
    assert white.fill == pytest.approx((1.0, 1.0, 1.0))
    assert white.line == shade.line, "the lines are drawn as they were"


def test_a_solid_or_empty_cut_is_not_changed_by_a_background():
    """Solid floods the cut in its own colour, and None leaves the model's
    solid looking solid; neither has a hatch to lie on anything."""
    for pattern in ("solid", "none"):
        plain = caps.cap_style(SectionFill(pattern), (1.0, 0.0, 0.0))
        given = caps.cap_style(SectionFill(pattern, background=(1, 1, 1)),
                               (1.0, 0.0, 0.0))
        assert given == plain


# --- on paper ---------------------------------------------------------------

def test_on_paper_the_background_is_flooded_under_the_lines():
    lines, _outlines, floods = section_drawing(
        [[SQUARE]], 0.0, 0.0, 1.0,
        [SectionFill("lines", 45.0, 1.0, background=(1.0, 1.0, 0.0))])

    assert lines and lines[0][1], "still hatched"
    assert floods == [((1.0, 1.0, 0.0), [SQUARE])]


def test_on_paper_the_object_s_background_is_the_bare_paper():
    _lines, _outlines, floods = section_drawing(
        [[SQUARE]], 0.0, 0.0, 1.0, [SectionFill("lines", 45.0, 1.0)])

    assert floods == []


def test_the_background_is_saved_with_the_layer_and_the_object(tmp_path):
    from serpentine3d.fileio import native

    scene, walls, box = _scene()
    scene.layers.set_hatch_background(walls.id, "#123456")
    scene.update(box.id, section_fill=section_fill_dict(
        "lines", background="layer"))
    path = str(tmp_path / "ground.serp")
    native.save_scene(scene, path)

    back = Scene()
    native.load_scene(back, path)
    layer = back.layers.find_by_path("Walls")
    assert layer.hatch_background == "#123456"
    (solid,) = [o for o in back.all() if o.kind == "solid"]
    assert solid.section_fill["background"] == "layer"


def test_a_script_can_set_the_background(_qapp):
    from PySide6.QtWidgets import QApplication

    from serpentine3d.api import ApiError, SerpApi
    from serpentine3d.app import MainWindow

    w = MainWindow()
    try:
        api = SerpApi(w)
        api.layers(action="create", name="Walls")
        api.layers(action="style", name="Walls",
                   style={"hatch_background": "#ffffff"})
        walls = next(row for row in api.scene_info()["layers"]
                     if row["name"] == "Walls")
        assert walls["hatch"]["background"] == "#ffffff"
        with pytest.raises(ApiError):
            api.layers(action="style", name="Walls",
                       style={"hatch_background": "tartan"})
    finally:
        w.mark_saved()
        w.close()
        QApplication.processEvents()


def _layer_page(name):
    from PySide6.QtWidgets import QApplication

    from serpentine3d.core.history import History
    from serpentine3d.core.selection import SelectionManager
    from serpentine3d.ui.layers_panel import LayersPanel
    from serpentine3d.ui.properties import PropertiesPanel

    scene = Scene()
    selection = SelectionManager(scene)
    history = History(scene)
    props = PropertiesPanel(scene, selection, history)
    panel = LayersPanel(scene, history, selection=selection)
    props.follow_layers(panel)
    props.show()
    layer = scene.layers.create(name)
    scene.notify()
    QApplication.processEvents()
    for i in range(panel.tree.topLevelItemCount()):
        item = panel.tree.topLevelItem(i)
        item.setSelected(panel._layer_id(item) == layer.id)
    QApplication.processEvents()
    return scene, history, props, layer


def test_the_layer_page_shows_and_sets_the_background(_qapp):
    from PySide6.QtWidgets import QApplication

    scene, history, props, walls = _layer_page("Walls")
    combo = props.layer_hatch_background
    assert combo.currentText() == "None"
    assert props.layer_form.isRowVisible(combo)

    combo.setCurrentIndex(combo.findData("layer"))
    QApplication.processEvents()
    assert scene.layers.get(walls.id).hatch_background == "layer"
    history.undo()
    assert scene.layers.get(walls.id).hatch_background == "none"


def test_a_fill_with_no_lines_has_no_background_to_set(_qapp):
    from PySide6.QtWidgets import QApplication

    _scene_, _h, props, _walls = _layer_page("Walls")
    for pattern, shown in (("lines", True), ("cross", True),
                           ("solid", False), ("none", False)):
        props.layer_hatch.setCurrentIndex(props.layer_hatch.findData(pattern))
        QApplication.processEvents()
        assert props.layer_form.isRowVisible(
            props.layer_hatch_background) is shown, pattern


def test_the_pattern_list_offers_loaded_patterns_and_a_way_to_load(_qapp):
    from PySide6.QtWidgets import QApplication

    from serpentine3d.core.hatch_patterns import merge_into, parse_pat

    scene, _h, props, walls = _layer_page("Walls")
    asked = []
    props.hatchPatternsRequested.connect(asked.append)
    merge_into(scene.hatch_patterns,
               parse_pat("*ANSI31, Iron\n45, 0,0, 0,.125\n"))
    scene.notify()
    QApplication.processEvents()

    combo = props.layer_hatch
    combo.setCurrentIndex(combo.findData("ANSI31"))
    QApplication.processEvents()
    assert scene.layers.get(walls.id).hatch == "ANSI31"
    assert props.layer_form.isRowVisible(props.layer_hatch_spacing)

    combo.setCurrentIndex(combo.findData("load-patterns"))
    QApplication.processEvents()
    assert asked == ["Load"]
    assert scene.layers.get(walls.id).hatch == "ANSI31", \
        "asking to load a file is not a pattern"
    assert combo.currentData() == "ANSI31"


def test_a_detail_cut_by_a_clipping_plane_shows_the_background(
        _qapp, monkeypatch):
    """A detail with no section of its own is still cut by a clipping
    plane (#94), and its cut lies on the background the layer gives it,
    as one with a section does."""
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QApplication

    from serpentine3d.app import MainWindow
    from serpentine3d.core.layout import DetailView, Layout
    from serpentine3d.ui import annot_paint

    w = MainWindow()
    try:
        box = w.scene.add(g.make_box((0, 0, 0), 5, 5, 5))
        w.scene.layers.set_hatch_background(box.layer_id, "#0055ff")
        lay = Layout(name="Sheet")
        detail = DetailView(x=0, y=0, w=50, h=50, display_mode="hidden")
        assert detail.section_offset is None
        lay.details.append(detail)
        w.scene.layouts.append(lay)
        view = w.viewport.layout_view
        view.layout_id = lay.id
        monkeypatch.setattr(type(view), "layout", property(lambda s: lay))
        monkeypatch.setattr(view, "_detail_hlr", lambda d: {
            "cut": [[SQUARE]], "cut_by_obj": [(box.id, "lines", [SQUARE])]})
        flooded = []
        monkeypatch.setattr(annot_paint, "fill_cut_solid",
                            lambda p, f, regions, color=None:
                            flooded.append(color))
        image = QImage(100, 100, QImage.Format.Format_ARGB32)
        painter = QPainter(image)
        try:
            view._paint_cut_fills(painter)
        finally:
            painter.end()
        assert flooded == [pytest.approx((0.0, 1 / 3, 1.0))]
    finally:
        w.mark_saved()
        w.close()
        QApplication.processEvents()


# --- a hatch object -----------------------------------------------------------

def _hatch(scene, pattern="lines"):
    from serpentine3d.core.hatch import HatchShape
    (face,) = g.planar_regions([g.make_polyline(
        [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)], closed=True)])
    return scene.add(HatchShape(face, pattern, spacing=1.0), name="Hatch")


def test_a_hatch_takes_its_layer_s_colour_and_background():
    scene = Scene()
    hatch = _hatch(scene)
    assert scene.hatch_look_of(hatch) == (None, None), "ink, on nothing"

    scene.layers.set_hatch_color(hatch.layer_id, "#aa55ff")
    scene.layers.set_hatch_background(hatch.layer_id, "#ff5500")
    color, ground = scene.hatch_look_of(scene.get(hatch.id))
    assert color == pytest.approx((0xaa / 255, 0x55 / 255, 1.0))
    assert ground == pytest.approx((1.0, 0x55 / 255, 0.0))


def test_a_hatch_can_have_a_colour_and_background_of_its_own():
    scene = Scene()
    hatch = _hatch(scene)
    scene.layers.set_hatch_background(hatch.layer_id, "#ff5500")
    hatch = scene.update(hatch.id, hatch_style={"color": "#00aa00",
                                                "background": "none"})
    color, ground = scene.hatch_look_of(hatch)
    assert color == pytest.approx((0.0, 0xaa / 255, 0.0))
    assert ground is None, "None of its own over the layer's orange"


def test_a_hatch_s_own_look_is_saved(tmp_path):
    from serpentine3d.fileio import native

    scene = Scene()
    hatch = _hatch(scene)
    scene.update(hatch.id, hatch_style={"background": "layer"})
    path = str(tmp_path / "own.serp")
    native.save_scene(scene, path)
    back = Scene()
    native.load_scene(back, path)
    (again,) = [o for o in back.all() if o.kind == "hatch"]
    assert again.hatch_style == {"background": "layer"}


def test_a_detail_draws_a_hatch_on_its_background_in_its_colour():
    from serpentine3d.core.layout import detail_hatches
    tris = [[(0, 0), (1, 0), (0, 1)]]
    segs = [[(0, 0.5), (0.5, 0.5)]]
    floods, lines = detail_hatches(
        [("a", tris, segs, []), ("b", tris, segs, [((1.0, 1.0), 0.1)])],
        [((1, 0, 0), (0, 0, 1), False, 0.5), (None, None, False, 0.0)],
        10.0, 20.0, 2.0)
    assert [c for c, _t in floods] == [(0, 0, 1), None], \
        "a's background, and b's dot filled in its ink"
    assert floods[0][1][0][1] == pytest.approx((12.0, 20.0))
    dot = np.asarray(floods[1][1]).reshape(-1, 2)
    assert np.linalg.norm(dot - (12.0, 22.0), axis=1).max() == \
        pytest.approx(0.2), "a dot of radius 0.1 at (1, 1), on the paper"
    assert {(c, w) for c, w, _s in lines} == {((1, 0, 0), 0.5),
                                              (None, 0.0)}


def test_the_hatch_page_offers_by_layer_first(_qapp):
    from PySide6.QtWidgets import QApplication

    from serpentine3d.core.history import History
    from serpentine3d.core.selection import SelectionManager
    from serpentine3d.ui.properties import PropertiesPanel

    scene = Scene()
    selection = SelectionManager(scene)
    props = PropertiesPanel(scene, selection, History(scene))
    props.show()
    hatch = _hatch(scene)
    selection.set([hatch.id])
    QApplication.processEvents()
    props.refresh()

    for combo in (props.hatch_color, props.hatch_background):
        assert combo.currentText() == "By layer"
    props.hatch_background.setCurrentIndex(
        props.hatch_background.findData("none"))
    QApplication.processEvents()
    assert scene.get(hatch.id).hatch_style == {"background": "none"}
    props.hatch_background.setCurrentIndex(
        props.hatch_background.findData("bylayer"))
    QApplication.processEvents()
    assert scene.get(hatch.id).hatch_style is None
