"""Points on, then take hold of one of them.

Turning a polyline's points on drew them and let you fling one about with the
mouse, and that was the whole of it. Clicking a point selected nothing, so
there was nothing for the gumball to anchor to: it stayed where it was, on the
whole curve, and the only way to move a corner was a free drag in the plane of
the screen. No axis, no typed distance, no way to move two corners together.

A control point you have clicked is a picked thing like any other. It goes in
the selection, the gumball comes to it, and its arrows move that point and
leave the rest of the curve where it is.
"""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui.gumball import SCALE_POS, SHAFT0, CONE1
from serpentine3d.ui.viewport import Viewport

CORNERS = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 10.0, 0.0),
           (20.0, 10.0, 0.0)]
SHIFT = Qt.KeyboardModifier.ShiftModifier
NONE = Qt.KeyboardModifier.NoModifier


@pytest.fixture
def pane():
    """A pane looking down on a polyline with its control points on."""
    QApplication.instance() or QApplication([])
    scene = Scene()
    vp = Viewport(scene, SelectionManager(scene))
    vp.resize(800, 600)
    vp.set_view("top")
    vp.grid_snap = False
    obj = scene.add(g.make_polyline(CORNERS))
    vp.camera.target = np.array([10.0, 5.0, 0.0])
    vp.camera.distance = 60.0
    vp.cv_enabled.add(obj.id)
    return vp, obj


def _near(a, b, tol=1e-6):
    return np.allclose(np.asarray(a, float), np.asarray(b, float), atol=tol)


def _points(vp, obj):
    return np.asarray(g.get_control_points(vp.scene.get(obj.id).shape), float)


def _screen(vp, pt):
    scr = vp.camera.project(np.asarray([pt], float), vp.width(), vp.height())
    return float(scr[0][0]), float(scr[0][1])


def _at(vp, obj, index):
    """The pixel a control point is drawn on."""
    return _screen(vp, _points(vp, obj)[index])


def _press(vp, x, y, mods=NONE):
    vp.mousePressEvent(QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(x, y), QPointF(x, y),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, mods))


def _click(vp, x, y, mods=NONE):
    """Press and let go again, the way a click actually arrives."""
    _press(vp, x, y, mods)
    vp.mouseReleaseEvent(QMouseEvent(
        QEvent.Type.MouseButtonRelease, QPointF(x, y), QPointF(x, y),
        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, mods))


def _drag_to(vp, x, y):
    vp.mouseMoveEvent(QMouseEvent(
        QEvent.Type.MouseMove, QPointF(x, y), QPointF(x, y),
        Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, NONE))


def _cvs(vp):
    return [(oid, i) for (oid, kind, i) in vp.selection.subobjects
            if kind == "cv"]


def _take(vp, handle):
    """Take hold of a gumball handle where it is drawn."""
    gb = vp.gumball
    anchor, axes = gb.anchor_and_axes()
    reach = {"move": (SHAFT0 + CONE1) / 2, "scale": SCALE_POS}[handle[0]]
    at = anchor + axes[handle[1]] * reach * gb._size_world(anchor)
    px, py = _screen(vp, at)
    assert gb.begin_drag(handle, px, py, NONE), "the handle refused the drag"
    return gb


# -- clicking one --

def test_clicking_a_control_point_picks_it(pane):
    vp, obj = pane
    _click(vp, *_at(vp, obj, 1))
    assert _cvs(vp) == [(obj.id, 1)]


def test_picking_a_point_lets_go_of_the_curve(pane):
    """The point is what you are editing now, not the whole polyline, and a
    gumball holding both would move the curve as well as the corner."""
    vp, obj = pane
    vp.selection.set([obj.id])
    _click(vp, *_at(vp, obj, 1))
    assert vp.selection.ids == []


def test_shift_takes_a_second_point(pane):
    vp, obj = pane
    _click(vp, *_at(vp, obj, 1))
    _click(vp, *_at(vp, obj, 2), mods=SHIFT)
    assert sorted(_cvs(vp)) == [(obj.id, 1), (obj.id, 2)]


def test_shift_on_a_point_already_picked_lets_it_go(pane):
    vp, obj = pane
    _click(vp, *_at(vp, obj, 1))
    _click(vp, *_at(vp, obj, 2), mods=SHIFT)
    _click(vp, *_at(vp, obj, 1), mods=SHIFT)
    assert _cvs(vp) == [(obj.id, 2)]


def test_clicking_another_point_replaces_the_first(pane):
    vp, obj = pane
    _click(vp, *_at(vp, obj, 1))
    _click(vp, *_at(vp, obj, 3))
    assert _cvs(vp) == [(obj.id, 3)]


def test_clicking_away_from_them_all_picks_nothing(pane):
    vp, obj = pane
    _click(vp, *_at(vp, obj, 1))
    _click(vp, 5.0, 5.0)
    assert vp._cv_drag is None


# -- and the gumball coming to it --

def test_the_gumball_comes_up_for_a_control_point(pane):
    vp, obj = pane
    assert not vp.gumball.active(), "nothing picked yet"
    _click(vp, *_at(vp, obj, 1))
    assert vp.gumball.active()


def test_the_gumball_sits_on_the_point_it_holds(pane):
    vp, obj = pane
    _click(vp, *_at(vp, obj, 1))
    anchor, _axes = vp.gumball.anchor_and_axes()
    assert _near(anchor, CORNERS[1])


def test_two_points_put_the_gumball_between_them(pane):
    vp, obj = pane
    _click(vp, *_at(vp, obj, 1))
    _click(vp, *_at(vp, obj, 2), mods=SHIFT)
    anchor, _axes = vp.gumball.anchor_and_axes()
    assert _near(anchor, np.mean([CORNERS[1], CORNERS[2]], axis=0))


def test_points_off_takes_the_gumball_with_them(pane):
    """A point nobody can see is not a thing you can still be holding."""
    vp, obj = pane
    _click(vp, *_at(vp, obj, 1))
    vp.cv_enabled.clear()
    assert not vp.gumball.active()


# -- moving the point with it --

def test_an_arrow_moves_the_point_and_leaves_the_rest(pane):
    vp, obj = pane
    _click(vp, *_at(vp, obj, 1))
    _take(vp, ("move", 1)).apply_scalar(-4.0)
    pts = _points(vp, obj)
    assert _near(pts[1], (10.0, -4.0, 0.0))
    assert _near(pts[0], CORNERS[0]) and _near(pts[2], CORNERS[2])
    assert _near(pts[3], CORNERS[3])


def test_the_polyline_is_still_one_curve_afterwards(pane):
    vp, obj = pane
    _click(vp, *_at(vp, obj, 1))
    _take(vp, ("move", 1)).apply_scalar(-4.0)
    shape = vp.scene.get(obj.id).shape
    assert len(g.edges_of(shape)) == len(CORNERS) - 1
    assert len(g.get_control_points(shape)) == len(CORNERS)


def test_two_points_move_together(pane):
    vp, obj = pane
    _click(vp, *_at(vp, obj, 1))
    _click(vp, *_at(vp, obj, 2), mods=SHIFT)
    _take(vp, ("move", 0)).apply_scalar(3.0)
    pts = _points(vp, obj)
    assert _near(pts[1], (13.0, 0.0, 0.0)) and _near(pts[2], (13.0, 10.0, 0.0))
    assert _near(pts[0], CORNERS[0]) and _near(pts[3], CORNERS[3])


def test_dragging_back_to_where_it_started_leaves_the_curve_alone(pane):
    """Each step of a drag is measured from the curve as it was found, so
    running the mouse out and back does not walk the point away."""
    vp, obj = pane
    _click(vp, *_at(vp, obj, 1))
    gb = _take(vp, ("move", 1))
    gb.apply_scalar(-4.0)
    gb.apply_scalar(0.0)
    assert _near(_points(vp, obj), CORNERS)


def test_scaling_moves_the_points_it_holds(pane):
    vp, obj = pane
    _click(vp, *_at(vp, obj, 1))
    _click(vp, *_at(vp, obj, 2), mods=SHIFT)
    gb = _take(vp, ("scale", 0))
    gb.apply_scalar(2.0, uniform=True)
    mid = np.mean([CORNERS[1], CORNERS[2]], axis=0)
    pts = _points(vp, obj)
    for i in (1, 2):
        assert _near(pts[i], mid + (np.asarray(CORNERS[i]) - mid) * 2.0)
    assert _near(pts[0], CORNERS[0]) and _near(pts[3], CORNERS[3])


def test_turning_the_point_about_the_gumball_moves_only_it(pane):
    vp, obj = pane
    _click(vp, *_at(vp, obj, 1))
    _click(vp, *_at(vp, obj, 2), mods=SHIFT)
    _take(vp, ("move", 0))              # any handle, to open the drag
    vp.gumball.drag["handle"] = ("rot", 2)
    vp.gumball.apply_scalar(90.0)
    mid = np.mean([CORNERS[1], CORNERS[2]], axis=0)
    pts = _points(vp, obj)
    assert _near(pts[1], mid + (5.0, 0.0, 0.0)) and abs(pts[1][2]) < 1e-6
    assert _near(pts[0], CORNERS[0]) and _near(pts[3], CORNERS[3])


# -- without taking away the drag that already worked --

def test_the_point_can_still_be_dragged_by_itself(pane):
    vp, obj = pane
    x, y = _at(vp, obj, 1)
    _press(vp, x, y)
    assert vp._cv_drag is not None, "the press did not arm a drag"
    _drag_to(vp, x, y - 40.0)
    pts = _points(vp, obj)
    assert pts[1][1] > 1.0, "the corner did not follow the mouse"
    assert _near(pts[0], CORNERS[0]) and _near(pts[2], CORNERS[2])
