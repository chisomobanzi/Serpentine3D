"""Osnap uses actual scan samples, including their depth, while drawing."""

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from serpentine3d.core import geometry as g, occ
from serpentine3d.core.pointcloud import PointCloudShape
from serpentine3d.core.scene import Scene
from serpentine3d.core.snaps import SnapIndex
from serpentine3d.ui.camera import Camera


def camera(view="top"):
    cam = Camera()
    cam.set_standard_view(view)
    cam.target = np.zeros(3)
    cam.distance = 60.
    return cam


def pixel(cam, point, size=(900, 700)):
    return cam.project(np.asarray([point], float), *size)[0, :2]


def hit(index, cam, point, offset=(0, 0), size=(900, 700)):
    px, py = pixel(cam, point, size) + offset
    return index.find(cam, px, py, *size)


def assert_point(result, expected):
    assert result is not None, "A visible scan sample must be an Osnap candidate"
    assert result[1] == "point"
    assert result[0] == pytest.approx(expected)


def test_nearest_sample_retains_xyz_and_respects_screen_radius_and_camera_front():
    scene, cam = Scene(), camera("right")
    # In Right view the eye is on +X, so the last point is behind it.
    scene.add(PointCloudShape([(3, 2, 7), (3, 4, 7), (100, -8, 4)]))
    index = SnapIndex(scene)
    assert_point(hit(index, cam, (3, 2, 7), (3, 2)), (3, 2, 7))
    assert_point(hit(index, cam, (3, 4, 7)), (3, 4, 7))
    assert hit(index, cam, (3, 2, 7), (0, 15)) is None
    assert hit(index, cam, (100, -8, 4)) is None


def test_coincident_screen_samples_choose_frontmost_even_when_it_is_last():
    scene, cam = Scene(), camera("right")
    scene.add(PointCloudShape([(-10, 2, 7), (0, 2, 7), (10, 2, 7)]))
    assert_point(hit(SnapIndex(scene), cam, (10, 2, 7)), (10, 2, 7))


def test_hidden_objects_and_parent_layers_stop_snapping_without_breaking_cad_snaps():
    scene, cam = Scene(), camera()
    parent = scene.layers.create("Scans")
    child = scene.layers.create("Cloud", parent=parent.id)
    cloud = scene.add(PointCloudShape([(2, 3, 7)]), layer_id=child.id)
    scene.add(g.make_line((-12, -8, 0), (-5, -8, 0)))
    index = SnapIndex(scene)
    assert_point(hit(index, cam, (2, 3, 7)), (2, 3, 7))
    cad = hit(index, cam, (-12, -8, 0))
    assert cad is not None and cad[1] == "end"
    assert cad[0] == pytest.approx((-12, -8, 0))
    scene.update(cloud.id, visible=False)
    assert hit(index, cam, (2, 3, 7)) is None
    scene.update(cloud.id, visible=True)
    assert_point(hit(index, cam, (2, 3, 7)), (2, 3, 7))
    scene.layers.set_visible(parent.id, False)
    assert hit(index, cam, (2, 3, 7)) is None
    scene.layers.set_visible(parent.id, True)
    assert_point(hit(index, cam, (2, 3, 7)), (2, 3, 7))


@pytest.fixture
def window():
    from serpentine3d.app import MainWindow
    win = MainWindow()
    win.viewport.resize(900, 700)
    win.viewport.camera.set_standard_view("top")
    win.viewport.camera.target = np.zeros(3)
    win.viewport.camera.distance = 60.
    win.viewport.grid_snap = False
    win.viewport.ortho = False
    yield win
    win.processor.cancel()
    win._saved_revision = win.scene.revision
    win.close()


def test_point_toggle_is_default_on_and_bar_commands_settings_and_reload_agree(window):
    from serpentine3d.ui.settings_dialog import SettingsDialog
    from serpentine3d.utils.config import Config
    vp, cfg = window.viewport, window.cfg
    window.scene.add(PointCloudShape([(2, 3, 7)]))
    assert vp.snaps.types.get("point") is True
    assert cfg.get("osnaps", "point") is True
    assert "point" in window.osnap_bar._buttons
    button = window.osnap_bar._buttons["point"]
    assert button.text() == "Point"
    button.click()
    assert vp.snaps.types["point"] is False
    assert hit(vp.snaps, vp.camera, (2, 3, 7), size=(vp.width(), vp.height())) is None
    assert SnapIndex(window.scene, Config()).types["point"] is False
    window.processor.run("osnap point on")
    assert vp.snaps.types["point"] is True and button.isChecked()
    dialog = SettingsDialog(window)
    try:
        assert "point" in dialog.os_boxes
        dialog.os_boxes["point"].setChecked(False)
        assert vp.snaps.types["point"] is False and not button.isChecked()
        assert SnapIndex(window.scene, Config()).types["point"] is False
        dialog.os_boxes["point"].setChecked(True)
    finally:
        dialog.close()
    window.processor.run("osnap all off")
    assert hit(vp.snaps, vp.camera, (2, 3, 7), size=(vp.width(), vp.height())) is None
    window.processor.run("osnap all on")
    assert_point(hit(vp.snaps, vp.camera, (2, 3, 7), size=(vp.width(), vp.height())), (2, 3, 7))


def test_line_command_mouse_clicks_use_sample_coordinates_above_the_cplane(window):
    a, b = (2, 3, 7), (-12, -8, 11)
    window.scene.add(PointCloudShape([a, b]))
    window.processor.run("line")
    vp = window.viewport
    for sample in (a, b):
        xy = pixel(vp.camera, sample, (vp.width(), vp.height()))
        assert vp.world_point_at(*(xy + (2, 1))) == pytest.approx(sample)
        assert vp._active_snap[1] == "point"
        QTest.mouseClick(vp, Qt.MouseButton.LeftButton,
                         pos=QPoint(round(xy[0] + 2), round(xy[1] + 1)))
    curves = [obj for obj in window.scene.all() if obj.kind == "curve"]
    assert len(curves) == 1
    edge = occ.edge_adaptor(g.edges_of(curves[0].shape)[0])
    start, end = edge.Value(edge.FirstParameter()), edge.Value(edge.LastParameter())
    assert (start.X(), start.Y(), start.Z()) == pytest.approx(a)
    assert (end.X(), end.Y(), end.Z()) == pytest.approx(b)


def test_large_cloud_off_stride_sample_snaps_without_reprojecting_all_samples_on_each_move(monkeypatch):
    scene, cam = Scene(), camera()
    points = np.zeros((200_001, 3), np.float32)
    points[:, 0] = np.linspace(1000, 10000, len(points))
    points[1] = (2, 3, 7)  # Must not vanish in a stride-decimated picking set.
    scene.add(PointCloudShape(points))
    index = SnapIndex(scene)
    assert_point(hit(index, cam, points[1]), points[1])
    projected = []
    original = cam.project

    def counted(points, *args, **kwargs):
        projected.append(len(points))
        return original(points, *args, **kwargs)

    monkeypatch.setattr(cam, "project", counted)
    for delta in range(-5, 6):
        assert_point(hit(index, cam, points[1], (delta, 0)), points[1])
    assert sum(projected) < len(points) // 8, (
        "Warm mouse queries must narrow candidates instead of projecting the whole cloud")


def test_replacing_moving_and_removing_cloud_invalidates_snap_candidates():
    scene, cam = Scene(), camera()
    obj = scene.add(PointCloudShape([(2, 3, 7)]))
    index = SnapIndex(scene)
    assert_point(hit(index, cam, (2, 3, 7)), (2, 3, 7))
    scene.replace_shape(obj.id, obj.shape.translated((20, 0, 0)))
    assert hit(index, cam, (2, 3, 7)) is None
    assert_point(hit(index, cam, (22, 3, 7)), (22, 3, 7))
    scene.replace_shape(obj.id, PointCloudShape([(-15, -8, 4)]))
    assert hit(index, cam, (22, 3, 7)) is None
    assert_point(hit(index, cam, (-15, -8, 4)), (-15, -8, 4))
    scene.remove(obj.id)
    assert hit(index, cam, (-15, -8, 4)) is None


def test_view_change_pan_zoom_and_resize_do_not_reuse_stale_screen_positions():
    scene, cam = Scene(), camera()
    sample = (8, 3, 7)
    scene.add(PointCloudShape([sample]))
    index = SnapIndex(scene)
    old_pixel = pixel(cam, sample)
    assert_point(hit(index, cam, sample), sample)
    cam.set_standard_view("perspective")
    cam.target = np.array((-10., -8., 0.))
    cam.distance = 80.
    assert_point(hit(index, cam, sample, size=(1100, 850)), sample)
    assert index.find(cam, *old_pixel, 1100, 850) is None
