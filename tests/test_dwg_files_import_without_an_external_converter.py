"""A genuine DWG works through Import and model/paper file-manager drops."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.GeomAbs import GeomAbs_Circle, GeomAbs_Line
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from serpentine3d import fileio
from serpentine3d.core import geometry as g
from serpentine3d.core.layout import DetailView, Layout
from serpentine3d.core.scene import Scene


FIXTURE = Path(__file__).parent / "fixtures" / "dwg" / "line-and-circle.dwg"
DROP_POS = QPoint(320, 240)


@pytest.fixture
def dwg_file(tmp_path):
    data = FIXTURE.read_bytes()
    assert data.startswith(b"AC1015"), "The fixture must be a real R2000 DWG"
    path = tmp_path / "Drawing with spaces.dwg"
    path.write_bytes(data)
    return path


@pytest.fixture
def window(monkeypatch):
    from serpentine3d.app import MainWindow

    win = MainWindow()
    win.resize(1200, 800)
    win.viewport.resize(640, 480)
    # Do not allow a failed importer to block the test behind a modal dialog.
    win.import_warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, text:
                        win.import_warnings.append((title, text)))
    try:
        yield win
    finally:
        if win.processor.busy:
            win.processor.cancel()
        win.mark_saved()
        win.close()


def _drop(target, path):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    enter = QDragEnterEvent(
        DROP_POS, Qt.DropAction.CopyAction, mime,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(target, enter)
    assert enter.isAccepted(), "DWG must be accepted like DXF over the viewport"
    drop = QDropEvent(
        QPointF(DROP_POS), Qt.DropAction.CopyAction, mime,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(target, drop)
    assert drop.isAccepted() and drop.dropAction() == Qt.DropAction.CopyAction
    QApplication.processEvents()


def _assert_geometry(objects, offset=(0.0, 0.0, 0.0)):
    assert len(objects) == 2
    # Find the entities by their measurements, independent of reader order.
    line, circle = sorted(objects, key=lambda obj: g.curve_length(obj.shape))
    for obj, expected_type in ((line, GeomAbs_Line), (circle, GeomAbs_Circle)):
        edges = g.edges_of(obj.shape)
        assert len(edges) == 1
        assert BRepAdaptor_Curve(edges[0]).GetType() == expected_type
    assert g.curve_length(line.shape) == pytest.approx(20.0)
    assert g.curve_length(circle.shape) == pytest.approx(10.0 * math.pi)
    delta = np.asarray(offset)
    for obj, lo, hi in (
        (line, (10, 20, 0), (30, 20, 0)),
        (circle, (40, 30, 0), (50, 40, 0)),
    ):
        actual_lo, actual_hi = g.bbox(obj.shape)
        assert actual_lo == pytest.approx(np.asarray(lo) + delta, abs=1e-6)
        assert actual_hi == pytest.approx(np.asarray(hi) + delta, abs=1e-6)


def _paper(window):
    layout = Layout(name="DWG sheet")
    window.scene.layouts.append(layout)
    window.viewport.space = layout.id
    lv = window.viewport.layout_view
    lv.entered_detail = None
    lv.fit()
    lv._fitted_for = layout.id
    return layout


def test_dwg_is_offered_in_the_normal_import_chooser():
    assert ".dwg" in fileio.IMPORT_EXTS
    assert "*.dwg" in fileio.import_filter()
    assert "*.dwg" in fileio.import_filter(pictures=True)


def test_a_genuine_dwg_imports_without_a_converter_installed_on_path(
        dwg_file, tmp_path, monkeypatch):
    # A user's install must include the reader; a developer machine's ODA or
    # LibreDWG executable must not be what makes this test succeed.
    monkeypatch.setenv("PATH", str(tmp_path / "no-system-converters"))
    source = dwg_file.read_bytes()
    scene = Scene()

    assert fileio.import_file(scene, str(dwg_file)) == 2

    _assert_geometry(scene.all())
    assert dwg_file.read_bytes() == source


@pytest.mark.parametrize("entry", ["menu", "drop", "uppercase-drop"])
def test_dwg_import_joins_the_model_and_undo_preserves_existing_work(
        window, dwg_file, monkeypatch, entry):
    if entry == "uppercase-drop":
        dwg_file = dwg_file.rename(dwg_file.with_suffix(".DWG"))
    source = dwg_file.read_bytes()
    existing = window.scene.add(g.make_box((80, 0, 0), 2, 3, 4),
                                name="Existing work")
    window.ctx.current_path = "Working document.serp"
    window.mark_saved()

    if entry == "menu":
        monkeypatch.setattr(window, "_pick_file", lambda **kwargs: str(dwg_file))
        window._file_import()
    else:
        _drop(window.viewport, dwg_file)

    assert not window.import_warnings, window.import_warnings
    assert len(window.scene.all()) == 3
    _assert_geometry([obj for obj in window.scene.all() if obj.id != existing.id])
    assert g.volume(window.scene.get(existing.id).shape) == pytest.approx(24)
    assert window.ctx.current_path == "Working document.serp"
    assert dwg_file.read_bytes() == source
    assert window.dirty
    assert window.history.can_undo
    window.history.undo()
    assert [obj.id for obj in window.scene.all()] == [existing.id]
    assert not window.history.can_undo


@pytest.mark.parametrize("entered_detail", [False, True], ids=["paper", "detail"])
def test_a_dwg_drop_uses_the_current_model_or_paper_space(
        window, dwg_file, entered_detail):
    existing = window.scene.add(g.make_box((80, 0, 0), 2, 3, 4))
    layout = _paper(window)
    if entered_detail:
        detail = DetailView(x=20, y=20, w=200, h=140)
        layout.details.append(detail)
        window.viewport.layout_view.entered_detail = detail.id
    lv = window.viewport.layout_view
    drop_point = np.array((*lv.screen_to_paper(DROP_POS.x(), DROP_POS.y()), 0.0))
    source = dwg_file.read_bytes()

    _drop(window.viewport, dwg_file)

    assert not window.import_warnings, window.import_warnings
    if entered_detail:
        assert layout.objects == []
        _assert_geometry([obj for obj in window.scene.all() if obj.id != existing.id])
    else:
        assert [obj.id for obj in window.scene.all()] == [existing.id]
        # The file bounds have centre (30,30,0); import should preserve their
        # size and relative positions while placing that centre at the cursor.
        _assert_geometry(layout.objects, drop_point - (30, 30, 0))
    assert dwg_file.read_bytes() == source
    assert window.history.can_undo
    window.history.undo()
    assert window.scene.layouts[0].objects == []
    assert [obj.id for obj in window.scene.all()] == [existing.id]
    assert not window.history.can_undo


@pytest.mark.parametrize("on_paper", [False, True], ids=["model", "paper"])
def test_a_corrupt_dwg_drop_reports_an_error_without_changing_the_drawing(
        window, tmp_path, on_paper):
    existing = window.scene.add(g.make_box((80, 0, 0), 2, 3, 4))
    layout = _paper(window) if on_paper else None
    paper_existing = layout.add(g.make_line((1, 2, 0), (3, 4, 0))) if layout else None
    path = tmp_path / "Damaged drawing.dwg"
    source = b"AC1015" + b"\x00" * 20
    path.write_bytes(source)
    window.mark_saved()

    _drop(window.viewport, path)

    assert window.import_warnings, "Unreadable DWG must report a useful import error"
    assert "Import" in window.import_warnings[0][0]
    assert window.import_warnings[0][1].strip()
    assert [obj.id for obj in window.scene.all()] == [existing.id]
    assert g.volume(window.scene.get(existing.id).shape) == pytest.approx(24)
    if layout:
        assert [obj.id for obj in layout.objects] == [paper_existing.id]
    assert not window.history.can_undo
    assert path.read_bytes() == source
