"""Split cuts the visible picture region, retaining its original pixel mapping.

Exercise the normal command, scene picking, history, portable files and the
existing GL submission boundary; no particular boundary storage is assumed.
"""

import numpy as np
import pytest
from PySide6.QtGui import QColor, QImage

from serpentine3d.commands.base import SelectReq
from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene
from serpentine3d.fileio import native
from tests.test_images_can_be_imported_as_pictures import window, _place


@pytest.fixture
def picture(window, tmp_path):
    path = tmp_path / "Survey.png"
    image = QImage(200, 100, QImage.Format.Format_RGB32)
    for y in range(image.height()):
        for x in range(image.width()):
            image.setPixelColor(x, y, QColor(x, y * 2, 73))
    assert image.save(str(path))
    window._import_path(str(path))
    _place(window, first=(0., 0., 0.), opposite=(20., 10., 0.))
    obj, = [o for o in window.scene.all() if o.kind == "picture"]
    layer = window.scene.layers.create("Reference images")
    obj = window.scene.update(obj.id, layer_id=layer.id, color=(.2, .4, .6),
                              material={"opacity": .8}, draw_order=3,
                              linetype="Dashed", annotation={"text": "Survey"})
    obj.shape.plane["alpha"] = .7
    vp = window.viewport
    vp.resize(1000, 800)
    vp.camera.set_standard_view("top")
    vp.camera.target = np.array([10., 5., 0.])
    vp.camera.distance = 40.
    return obj


def _pictures(scene):
    return [o for o in scene.all() if o.kind == "picture"]


def _split(window, target, cutter):
    proc = window.processor
    window.selection.clear()
    proc.run("split")
    proc.click_object(target.id)
    assert isinstance(proc.request, SelectReq) and "cutting" in proc.request.prompt.lower(), \
        "Split must accept an imported picture as its target"
    proc.click_object(cutter.id)
    proc.finish_selection()
    assert not proc.busy, "Split must finish after the cutting objects are accepted"
    assert window.scene.get(cutter.id) is not None, "The cutting curve must remain"


def _pick(window, point):
    vp = window.viewport
    p = vp.camera.project(np.asarray([point], float), vp.width(), vp.height())[0]
    return vp.pick_object(*p[:2])


@pytest.fixture
def picture_draws(monkeypatch):
    """Capture textured triangles without requiring offscreen OpenGL support."""
    from serpentine3d.ui import viewport as module
    pending, draws = {}, []

    def texture(path, image_data=None):
        image = QImage.fromData(image_data) if image_data else QImage(path)
        assert not image.isNull()
        pending["image"] = image
        return 1, image.width() / image.height()

    def upload(target, size, data, usage):
        pending["vertices"] = np.array(data, copy=True)

    def draw(mode, start, count):
        assert mode == module.GL.GL_TRIANGLES and count > 0 and count % 3 == 0
        vertices = pending["vertices"].reshape(-1, 5)[start:start + count]
        draws.append((vertices.copy(), pending["image"], pending["uAlpha"]))

    for name in ("glUniformMatrix4fv", "glUniform1i", "glActiveTexture",
                 "glBindTexture", "glBindVertexArray", "glBindBuffer", "glDepthMask"):
        monkeypatch.setattr(module.GL, name, lambda *args: None)
    monkeypatch.setattr(module.GL, "glUniform1f", lambda k, v: pending.update({k: v}))
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


def _assert_draws_keep_pixels(draws, expected_area=200.):
    area = 0.
    for vertices, image, alpha in draws:
        assert alpha == pytest.approx(.7)
        triangles = vertices.reshape(-1, 3, 5)
        for tri in triangles:
            area += np.linalg.norm(np.cross(tri[1, :3] - tri[0, :3],
                                           tri[2, :3] - tri[0, :3])) / 2
            # Compare the sampled source pixel with its location in the original
            # picture. This also permits implementations that crop pixel data.
            x, y, z, u, v = tri.mean(axis=0)
            px = min(image.width() - 1, max(0, int(u * image.width())))
            py = min(image.height() - 1, max(0, int((1 - v) * image.height())))
            color = image.pixelColor(px, py)
            assert color.red() == pytest.approx(x * 10, abs=2), "Split stretched the picture horizontally"
            assert color.green() == pytest.approx((10 - y) * 20, abs=3), "Split stretched the picture vertically"
            assert color.blue() == 73
    assert area == pytest.approx(expected_area, abs=.02), "The draw pass must cover only the cut regions"


@pytest.mark.parametrize("ends,samples,areas", [
    (((8., -3., 0.), (8., 13., 0.)), ((3., 4., 0.), (15., 4., 0.)), [80., 120.]),
    (((-2., -1., 0.), (22., 11., 0.)), ((3., 8., 0.), (17., 2., 0.)), [100., 100.]),
])
def test_split_makes_independent_picture_regions_with_original_pixels_and_attributes(
        window, picture, picture_draws, ends, samples, areas):
    cutter = window.scene.add(g.make_line(*ends))
    _split(window, picture, cutter)
    pieces = _pictures(window.scene)
    assert len(pieces) == 2, "Split must produce picture objects, not plain surfaces"
    assert sorted(p.shape.area() for p in pieces) == pytest.approx(areas)
    ids = [_pick(window, p) for p in samples]
    assert len(set(ids)) == 2 and set(ids) == {p.id for p in pieces}
    for piece in pieces:
        assert window.scene.is_selectable(piece.id)
        for field in ("layer_id", "color", "material", "draw_order", "linetype", "annotation"):
            assert getattr(piece, field) == getattr(picture, field)
    _assert_draws_keep_pixels(picture_draws(window.viewport))


def test_a_split_picture_can_be_split_again_without_resurrecting_its_missing_half(
        window, picture, picture_draws):
    cutter = window.scene.add(g.make_line((-2., -1., 0.), (22., 11., 0.)))
    _split(window, picture, cutter)
    target = window.scene.get(_pick(window, (3., 8., 0.)))
    cutter2 = window.scene.add(g.make_line((10., -2., 0.), (10., 12., 0.)))
    _split(window, target, cutter2)
    assert sorted(p.shape.area() for p in _pictures(window.scene)) == pytest.approx([25., 75., 100.])
    picked = [_pick(window, p) for p in ((3., 8., 0.), (15., 9., 0.), (17., 2., 0.))]
    assert len(set(picked)) == 3 and None not in picked
    _assert_draws_keep_pixels(picture_draws(window.viewport))


def test_closed_cutter_makes_a_picture_piece_and_a_surrounding_picture_with_a_hole(
        window, picture, picture_draws):
    cutter = window.scene.add(g.make_polyline(
        [(6., 3., 0.), (14., 3., 0.), (14., 7., 0.), (6., 7., 0.)], closed=True))
    _split(window, picture, cutter)
    pieces = _pictures(window.scene)
    assert sorted(p.shape.area() for p in pieces) == pytest.approx([32., 168.])
    inner = window.scene.get(_pick(window, (10., 5., 0.)))
    assert inner is not None and inner.shape.area() == pytest.approx(32.)
    window.scene.update(inner.id, visible=False)
    assert _pick(window, (10., 5., 0.)) is None, "The surrounding picture must not select through its hole"
    assert _pick(window, (2., 5., 0.)) in {p.id for p in pieces}
    _assert_draws_keep_pixels(picture_draws(window.viewport), expected_area=168.)


def test_split_picture_regions_survive_native_reopen_and_undo_redo(
        window, picture, picture_draws, tmp_path):
    cutter = window.scene.add(g.make_line((-2., -1., 0.), (22., 11., 0.)))
    _split(window, picture, cutter)
    path = tmp_path / "Cut pictures.serp"
    native.save_scene(window.scene, str(path))
    # Embedded pixels must remain usable when the original image disappears.
    (tmp_path / "Survey.png").unlink()
    loaded = Scene()
    native.load_scene(loaded, str(path))
    pieces = _pictures(loaded)
    assert len(pieces) == 2
    assert sorted(p.shape.area() for p in pieces) == pytest.approx([100., 100.])
    for p in pieces:
        assert loaded.is_selectable(p.id)
        assert not QImage.fromData(p.shape.plane["image_data"]).isNull()
    original_scene = window.viewport.scene
    try:
        window.viewport.scene = loaded
        _assert_draws_keep_pixels(picture_draws(window.viewport))
        assert _pick(window, (3., 8., 0.)) != _pick(window, (17., 2., 0.))
    finally:
        window.viewport.scene = original_scene
    window.history.undo()
    restored, = _pictures(window.scene)
    assert restored.id == picture.id and restored.shape.area() == pytest.approx(200.)
    assert window.scene.get(cutter.id) is not None
    window.history.redo()
    assert sorted(p.shape.area() for p in _pictures(window.scene)) == pytest.approx([100., 100.])
    _assert_draws_keep_pixels(picture_draws(window.viewport))


def test_split_with_a_nonintersecting_cutter_leaves_the_same_picture_intact(window, picture):
    cutter = window.scene.add(g.make_line((30., -2., 0.), (30., 12., 0.)))
    before_revision = window.scene.revision
    _split(window, picture, cutter)
    untouched, = _pictures(window.scene)
    assert untouched.id == picture.id, "A failed cut must not replace the picture with a duplicate"
    assert untouched.shape.area() == pytest.approx(200.)
    assert window.scene.revision == before_revision
