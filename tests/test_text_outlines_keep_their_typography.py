"""Issue #18: model lettering keeps font metrics, smooth curves and counters."""

import numpy as np
import pytest

from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.GeomAbs import GeomAbs_Line
from PySide6.QtGui import QFontDatabase, QFontMetricsF, QPainterPath

from serpentine3d.core import geometry as g
from serpentine3d.core.text import text_curves


@pytest.fixture
def lettering_font():
    """A real installed family whose B/O/R have familiar separate counters."""
    available = set(QFontDatabase.families())
    for family, regular, styled in (
        ("DejaVu Sans", "Book", "Bold Oblique"),
        ("Liberation Sans", "Regular", "Bold Italic"),
        ("Arial", "Regular", "Bold Italic"),
        ("Noto Sans", "Regular", "Bold Italic"),
    ):
        if family in available and {regular, styled} <= set(QFontDatabase.styles(family)):
            return family, regular, styled
    pytest.skip("No installed test font with regular and bold italic/oblique styles")


def _bounds(curves):
    boxes = [g.bbox(curve) for curve in curves]
    return np.min([box[0] for box in boxes], axis=0), np.max(
        [box[1] for box in boxes], axis=0)


def _font_metrics(family, style):
    # A high-resolution reference avoids depending on the outline builder's
    # internal font resolution while retaining the font's own metrics. Bounds
    # allow small metric rounding differences at a lower rendering resolution.
    font = QFontDatabase.font(family, style, 12)
    font.setPixelSize(2048)
    return font, QFontMetricsF(font)


def _expected_bounds(text, height, family, style, alignment="left"):
    font, metrics = _font_metrics(family, style)
    scale = height / metrics.capHeight()
    path = QPainterPath()
    factor = {"left": 0, "center": 0.5, "right": 1}[alignment]
    for row, line in enumerate(text.split("\n")):
        path.addText(-factor * metrics.horizontalAdvance(line),
                     row * metrics.lineSpacing(), font, line)
    box = path.boundingRect()
    return (np.array([box.left() * scale, -box.bottom() * scale, 0.0]),
            np.array([box.right() * scale, -box.top() * scale, 0.0]))


def test_requested_height_uses_the_font_cap_height(lettering_font):
    family, regular, _ = lettering_font
    bounds = _bounds(text_curves("H", 10, family))
    expected = _expected_bounds("H", 10, family, regular)
    assert bounds[1][1] - bounds[0][1] == pytest.approx(10, abs=0.04), (
        "A ten-unit capital letter must not use a guessed font-height factor")
    np.testing.assert_allclose(bounds, expected, atol=0.12)


def test_an_available_font_style_changes_the_actual_letter_outlines(lettering_font):
    family, regular, styled = lettering_font
    plain = _bounds(text_curves("HMWI", 10, family, font_style=regular))
    formatted = _bounds(text_curves("HMWI", 10, family, font_style=styled))
    np.testing.assert_allclose(
        formatted, _expected_bounds("HMWI", 10, family, styled), atol=0.12)
    assert not np.allclose(plain, formatted, atol=0.1), (
        "Choosing an available bold italic style must affect the geometry")


def test_newlines_and_blank_lines_preserve_font_baseline_spacing(lettering_font):
    family, regular, _ = lettering_font
    curves = text_curves("HH\n\nH", 10, family)
    assert len(curves) == 3
    lower_edges = sorted(g.bbox(curve)[0][1] for curve in curves)
    assert lower_edges[1] - lower_edges[0] > 20, (
        "Newlines must place glyphs on separate baselines and keep blank lines")
    np.testing.assert_allclose(
        _bounds(curves), _expected_bounds("HH\n\nH", 10, family, regular),
        atol=0.12)


@pytest.mark.parametrize("alignment", ["left", "center", "right"])
def test_each_line_aligns_to_the_placement_origin(lettering_font, alignment):
    family, regular, _ = lettering_font
    curves = text_curves("HHHH\nH", 10, family, alignment=alignment)
    assert len(curves) == 5
    upper = [curve for curve in curves if g.bbox(curve)[1][1] > 0]
    lower = [curve for curve in curves if g.bbox(curve)[1][1] < 0]
    assert len(upper) == 4 and len(lower) == 1
    np.testing.assert_allclose(
        _bounds(upper), _expected_bounds("HHHH", 10, family, regular, alignment),
        atol=0.12)
    expected_lower = _expected_bounds("H", 10, family, regular, alignment)
    _, metrics = _font_metrics(family, regular)
    baseline_drop = metrics.lineSpacing() * 10 / metrics.capHeight()
    expected_lower = np.array(expected_lower) - [0, baseline_drop, 0]
    np.testing.assert_allclose(_bounds(lower), expected_lower, atol=0.12)


def test_round_letter_outlines_retain_curved_edges(lettering_font):
    family, _, _ = lettering_font
    curves = text_curves("O", 10, family)
    assert len(curves) == 2
    for contour in curves:
        assert any(BRepAdaptor_Curve(edge).GetType() != GeomAbs_Line
                   for edge in g.edges_of(contour)), (
            "Round glyph contours must retain smooth curves instead of polygon facets")
        assert g.is_closed_curve(contour)
        assert g.is_valid(contour)


@pytest.mark.parametrize(("letter", "contour_count"), [("B", 3), ("O", 2), ("R", 2)])
def test_letter_counters_stay_separate_and_extrude_as_holes(
        lettering_font, letter, contour_count):
    family, _, _ = lettering_font
    contours = text_curves(letter, 10, family)
    assert len(contours) == contour_count
    assert all(g.is_closed_curve(contour) and g.is_valid(contour)
               for contour in contours)
    areas = sorted(g.surface_area(g.planar_face(contour)) for contour in contours)
    material_area = areas[-1] - sum(areas[:-1])
    assert 0 < material_area < areas[-1]

    solid, = g.extrude_profiles(contours, (0, 0, 1), 2, cap=True)
    assert g.shape_kind(solid) == "solid"
    assert g.is_valid(solid)
    assert g.volume(solid) == pytest.approx(material_area * 2, rel=1e-6), (
        "Extruded letters must subtract the counters instead of filling their holes")


def test_several_letters_extrude_as_separate_valid_solids(lettering_font):
    family, _, _ = lettering_font
    contours = text_curves("BOR", 10, family)
    assert len(contours) == 7
    solids = g.extrude_profiles(contours, (0, 0, 1), 2, cap=True)
    assert len(solids) == 3
    assert all(g.shape_kind(solid) == "solid" and g.is_valid(solid)
               and g.volume(solid) > 0 for solid in solids)
