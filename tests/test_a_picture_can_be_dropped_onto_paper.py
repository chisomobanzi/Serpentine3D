"""A dropped picture belongs to bare paper when a layout is active."""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from serpentine3d.commands.base import PointReq
from serpentine3d.core.layout import Layout, sheet_pools
from serpentine3d.core.picture import PictureShape


@pytest.fixture
def paper_window():
    from serpentine3d.app import MainWindow

    window = MainWindow()
    window.resize(1200, 800)
    layout = Layout(name="Picture sheet")
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


def _drop(target, path):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    enter = QDragEnterEvent(
        QPoint(20, 20), Qt.DropAction.CopyAction, mime,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(target, enter)
    assert enter.isAccepted(), "A supported picture must be accepted over paper"
    drop = QDropEvent(
        QPointF(20, 20), Qt.DropAction.CopyAction, mime,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(target, drop)
    assert drop.isAccepted() and drop.dropAction() == Qt.DropAction.CopyAction
    QApplication.processEvents()


def _paper_pictures(layout):
    found = []
    for kind, items in sheet_pools(layout).items():
        for item in items:
            shape = getattr(item, "shape", item)
            if isinstance(shape, PictureShape):
                found.append((kind, item, shape))
    return found


@pytest.fixture
def captured_layout_pictures(monkeypatch):
    """Capture textured triangles submitted by ``LayoutView.paint``."""
    from serpentine3d.ui import viewport as viewport_module

    draws = []
    pending = {}

    def texture(path, image_data=None):
        image = QImage(path) if image_data is None else QImage.fromData(image_data)
        assert not image.isNull()
        pending["image"] = image
        return 1, image.width() / image.height()

    def uniform(name, value):
        pending[name] = value

    def upload(_target, _size, data, _usage):
        if "image" in pending:
            pending["quad"] = np.array(data, copy=True)

    def draw(mode, _start, count):
        if "image" in pending:
            assert mode == viewport_module.GL.GL_TRIANGLES and count == 6
            draws.append(dict(pending))

    for name in (
            "glUniformMatrix4fv", "glUniform1i", "glActiveTexture",
            "glBindTexture", "glBindVertexArray", "glBindBuffer",
            "glDepthMask", "glDisable", "glEnable"):
        monkeypatch.setattr(viewport_module.GL, name, lambda *args: None)
    monkeypatch.setattr(viewport_module.GL, "glUniform1f", uniform)
    monkeypatch.setattr(viewport_module.GL, "glBufferData", upload)
    monkeypatch.setattr(viewport_module.GL, "glDrawArrays", draw)

    def capture(window):
        draws.clear()
        pending.clear()
        viewport = window.viewport
        view = viewport.layout_view
        monkeypatch.setattr(viewport, "_texture_for", texture)
        monkeypatch.setattr(viewport, "_use", lambda *args: None)
        monkeypatch.setattr(viewport, "_uloc", lambda _program, name: name)
        for name in ("_tex_prog", "_tex_vao", "_tex_vbo"):
            monkeypatch.setattr(viewport, name, 1, raising=False)
        monkeypatch.setattr(viewport, "_frame_anchor", None)
        # Keep this focused on the image layer; the paper, margin and ordinary
        # curve paths have independent rendering tests.
        monkeypatch.setattr(view, "_fill_rect", lambda *args: None)
        monkeypatch.setattr(view, "_stroke_rect", lambda *args, **kwargs: None)
        monkeypatch.setattr(view, "_paint_objects", lambda *args: None)
        view.paint()
        return list(draws)

    return capture


def test_dropped_picture_previews_and_finishes_as_one_selectable_paper_item(
        paper_window, captured_layout_pictures, tmp_path):
    window, layout = paper_window
    source = tmp_path / "Reference image.png"
    image = QImage(12, 8, QImage.Format.Format_ARGB32)
    image.fill(QColor("tomato"))
    assert image.save(str(source))
    encoded = source.read_bytes()

    _drop(window.viewport, source)
    assert isinstance(window.processor.request, PointReq)
    window.processor.provide((40.0, 60.0, 0.0))
    assert isinstance(window.processor.request, PointReq)

    QTest.qWait(40)  # command ghosts are intentionally capped at 30 Hz
    window.viewport.mouseWorldMoved.emit((100.0, 62.0, 0.0))
    preview, = captured_layout_pictures(window)
    assert 0.0 < preview["uAlpha"] < 1.0
    assert preview["image"] == image
    assert preview["quad"][[0, 1, 2, 5], :3] == pytest.approx(np.array([
        [40.0, 60.0, 0.0], [100.0, 60.0, 0.0],
        [100.0, 100.0, 0.0], [40.0, 100.0, 0.0],
    ])), "The live paper preview must retain the source image's 12:8 aspect"
    assert not _paper_pictures(layout), "The preview must not edit the sheet"

    window.processor.provide((100.0, 62.0, 0.0))
    QApplication.processEvents()
    assert not window.processor.busy
    assert not window.scene.image_planes
    assert window.scene.all() == [], "A bare-paper drop must not create model geometry"
    [(kind, item, picture)] = _paper_pictures(layout)
    assert item.points == [], "A paper picture has no CAD point marks to paint"
    assert picture.plane["image_data"] == encoded
    assert picture.plane["origin"] == pytest.approx([40.0, 60.0, 0.0])
    assert picture.plane["u"] == pytest.approx([60.0, 0.0, 0.0])
    assert picture.plane["v"] == pytest.approx([0.0, 40.0, 0.0])

    # The visible image itself is the pick target, not only its thin border.
    sx, sy = window.viewport.layout_view.paper_to_screen(70.0, 80.0)
    window.viewport.layout_view.press(sx, sy)
    assert window.viewport.layout_view.selected == [(kind, item)]

    assert window.history.can_undo
    window.history.undo()
    restored = window.scene.layouts[0]
    assert not _paper_pictures(restored)
    assert not window.scene.image_planes and window.scene.all() == []
    assert not window.history.can_undo, "One placed paper picture needs one undo step"


def test_shift_dragging_the_paper_gumball_pad_scales_a_picture(paper_window,
                                                               tmp_path):
    window, layout = paper_window
    source = tmp_path / "Scale me.png"
    image = QImage(12, 8, QImage.Format.Format_ARGB32)
    image.fill(QColor("royalblue"))
    assert image.save(str(source))
    data = source.read_bytes()
    item = layout.add(PictureShape({
        "path": str(source), "image_data": data,
        "origin": [40.0, 60.0, 0.0],
        "u": [60.0, 0.0, 0.0], "v": [0.0, 40.0, 0.0],
        "alpha": 1.0,
    }), name=source.name)
    view = window.viewport.layout_view
    view.selected = [("object", item)]
    original = np.asarray((item.shape.vertices.min(axis=0),
                           item.shape.vertices.max(axis=0)))
    original_centre = original.mean(axis=0)
    undo0 = len(window.history._undo)

    gumball = view.gumball
    anchor = gumball.anchor()
    size = gumball._size_mm()
    from serpentine3d.ui.paper_gumball import PAD0, PAD1
    pad_middle = (PAD0 + PAD1) / 2
    sx, sy = view.paper_to_screen(anchor[0] + pad_middle * size,
                                  anchor[1] + pad_middle * size)
    shift = Qt.KeyboardModifier.ShiftModifier
    assert gumball.hit_test(sx, sy) == ("pad", 2)
    assert gumball.begin_drag(("pad", 2), sx, sy, shift)
    px, py = view.screen_to_paper(sx, sy)
    tx, ty = view.paper_to_screen(px + 12.0, py + 12.0)
    gumball.drag_to(tx, ty, shift)
    gumball.end_drag()

    scaled = np.asarray((item.shape.vertices.min(axis=0),
                         item.shape.vertices.max(axis=0)))
    factors = (scaled[1] - scaled[0])[:2] / (original[1] - original[0])[:2]
    assert factors[0] > 1.1
    assert factors[0] == pytest.approx(factors[1])
    assert scaled.mean(axis=0) == pytest.approx(original_centre)
    assert isinstance(item.shape, PictureShape)
    assert item.shape.plane["image_data"] == data
    assert len(window.history._undo) == undo0 + 1

    window.history.undo()
    restored, = window.scene.layouts[0].objects
    assert np.asarray((restored.shape.vertices.min(axis=0),
                       restored.shape.vertices.max(axis=0))) == pytest.approx(
                           original)


def test_rotate_command_and_move_snaps_on_paper_image(paper_window):
    window, layout = paper_window
    item = layout.add(PictureShape({
        "origin": [40., 60., 0.], "u": [60., 0., 0.],
        "v": [0., 40., 0.], "image_data": b"embedded", "alpha": 1.,
    }))
    lv = window.viewport.layout_view
    lv.selected = [("object", item)]
    window.processor.run("rotate")
    assert isinstance(window.processor.request, PointReq)
    window.processor.provide((40., 60., 0.))
    window.processor.provide(90.0)
    assert not window.processor.busy
    assert item.shape.plane["u"] == pytest.approx([0., 60., 0.], abs=1e-6)
    assert item.shape.plane["v"] == pytest.approx([-40., 0., 0.], abs=1e-6)
    assert not window.scene.all()
    window.processor.run("move")
    assert isinstance(window.processor.request, PointReq)
    snaps = window.viewport.snaps
    snaps.enabled = True
    for kind, point in (("end", (40., 120.)), ("mid", (40., 90.)),
                        ("center", (20., 90.))):
        for key in snaps.types:
            snaps.types[key] = key == kind
        sx, sy = lv.paper_to_screen(*point)
        got = window.viewport.world_point_at(sx + 2, sy + 2)
        assert got == pytest.approx((*point, 0.), abs=1e-6)
        assert window.viewport._active_snap[1] == kind
        snaps.types[kind] = False
        assert lv.note_snap(sx, sy, snaps) is None
    window.processor.cancel()
    window.history.undo()
    assert layout.objects[0].shape.plane["image_data"] == b"embedded"
