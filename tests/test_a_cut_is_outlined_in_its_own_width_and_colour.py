"""A cut face is outlined in a width and colour of its own (#82).

The line round a section cut was the one thing about it a layer could not
say: every cut on every sheet was outlined 0.5 mm in ink, and a clipping
plane in the model left its caps with no outline at all. Now the width on
the paper and the colour are the layer's, alongside its hatch, and an
object with a section style of its own has its own cut line too, the way
Rhino's section style carries its boundary. A width of None draws no line.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from serpentine3d.core import geometry as g
from serpentine3d.core.tessellate import DisplayMesh
from serpentine3d.core.history import History
from serpentine3d.core.layers import (DEFAULT_LAYER_ID, Layer, LayerManager,
                                      section_fill_dict)
from serpentine3d.core.layout import SectionFill, section_drawing
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.fileio import native, pdf
from serpentine3d.ui import section_caps as caps
from serpentine3d.ui.layers_panel import LayersPanel
from serpentine3d.ui.properties import PropertiesPanel

SQUARE = [(-10.0, -10.0), (10.0, -10.0), (10.0, 10.0), (-10.0, 10.0)]
RED = (1.0, 0.0, 0.0)


# -- the layer ----------------------------------------------------------------

def test_a_layer_outlines_its_cuts_0_5_mm_in_ink():
    """What every cut was outlined with before, so no drawing changes."""
    layer = Layer("l", "L", (1.0, 1.0, 1.0))
    assert (layer.cut_line_width, layer.cut_line_color) == (0.5, "ink")


def test_the_width_is_never_below_none():
    lm = LayerManager()
    lm.set_cut_line_width(DEFAULT_LAYER_ID, 0.7)
    assert lm.get(DEFAULT_LAYER_ID).cut_line_width == 0.7
    lm.set_cut_line_width(DEFAULT_LAYER_ID, -1.0)
    assert lm.get(DEFAULT_LAYER_ID).cut_line_width == 0.0
    lm.set_cut_line_width(DEFAULT_LAYER_ID, float("inf"))
    assert lm.get(DEFAULT_LAYER_ID).cut_line_width <= 5.0, \
        "a width past any pen would cover the drawing"


@pytest.mark.parametrize("given, kept", [
    ("ink", "ink"), ("Layer", "layer"), ("#FF8800", "#ff8800"),
    ((1.0, 0.5, 0.0), "#ff8000"), ("tartan", "ink"),
])
def test_the_colour_is_ink_the_layer_s_or_one_of_its_own(given, kept):
    lm = LayerManager()
    lm.set_cut_line_color(DEFAULT_LAYER_ID, given)
    assert lm.get(DEFAULT_LAYER_ID).cut_line_color == kept


def _scene():
    scene = Scene()
    walls = scene.layers.create("Walls", color=(0.2, 0.4, 0.6))
    box = scene.add(g.make_box((0, 0, 0), 5, 5, 5))
    scene.update(box.id, layer_id=walls.id)
    return scene, walls, scene.get(box.id)


def test_a_cut_through_an_object_is_outlined_the_way_its_layer_says():
    scene, walls, box = _scene()
    fill = scene.section_fill_of(box)
    assert (fill.cut_line_width, fill.cut_line_color) == (0.5, None), \
        "ink is no colour"
    scene.layers.set_cut_line_width(walls.id, 0.25)
    scene.layers.set_cut_line_color(walls.id, "layer")
    fill = scene.section_fill_of(scene.get(box.id))
    assert fill.cut_line_width == 0.25
    assert fill.cut_line_color == pytest.approx((0.2, 0.4, 0.6))


# -- the object ---------------------------------------------------------------

def test_an_object_s_own_section_style_carries_its_own_cut_line():
    scene, walls, box = _scene()
    scene.layers.set_cut_line_width(walls.id, 0.25)
    box = scene.update(box.id, section_fill=section_fill_dict(
        "solid", cut_line_width=1.0, cut_line_color="#ff0000"))
    fill = scene.section_fill_of(box)
    assert fill.cut_line_width == 1.0, "the layer's width won over its own"
    assert fill.cut_line_color == pytest.approx(RED)


def test_a_section_style_is_kept_tidy():
    own = section_fill_dict("lines", cut_line_width=-2.0,
                            cut_line_color="tartan")
    assert (own["cut_line_width"], own["cut_line_color"]) == (0.0, "ink")


def test_a_section_style_from_before_outlines_the_old_way():
    """An object given a style of its own before cut lines had one."""
    own = section_fill_dict(**{"pattern": "cross", "angle": 30.0,
                               "spacing": 2.0, "color": "ink"})
    assert (own["cut_line_width"], own["cut_line_color"]) == (0.5, "ink")


# -- the drawing --------------------------------------------------------------

def test_each_face_is_outlined_in_its_own_width_and_colour():
    _lines, outlines, _floods = section_drawing(
        [[SQUARE], [SQUARE], [SQUARE]], 0.0, 0.0, 1.0,
        [SectionFill("lines"), SectionFill("lines"),
         SectionFill("lines", cut_line_width=1.0, cut_line_color=RED)])
    assert [(color, width, len(rings)) for color, width, rings in outlines] \
        == [(None, 0.5, 2), (RED, 1.0, 1)], \
        "faces outlined alike were not drawn as one pen"


def test_a_width_of_none_leaves_the_face_without_an_outline():
    lines, outlines, _floods = section_drawing(
        [[SQUARE]], 0.0, 0.0, 1.0, [SectionFill("lines", cut_line_width=0.0)])
    assert lines, "the hatch went too"
    assert outlines == []


class _Pens:
    """A painter that writes down the pen of every outline it draws."""

    def __init__(self):
        self.outlines = []
        self._pen = None

    def __getattr__(self, name):
        return lambda *a, **k: None

    def setPen(self, pen):
        self._pen = pen

    def drawPolyline(self, poly):
        self.outlines.append((self._pen.color().name(), self._pen.widthF()))


def _plot(fill, k=2.0):
    detail = SimpleNamespace(x=0.0, y=0.0, w=100.0, h=100.0, scale_denom=1.0,
                             display_mode="shaded")
    data = {"visible": [], "hidden": [], "cut": [[SQUARE]],
            "visible_groups": [], "cut_by_obj": [("o", fill.pattern, [SQUARE])]}
    view = SimpleNamespace(_detail_hlr=lambda d: data,
                           _region_fills=lambda d: [fill])
    rec = _Pens()
    pdf._paint_detail_vector(rec, view, detail,
                             SimpleNamespace(paper_h=200.0, paper_w=300.0), k)
    return rec.outlines


def test_the_plot_outlines_a_cut_in_its_width_and_colour():
    assert _plot(SectionFill("lines", cut_line_width=0.7,
                             cut_line_color=RED)) == [("#ff0000", 1.4)]


def test_the_plot_outlines_in_ink_by_default():
    ((color, width),) = _plot(SectionFill("cross"))
    assert width == pytest.approx(1.0)                  # 0.5 mm, at 2 a mm
    assert color == "#0a0a0c"


def test_the_plot_leaves_a_face_with_no_cut_line_unoutlined():
    assert _plot(SectionFill("solid", cut_line_width=0.0)) == []


# -- a clipping plane in the model --------------------------------------------

def _cube(size=2.0):
    """A closed cube's corners and the twelve triangles of its faces."""
    s = size
    vertices = np.array([(0, 0, 0), (s, 0, 0), (s, s, 0), (0, s, 0),
                         (0, 0, s), (s, 0, s), (s, s, s), (0, s, s)], float)
    triangles = np.array([(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7),
                          (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5),
                          (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)])
    return vertices, triangles


def test_a_plane_through_a_solid_meets_its_faces_in_a_closed_ring():
    vertices, triangles = _cube()
    segs = caps.plane_cut_segments(vertices, triangles, (0, 0, 0.5),
                                   (0, 0, 1))
    assert segs.shape[1:] == (2, 3)
    assert np.allclose(segs[:, :, 2], 0.5), "a line left the plane"
    length = np.linalg.norm(segs[:, 1] - segs[:, 0], axis=1).sum()
    assert length == pytest.approx(8.0), "the ring is not the cube's girth"


def test_a_plane_that_misses_draws_no_line():
    vertices, triangles = _cube()
    assert len(caps.plane_cut_segments(vertices, triangles, (0, 0, 9),
                                       (0, 0, 1))) == 0


def test_a_plane_through_a_corner_draws_no_specks():
    """A vertex lying on the plane gives a triangle no length of cut."""
    vertices, triangles = _cube()
    segs = caps.plane_cut_segments(vertices, triangles, (0, 0, 0),
                                   (1, 1, 1) / np.sqrt(3.0))
    lengths = np.linalg.norm(segs[:, 1] - segs[:, 0], axis=1)
    assert (lengths > 1e-9).all()


def test_the_cut_line_on_screen_follows_the_section():
    assert caps.cut_line_style(SectionFill("lines")) == \
        ((*caps.INK_ON_SCREEN, 1.0), 2.0), "0.5 mm is not 2 px of ink"
    assert caps.cut_line_style(SectionFill(
        "solid", cut_line_width=1.0, cut_line_color=RED)) == \
        ((*RED, 1.0), 4.0)
    assert caps.cut_line_style(SectionFill("none", cut_line_width=0.0)) \
        is None


def test_a_ring_is_worked_out_once_until_the_plane_or_solid_moves(monkeypatch):
    calls = []
    real = caps.plane_cut_segments
    monkeypatch.setattr(caps, "plane_cut_segments",
                        lambda *a: calls.append(1) or real(*a))
    vertices, triangles = _cube()

    def _mesh():
        """A display mesh of that cube: coordinates are kept as offsets
        from where it sits, and the cut is worked out there."""
        dm = DisplayMesh()
        dm.vertices = vertices
        dm.triangles = triangles
        return dm

    mesh = _mesh()
    plane = caps.cap_planes([((0, 0, 0.5), (0, 0, 1), True)])[0]
    rings = caps.CutLines()
    for _frame in range(3):
        rings.segments("box", mesh, plane)
        rings.end_frame()
    assert len(calls) == 1
    moved = caps.cap_planes([((0, 0, 0.7), (0, 0, 1), True)])[0]
    rings.segments("box", mesh, moved)
    assert len(calls) == 2
    rings.segments("box", _mesh(), moved)
    assert len(calls) == 3, "a new mesh kept the old ring"


# -- the file -----------------------------------------------------------------

def test_a_layer_s_cut_line_survives_the_file_and_a_merge(tmp_path):
    scene = Scene()
    lid = scene.layers.create("Steel").id
    scene.layers.set_cut_line_width(lid, 0.35)
    scene.layers.set_cut_line_color(lid, "#336699")
    path = str(tmp_path / "doc.serp3d")
    native.save_scene(scene, path)
    for read in (native.load_scene, native.merge_scene):
        out = Scene()
        read(out, path)
        steel = out.layers.find_by_name("Steel")
        assert (steel.cut_line_width, steel.cut_line_color) \
            == (0.35, "#336699"), read.__name__


def test_a_file_from_before_opens_with_the_old_cut_line():
    scene = Scene()
    native._load_doc(scene, {"format": "serpentine3d", "layers": [
        {"id": "default", "name": "Default", "color": [0.85, 0.85, 0.85]}]})
    layer = scene.layers.get(DEFAULT_LAYER_ID)
    assert (layer.cut_line_width, layer.cut_line_color) == (0.5, "ink")


def test_an_object_s_cut_line_survives_the_file(tmp_path):
    scene, walls, box = _scene()
    own = section_fill_dict("solid", cut_line_width=0.0,
                            cut_line_color="layer")
    scene.update(box.id, section_fill=own)
    path = str(tmp_path / "doc.serp3d")
    native.save_scene(scene, path)
    for read in (native.load_scene, native.merge_scene):
        out = Scene()
        read(out, path)
        (back,) = [o for o in out.all() if o.kind == "solid"]
        assert back.section_fill == own, read.__name__


# -- the layer page -----------------------------------------------------------

def _layer_page(*names):
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


def _choose(combo, data):
    combo.setCurrentIndex(combo.findData(data))
    QApplication.processEvents()


def test_the_layer_page_shows_and_sets_the_cut_line():
    scene, history, props, (walls,) = _layer_page("Walls")
    assert props.layer_cut_width.currentText() == "0.5"
    assert props.layer_cut_color.currentText() == "Ink"

    _type(props.layer_cut_width, "0.7 mm")
    assert scene.layers.get(walls.id).cut_line_width == 0.7
    _type(props.layer_cut_width, "None")
    assert scene.layers.get(walls.id).cut_line_width == 0.0
    assert props.layer_cut_width.currentText() == "None"
    history.undo()
    assert scene.layers.get(walls.id).cut_line_width == 0.7, \
        "the width was not an undo step of its own"

    _choose(props.layer_cut_color, "layer")
    assert scene.layers.get(walls.id).cut_line_color == "layer"


def test_a_width_that_is_not_one_puts_the_page_back():
    scene, _h, props, (walls,) = _layer_page("Walls")
    _type(props.layer_cut_width, "thick")
    assert scene.layers.get(walls.id).cut_line_width == 0.5
    assert props.layer_cut_width.currentText() == "0.5"


def test_every_fill_has_a_cut_line_even_none():
    """An empty cut is still outlined: that is all there is of it."""
    _scene_, _h, props, _made = _layer_page("Walls")
    for pattern in ("lines", "cross", "solid", "none"):
        _choose(props.layer_hatch, pattern)
        assert props.layer_form.isRowVisible(props.layer_cut_width), pattern
        assert props.layer_form.isRowVisible(props.layer_cut_color), pattern


def test_layers_that_disagree_show_a_blank_cut_line():
    scene, _h, props, (walls, glass) = _layer_page("Walls", "Glass")
    scene.layers.set_cut_line_width(glass.id, 0.25)
    scene.layers.set_cut_line_color(glass.id, "layer")
    scene.notify()
    QApplication.processEvents()
    assert props.layer_cut_width.currentText() == ""
    assert props.layer_cut_color.currentIndex() == -1


def test_choosing_a_cut_line_colour_of_its_own(monkeypatch):
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QColorDialog
    monkeypatch.setattr(QColorDialog, "getColor",
                        staticmethod(lambda *a, **k: QColor("#4080c0")))
    scene, _h, props, (walls,) = _layer_page("Walls")
    _choose(props.layer_cut_color, "choose")
    assert scene.layers.get(walls.id).cut_line_color == "#4080c0"
    assert scene.layers.get(walls.id).hatch_color == "ink", \
        "the cut line's colour landed on the hatch"
    assert props.layer_cut_color.currentData() == "#4080c0"


# -- the object page ----------------------------------------------------------

def _object_page():
    scene, walls, box = _scene()
    selection = SelectionManager(scene)
    history = History(scene)
    props = PropertiesPanel(scene, selection, history)
    props.show()
    selection.set([box.id])
    QApplication.processEvents()
    return scene, walls, props, box


def test_an_object_following_its_layer_shows_no_cut_line_of_its_own():
    _scene_, _walls, props, _box = _object_page()
    look = props.section_look
    assert not props.form.isRowVisible(look.cut_width)
    assert not props.form.isRowVisible(look.cut_color)


def test_a_style_of_its_own_starts_from_the_layer_s_cut_line():
    scene, walls, props, box = _object_page()
    scene.layers.set_cut_line_width(walls.id, 0.35)
    scene.layers.set_cut_line_color(walls.id, "#00ff00")
    _choose(props.section_hatch, "cross")
    own = scene.get(box.id).section_fill
    assert (own["cut_line_width"], own["cut_line_color"]) == (0.35, "#00ff00")
    look = props.section_look
    assert props.form.isRowVisible(look.cut_width)
    assert look.cut_width.currentText() == "0.35"

    _type(look.cut_width, "1")
    own = scene.get(box.id).section_fill
    assert own["cut_line_width"] == 1.0
    assert own["pattern"] == "cross", "the edit lost the rest of the style"
    assert scene.layers.get(walls.id).cut_line_width == 0.35, \
        "the object's edit went to its layer"


# -- the command and the API --------------------------------------------------

def test_the_sectionhatch_command_starts_from_the_layer_s_cut_line(env):
    scene, selection, _hist, _ctx, proc = env
    box = scene.add(g.make_box((0, 0, 0), 5, 5, 5))
    scene.layers.set_cut_line_width(box.layer_id, 0.7)
    selection.set([box.id])
    proc.run("sectionhatch")
    proc.provide_text("Solid")
    assert scene.get(box.id).section_fill["cut_line_width"] == 0.7


def _api(scene):
    from serpentine3d.api import SerpApi
    window = SimpleNamespace(scene=scene, selection=SelectionManager(scene),
                             history=History(scene),
                             viewport=SimpleNamespace(display_mode="shaded"),
                             processor=None)
    return SerpApi(window)


def test_a_script_can_set_a_layer_s_cut_line_and_read_it_back():
    scene = Scene()
    scene.layers.create("Walls")
    api = _api(scene)
    api.layers(action="style", name="Walls", style={
        "cut_line_width": 0.35, "cut_line_color": "layer"})
    walls = next(row for row in api.scene_info()["layers"]
                 if row["name"] == "Walls")
    assert walls["cut_line"] == {"width": 0.35, "color": "layer"}


def test_a_cut_line_colour_the_layer_cannot_take_is_refused():
    from serpentine3d.api import ApiError
    scene = Scene()
    scene.layers.create("Walls")
    with pytest.raises(ApiError, match="cut_line_color"):
        _api(scene).layers(action="style", name="Walls",
                           style={"cut_line_color": "tartan"})
