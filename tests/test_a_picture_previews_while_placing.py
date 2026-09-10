"""A picture's second corner previews its pixels, size and construction plane.

Record the existing picture draw pass at the GL submission boundary so these
tests run offscreen. The command and all pane wiring remain real; no preview
storage API is assumed, and the real packaged window is checked separately.
"""

import numpy as np
import pytest
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest

from serpentine3d.app import MainWindow
from serpentine3d.commands.base import PointReq
from serpentine3d.core.cplane import CPlane
from serpentine3d.core.scene import Scene
from serpentine3d.fileio import native


@pytest.fixture
def window():
    win = MainWindow()
    win.resize(1200, 800)
    win.set_view_layout("quad")
    yield win
    if win.processor.busy:
        win.processor.cancel()
    win.mark_saved()
    win.close()


@pytest.fixture
def picture(tmp_path):
    path = tmp_path / "Preview picture.png"
    image = QImage(12, 8, QImage.Format.Format_ARGB32)
    image.fill(QColor("tomato"))
    image.setPixelColor(0, 0, QColor("blue"))
    image.setPixelColor(11, 7, QColor(0, 0, 0, 0))
    assert image.save(str(path))
    return path


@pytest.fixture
def drawn_pictures(monkeypatch):
    """Return image/alpha/quad submissions without needing an OpenGL context."""
    from serpentine3d.ui import viewport as module

    draws = []
    pending = {}

    def texture(path, image_data=None):
        image = QImage(path) if image_data is None else QImage.fromData(image_data)
        assert not image.isNull(), "The preview must use decodable image pixels"
        pending["image"] = image
        return 1, image.width() / image.height()

    def uniform(name, value):
        pending[name] = value

    def upload(target, size, data, usage):
        pending["quad"] = np.array(data, copy=True)

    def draw(mode, start, count):
        assert mode == module.GL.GL_TRIANGLES and count == 6
        draws.append(dict(pending))

    for name in ("glUniformMatrix4fv", "glUniform1i", "glActiveTexture",
                 "glBindTexture", "glBindVertexArray", "glBindBuffer",
                 "glDepthMask"):
        monkeypatch.setattr(module.GL, name, lambda *args: None)
    monkeypatch.setattr(module.GL, "glUniform1f", uniform)
    monkeypatch.setattr(module.GL, "glBufferData", upload)
    monkeypatch.setattr(module.GL, "glDrawArrays", draw)

    def capture(vp):
        draws.clear()
        pending.clear()
        monkeypatch.setattr(vp, "_texture_for", texture)
        monkeypatch.setattr(vp, "_use", lambda *args: None)
        monkeypatch.setattr(vp, "_uloc", lambda program, name: name)
        for name in ("_tex_prog", "_tex_vao", "_tex_vbo"):
            monkeypatch.setattr(vp, name, 1, raising=False)
        monkeypatch.setattr(vp, "_frame_anchor", np.zeros(3))
        vp._draw_image_planes(np.eye(4, dtype=np.float32))
        return list(draws)

    return capture


def _start(win, path, first):
    win.processor.run("import --headless")
    win.processor.provide(str(path))
    assert isinstance(win.processor.request, PointReq)
    win.processor.provide(first)
    assert isinstance(win.processor.request, PointReq)


def _move(win, cursor):
    # The existing command ghost pipeline is capped at 30 Hz.
    QTest.qWait(40)
    win._active_vp.mouseWorldMoved.emit(cursor)


def _one_picture(capture, vp):
    draws = capture(vp)
    assert len(draws) == 1, \
        "While choosing the second corner, each pane must draw the actual picture"
    return draws[0]


def test_pointer_previews_image_pixels_and_aspect_in_every_pane(
        window, picture, drawn_pictures):
    plane = CPlane(origin=(11, -7, 5), normal=(1, 0, 0), xdir=(0, 1, 0))
    window._active_vp.cplane = plane
    first = plane.to_world(2, 3)
    _start(window, picture, first)
    revision = window.scene.revision
    panes = window.all_viewports()
    assert len(panes) == 4
    assert all(not drawn_pictures(vp) for vp in panes)

    for width, pointer_height in ((12, 1), (-24, -3)):
        _move(window, plane.to_world(2 + width, 3 + pointer_height))
        expected_height = abs(width) * 8 / 12 * np.sign(pointer_height)
        expected_corners = [plane.to_world(2, 3),
                            plane.to_world(2 + width, 3),
                            plane.to_world(2 + width, 3 + expected_height),
                            plane.to_world(2, 3 + expected_height)]
        for vp in panes:
            drawn = _one_picture(drawn_pictures, vp)
            assert 0 < drawn["uAlpha"] < 1, "Placement preview must be translucent"
            assert drawn["image"] == QImage(str(picture))
            assert drawn["quad"][[0, 1, 2, 5], :3] == pytest.approx(
                np.asarray(expected_corners))
            assert drawn["quad"][[0, 1, 2, 5], 3:] == pytest.approx(
                np.array([[0, 0], [1, 0], [1, 1], [0, 1]]))
        assert window.scene.revision == revision, "Pointer motion must not edit the document"
        assert not window.scene.image_planes


def test_second_click_replaces_preview_with_one_opaque_undoable_picture(
        window, picture, drawn_pictures):
    _start(window, picture, (1, 2, 0))
    _move(window, (13, 4, 0))
    preview = _one_picture(drawn_pictures, window.viewport)
    assert 0 < preview["uAlpha"] < 1
    window.processor.provide((13, 4, 0))
    assert not window.processor.busy
    for vp in window.all_viewports():
        final = _one_picture(drawn_pictures, vp)
        assert final["uAlpha"] == 1
        assert final["quad"] == pytest.approx(preview["quad"])
    assert len(window.scene.image_planes) == 1
    window.history.undo()
    assert not window.scene.image_planes
    assert all(not drawn_pictures(vp) for vp in window.all_viewports())
    assert not window.history.can_undo


def test_cancelling_clears_every_preview_and_unfinished_picture_is_never_saved(
        window, picture, drawn_pictures, tmp_path):
    window.mark_saved()
    _start(window, picture, (0, 0, 0))
    _move(window, (12, 4, 0))
    for vp in window.all_viewports():
        _one_picture(drawn_pictures, vp)
    saved = tmp_path / "Unfinished.serp"
    native.save_scene(window.scene, str(saved))
    loaded = Scene()
    native.load_scene(loaded, str(saved))
    assert not loaded.image_planes
    window.processor.cancel()
    assert all(not drawn_pictures(vp) for vp in window.all_viewports())
    assert not window.scene.image_planes
    assert not window.history.can_undo
    assert not window.dirty


def test_picture_draw_recorder_observes_existing_completed_pictures(
        window, picture, drawn_pictures):
    """The offscreen recorder sees the existing renderer before preview exists."""
    _start(window, picture, (0, 0, 0))
    window.processor.provide((12, 4, 0))
    for vp in window.all_viewports():
        drawn = _one_picture(drawn_pictures, vp)
        assert drawn["uAlpha"] == 1
        assert drawn["image"] == QImage(str(picture))
        assert drawn["quad"][[0, 1, 2, 5], :3] == pytest.approx(
            np.array([[0, 0, 0], [12, 0, 0], [12, 8, 0], [0, 8, 0]]))
