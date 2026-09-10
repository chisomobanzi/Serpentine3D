"""Pictures are editable scene objects, including after reopening a drawing."""
import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene
from serpentine3d.fileio import native
from tests.test_images_can_be_imported_as_pictures import window, _image, _place


def placed(window, tmp_path):
    source = _image(tmp_path / "Selectable.png")
    window._import_path(str(source))
    _place(window, first=(-12., -8., 0.), opposite=(12., 8., 0.))
    pictures = [o for o in window.scene.all() if o.kind == "picture"]
    assert len(pictures) == 1, "A picture must participate in scene selection"
    return pictures[0]


@pytest.mark.parametrize("mode", ["wireframe", "shaded", "rendered"])
def test_clicking_the_picture_interior_selects_and_delete_undo_restores_it(window, tmp_path, mode):
    obj = placed(window, tmp_path)
    vp = window.viewport
    vp.resize(800, 600)
    vp.camera.set_standard_view("top")
    vp.camera.target = np.zeros(3)
    vp.camera.distance = 100.
    vp.display_mode = mode
    p = vp.camera.project(np.array([[0., 0., 0.]]), vp.width(), vp.height())[0]
    assert vp.pick_object(*p[:2]) == obj.id
    QTest.mouseClick(vp, Qt.MouseButton.LeftButton, pos=QPoint(round(p[0]), round(p[1])))
    assert obj.id in window.selection.ids
    assert vp._box_pick(0, 0, vp.width(), vp.height(), True) == [obj.id]
    window.processor.run("delete")
    assert not window.scene.image_planes
    window.history.undo()
    assert window.scene.get(obj.id) is not None
    assert window.scene.image_planes[0]["image_data"] == obj.shape.plane["image_data"]


def test_moving_copying_and_scaling_a_selected_picture_keep_its_pixels(window, tmp_path):
    obj = placed(window, tmp_path)
    window.selection.set([obj.id])
    window.processor.run("move")
    window.processor.provide((0., 0., 0.))
    window.processor.provide((30., 5., 2.))
    moved = window.scene.get(obj.id)
    assert moved.shape.plane["origin"] == pytest.approx([18., -3., 2.])
    data = obj.shape.plane["image_data"]
    assert moved.shape.plane["image_data"] == data
    scaled = g.scale(moved.shape, (0., 0., 0.), 2.)
    copied = window.scene.add_from(scaled, moved)
    assert copied.kind == "picture"
    assert copied.shape.plane["u"] == pytest.approx([48., 0., 0.])
    assert copied.shape.plane["image_data"] == data
    restored = g.shape_from_bytes(g.shape_to_bytes(copied.shape))
    assert restored.plane == copied.shape.plane
    window.history.undo()
    assert window.scene.get(obj.id).shape.plane["origin"] == [-12., -8., 0.]


def test_saved_pictures_remain_selectable_and_keep_layer_visibility_and_lock(window, tmp_path):
    obj = placed(window, tmp_path)
    layer = window.scene.layers.create("References")
    window.scene.update(obj.id, layer_id=layer.id, name="Plan", locked=True, visible=False,
                        block_id="reference-block", draw_order=3, linetype="Dashed")
    saved = tmp_path / "Pictures.serp"
    native.save_scene(window.scene, str(saved))
    loaded = Scene()
    native.load_scene(loaded, str(saved))
    picture, = loaded.all()
    assert picture.kind == "picture" and picture.name == "Plan"
    assert loaded.layers.get(picture.layer_id).name == "References"
    assert picture.block_id == "reference-block" and picture.draw_order == 3
    assert picture.linetype == "Dashed"
    assert picture.locked and not picture.visible
    assert not loaded.is_selectable(picture.id)
    loaded.update(picture.id, locked=False, visible=True)
    assert loaded.is_selectable(picture.id)
    assert picture.shape.plane["image_data"] == obj.shape.plane["image_data"]


def test_existing_picture_does_not_break_point_placement_or_corner_snapping(window, tmp_path):
    obj = placed(window, tmp_path)
    vp = window.viewport
    vp.resize(800, 600)
    vp.camera.set_standard_view("top")
    vp.camera.target = np.zeros(3)
    vp.camera.distance = 100.
    vp.snaps.enabled = True
    window.processor.run("line")
    corner = obj.shape.vertices[0]
    screen = vp.camera.project(np.asarray([corner]), vp.width(), vp.height())[0]
    assert vp.world_point_at(*screen[:2]) == pytest.approx(corner)
    assert vp.world_point_at(600, 200) is not None
    QTest.mouseClick(vp, Qt.MouseButton.LeftButton,
                     pos=QPoint(round(screen[0]), round(screen[1])))
    assert window.processor.request.rubber_from == pytest.approx(corner)
    window.processor.cancel()
