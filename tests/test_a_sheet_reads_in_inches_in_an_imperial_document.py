"""A sheet reads and is typed in inches in an inch or a feet document.

A sheet is kept in millimetres, and everything on it that gave a length gave
millimetres. In an inch document a dimension drawn on bare paper wrote its
millimetres with an inch mark after them, so 50.8 mm of paper read 50.8".
What was typed there took a bare number as millimetres but a unit as the
document's, so "1in,1in" on an inch sheet landed 1 mm in, and "50mm,0" in a
metre document landed 0.05 mm in.

A sheet now works in the units Rhino's templates give their layouts: inches
in an inch or a feet document, millimetres in a metric one. It is still kept
in millimetres, so a drawing opens and plots as it did; what changes is what
a length on it reads as and what a typed one means. A dimension over a
detail reads the model, in the model's units, as before. Print widths and
hatch spacing stay in millimetres in any document; text and arrows are sized
in the sheet's units (test_text_on_an_inch_sheet_is_sized_in_inches.py).
"""

from __future__ import annotations

import ezdxf
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter

from serpentine3d.app import MainWindow
from serpentine3d.core import geometry as g
from serpentine3d.core.layout import (PAPER_SIZES, DetailView, Layout, LinearDim,
                                      layouts_from_json, layouts_to_json)
from serpentine3d.ui.camera import STANDARD_VIEWS
from serpentine3d.ui.gumball import CONE1, SHAFT0

# 50.8 mm of bare paper, its line a little above it
TWO_INCHES = ((220.0, 200.0, 0.0), (270.8, 200.0, 0.0), (245.0, 215.0, 0.0))


@pytest.fixture
def window():
    made = []

    def make(units):
        """A document in `units` with a part in it, and a Tabloid sheet."""
        w = MainWindow()
        w.resize(1200, 800)
        w.scene.units = units
        w.scene.add(g.make_box((0.0, 0.0, 0.0), 10.0, 8.0, 1.0), name="part")
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


def _run(w, name, *answers):
    """A command, answered as typed (text) or as picked (a point in mm)."""
    proc = w.processor
    proc.run(name)
    for answer in answers:
        if isinstance(answer, str):
            proc.provide_text(answer)
        else:
            proc.provide(answer)
    assert not proc.busy


def _detail(w, lay, scale):
    """A Top detail at `scale` in the sheet's lower left, 180 x 130 mm."""
    _run(w, "detail", "View", "Top", "Scale", scale,
         (20.0, 20.0, 0.0), (200.0, 150.0, 0.0))
    return lay.details[-1]


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


def _shown(w, lay) -> tuple[list, list]:
    """The words the sheet shows on screen, and the words its PDF prints."""
    from serpentine3d.fileio import pdf
    lv = w.viewport.layout_view
    lv.fit()
    lv._fitted_for = lay.id
    return (_words(lv.paint_overlay),
            _words(lambda painter: pdf._paint_layout(painter, w, lay, 2.0)))


# -- a dimension on bare paper --------------------------------------------------

def test_a_dimension_on_bare_paper_reads_inches_in_an_inch_document(window):
    """50.8 mm of paper is two inches, and read 50.8"."""
    w, lay = window("in")
    _run(w, "dim", *TWO_INCHES)
    for words in _shown(w, lay):
        assert '2"' in words
        assert '50.8"' not in words


def test_a_feet_document_reads_its_sheet_in_inches(window):
    """As Rhino's feet template sets its layouts: 2", not 0'-2"."""
    w, lay = window("ft")
    _run(w, "dim", *TWO_INCHES)
    for words in _shown(w, lay):
        assert '2"' in words


@pytest.mark.parametrize("units", ["mm", "cm", "m"])
def test_a_metric_document_reads_its_sheet_in_millimetres(window, units):
    """Not 50.8 cm, or 50.8 m."""
    w, lay = window(units)
    _run(w, "dim", *TWO_INCHES)
    for words in _shown(w, lay):
        assert "50.8 mm" in words


def test_the_dxf_writes_what_the_sheet_shows(window, tmp_path):
    from serpentine3d.fileio.dxf import export_layout_dxf
    w, lay = window("in")
    _run(w, "dim", *TWO_INCHES)
    path = str(tmp_path / "sheet.dxf")
    export_layout_dxf(w, lay, path)
    texts = [e.dxf.text for e in ezdxf.readfile(path).modelspace().query("TEXT")]
    assert '2"' in texts


def test_placing_one_says_how_long_it_is_on_paper(window):
    w, _lay = window("in")
    said = []
    w.ctx.add_echo_listener(said.append)
    _run(w, "dim", *TWO_INCHES)
    assert 'Dimension placed: 2" on paper' in said


def test_a_radius_and_a_diameter_on_bare_paper_read_inches(window):
    w, lay = window("in")
    _run(w, "dimradius", (300.0, 200.0, 0.0), (325.4, 200.0, 0.0))
    _run(w, "dimdiameter", (300.0, 100.0, 0.0), (325.4, 100.0, 0.0))
    for words in _shown(w, lay):
        assert 'R1"' in words
        assert 'Ø2"' in words


# -- a dimension over a detail ---------------------------------------------------

def test_a_dimension_over_a_detail_still_reads_the_model(window):
    """50.8 mm of paper at 1:4 is 8 inches of the model."""
    w, lay = window("in")
    _detail(w, lay, "1:4")
    _run(w, "dim", (60.0, 60.0, 0.0), (110.8, 60.0, 0.0), (85.0, 80.0, 0.0))
    for words in _shown(w, lay):
        assert '8"' in words


def test_a_centimetre_dimension_at_1_to_10_reads_the_model(window):
    """A centimetre detail at 1:10 shows a model centimetre to the paper
    millimetre, the same 1 a dimension on bare paper keeps, so that number
    cannot be what tells the two apart."""
    w, lay = window("cm")
    _detail(w, lay, "1:10")
    _run(w, "dim", (60.0, 60.0, 0.0), (110.8, 60.0, 0.0), (85.0, 80.0, 0.0))
    for words in _shown(w, lay):
        assert "50.8 cm" in words


def test_a_sheet_drawn_before_reads_its_paper_dimensions_in_inches(window):
    """Dimensions saved before they said what they measure: one with no
    detail under it and a scale of one was drawn on bare paper."""
    w, lay = window("in")
    det = _detail(w, lay, "1:4")
    lay.dims += [LinearDim(x1=220.0, y1=200.0, x2=270.8, y2=200.0, offset=15.0),
                 LinearDim(x1=60.0, y1=60.0, x2=110.8, y2=60.0, offset=20.0,
                           scale_denom=det.scale_denom)]
    data = layouts_to_json([lay])
    for d in data[0]["dims"]:
        d.pop("measures_paper", None)
    w.scene.layouts[:] = layouts_from_json(data)
    old = w.scene.layouts[0]
    w.switch_space(old.id)
    for words in _shown(w, old):
        assert '2"' in words
        assert '8"' in words


def test_changing_the_units_keeps_a_paper_dimension_reading_the_paper(window):
    w, lay = window("mm")
    _run(w, "dim", *TWO_INCHES)
    _run(w, "units", "in", "No")
    assert '2"' in _shown(w, lay)[0]
    _run(w, "units", "mm", "No")
    assert "50.8 mm" in _shown(w, lay)[0]


# -- what is typed on paper -------------------------------------------------------

def test_a_point_typed_on_an_inch_sheet_is_in_inches(window):
    w, lay = window("in")
    _run(w, "dim", "1,1", "3,1", "2,2")
    dim = lay.dims[-1]
    assert (dim.x1, dim.y1, dim.x2, dim.y2) == pytest.approx(
        (25.4, 25.4, 76.2, 25.4))


def test_relative_and_polar_points_on_an_inch_sheet_are_in_inches(window):
    w, lay = window("in")
    _run(w, "dim", "1,1", "@2,0", "1<90")
    dim = lay.dims[-1]
    assert (dim.x2, dim.y2) == pytest.approx((76.2, 25.4))
    assert dim.offset == pytest.approx(25.4)


@pytest.mark.parametrize("units, typed, landed", [
    ("in", "50.8mm,25.4mm", (50.8, 25.4)),
    ("ft", "2,1", (50.8, 25.4)),
    ("m", "50mm,20mm", (50.0, 20.0)),
    ("m", "50,20", (50.0, 20.0)),
    ("mm", "1in,1in", (25.4, 25.4)),
])
def test_a_unit_typed_on_paper_means_that_unit(window, units, typed, landed):
    w, lay = window(units)
    _run(w, "dim", typed, (300.0, 100.0, 0.0), (250.0, 150.0, 0.0))
    dim = lay.dims[-1]
    assert (dim.x1, dim.y1) == pytest.approx(landed)


def test_a_length_typed_on_an_inch_sheet_is_in_inches(window):
    """A circle on paper, its radius typed: an inch."""
    w, lay = window("in")
    said = []
    w.ctx.add_echo_listener(said.append)
    _run(w, "circle", "2,2", "1")
    (x0, y0, _), (x1, y1, _) = g.bbox(lay.objects[-1].shape)
    assert (x1 - x0) / 2 == pytest.approx(25.4, abs=1e-5)
    assert ((x0 + x1) / 2, (y0 + y1) / 2) == pytest.approx((50.8, 50.8), abs=1e-5)
    assert any("(r=1)" in s for s in said)


# -- what is read off paper --------------------------------------------------------

def test_the_length_beside_the_cursor_reads_inches_on_an_inch_sheet(window):
    w, _lay = window("in")
    assert w.viewport._readout_length(50.8) == '2"'


@pytest.mark.parametrize("units", ["mm", "m"])
def test_the_length_beside_the_cursor_reads_millimetres_on_a_metric_sheet(
        window, units):
    w, _lay = window(units)
    assert w.viewport._readout_length(50.8) == "50.8 mm"


def _pick(w, kind, thing):
    lv = w.viewport.layout_view
    lv.selected = [(kind, thing)]
    w.viewport.layoutSelectionChanged.emit()


def test_properties_reads_paper_in_inches(window):
    w, lay = window("in")
    curve = lay.add(g.make_polyline([(20.0, 20.0, 0.0), (70.8, 20.0, 0.0)]),
                    name="Rule")
    _pick(w, "object", curve)
    assert w.properties.measure_label.text() == 'Length: 2"'
    square = lay.add(g.planar_face(g.make_rectangle((100.0, 20.0, 0.0),
                                                   (150.8, 70.8, 0.0))),
                     name="Patch")
    _pick(w, "object", square)
    assert w.properties.measure_label.text() == "Area: 4.00 in²"


def test_properties_gives_a_frame_in_inches(window):
    w, lay = window("in")
    det = _detail(w, lay, "1:4")
    _pick(w, "detail", det)
    assert w.properties.measure_label.text() == 'Frame: 7.087 × 5.118 in'


def test_a_custom_sheet_is_asked_for_in_inches(window):
    w, _lay = window("in")
    said = []
    w.ctx.add_echo_listener(said.append)
    _run(w, "layout", "New", "Shop", "Custom", "24", "18")
    made = w.scene.layouts[-1]
    assert (made.paper_w, made.paper_h) == pytest.approx((609.6, 457.2))
    assert any("24 × 18 in" in s for s in said)


# -- the gumball on paper --------------------------------------------------------

def _gumball_on(w, lay, det):
    w.viewport.resize(640, 480)
    lv = w.viewport.layout_view
    lv.fit()
    lv._fitted_for = lay.id
    lv.selected = [("detail", det)]
    gb = lv.gumball
    ax, ay = gb.anchor()
    reach = (SHAFT0 + CONE1) / 2 * gb._size_mm()
    return lv, gb, lv.paper_to_screen(ax + reach, ay)


def _paper_detail(lay):
    az, el = STANDARD_VIEWS["front"]
    det = DetailView(x=160.0, y=100.0, w=120.0, h=90.0, azimuth=az,
                     elevation=el, target=[0.0, 0.0, 0.0], scale_denom=2.0)
    lay.details.append(det)
    return det


def test_the_paper_gumball_takes_a_typed_inch(window):
    w, lay = window("in")
    det = _paper_detail(lay)
    _lv, gb, (sx, sy) = _gumball_on(w, lay, det)
    x0 = det.x
    assert gb.begin_drag(("move", 0), sx, sy)
    gb.arm()
    gb.type_char("1")
    assert gb.commit_typed()
    assert det.x == pytest.approx(x0 + 25.4)


def test_the_paper_gumball_reads_inches(window):
    w, lay = window("in")
    det = _paper_detail(lay)
    lv, gb, (sx, sy) = _gumball_on(w, lay, det)
    press = lv.screen_to_paper(sx, sy)
    assert gb.begin_drag(("move", 0), sx, sy)
    gb.drag_to(*lv.paper_to_screen(press[0] + 25.4, press[1]))
    text, _at = gb.readout()
    assert text == '1.000"'
