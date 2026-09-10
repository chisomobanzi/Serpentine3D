"""Trim removes chosen picture regions without changing their pixel mapping."""

import pytest
from PySide6.QtGui import QImage

from serpentine3d.commands.base import SelectReq
from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene
from serpentine3d.fileio import native
from tests.test_pictures_can_be_split import (
    window, picture, picture_draws, _pictures, _pick, _split,
    _assert_draws_keep_pixels,
)


def _start_trim(window, target, cutter):
    proc = window.processor
    window.selection.clear()
    proc.run("trim")
    proc.click_object(cutter.id)
    proc.finish_selection()
    assert isinstance(proc.request, SelectReq) and "object to trim" in proc.request.prompt.lower()
    proc.click_object(target.id)


def _trim(window, target, cutter, remove_at, also_select=()):
    _start_trim(window, target, cutter)
    proc = window.processor
    assert isinstance(proc.request, SelectReq) and "trim away" in proc.request.prompt.lower(), \
        "Trim must accept a picture target and ask which cut region to remove"
    doomed_id = _pick(window, remove_at)
    assert doomed_id in {p.id for p in _pictures(window.scene)}
    for obj in also_select:
        proc.click_object(obj.id)
    proc.click_object(doomed_id)
    proc.finish_selection()
    assert not proc.busy
    assert window.scene.get(doomed_id) is None
    assert window.scene.get(cutter.id) is not None, "Trim must retain its cutting object"


def test_trim_keeps_picture_pixels_and_attributes_and_does_not_delete_other_selected_objects(
        window, picture, picture_draws):
    cutter = window.scene.add(g.make_line((8., -3., 0.), (8., 13., 0.)))
    unrelated = window.scene.add(g.make_line((25., 0., 0.), (25., 10., 0.)))
    _trim(window, picture, cutter, (3., 4., 0.), also_select=(cutter, unrelated))
    kept, = _pictures(window.scene)
    assert kept.shape.area() == pytest.approx(120.)
    assert _pick(window, (3., 4., 0.)) is None
    assert _pick(window, (15., 4., 0.)) == kept.id
    assert window.scene.get(unrelated.id) is not None, "Only pieces created by this Trim can be removed"
    for field in ("layer_id", "color", "material", "draw_order", "linetype", "annotation"):
        assert getattr(kept, field) == getattr(picture, field)
    _assert_draws_keep_pixels(picture_draws(window.viewport), expected_area=120.)


def test_trim_a_previously_split_picture_never_brings_back_its_missing_region(
        window, picture, picture_draws):
    diagonal = window.scene.add(g.make_line((-2., -1., 0.), (22., 11., 0.)))
    _split(window, picture, diagonal)
    target = window.scene.get(_pick(window, (3., 8., 0.)))
    other_id = _pick(window, (17., 2., 0.))
    cutter = window.scene.add(g.make_line((10., -2., 0.), (10., 12., 0.)))
    _trim(window, target, cutter, (15., 9., 0.))
    assert sorted(p.shape.area() for p in _pictures(window.scene)) == pytest.approx([75., 100.])
    assert _pick(window, (15., 9., 0.)) is None
    assert _pick(window, (3., 8., 0.)) is not None
    assert _pick(window, (17., 2., 0.)) == other_id
    _assert_draws_keep_pixels(picture_draws(window.viewport), expected_area=175.)


def test_trim_closed_cutter_leaves_a_real_hole_in_picture_drawing_and_picking(
        window, picture, picture_draws):
    cutter = window.scene.add(g.make_polyline(
        [(6., 3., 0.), (14., 3., 0.), (14., 7., 0.), (6., 7., 0.)], closed=True))
    _trim(window, picture, cutter, (10., 5., 0.))
    kept, = _pictures(window.scene)
    assert kept.shape.area() == pytest.approx(168.)
    assert _pick(window, (10., 5., 0.)) is None, "A trimmed hole must not select its surrounding picture"
    assert _pick(window, (2., 5., 0.)) == kept.id
    _assert_draws_keep_pixels(picture_draws(window.viewport), expected_area=168.)


def test_trimmed_picture_is_portable_and_one_undo_restores_the_original(
        window, picture, picture_draws, tmp_path):
    cutter = window.scene.add(g.make_line((-2., -1., 0.), (22., 11., 0.)))
    _trim(window, picture, cutter, (17., 2., 0.))
    path = tmp_path / "Trimmed picture.serp"
    native.save_scene(window.scene, str(path))
    (tmp_path / "Survey.png").unlink()
    loaded = Scene()
    native.load_scene(loaded, str(path))
    kept, = _pictures(loaded)
    assert kept.shape.area() == pytest.approx(100.)
    assert not QImage.fromData(kept.shape.plane["image_data"]).isNull()
    original_scene = window.viewport.scene
    try:
        window.viewport.scene = loaded
        assert _pick(window, (17., 2., 0.)) is None
        assert _pick(window, (3., 8., 0.)) == kept.id
        _assert_draws_keep_pixels(picture_draws(window.viewport), expected_area=100.)
    finally:
        window.viewport.scene = original_scene
    window.history.undo()
    restored, = _pictures(window.scene)
    assert restored.id == picture.id and restored.shape.area() == pytest.approx(200.)
    assert window.scene.get(cutter.id) is not None
    window.history.redo()
    redone, = _pictures(window.scene)
    assert redone.shape.area() == pytest.approx(100.)
    assert _pick(window, (17., 2., 0.)) is None
    _assert_draws_keep_pixels(picture_draws(window.viewport), expected_area=100.)


def test_trim_with_a_nonintersecting_cutter_leaves_the_same_picture_intact(window, picture):
    cutter = window.scene.add(g.make_line((30., -2., 0.), (30., 12., 0.)))
    before_revision = window.scene.revision
    _start_trim(window, picture, cutter)
    assert not window.processor.busy, "A cutter that misses the picture must finish without asking to remove it"
    untouched, = _pictures(window.scene)
    assert untouched.id == picture.id
    assert untouched.shape.area() == pytest.approx(200.)
    assert window.scene.get(cutter.id) is not None
    assert window.scene.revision == before_revision
