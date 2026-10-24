"""A detail's scale is a ratio of real lengths, whatever the document's units.

A detail keeps its scale as the model units one millimetre of paper shows,
and everything that wrote a scale down or read one in took that number for
the ratio. In a millimetre document the two are the same number. In an inch
document they are not: a detail labelled 1:4 showed four inches to the
paper millimetre, which is 1:101.6, and an 18 inch part plotted 4.5 mm wide
instead of 114.3 mm (#102).

The number a detail keeps is still model units to the paper millimetre, so
a sheet already drawn plots exactly as it did. What changes is what a scale
typed, picked or printed means: 1:4 is a quarter of real size in any units,
and an inch sheet drawn before says the 1:101.6 it has always plotted at.
Drawings in inches and in feet are also offered the scales they are drawn
at, written the way they write them: 1/4" = 1'-0".
"""

from __future__ import annotations

import math

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QComboBox

from serpentine3d.app import MainWindow
from serpentine3d.core import geometry as g
from serpentine3d.core.layout import (
    PAPER_SIZES, DetailView, Layout, detail_project, format_scale,
    parse_scale, resolve_associative, scale_presets,
)
from serpentine3d.ui.camera import STANDARD_VIEWS
from serpentine3d.utils.units import TO_MM

QUARTER_INCH = "1/4\" = 1'-0\""
INCH_A_FOOT = "1\" = 1'-0\""


@pytest.fixture
def window():
    made = []

    def make(units, width, depth):
        """A document in `units` holding a part `width` x `depth` on plan,
        and a Tabloid sheet to draw it on: the report's drawing."""
        w = MainWindow()
        w.resize(1200, 800)
        w.scene.units = units
        w.scene.add(g.make_box((0.0, 0.0, 0.0), width, depth, 1.0),
                    name="seat blank")
        paper_w, paper_h = PAPER_SIZES["Tabloid"]
        lay = Layout(name="Sheet1", paper_w=paper_w, paper_h=paper_h)
        w.scene.layouts.append(lay)
        w.switch_space(lay.id)
        made.append(w)
        return w, lay

    yield make
    for w in made:
        w.mark_saved()
        w.close()


def _place(w, lay, scale, view="Top"):
    """`detail` as the report ran it: a view, a scale, any frame."""
    proc = w.processor
    proc.run("detail")
    proc.provide_text("View")
    proc.provide_text(view)
    proc.provide_text("Scale")
    proc.provide_text(scale)
    proc.provide((20.0, 20.0, 0.0))
    proc.provide((400.0, 260.0, 0.0))
    assert not proc.busy
    return lay.details[-1]


class _Plotter:
    """Enough of a painter to take down the lines a detail plots."""

    def __init__(self):
        self.points = []

    def drawPolyline(self, poly):
        self.points += [(poly.at(i).x(), poly.at(i).y())
                        for i in range(poly.size())]

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


def _plotted(w, lay, det):
    """The part's width and height as the PDF draws it, in millimetres."""
    from serpentine3d.fileio import pdf
    plotter = _Plotter()
    pdf._paint_detail_vector(plotter, w.viewport.layout_view, det, lay, 1.0)
    xs, ys = zip(*plotter.points)
    return max(xs) - min(xs), max(ys) - min(ys)


# -- the report ---------------------------------------------------------------

def test_1_to_4_in_an_inch_document_plots_a_quarter_of_real_size(window):
    """The report as it was met: an 18 x 16 inch part at 1:4 measured
    4.50 x 4.00 mm on the PDF, where a quarter of it is 114.3 x 101.6."""
    w, lay = window("in", 18.0, 16.0)
    det = _place(w, lay, "1:4")
    assert _plotted(w, lay, det) == pytest.approx((114.3, 101.6), abs=0.05)
    assert det.scale_text("in") == "1:4"


def test_a_millimetre_document_plots_as_it_always_has(window):
    w, lay = window("mm", 457.2, 406.4)
    det = _place(w, lay, "1:4")
    assert _plotted(w, lay, det) == pytest.approx((114.3, 101.6), abs=0.05)
    assert det.scale_denom == pytest.approx(4.0)
    assert det.scale_text("mm") == "1:4"


def _old_inch_sheet(lay):
    """The report's detail as 0.12.1 kept it: '1:4', four inches to the
    paper millimetre."""
    az, el = STANDARD_VIEWS["top"]
    det = DetailView(x=20.0, y=20.0, w=380.0, h=240.0, azimuth=az,
                     elevation=el, target=[9.0, 8.0, 0.5], scale_denom=4.0,
                     display_mode="hidden")
    lay.details.append(det)
    return det


def test_an_inch_sheet_drawn_before_plots_as_it_did(window):
    w, lay = window("in", 18.0, 16.0)
    det = _old_inch_sheet(lay)
    assert _plotted(w, lay, det) == pytest.approx((4.5, 4.0), abs=0.05)


def test_a_new_detail_starts_at_1_to_100_in_any_units(window):
    """Not at a hundred inches to the millimetre, which is 1:2540."""
    w, lay = window("in", 18.0, 16.0)
    proc = w.processor
    proc.run("detail")
    proc.provide((20.0, 20.0, 0.0))
    proc.provide((400.0, 260.0, 0.0))
    assert not proc.busy
    det = lay.details[0]
    assert det.scale_denom * TO_MM["in"] == pytest.approx(100.0)
    assert det.scale_text("in") == "1:100"


# -- what a scale says --------------------------------------------------------

@pytest.mark.parametrize("text, units, ratio", [
    ("1:4", "in", 4.0),
    ("1:4", "mm", 4.0),
    ("1:50", "m", 50.0),
    ("2:1", "in", 0.5),
    ("4", "in", 4.0),
    (QUARTER_INCH, "ft", 48.0),
    (QUARTER_INCH, "mm", 48.0),      # a length with its units is that length
    ("1-1/2\" = 1'-0\"", "in", 8.0),
    ("1\" = 20'", "in", 240.0),
    ("10mm = 1m", "in", 100.0),
    ("1 = 10", "m", 10.0),           # and one without is in the document's
])
def test_a_typed_scale_is_the_ratio_it_says(text, units, ratio):
    assert parse_scale(text, units) * TO_MM[units] == pytest.approx(ratio)


@pytest.mark.parametrize("text", [
    "banana", "", "0", "1:0", "0:4", "-1:4", "1 =", "= 1'", "0\" = 1'",
    "1\" = banana", "inf", "nan",
])
def test_what_is_not_a_scale_is_refused(text):
    assert parse_scale(text, "in") is None


@pytest.mark.parametrize("units, ratio, text", [
    ("in", 4.0, "1:4"),
    ("in", 101.6, "1:101.6"),
    ("in", 0.5, "2:1"),
    ("in", 48.0, QUARTER_INCH),
    ("ft", 12.0, INCH_A_FOOT),
    ("ft", 240.0, "1\" = 20'"),
    ("mm", 48.0, "1:48"),            # a metric drawing has no use for the name
    ("m", 100.0, "1:100"),
])
def test_a_scale_is_written_as_the_ratio_it_is(units, ratio, text):
    assert format_scale(ratio / TO_MM[units], units) == text


@pytest.mark.parametrize("units", ["mm", "cm", "m", "in", "ft"])
def test_every_scale_on_offer_reads_back_as_itself(units):
    for name in scale_presets(units):
        assert format_scale(parse_scale(name, units), units) == name


@pytest.mark.parametrize("units", ["in", "ft"])
def test_inches_and_feet_are_offered_the_scales_they_draw_at(units):
    """Full size and half for the workshop, and the architect's and the
    engineer's scales written the way they write them."""
    offered = scale_presets(units)
    for name in ("1:1", "1:2", INCH_A_FOOT, QUARTER_INCH, "1\" = 20'"):
        assert name in offered
    ratios = {round(parse_scale(n, units) * TO_MM[units], 6) for n in offered}
    assert len(ratios) == len(offered), "a scale offered twice, by two names"


# -- what the sheet says ------------------------------------------------------

class _Words(QPainter):
    """A real painter that keeps the words drawn through it."""

    def __init__(self, device):
        super().__init__(device)
        self.words = []

    def drawText(self, *args):
        self.words += [a for a in args if isinstance(a, str)]
        return super().drawText(*args)


def _words(paint) -> list:
    image = QImage(1200, 800, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.white)
    painter = _Words(image)
    try:
        paint(painter)
    finally:
        painter.end()
    return painter.words


def test_the_sheet_and_the_pdf_print_the_scale_it_plots_at(window):
    """The label, and the title block's scale, on the screen and on paper."""
    from serpentine3d.fileio import pdf
    w, lay = window("in", 18.0, 16.0)
    _old_inch_sheet(lay)
    lay.title_block = {"template": "standard", "fields": {
        "project": "Seat", "title": "Blank", "author": ""}}
    lv = w.viewport.layout_view
    lv.fit()
    lv._fitted_for = lay.id

    on_screen = _words(lv.paint_overlay)
    on_paper = _words(lambda painter: pdf._paint_layout(painter, w, lay, 2.0))

    for words in (on_screen, on_paper):
        assert "1:101.6" in words
        assert "scale: 1:101.6" in words


# -- on the Properties panel --------------------------------------------------

def _pick(w, det):
    lv = w.viewport.layout_view
    lv.selected = [("detail", det)]
    w.viewport.layoutSelectionChanged.emit()


def _items(combo: QComboBox) -> list[str]:
    return [combo.itemText(i) for i in range(combo.count())]


def _scale_combo(panel) -> QComboBox:
    """The scale control, found by what it offers in any units."""
    for combo in panel.findChildren(QComboBox):
        if "1:1" in _items(combo) and "1:2" in _items(combo):
            return combo
    raise AssertionError("no scale control on the panel for a detail")


def _type(combo: QComboBox, text: str):
    edit = combo.lineEdit()
    edit.clear()
    QTest.keyClicks(edit, text)
    QTest.keyClick(edit, Qt.Key.Key_Return)


def test_an_inch_detail_is_offered_an_architects_scale_by_its_name(window):
    w, lay = window("in", 18.0, 16.0)
    det = _place(w, lay, "1:4")
    _pick(w, det)
    combo = _scale_combo(w.properties)
    assert combo.currentText() == "1:4"
    assert QUARTER_INCH in _items(combo)

    combo.setCurrentText(QUARTER_INCH)

    assert det.scale_denom * TO_MM["in"] == pytest.approx(48.0)
    assert combo.currentText() == QUARTER_INCH


def test_a_scale_typed_on_the_panel_is_real_size_too(window):
    w, lay = window("in", 18.0, 16.0)
    det = _place(w, lay, "1:2")
    _pick(w, det)
    _type(_scale_combo(w.properties), "1:4")
    assert _plotted(w, lay, det) == pytest.approx((114.3, 101.6), abs=0.05)


def test_the_list_follows_the_documents_units(window):
    w, lay = window("mm", 457.2, 406.4)
    det = _place(w, lay, "1:4")
    _pick(w, det)
    combo = _scale_combo(w.properties)
    assert "1:50" in _items(combo) and QUARTER_INCH not in _items(combo)

    _units(w, "in", "Yes")
    _pick(w, det)

    assert QUARTER_INCH in _items(combo) and "1:50" not in _items(combo)
    assert combo.currentText() == "1:4"


# -- changing the units -------------------------------------------------------

def _units(w, units, rescale):
    proc = w.processor
    proc.run("units")
    proc.provide_text(units)
    proc.provide_text(rescale)
    assert not proc.busy


def test_rescaling_to_inches_keeps_the_sheet_as_it_was(window):
    """The model keeps its real size, so the detail keeps its scale and
    looks where it did, and its dimension reads the same length."""
    w, lay = window("mm", 457.2, 406.4)
    det = _place(w, lay, "1:4")
    a = detail_project(det, (0.0, 0.0, 0.0))
    b = detail_project(det, (457.2, 0.0, 0.0))
    proc = w.processor
    proc.run("dim")
    for point in (a, b, (a[0], a[1] - 10.0)):
        proc.provide((point[0], point[1], 0.0))
    assert not proc.busy
    before = _plotted(w, lay, det)

    _units(w, "in", "Yes")

    assert det.scale_text("in") == "1:4"
    assert _plotted(w, lay, det) == pytest.approx(before, abs=0.05)
    assert detail_project(det, (0.0, 0.0, 0.0)) == pytest.approx(a)
    resolve_associative(lay)
    dim = lay.dims[0]
    length = math.dist((dim.x1, dim.y1), (dim.x2, dim.y2))
    assert (dim.x1, dim.y1) == pytest.approx(a)
    assert w.scene.format_length(length * dim.scale_denom) == "18\""


@pytest.mark.parametrize("rescale", ["Yes", "No"])
def test_undoing_the_units_puts_the_sheet_back_in_one_step(window, rescale):
    w, lay = window("mm", 457.2, 406.4)
    _place(w, lay, "1:4")
    _units(w, "in", rescale)

    w.history.undo()

    back = w.scene.layouts[0].details[0]
    assert w.scene.units == "mm"
    assert back.scale_denom == pytest.approx(4.0)
    assert back.target == pytest.approx([228.6, 203.2, 0.5])
    lo, hi = w.scene.bbox()
    assert hi[0] - lo[0] == pytest.approx(457.2)


def test_new_units_without_rescaling_keep_the_scale_it_was_set_at(window):
    """The part is 457.2 inches now, and a quarter of it is still a quarter."""
    w, lay = window("mm", 457.2, 406.4)
    det = _place(w, lay, "1:4")
    _units(w, "in", "No")
    assert det.scale_text("in") == "1:4"
    assert _plotted(w, lay, det) == pytest.approx(
        (114.3 * 25.4, 101.6 * 25.4), abs=0.05)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
