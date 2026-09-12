"""Planar vector files dropped on a sheet become paper geometry."""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication

from serpentine3d import fileio
from serpentine3d.core import geometry as g
from serpentine3d.core.layout import DetailView, Layout
from serpentine3d.core.scene import Scene


DROP_POS = QPoint(320, 240)


@pytest.fixture
def paper_window():
    from serpentine3d.app import MainWindow

    window = MainWindow()
    window.resize(1200, 800)
    window.viewport.resize(640, 480)
    layout = Layout(name="Vector sheet")
    window.scene.layouts.append(layout)
    window.viewport.space = layout.id
    window.viewport.layout_view.entered_detail = None
    window.viewport.layout_view.fit()
    window.viewport.layout_view._fitted_for = layout.id
    try:
        yield window, layout
    finally:
        if window.processor.busy:
            window.processor.cancel()
        window.mark_saved()
        window.close()


@pytest.fixture(params=["dxf", "svg"])
def planar_file(request, tmp_path):
    path = tmp_path / f"Two rectangles.{request.param}"
    if request.param == "dxf":
        import ezdxf

        doc = ezdxf.new()
        msp = doc.modelspace()
        msp.add_lwpolyline(
            [(10, 20), (30, 20), (30, 30), (10, 30)], close=True)
        msp.add_lwpolyline(
            [(45, 35), (50, 35), (50, 40), (45, 40)], close=True)
        doc.saveas(path)
    else:
        path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg">'
            '<rect x="10" y="20" width="20" height="10"/>'
            '<rect x="45" y="35" width="5" height="5"/>'
            '</svg>',
            encoding="utf-8",
        )
    return path


def _drop(target, path, pos=DROP_POS):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    enter = QDragEnterEvent(
        pos, Qt.DropAction.CopyAction, mime,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(target, enter)
    assert enter.isAccepted(), "A supported planar file must be accepted over paper"
    drop = QDropEvent(
        QPointF(pos), Qt.DropAction.CopyAction, mime,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(target, drop)
    assert drop.isAccepted() and drop.dropAction() == Qt.DropAction.CopyAction
    QApplication.processEvents()


def _bounds(objects):
    boxes = [g.bbox(obj.shape) for obj in objects]
    lo = np.min([box[0] for box in boxes], axis=0)
    hi = np.max([box[1] for box in boxes], axis=0)
    return boxes, lo, hi


def _reference_objects(path):
    scene = Scene()
    assert fileio.import_file(scene, str(path)) == 2
    return scene.all()


def test_a_planar_file_dropped_on_bare_paper_lands_at_the_cursor_as_one_undo(
        paper_window, planar_file):
    window, layout = paper_window
    reference = _reference_objects(planar_file)
    reference_boxes, reference_lo, reference_hi = _bounds(reference)
    lv = window.viewport.layout_view
    drop_point = np.array((*lv.screen_to_paper(DROP_POS.x(), DROP_POS.y()), 0.0))
    before_undo = len(window.history._undo)

    _drop(window.viewport, planar_file)

    assert window.scene.all() == [], "Bare-paper import must not create model geometry"
    assert len(layout.objects) == len(reference) == 2
    paper_boxes, paper_lo, paper_hi = _bounds(layout.objects)
    assert (paper_hi - paper_lo) == pytest.approx(reference_hi - reference_lo)
    assert (paper_lo + paper_hi) / 2 == pytest.approx(drop_point)

    # Paper import may translate the group to the cursor, but it must retain
    # the file's scale, object order, and geometry relative to its neighbours.
    delta = drop_point - (reference_lo + reference_hi) / 2
    for paper_box, reference_box in zip(paper_boxes, reference_boxes):
        assert paper_box[0] == pytest.approx(np.asarray(reference_box[0]) + delta)
        assert paper_box[1] == pytest.approx(np.asarray(reference_box[1]) + delta)

    # A visible imported edge participates in ordinary paper selection.
    first = layout.objects[0]
    edge = first.polylines[0]
    midpoint = (np.asarray(edge[0]) + np.asarray(edge[1])) / 2
    sx, sy = lv.paper_to_screen(float(midpoint[0]), float(midpoint[1]))
    lv.press(sx, sy)
    assert any(item is first for _kind, item in lv.selected)

    assert len(window.history._undo) == before_undo + 1
    window.history.undo()
    assert window.scene.layouts[0].objects == []
    assert window.scene.all() == []
    assert not window.history.can_undo, "One dropped file needs one undo step"


def test_the_same_drop_inside_an_entered_detail_remains_a_model_import(
        paper_window, planar_file):
    window, layout = paper_window
    detail = DetailView(x=20, y=20, w=200, h=140)
    layout.details.append(detail)
    window.viewport.layout_view.entered_detail = detail.id
    reference = _reference_objects(planar_file)
    reference_boxes, _lo, _hi = _bounds(reference)

    _drop(window.viewport, planar_file)

    assert layout.objects == []
    imported = window.scene.all()
    assert len(imported) == len(reference) == 2
    imported_boxes, _lo, _hi = _bounds(imported)
    for imported_box, reference_box in zip(imported_boxes, reference_boxes):
        assert imported_box[0] == pytest.approx(reference_box[0])
        assert imported_box[1] == pytest.approx(reference_box[1])
