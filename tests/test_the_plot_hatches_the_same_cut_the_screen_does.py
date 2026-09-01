"""What the plot draws over a section cut is what the screen drew.

The screen and the PDF each used to take the detail's section outlines
and work out the hatching for themselves, which is how a bore came to be
filled in on paper while the same drawing looked right on screen. Both
now ask one function the same question, so a hole stays a hole
everywhere.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from serpentine3d.core.layout import cut_hatching
from serpentine3d.fileio import pdf


SQUARE = [(-10.0, -10.0), (10.0, -10.0), (10.0, 10.0), (-10.0, 10.0)]
HOLE = [(-4.0, -4.0), (4.0, -4.0), (4.0, 4.0), (-4.0, 4.0)]
PAPER_H = 200.0


class Recorder:
    """A painter that writes down what it was asked to draw."""

    def __init__(self):
        self.lines = []
        self.polylines = []

    def save(self):
        pass

    def restore(self):
        pass

    def setClipRect(self, *a):
        pass

    def setPen(self, pen):
        pass

    def drawLine(self, a, b):
        self.lines.append(((a.x(), a.y()), (b.x(), b.y())))

    def drawPolyline(self, poly):
        self.polylines.append([(p.x(), p.y()) for p in poly])


def _plot(regions):
    """Plot one detail whose only content is the section cut."""
    detail = SimpleNamespace(x=0.0, y=0.0, w=100.0, h=100.0,
                             scale_denom=1.0, display_mode="shaded")
    view = SimpleNamespace(_detail_hlr=lambda d: {
        "visible": [], "hidden": [], "cut": regions, "visible_groups": []})
    rec = Recorder()
    pdf._paint_detail_vector(rec, view, detail, SimpleNamespace(
        paper_h=PAPER_H, paper_w=300.0), 1.0)
    return rec


def _flip(seg):
    """A paper segment as the plot writes it, y measured from the top."""
    (ax, ay), (bx, by) = seg
    return ((ax, PAPER_H - ay), (bx, PAPER_H - by))


def test_the_plot_hatches_exactly_what_the_screen_hatches():
    rec = _plot([[SQUARE, HOLE]])
    fill, _loops, _solid = cut_hatching([[SQUARE, HOLE]], 50.0, 50.0, 1.0)
    assert fill, "nothing to compare: the cut produced no hatching at all"
    assert rec.lines == [_flip(seg) for seg in fill], \
        "the plot worked the hatching out for itself and got another answer"


def test_the_bore_is_left_empty_on_paper():
    """The one thing a section drawing exists to say: this is a pipe."""
    rec = _plot([[SQUARE, HOLE]])
    middle = [seg for seg in rec.lines
              if all(abs(x - 50.0) < 3.0 and abs((PAPER_H - y) - 50.0) < 3.0
                     for x, y in seg)]
    assert middle == [], f"{len(middle)} hatch lines ran through the bore"


def test_the_hole_is_outlined_as_well_as_the_ring():
    rec = _plot([[SQUARE, HOLE]])
    assert len(rec.polylines) == 2, \
        "the bore has no line round it, so it reads as part of the material"


def test_an_outline_closes_so_the_last_edge_is_drawn():
    rec = _plot([[SQUARE]])
    ring = rec.polylines[0]
    assert ring[0] == pytest.approx(ring[-1]), \
        "the cut face is drawn with one side missing"


def test_a_detail_with_no_cut_draws_no_hatching():
    rec = _plot([])
    assert rec.lines == [] and rec.polylines == []
