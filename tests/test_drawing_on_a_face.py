"""Drawing on a face without setting a construction plane first.

Putting a rectangle on the side of a box used to take a trip through CPlane
3Point and another one back. A drawing command's first point now takes the
plane of the flat face under it, for that command and no longer, and the plane
you set is still there when it ends.
"""

import json

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent

from serpentine3d.commands.base import PointReq
from serpentine3d.core import geometry as g
from serpentine3d.core.cplane import CPlane, face_outline, on_face


def _square(z=0.0):
    verts = np.array([[0, 0, z], [4, 0, z], [4, 2, z], [0, 2, z]], float)
    return verts, np.array([[0, 1, 2], [0, 2, 3]], np.uint32)


def test_the_outline_leaves_out_the_diagonal():
    verts, tris = _square()
    assert len(face_outline(verts, tris)) == 4


def test_a_face_gives_its_own_plane_through_its_middle():
    verts, tris = _square(z=5.0)
    plane, _ = on_face(verts, tris, (0, 0, 1), CPlane())
    assert np.allclose(plane.normal, (0, 0, 1))
    assert np.allclose(plane.origin, (2, 1, 5))


def test_the_normal_comes_out_on_the_side_you_are_looking_at():
    verts, tris = _square()
    plane, _ = on_face(verts, tris, (0, 0, -1), CPlane())
    assert np.allclose(plane.normal, (0, 0, -1))


def test_a_bent_patch_is_not_a_face_to_draw_on():
    verts = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 1]], float)
    tris = np.array([[0, 1, 2], [0, 2, 3]], np.uint32)
    assert on_face(verts, tris, (0, 0, 1), CPlane()) is None


def test_up_stays_up_on_a_wall():
    for normal in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0)):
        n = np.asarray(normal, float)
        side = np.cross((0, 0, 1), n)
        verts = np.array([-side - (0, 0, 1), side - (0, 0, 1),
                          side + (0, 0, 1), -side + (0, 0, 1)], float)
        tris = np.array([[0, 1, 2], [0, 2, 3]], np.uint32)
        plane, _ = on_face(verts, tris, n, CPlane())
        assert np.allclose(plane.ydir, (0, 0, 1)), normal


def test_the_axes_lie_along_a_turned_face():
    turn = np.radians(30)
    x = np.array([np.cos(turn), np.sin(turn), 0.0])
    y = np.array([-np.sin(turn), np.cos(turn), 0.0])
    verts = np.array([0 * x, 4 * x, 4 * x + 2 * y, 2 * y], float)
    tris = np.array([[0, 1, 2], [0, 2, 3]], np.uint32)
    plane, _ = on_face(verts, tris, (0, 0, 1), CPlane())
    assert np.allclose(plane.xdir, x)


def test_a_round_face_keeps_the_axes_it_was_handed():
    ring = np.linspace(0, 2 * np.pi, 48, endpoint=False) + 0.3
    verts = np.column_stack([np.cos(ring), np.sin(ring), np.zeros(48)])
    verts = np.vstack([verts, (0, 0, 0)])
    tris = np.array([[48, i, (i + 1) % 48] for i in range(48)], np.uint32)
    plane, _ = on_face(verts, tris, (0, 0, 1), CPlane())
    assert np.allclose(plane.xdir, (1, 0, 0))


@pytest.fixture
def window(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({}))
    monkeypatch.setenv("SERP3D_CONFIG", str(cfg))
    monkeypatch.setenv("SERP3D_AUTOSAVE_DIR", str(tmp_path / "autosave"))
    from serpentine3d.app import MainWindow
    w = MainWindow()
    w.resize(1200, 800)
    w.scene.add(g.make_box((-5.0, -5.0, 0.0), 10.0, 10.0, 10.0))
    vp = w.viewport
    vp.resize(900, 700)
    vp.camera.set_standard_view("perspective")
    vp.camera.target = np.array([0.0, 0.0, 5.0])
    vp.camera.distance = 90.0
    vp.snaps.enabled = False
    yield w
    w._saved_revision = w.scene.revision
    w.close()


def _pixel(vp, point):
    at = vp.camera.project(np.asarray([point], float), vp.width(),
                           vp.height())[0]
    return QPointF(float(at[0]), float(at[1]))


def _hover(vp, point):
    pos = _pixel(vp, point)
    return vp.world_point_at(pos.x(), pos.y())


def _click(vp, point):
    pos = _pixel(vp, point)
    vp.pointPicked.emit(vp.world_point_at(pos.x(), pos.y()))


TOP = (1.0, -1.0, 10.0)
OFF = (60.0, 60.0, 0.0)


def test_the_plane_follows_the_cursor_up_to_the_first_point(window):
    vp = window.viewport
    window.processor.run("rectangle")
    point = _hover(vp, TOP)
    assert vp.active_cplane().name == "Face"
    assert point[2] == pytest.approx(10.0)
    _hover(vp, OFF)
    assert vp.active_cplane() is vp.cplane


def test_a_rectangle_lands_on_the_face_and_the_plane_goes_back(window):
    vp = window.viewport
    mine = vp.cplane
    window.processor.run("rectangle")
    _click(vp, TOP)
    assert vp.active_cplane().name == "Face"
    _click(vp, (3.0, 3.0, 10.0))
    assert not window.processor.busy
    made = window.scene.all()[-1]
    lo, hi = g.bbox(made.shape)
    assert lo[2] == pytest.approx(10.0) and hi[2] == pytest.approx(10.0)
    assert vp.cplane is mine and vp.active_cplane() is mine


def test_the_second_point_stays_on_the_face_past_its_edge(window):
    vp = window.viewport
    window.processor.run("line")
    _click(vp, TOP)
    point = _hover(vp, OFF)
    assert vp.follow_faces is False
    assert window.processor.request is not None
    assert vp.cplane.from_world(point)[2] != pytest.approx(0.0)
    assert point[2] == pytest.approx(10.0)
    window.processor.cancel()


def test_a_cancel_lets_go_of_the_face(window):
    vp = window.viewport
    window.processor.run("line")
    _click(vp, TOP)
    window.processor.cancel()
    assert vp.face_plane is None and vp.active_cplane() is vp.cplane


def test_a_box_stands_up_off_the_side_it_was_started_on(window):
    vp = window.viewport
    window.processor.run("box")
    _hover(vp, (1.0, -5.0, 5.0))
    plane = vp.active_cplane()
    assert np.allclose(plane.normal, (0, -1, 0))
    assert np.allclose(plane.ydir, (0, 0, 1))
    window.processor.cancel()


def test_every_pane_keeps_the_face_once_a_point_is_on_it(window):
    vp = window.viewport
    other = window.new_viewport_dock("Right")
    window._set_active_viewport(vp)
    window.processor.run("line")
    _click(vp, TOP)
    assert other.active_cplane() is vp.active_cplane()
    window.processor.cancel()
    assert other.face_plane is None


def test_a_command_that_only_measures_is_left_alone(window):
    vp = window.viewport
    window.processor.run("distance")
    assert isinstance(window.processor.request, PointReq)
    assert vp.follow_faces is False
    _hover(vp, TOP)
    assert vp.active_cplane() is vp.cplane
    window.processor.cancel()


def test_a_curved_face_leaves_the_plane_where_it_was(window):
    vp = window.viewport
    window.scene.add(g.make_cylinder((20.0, 0.0, 0.0), 5.0, 10.0,
                                     (0.0, 0.0, 1.0)))
    window.processor.run("line")
    _hover(vp, (20.0, -5.0, 5.0))
    assert vp.active_cplane() is vp.cplane
    window.processor.cancel()


def test_it_can_be_turned_off_for_good(window):
    vp = window.viewport
    window.run_command("autocplane")
    assert vp.auto_cplane is False
    assert window.cfg.get("auto_cplane") is False
    window.processor.run("rectangle")
    _hover(vp, TOP)
    assert vp.active_cplane() is vp.cplane
    window.processor.cancel()


def test_turning_it_off_at_the_first_prompt_takes_the_plane_back(window):
    vp = window.viewport
    window.processor.run("rectangle")
    _hover(vp, TOP)
    window.run_command("autocplane")
    assert window.processor.busy
    assert vp.active_cplane() is vp.cplane
    window.processor.cancel()


def test_the_face_being_followed_carries_its_outline(window):
    vp = window.viewport
    window.processor.run("rectangle")
    _hover(vp, TOP)
    assert len(vp.face_plane[1]) == 4
    window.processor.cancel()


def test_a_real_click_goes_through_the_press_handler(window):
    vp = window.viewport
    window.processor.run("point")
    pos = _pixel(vp, TOP)
    vp.mousePressEvent(QMouseEvent(
        QEvent.Type.MouseButtonPress, pos, pos, Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    made = window.scene.all()[-1]
    assert g.bbox(made.shape)[0][2] == pytest.approx(10.0)
