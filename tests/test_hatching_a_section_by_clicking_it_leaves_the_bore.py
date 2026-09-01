"""Clicking inside a sectioned pipe hatches the wall, not the bore.

Region mode drops a hatch into whatever closed area you click in. On a
section cut that area is a ring of material, and the bore in the middle
of it is not material at all: a hatch that fills it says "solid bar"
about a model that says "pipe". The cut knows where its holes are, so
the hatch it produces knows too, and the sheet draws it that way.
"""

from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtCore import QPointF
from PySide6.QtGui import QPainterPath

from serpentine3d.commands import drafting
from serpentine3d.core.layout import DetailView, Hatch, Layout
from serpentine3d.ui.annot_paint import draw_hatch


# A ring of wall around a square bore, in the detail's own units.
SQUARE = [(-10.0, -10.0), (10.0, -10.0), (10.0, 10.0), (-10.0, 10.0),
          (-10.0, -10.0)]
HOLE = [(-4.0, -4.0), (4.0, -4.0), (4.0, 4.0), (-4.0, 4.0), (-4.0, -4.0)]


def _sheet(monkeypatch, *, cut=(), visible=()):
    """A layout with one 1:1 detail at the middle of the sheet."""
    lay = Layout()
    det = DetailView(x=0.0, y=0.0, w=100.0, h=100.0, scale_denom=1.0)
    lay.details.append(det)
    view = SimpleNamespace(_detail_hlr=lambda d: {
        "visible": list(visible), "hidden": [], "cut": list(cut)})
    monkeypatch.setattr(drafting, "_layout_view", lambda ctx: view)
    return lay


# -- what a click picks up ------------------------------------------------

def test_a_click_in_the_wall_takes_the_bore_along_as_a_hole(monkeypatch):
    lay = _sheet(monkeypatch, cut=[[SQUARE, HOLE]])
    points, holes = drafting._region_at(None, lay, 57.0, 50.0)
    assert len(holes) == 1, "the wall was hatched as though it were solid"
    assert min(x for x, _y in points) == 40.0, "picked up the wrong loop"
    assert min(x for x, _y in holes[0]) == 46.0


def test_a_click_in_the_bore_hatches_the_bore_you_pointed_at(monkeypatch):
    """You pointed at the hole, so the hole is the region."""
    lay = _sheet(monkeypatch, cut=[[SQUARE, HOLE]])
    points, holes = drafting._region_at(None, lay, 50.0, 50.0)
    assert holes == []
    assert min(x for x, _y in points) == 46.0


def test_plain_linework_has_nothing_punched_out_of_it(monkeypatch):
    lay = _sheet(monkeypatch, visible=[SQUARE])
    points, holes = drafting._region_at(None, lay, 50.0, 50.0)
    assert holes == [] and len(points) == 4


def test_a_click_on_empty_paper_finds_no_region(monkeypatch):
    lay = _sheet(monkeypatch, cut=[[SQUARE, HOLE]])
    assert drafting._region_at(None, lay, 95.0, 95.0) is None


# -- and how the sheet draws it -------------------------------------------

class Recorder:
    """A painter that writes down the shapes it was handed."""

    def __init__(self):
        self.polygons = []
        self.paths = []
        self.lines = []

    def setPen(self, pen):
        pass

    def setBrush(self, brush):
        pass

    def drawPolygon(self, poly):
        self.polygons.append([(p.x(), p.y()) for p in poly])

    def drawPath(self, path):
        self.paths.append(QPainterPath(path))

    def drawLine(self, a, b):
        self.lines.append(((a.x(), a.y()), (b.x(), b.y())))


def _draw(hatch):
    rec = Recorder()
    draw_hatch(rec, lambda x, y: (x, y), 1.0, hatch)
    return rec


def _holed(pattern="lines"):
    return Hatch(points=[list(p) for p in SQUARE[:-1]],
                 holes=[[list(p) for p in HOLE[:-1]]],
                 pattern=pattern, angle=0.0, spacing=2.0)


def test_the_hole_gets_a_line_round_it_like_any_other_edge():
    assert len(_draw(_holed()).polygons) == 2, \
        "the bore has no outline, so it reads as part of the wall"


def _through_the_bore(seg):
    """Does any part of this hatch line lie inside the bore?"""
    (ax, ay), (bx, by) = seg
    for i in range(41):
        t = i / 40
        x, y = ax + (bx - ax) * t, ay + (by - ay) * t
        if abs(x) < 3.9 and abs(y) < 3.9:
            return True
    return False


def test_the_hatching_stops_at_the_bore_and_picks_up_again():
    lines = _draw(_holed()).lines
    assert lines, "nothing was hatched at all"
    crossing = [seg for seg in lines if _through_the_bore(seg)]
    assert crossing == [], f"{len(crossing)} hatch lines crossed the bore"


def test_a_solid_hatch_fills_the_wall_and_not_the_bore():
    """Solid fill is one shape with a hole in it, not two shapes."""
    rec = _draw(_holed("solid"))
    assert len(rec.paths) == 1, \
        "a solid hatch is drawn as one filled area, not a shape per ring"
    path = rec.paths[0]
    assert path.contains(QPointF(7.0, 0.0)), "the wall was left unfilled"
    assert not path.contains(QPointF(0.0, 0.0)), \
        "the bore filled in, so the section reads as a solid bar"


def test_a_hatch_with_no_holes_is_drawn_the_way_it_always_was():
    plain = Hatch(points=[list(p) for p in SQUARE[:-1]], pattern="lines",
                  angle=0.0, spacing=2.0)
    assert len(_draw(plain).polygons) == 1
