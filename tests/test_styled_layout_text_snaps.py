"""Layout text snaps follow the height resolved from a named style."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest

from serpentine3d.app import MainWindow
from serpentine3d.core import geometry as g, occ
from serpentine3d.core.layout import Layout, TextNote
from serpentine3d.core.text import text_path


@pytest.fixture
def styled_sheet():
    families = set(QFontDatabase.families())
    family = next(
        (name for name in
         ("DejaVu Sans", "Liberation Sans", "Arial", "Noto Sans")
         if name in families),
        None,
    )
    if family is None:
        pytest.skip("No installed lettering font")
    styles = QFontDatabase.styles(family)
    font_style = next(
        (name for name in styles if name in ("Book", "Regular")), styles[0]
    )

    window = MainWindow()
    window.resize(1200, 800)
    window.viewport.resize(900, 650)
    window.scene.annot_styles["Sheet Title"] = {
        "text_height": 18.0,
        "arrow_size": 2.2,
        "dim_offset": 8.0,
    }
    layout = Layout(name="Styled text snaps")
    note = TextNote(
        x=170.0,
        y=120.0,
        text="STYLE\nSNAP",
        height=2.0,
        style="Sheet Title",
        font_family=family,
        font_style=font_style,
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


def _rendered_semantic_points(note, resolved_height):
    rect = text_path(
        note.text,
        resolved_height,
        note.font_family,
        font_style=note.font_style,
        alignment=note.alignment,
    ).boundingRect()
    x0, y0, x1, y1 = (
        note.x + rect.left(),
        note.y - rect.bottom(),
        note.x + rect.right(),
        note.y - rect.top(),
    )
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    return {
        "end": ((x0, y0), (x1, y0), (x1, y1), (x0, y1)),
        "mid": ((cx, y0), (x1, cy), (cx, y1), (x0, cy)),
        "center": ((cx, cy),),
    }


def _only_snap(viewport, kind):
    viewport.snaps.enabled = True
    for candidate in viewport.snaps.types:
        viewport.snaps.types[candidate] = candidate == kind


def _near(view, point):
    sx, sy = view.paper_to_screen(*point)
    return sx + 3.0, sy + 2.0


@pytest.mark.parametrize(
    ("kind", "candidate_index"),
    [("end", 2), ("mid", 1), ("center", 0)],
)
def test_named_style_snaps_land_on_the_rendered_text_bounds(
        styled_sheet, kind, candidate_index):
    window, view, _layout, note = styled_sheet
    expected = _rendered_semantic_points(note, 18.0)[kind][candidate_index]
    window.processor.run("line")
    _only_snap(window.viewport, kind)

    got = window.viewport.world_point_at(*_near(view, expected))

    assert got == pytest.approx((*expected, 0.0), abs=1e-9)
    assert window.viewport._active_snap is not None
    snapped, snapped_kind = window.viewport._active_snap
    assert snapped == pytest.approx((*expected, 0.0), abs=1e-9)
    assert snapped_kind == kind


def test_line_clicks_store_the_rendered_corners_of_named_style_text(
        styled_sheet):
    window, view, layout, note = styled_sheet
    corners = _rendered_semantic_points(note, 18.0)["end"]
    expected = (corners[0], corners[2])
    window.processor.run("line")
    _only_snap(window.viewport, "end")

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
