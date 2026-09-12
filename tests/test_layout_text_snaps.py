"""Object snaps offered by formatted text that lives on a layout."""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest

from serpentine3d.app import MainWindow
from serpentine3d.core import geometry as g, occ
from serpentine3d.core.layout import (
    DetailView,
    Layout,
    TextNote,
    annotation_bounds,
    detail_unproject,
)
from serpentine3d.ui import theme
from serpentine3d.ui import viewport as viewport_module


@pytest.fixture
def lettering_font():
    families = set(QFontDatabase.families())
    for family in ("DejaVu Sans", "Liberation Sans", "Arial", "Noto Sans"):
        if family in families:
            styles = QFontDatabase.styles(family)
            regular = next(
                (style for style in styles if style in ("Book", "Regular")),
                styles[0],
            )
            return family, regular
    pytest.skip("No installed lettering font")


@pytest.fixture
def sheet(lettering_font):
    """A hidden viewport fitted to one sheet carrying formatted lettering."""
    family, style = lettering_font
    window = MainWindow()
    window.resize(1200, 800)
    window.viewport.resize(900, 650)
    layout = Layout(name="Text snaps")
    note = TextNote(
        x=145.0,
        y=110.0,
        text="SNAP\nGRID",
        height=12.0,
        font_family=family,
        font_style=style,
        alignment="center",
    )
    layout.notes.append(note)
    window.scene.layouts.append(layout)
    window.viewport.space = layout.id
    view = window.viewport.layout_view
    view.fit()
    view._fitted_for = layout.id
    window.viewport.grid_snap = False
    yield window, view, layout, note
    window.processor.cancel()
    window.mark_saved()
    window.close()


def _semantic_points(note):
    x0, y0, x1, y1 = annotation_bounds("note", note)
    corners = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
    mids = (
        ((x0 + x1) / 2.0, y0),
        (x1, (y0 + y1) / 2.0),
        ((x0 + x1) / 2.0, y1),
        (x0, (y0 + y1) / 2.0),
    )
    return {
        "point": ((note.x, note.y),),
        "end": corners,
        "mid": mids,
        "center": (((x0 + x1) / 2.0, (y0 + y1) / 2.0),),
    }


def _only_snap(viewport, kind):
    viewport.snaps.enabled = True
    for candidate in viewport.snaps.types:
        viewport.snaps.types[candidate] = candidate == kind


def _near(view, point, dx=3.0, dy=2.0):
    sx, sy = view.paper_to_screen(*point)
    return sx + dx, sy + dy


@pytest.mark.parametrize("kind", ["point", "end", "mid", "center"])
def test_a_formatted_note_offers_its_anchor_and_rendered_bounds(sheet, kind):
    window, view, _layout, note = sheet
    window.processor.run("line")
    _only_snap(window.viewport, kind)

    for expected in _semantic_points(note)[kind]:
        got = window.viewport.world_point_at(*_near(view, expected))
        assert got == pytest.approx((*expected, 0.0), abs=1e-9)
        assert window.viewport._active_snap is not None
        snapped, snapped_kind = window.viewport._active_snap
        assert snapped == pytest.approx((*expected, 0.0), abs=1e-9)
        assert snapped_kind == kind


@pytest.mark.parametrize(
    ("switch", "kind"),
    [("master", "end"), ("type", "point")],
)
def test_disabled_paper_text_snaps_do_not_activate(sheet, switch, kind):
    window, view, _layout, note = sheet
    window.processor.run("line")
    _only_snap(window.viewport, kind)
    expected = _semantic_points(note)[kind][0]
    pos = _near(view, expected)

    assert window.viewport.world_point_at(*pos) == pytest.approx(
        (*expected, 0.0), abs=1e-9
    )
    assert window.viewport._active_snap is not None

    if switch == "master":
        window.viewport.snaps.enabled = False
    else:
        window.viewport.snaps.types[kind] = False
    unsnapped = window.viewport.world_point_at(*pos)
    assert window.viewport._active_snap is None
    assert np.linalg.norm(np.asarray(unsnapped[:2]) - expected) > 0.1


def test_line_clicks_store_the_exact_note_corners_on_paper(sheet):
    window, view, layout, note = sheet
    window.processor.run("line")
    _only_snap(window.viewport, "end")
    corners = _semantic_points(note)["end"]
    expected = (corners[0], corners[2])

    for corner in expected:
        sx, sy = _near(view, corner)
        QTest.mouseClick(
            window.viewport,
            Qt.MouseButton.LeftButton,
            pos=QPoint(round(sx), round(sy)),
        )

    assert len(layout.objects) == 1
    assert window.scene.all() == []
    edge = occ.edge_adaptor(g.edges_of(layout.objects[0].shape)[0])
    start = edge.Value(edge.FirstParameter())
    end = edge.Value(edge.LastParameter())
    assert (start.X(), start.Y(), start.Z()) == pytest.approx(
        (*expected[0], 0.0), abs=1e-9
    )
    assert (end.X(), end.Y(), end.Z()) == pytest.approx(
        (*expected[1], 0.0), abs=1e-9
    )


def test_entered_detail_keeps_model_snapping_separate_from_note_snapping(sheet):
    window, view, layout, note = sheet
    paper_corner = _semantic_points(note)["end"][0]
    detail = DetailView(
        x=70.0,
        y=45.0,
        w=200.0,
        h=150.0,
        scale_denom=2.0,
        target=[400.0, 250.0, 0.0],
    )
    assert detail.contains(*paper_corner)
    layout.details.append(detail)
    model_end = tuple(detail_unproject(detail, *paper_corner))
    window.scene.add(g.make_line(model_end, np.asarray(model_end) + (30, 0, 0)))
    view.entered_detail = detail.id

    window.processor.run("line")
    _only_snap(window.viewport, "end")
    got = window.viewport.world_point_at(*_near(view, paper_corner))

    assert got == pytest.approx(model_end, abs=1e-9)
    assert got != pytest.approx((*paper_corner, 0.0), abs=1e-3)
    assert window.viewport._active_snap is not None
    assert window.viewport._active_snap[1] == "end"


def test_note_selection_rectangle_uses_the_same_bounds_as_its_snaps(sheet):
    window, view, _layout, note = sheet
    view.selected = [("note", note)]

    class Painter:
        def __init__(self):
            self.rectangles = []

        def setPen(self, _pen):
            pass

        def setBrush(self, _brush):
            pass

        def drawRect(self, x, y, width, height):
            self.rectangles.append((x, y, width, height))

    painter = Painter()
    view._paint_selection(painter)
    x0, y0, x1, y1 = annotation_bounds("note", note, window.scene)
    sx0, sy0 = view.paper_to_screen(x0, y0)
    sx1, sy1 = view.paper_to_screen(x1, y1)
    expected = (int(min(sx0, sx1)), int(min(sy0, sy1)),
                int(abs(sx1 - sx0)), int(abs(sy1 - sy0)))
    assert painter.rectangles == [expected]


def test_layout_snap_marker_uses_visible_selection_ink_on_pale_paper():
    color_for = getattr(viewport_module, "_snap_marker_color", None)
    assert callable(color_for)
    assert color_for("layout") == (*theme.SELECTION_COLOR, 1.0)
    assert color_for("model") == (1.0, 1.0, 1.0, 0.95)
