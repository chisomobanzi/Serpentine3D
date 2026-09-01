"""A cut face that names a solid material is flooded, not lined.

Lines and crosses are segments, and a detail draws them with the rest of
its linework. Solid is not: it is the face itself, bore and all, and
only a painter can flood a shape with a hole in it. So it comes back
from the hatching on its own and is laid over the detail afterwards, on
the screen and on the plot alike, in the same see-through grey a solid
hatch dropped on the paper by hand is drawn in.
"""

from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QImage, QPainter, QPainterPath

from serpentine3d.core import geometry as g
from serpentine3d.core.layout import cut_patterns
from serpentine3d.fileio import pdf

import pytest


SQUARE = [(-10.0, -10.0), (10.0, -10.0), (10.0, 10.0), (-10.0, 10.0)]
HOLE = [(-4.0, -4.0), (4.0, -4.0), (4.0, 4.0), (-4.0, 4.0)]
OVER = [(0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)]
PAPER_H = 200.0


def _dev(x, y):
    """Where a paper millimetre lands on the plot, at k=1."""
    return QPointF(x, PAPER_H - y)


# -- what each face is made of --------------------------------------------

def test_the_materials_come_out_in_the_order_the_faces_do():
    data = {"cut": [1, 2, 3],
            "cut_by_obj": [("a", "solid", 1), ("b", "", 2),
                           ("c", "cross", 3)]}
    assert cut_patterns(data) == ["solid", "", "cross"]


def test_a_detail_with_no_record_of_what_it_cut_hatches_as_before():
    """An older cache, or a fake in a test, must not stop the drawing."""
    assert cut_patterns({"cut": [1, 2]}) == []


# -- the plot -------------------------------------------------------------

class Recorder:
    """A painter that writes down what it was asked to draw."""

    def __init__(self):
        self.lines = []
        self.polylines = []
        self.paths = []

    def save(self):
        pass

    def restore(self):
        pass

    def setClipRect(self, *a):
        pass

    def setPen(self, pen):
        pass

    def setBrush(self, brush):
        pass

    def drawLine(self, a, b):
        self.lines.append(((a.x(), a.y()), (b.x(), b.y())))

    def drawPolyline(self, poly):
        self.polylines.append([(p.x(), p.y()) for p in poly])

    def drawPath(self, path):
        self.paths.append(QPainterPath(path))


def _plot(regions, patterns):
    """Plot one detail whose only content is a section cut."""
    detail = SimpleNamespace(x=0.0, y=0.0, w=100.0, h=100.0,
                             scale_denom=1.0, display_mode="shaded")
    data = {"visible": [], "hidden": [], "cut": regions,
            "visible_groups": [],
            "cut_by_obj": [(i, p, r) for i, (p, r)
                           in enumerate(zip(patterns, regions))]}
    view = SimpleNamespace(_detail_hlr=lambda d: data)
    rec = Recorder()
    pdf._paint_detail_vector(rec, view, detail, SimpleNamespace(
        paper_h=PAPER_H, paper_w=300.0), 1.0)
    return rec


def test_a_solid_cut_is_flooded_on_paper():
    rec = _plot([[SQUARE]], ["solid"])
    assert len(rec.paths) == 1, "the face was left as an empty outline"
    assert rec.paths[0].contains(_dev(45.0, 45.0)), \
        "the flood missed the material it was meant to fill"


def test_a_flooded_cut_leaves_its_bore_open():
    rec = _plot([[SQUARE, HOLE]], ["solid"])
    assert not rec.paths[0].contains(_dev(50.0, 50.0)), \
        "the bore was filled in, so the pipe plots as a bar"


def test_a_flooded_cut_draws_no_hatch_lines():
    assert _plot([[SQUARE]], ["solid"]).lines == [], \
        "the face was hatched as well as flooded"


def test_a_face_is_still_outlined_when_it_is_flooded():
    assert len(_plot([[SQUARE, HOLE]], ["solid"]).polylines) == 2


def test_two_faces_of_one_material_do_not_cancel_each_other_out():
    """Cut faces overlap on the page; even-odd across them would void it."""
    rec = _plot([[SQUARE], [OVER]], ["solid", "solid"])
    assert any(p.contains(_dev(55.0, 55.0)) for p in rec.paths), \
        "where the two faces lie over each other the plot came out empty"


def test_a_cross_cut_is_hatched_twice_on_paper():
    plain = len(_plot([[SQUARE]], ["lines"]).lines)
    assert plain > 0
    assert len(_plot([[SQUARE]], ["cross"]).lines) > plain, \
        "the second set of lines never reached the plot"


def test_a_cut_with_no_material_plots_the_way_it_always_did():
    was = _plot([[SQUARE, HOLE]], [""])
    assert was.paths == []
    assert was.lines == _plot([[SQUARE, HOLE]], ["lines"]).lines


# -- the screen -----------------------------------------------------------

class Watcher(QPainter):
    """A real painter that keeps the paths and clips that go through it."""

    def __init__(self, device):
        super().__init__(device)
        self.paths = []
        self.clips = []

    def drawPath(self, path):
        self.paths.append(QPainterPath(path))
        super().drawPath(path)

    def setClipRect(self, *a):
        self.clips.append(a)
        return super().setClipRect(*a)


@pytest.fixture
def cut_sheet():
    """One bar, cut, on a layer that says what the bar is made of."""
    from serpentine3d.app import MainWindow
    from serpentine3d.core.layout import DetailView, Layout
    from serpentine3d.ui.camera import STANDARD_VIEWS

    w = MainWindow()
    w.resize(1200, 800)
    steel = w.scene.layers.create("Steel")
    obj = w.scene.add(g.make_box((-20.0, -20.0, 0.0), 40.0, 40.0, 40.0))
    w.scene.update(obj.id, layer_id=steel.id)
    az, el = STANDARD_VIEWS["front"]
    det = DetailView(x=40.0, y=60.0, w=200.0, h=150.0, azimuth=az,
                     elevation=el, target=[0.0, 0.0, 20.0], scale_denom=2.0,
                     display_mode="hidden", section_offset=0.0)
    lay = Layout(name="Sheet1")
    lay.details.append(det)
    w.scene.layouts.append(lay)
    w.switch_space(lay.id)
    return w, w.viewport.layout_view, det, steel


def _overlay(w, lv):
    image = QImage(1200, 800, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.white)
    painter = Watcher(image)
    try:
        lv.paint_overlay(painter)
    finally:
        painter.end()
    w.mark_saved()
    return painter


def test_the_screen_floods_a_solid_cut_too(cut_sheet):
    w, lv, _det, steel = cut_sheet
    w.scene.layers.set_hatch(steel.id, "solid")
    lv._hlr_cache.clear()
    assert _overlay(w, lv).paths, \
        "the cut face is flooded on the plot and empty on screen"


def test_the_screen_floods_nothing_when_no_layer_asks_for_it(cut_sheet):
    w, lv, _det, _steel = cut_sheet
    assert _overlay(w, lv).paths == []


def test_a_flood_stays_inside_the_detail_it_belongs_to(cut_sheet):
    """Nothing a detail draws may spill over the rest of the sheet."""
    w, lv, det, steel = cut_sheet
    w.scene.layers.set_hatch(steel.id, "solid")
    lv._hlr_cache.clear()
    clips = _overlay(w, lv).clips
    x0, y0 = lv.paper_to_screen(det.x, det.y + det.h)
    assert any(abs(c[0] - x0) <= 1 and abs(c[1] - y0) <= 1
               for c in clips if len(c) == 4), \
        f"the flood was drawn unclipped: {clips}"
