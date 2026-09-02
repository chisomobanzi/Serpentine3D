"""A clipping plane draws an arrow along its normal.

Asked for by a user: the plane could have a line showing its orientation.
A clipping plane is a rectangle, and a rectangle looks the same from both
sides, so nothing on screen says which half of the model it is about to
take away. You find out by dragging something across it and watching the
thing vanish, which is a strange way to be told.

The arrow points at the half that goes. It and the cut are read from one
function, so they cannot drift apart.
"""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui import theme
from serpentine3d.ui.camera import Camera
from serpentine3d.ui.viewport import (CLIP_ARROW_PX, Viewport, clip_equation,
                                      clip_normal_arrows, clip_plane_frames)


def _rect_on_xy(z=0.0):
    """A rectangle lying flat on the world XY plane, wound anticlockwise."""
    return g.planar_face(g.make_polyline(
        [(-5, -5, z), (5, -5, z), (5, 5, z), (-5, 5, z)], closed=True))


def _scene_with_plane(enabled=True, flipped=False):
    scene = Scene()
    face = _rect_on_xy()
    if flipped:
        face = g.mirror(face, (0, 0, 0), (0, 0, 1))
    obj = scene.add(face, name="Clipping Plane 01")
    scene.update(obj.id, clip_plane={"enabled": enabled})
    return scene


def _hidden_by(origin, normal, point):
    """What the shader works out for `point`: it is drawn when this is
    positive and thrown away when it is negative."""
    eq = clip_equation(origin, normal)
    return float(np.dot(eq[:3], np.asarray(point, float)) + eq[3]) < 0


# --- where the arrow points ------------------------------------------------

def test_the_arrow_points_at_the_half_that_gets_hidden():
    """The whole point of drawing it. Whichever way round the plane is,
    following the arrow takes you into the part of the model that is gone."""
    (origin, normal, _enabled), = clip_plane_frames(_scene_with_plane().all())
    n = np.asarray(normal, float)
    o = np.asarray(origin, float)

    assert _hidden_by(o, n, o + n * 5)
    assert not _hidden_by(o, n, o - n * 5)


def test_flipping_the_plane_turns_the_arrow_round():
    """Flip is how you say you meant the other half, so the arrow has to
    say it too."""
    (_, up, _), = clip_plane_frames(_scene_with_plane().all())
    (_, down, _), = clip_plane_frames(
        _scene_with_plane(flipped=True).all())

    assert np.dot(up, down) < -0.99


def test_the_arrow_starts_at_the_middle_of_the_plane():
    """Anywhere else and it reads as belonging to whatever it is nearest."""
    (origin, _, _), = clip_plane_frames(_scene_with_plane().all())

    assert np.allclose(origin, (0, 0, 0), atol=1e-9)


# --- which planes get one --------------------------------------------------

def test_a_paused_plane_still_says_which_way_it_faces():
    """Pausing a plane is what you do while you are still deciding, which
    is exactly when you want to see which way it is round. It comes back
    marked paused so it can be drawn faintly rather than not at all."""
    frames = clip_plane_frames(_scene_with_plane(enabled=False).all())

    assert len(frames) == 1
    assert frames[0][2] is False


def test_ordinary_objects_get_no_arrow():
    scene = Scene()
    scene.add(g.make_box((0, 0, 0), 10, 10, 10))
    scene.add(g.make_line((0, 0, 0), (10, 0, 0)))

    assert clip_plane_frames(scene.all()) == []


# --- the arrow itself ------------------------------------------------------

def _camera():
    cam = Camera()
    cam.target = np.array([0.0, 0.0, 0.0])
    cam.distance = 80.0
    return cam


def test_the_arrow_leaves_the_plane_along_its_normal():
    """The shaft is the first segment: it starts on the plane and ends out
    along the normal, and the barbs behind the tip make it an arrow rather
    than a line you have to guess the sense of."""
    frames = clip_plane_frames(_scene_with_plane().all())
    (segs, _color), = clip_normal_arrows(frames, _camera(), 800, 600)

    tail, tip = segs[0], segs[1]
    normal = np.asarray(frames[0][1], float)
    assert np.allclose(tail, frames[0][0], atol=1e-9)
    assert np.dot(tip - tail, normal) > 0
    assert len(segs) == 6                    # shaft, then two barbs


def test_the_arrow_is_the_same_size_on_screen_however_far_away_it_is():
    """Fixed on the glass, like the direction arrows and the control point
    markers. A plane at the far end of a big model should still be readable
    and a near one should not throw a spike across the viewport.

    Measured with the plane facing across the screen, where the shaft lies
    flat against the glass and its length in pixels is the whole story."""
    cam = _camera()
    right, _up = cam.right_up()
    lengths = []
    for distance in (40.0, 400.0):
        cam.distance = distance
        (segs, _), = clip_normal_arrows(
            [((0.0, 0.0, 0.0), tuple(right), True)], cam, 800, 600)
        scr = cam.project(np.asarray(segs[:2]), 800, 600)
        lengths.append(float(np.hypot(*(scr[1][:2] - scr[0][:2]))))

    assert lengths[0] == pytest.approx(CLIP_ARROW_PX, rel=0.02)
    assert lengths[1] == pytest.approx(CLIP_ARROW_PX, rel=0.02)


def test_a_paused_plane_gets_a_faint_arrow_drawn_under_the_live_ones():
    """Two passes, paused first, so where planes lie on top of each other
    the arrow you see is the one that is actually cutting."""
    scene = _scene_with_plane()
    paused = scene.add(_rect_on_xy(z=2.0), name="Clipping Plane 02")
    scene.update(paused.id, clip_plane={"enabled": False})

    passes = clip_normal_arrows(clip_plane_frames(scene.all()),
                                _camera(), 800, 600)

    assert [c for _s, c in passes] == [theme.CLIP_NORMAL_PAUSED,
                                       theme.CLIP_NORMAL]


def test_no_clipping_planes_means_no_arrows():
    assert clip_normal_arrows([], _camera(), 800, 600) == []


# --- the arrow and the cut are the same thing ------------------------------

@pytest.fixture
def pane():
    QApplication.instance() or QApplication([])
    scene = Scene()
    return Viewport(scene, SelectionManager(scene))


def test_the_cut_uses_the_direction_the_arrow_is_drawn_in(pane):
    """If these two ever came from different code, the arrow would point
    one way and the model would vanish the other, which is worse than
    drawing nothing."""
    face = _rect_on_xy()
    obj = pane.scene.add(face, name="Clipping Plane 01")
    pane.scene.update(obj.id, clip_plane={"enabled": True})

    frames = clip_plane_frames(pane.scene.visible_objects())
    expected = [clip_equation(o, n) for o, n, on in frames if on]

    assert np.allclose(pane._clip_vectors(), expected)


def test_a_paused_plane_cuts_nothing(pane):
    obj = pane.scene.add(_rect_on_xy(), name="Clipping Plane 01")
    pane.scene.update(obj.id, clip_plane={"enabled": False})

    assert clip_plane_frames(pane.scene.visible_objects()) != []
    assert pane._clip_vectors() == []
