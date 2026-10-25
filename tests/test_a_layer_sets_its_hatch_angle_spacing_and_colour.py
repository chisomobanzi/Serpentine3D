"""A layer says how its cuts are hatched: the pattern, the angle and spacing
of its lines on the paper, and the colour they are drawn in (#40).

A layer used to carry the pattern and nothing else, so every cut in the
drawing was hatched at 45 degrees, 2.5 mm apart, in the one grey. Now the
angle, the spacing and the colour are the layer's too. The spacing is
measured on the printed sheet, so a 1:50 detail and a 1:5 detail of the
same wall hatch at the same density. The colour starts as Ink, the near
black everything else on a sheet is drawn in; it can be the layer's own
colour instead, or one picked for it.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from serpentine3d.core import geometry as g
from serpentine3d.core.history import History
from serpentine3d.core.layers import DEFAULT_LAYER_ID, Layer, LayerManager
from serpentine3d.core.layout import SectionFill, section_drawing
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.fileio import native, pdf
from serpentine3d.ui.layers_panel import LayersPanel
from serpentine3d.ui.properties import PropertiesPanel

SQUARE = [(-10.0, -10.0), (10.0, -10.0), (10.0, 10.0), (-10.0, 10.0)]


# -- the layer ----------------------------------------------------------------

def test_a_layer_starts_at_45_degrees_2_5_mm_apart_in_ink():
    """What every cut was drawn with before, so no drawing changes."""
    layer = Layer("l", "L", (1.0, 1.0, 1.0))
    assert (layer.hatch_angle, layer.hatch_spacing, layer.hatch_color) \
        == (45.0, 2.5, "ink")


def test_the_angle_is_kept_within_half_a_turn():
    """Lines at 225 degrees are lines at 45."""
    lm = LayerManager()
    lm.set_hatch_angle(DEFAULT_LAYER_ID, 225.0)
    assert lm.get(DEFAULT_LAYER_ID).hatch_angle == pytest.approx(45.0)
    lm.set_hatch_angle(DEFAULT_LAYER_ID, -30.0)
    assert lm.get(DEFAULT_LAYER_ID).hatch_angle == pytest.approx(150.0)


def test_the_spacing_never_closes_up_entirely():
    lm = LayerManager()
    lm.set_hatch_spacing(DEFAULT_LAYER_ID, 0.0)
    assert lm.get(DEFAULT_LAYER_ID).hatch_spacing == pytest.approx(0.2)


@pytest.mark.parametrize("given, kept", [
    ("ink", "ink"), ("Layer", "layer"), ("#FF8800", "#ff8800"),
    ((1.0, 0.5, 0.0), "#ff8000"), ("tartan", "ink"), (None, "ink"),
])
def test_the_colour_is_ink_the_layer_s_or_one_of_its_own(given, kept):
    lm = LayerManager()
    lm.set_hatch_color(DEFAULT_LAYER_ID, given)
    assert lm.get(DEFAULT_LAYER_ID).hatch_color == kept


def test_what_a_cut_through_an_object_is_filled_with():
    scene = Scene()
    walls = scene.layers.create("Walls", color=(0.2, 0.4, 0.6))
    box = scene.add(g.make_box((0, 0, 0), 5, 5, 5))
    scene.update(box.id, layer_id=walls.id)
    layers = scene.layers
    layers.set_hatch(walls.id, "cross")
    layers.set_hatch_angle(walls.id, 30.0)
    layers.set_hatch_spacing(walls.id, 1.5)

    fill = scene.section_fill_of(scene.get(box.id))
    assert fill == SectionFill("cross", 30.0, 1.5, None), "ink is no colour"
    layers.set_hatch_color(walls.id, "layer")
    assert scene.section_fill_of(scene.get(box.id)).color \
        == pytest.approx((0.2, 0.4, 0.6))
    layers.set_hatch_color(walls.id, "#ff0000")
    assert scene.section_fill_of(scene.get(box.id)).color \
        == pytest.approx((1.0, 0.0, 0.0))


# -- the file -----------------------------------------------------------------

def test_all_three_survive_the_file(tmp_path):
    scene = Scene()
    lid = scene.layers.create("Steel").id
    scene.layers.set_hatch_angle(lid, 60.0)
    scene.layers.set_hatch_spacing(lid, 4.0)
    scene.layers.set_hatch_color(lid, "#336699")
    path = str(tmp_path / "doc.serp3d")
    native.save_scene(scene, path)

    out = Scene()
    native.load_scene(out, path)
    steel = out.layers.find_by_name("Steel")
    assert (steel.hatch_angle, steel.hatch_spacing, steel.hatch_color) \
        == (60.0, 4.0, "#336699")

    merged = Scene()
    native.merge_scene(merged, path)
    steel = merged.layers.find_by_name("Steel")
    assert (steel.hatch_angle, steel.hatch_spacing, steel.hatch_color) \
        == (60.0, 4.0, "#336699"), "merging another file dropped them"


def test_a_file_from_before_opens_at_the_old_hatch():
    scene = Scene()
    native._load_doc(scene, {"format": "serpentine3d", "layers": [
        {"id": "default", "name": "Default", "color": [0.85, 0.85, 0.85]}]})
    layer = scene.layers.get(DEFAULT_LAYER_ID)
    assert (layer.hatch_angle, layer.hatch_spacing, layer.hatch_color) \
        == (45.0, 2.5, "ink")


# -- the cut ------------------------------------------------------------------

def _directions(segments):
    return {round(math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))) % 180
            for a, b in segments}


def test_each_cut_is_hatched_at_its_own_angle_and_spacing():
    lines, outlines, floods = section_drawing(
        [[SQUARE], [SQUARE]], 0.0, 0.0, 1.0,
        [SectionFill("lines", 30.0, 2.0), SectionFill("lines", 120.0, 4.0)])
    assert floods == []
    ((_ink, _width, rings),) = outlines      # both outlined alike: one pen
    assert len(rings) == 2
    (ink, segments), = lines          # both in ink: one group
    assert ink is None
    assert _directions(segments) == {30, 120}
    by_angle = {}
    for a, b in segments:
        angle = round(math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))) % 180
        by_angle[angle] = by_angle.get(angle, 0) + 1
    assert by_angle[30] > 1.6 * by_angle[120], \
        "the tighter spacing did not draw more lines"


def test_a_coloured_cut_comes_out_in_its_colour():
    red = (1.0, 0.0, 0.0)
    lines, _loops, floods = section_drawing(
        [[SQUARE], [SQUARE]], 0.0, 0.0, 1.0,
        [SectionFill("lines", color=red), SectionFill("solid", color=red)])
    assert [color for color, _segs in lines] == [red]
    assert [color for color, _rings in floods] == [red]


def test_none_draws_only_the_outline_whatever_its_colour():
    lines, outlines, floods = section_drawing(
        [[SQUARE]], 0.0, 0.0, 1.0, [SectionFill("none", color=(1, 0, 0))])
    assert lines == [] and floods == [] and len(outlines) == 1


class _Recorder:
    """A painter that writes down the colour of every line it draws."""

    def __init__(self):
        self.pens = []

    def __getattr__(self, name):
        return lambda *a, **k: None

    def setPen(self, pen):
        self._pen = pen

    def drawLine(self, a, b):
        self.pens.append(self._pen.color().name())


def test_the_plot_draws_a_cut_in_its_layer_s_colour():
    detail = SimpleNamespace(x=0.0, y=0.0, w=100.0, h=100.0, scale_denom=1.0,
                             display_mode="shaded")
    data = {"visible": [], "hidden": [], "cut": [[SQUARE]],
            "visible_groups": [], "cut_by_obj": [("o", "lines", [SQUARE])]}
    view = SimpleNamespace(
        _detail_hlr=lambda d: data,
        _region_fills=lambda d: [SectionFill("lines", color=(0.0, 0.0, 1.0))])
    rec = _Recorder()
    pdf._paint_detail_vector(rec, view, detail,
                             SimpleNamespace(paper_h=200.0, paper_w=300.0),
                             1.0)
    assert rec.pens and set(rec.pens) == {"#0000ff"}


class _Sequence(_Recorder):
    """Writes down, in order, every flood and every outline."""

    def __init__(self):
        super().__init__()
        self.calls = []

    def drawPath(self, path):
        self.calls.append("flood")

    def drawPolyline(self, poly):
        self.calls.append("outline")


def test_the_plot_outlines_a_coloured_flood_after_filling_it():
    """An opaque colour drawn over the outline would hide half of it."""
    detail = SimpleNamespace(x=0.0, y=0.0, w=100.0, h=100.0, scale_denom=1.0,
                             display_mode="shaded")
    data = {"visible": [], "hidden": [], "cut": [[SQUARE]],
            "visible_groups": [], "cut_by_obj": [("o", "solid", [SQUARE])]}
    view = SimpleNamespace(
        _detail_hlr=lambda d: data,
        _region_fills=lambda d: [SectionFill("solid", color=(0.2, 0.3, 0.5))])
    rec = _Sequence()
    pdf._paint_detail_vector(rec, view, detail,
                             SimpleNamespace(paper_h=200.0, paper_w=300.0),
                             1.0)
    assert rec.calls == ["flood", "outline"]


# -- the layer page -----------------------------------------------------------

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


def _row_shown(props, field):
    return props.layer_form.isRowVisible(field)


def test_the_page_shows_and_sets_angle_and_spacing():
    scene, history, props, (walls,) = _page("Walls")
    assert props.layer_hatch_angle.currentText() == "45"
    assert props.layer_hatch_spacing.currentText() == "2.5"

    _type(props.layer_hatch_angle, "30°")
    _type(props.layer_hatch_spacing, "1.5 mm")
    layer = scene.layers.get(walls.id)
    assert (layer.hatch_angle, layer.hatch_spacing) == (30.0, 1.5)

    history.undo()
    assert scene.layers.get(walls.id).hatch_spacing == 2.5, \
        "the spacing was not an undo step of its own"


def test_angle_and_spacing_only_show_for_a_pattern_that_has_lines():
    scene, _h, props, (walls,) = _page("Walls")
    for pattern, lined, filled in (("lines", True, True),
                                   ("cross", True, True),
                                   ("solid", False, True),
                                   ("none", False, False)):
        props.layer_hatch.setCurrentIndex(props.layer_hatch.findData(pattern))
        QApplication.processEvents()
        assert _row_shown(props, props.layer_hatch_angle) is lined, pattern
        assert _row_shown(props, props.layer_hatch_spacing) is lined, pattern
        assert _row_shown(props, props.layer_hatch_color) is filled, pattern


def test_the_colour_row_offers_ink_and_the_layer_s_colour():
    scene, _h, props, (walls,) = _page("Walls")
    combo = props.layer_hatch_color
    assert combo.currentText() == "Ink"
    combo.setCurrentIndex(combo.findData("layer"))
    QApplication.processEvents()
    assert scene.layers.get(walls.id).hatch_color == "layer"


def test_choosing_a_colour_of_its_own(monkeypatch):
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QColorDialog
    monkeypatch.setattr(QColorDialog, "getColor",
                        staticmethod(lambda *a, **k: QColor("#4080c0")))
    scene, _h, props, (walls,) = _page("Walls")
    combo = props.layer_hatch_color
    combo.setCurrentIndex(combo.findData("choose"))
    QApplication.processEvents()
    assert scene.layers.get(walls.id).hatch_color == "#4080c0"
    assert combo.currentData() == "#4080c0", "the page lost the chosen colour"


def test_a_colour_dialog_closed_without_choosing_changes_nothing(monkeypatch):
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QColorDialog
    monkeypatch.setattr(QColorDialog, "getColor",
                        staticmethod(lambda *a, **k: QColor()))
    scene, _h, props, (walls,) = _page("Walls")
    combo = props.layer_hatch_color
    combo.setCurrentIndex(combo.findData("choose"))
    QApplication.processEvents()
    assert scene.layers.get(walls.id).hatch_color == "ink"
    assert combo.currentData() == "ink"


def test_layers_that_disagree_show_a_blank():
    scene, _h, props, (walls, glass) = _page("Walls", "Glass")
    scene.layers.set_hatch_angle(glass.id, 60.0)
    scene.layers.set_hatch_color(glass.id, "layer")
    scene.notify()
    QApplication.processEvents()
    assert props.layer_hatch_angle.currentText() == ""
    assert props.layer_hatch_spacing.currentText() == "2.5"
    assert props.layer_hatch_color.currentIndex() == -1


# -- the commands -------------------------------------------------------------

def test_the_layer_command_asks_for_angle_and_spacing(env):
    scene, _sel, _hist, _ctx, proc = env
    layer = scene.layers.create("Walls")
    proc.run("layer")
    for text in ("Hatch", "Walls", "Cross", "60", "4"):
        proc.provide_text(text)
    layer = scene.layers.get(layer.id)
    assert (layer.hatch, layer.hatch_angle, layer.hatch_spacing) \
        == ("cross", 60.0, 4.0)


def test_a_hatch_drawn_on_a_sheet_starts_from_the_layer(env):
    from serpentine3d.core.layout import Layout
    from tests.conftest import StubViewport
    scene, _sel, _hist, ctx, proc = env
    lay = Layout(name="Sheet")
    scene.layouts.append(lay)
    ctx.viewport = StubViewport(lay.id)
    scene.layers.set_hatch_angle(DEFAULT_LAYER_ID, 30.0)
    scene.layers.set_hatch_spacing(DEFAULT_LAYER_ID, 1.5)
    proc.run("hatch")
    for point in ("10,10", "40,10", "40,40"):
        proc.provide_text(point)
    proc.provide_text("")              # close the outline
    proc.provide_text("Lines")
    assert proc.request.default == pytest.approx(1.5)
    proc.provide_text("")
    assert proc.request.default == pytest.approx(30.0)


# -- the API ------------------------------------------------------------------

def _api(scene):
    from serpentine3d.api import SerpApi
    window = SimpleNamespace(scene=scene, selection=SelectionManager(scene),
                             history=History(scene),
                             viewport=SimpleNamespace(display_mode="shaded"),
                             processor=None)
    return SerpApi(window)


def test_a_script_can_style_a_layer_and_read_it_back():
    scene = Scene()
    scene.layers.create("Walls")
    api = _api(scene)
    api.layers(action="style", name="Walls", style={
        "linetype": "Dashed", "print_width": 0.5, "hatch": "cross",
        "hatch_angle": 30, "hatch_spacing": 2.0, "hatch_color": "layer"})
    walls = next(row for row in api.scene_info()["layers"]
                 if row["name"] == "Walls")
    assert walls["linetype"] == "Dashed"
    assert walls["print_width"] == 0.5
    assert walls["screen_width"] == pytest.approx(2.0)
    assert not walls["screen_pinned"]
    assert walls["hatch"] == {"pattern": "cross", "angle": 30.0,
                              "spacing": 2.0, "color": "layer",
                              "background": "object"}
    api.layers(action="style", name="Walls", style={"screen_width": 3})
    walls = next(row for row in api.scene_info()["layers"]
                 if row["name"] == "Walls")
    assert walls["screen_width"] == 3 and walls["screen_pinned"]


def test_a_style_the_layer_cannot_take_is_refused():
    from serpentine3d.api import ApiError
    scene = Scene()
    scene.layers.create("Walls")
    with pytest.raises(ApiError, match="hatch_colour"):
        _api(scene).layers(action="style", name="Walls",
                           style={"hatch_colour": "red"})
