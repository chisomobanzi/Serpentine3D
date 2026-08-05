"""Points on should look like points on, and a band should catch them.

Two complaints, one cause each. The markers were two arms along world X and
world Y, which is a cross only when you happen to be looking down Z: from
anywhere near the horizon both arms lie edge-on and the marker collapses into
the curve it is sitting on, in white, on a white curve. And the rubber band
only ever asked which objects it had caught, so a rectangle dragged round a
row of vertices selected the curve they belong to and never the vertices.

The drawing itself cannot be exercised here — calling a viewport's GL path
from an offscreen test takes the whole run down with it — so the markers are
tested through the geometry they are built from, and the band through the
pick that decides what it caught.
"""

from __future__ import annotations

import inspect

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui import theme
from serpentine3d.ui.viewport import (CV_MARK_PX, Viewport, cv_marker_outline,
                                      cv_marker_quads, cv_marker_size)


@pytest.fixture
def vp():
    QApplication.instance() or QApplication([])
    scene = Scene()
    sel = SelectionManager(scene)
    v = Viewport(scene, sel)
    v.resize(800, 600)
    return v


def _polyline(vp, points=((0.0, 0.0, 0.0), (10.0, 0.0, 0.0),
                          (20.0, 0.0, 0.0), (30.0, 0.0, 0.0))):
    """A curve laid across a top view, with its points turned on."""
    obj = vp.scene.add(g.make_polyline([tuple(p) for p in points]))
    vp.cv_enabled.add(obj.id)
    vp.camera.set_standard_view("top")
    vp.camera.target = np.array([15.0, 0.0, 0.0])
    vp.camera.distance = 40.0
    return obj


def _screen(vp, obj):
    return vp.camera.project(vp._cv_points(obj), vp.width(), vp.height())


def _band_round(vp, obj, indices, pad=6.0):
    """A rectangle just big enough to hold those control points."""
    scr = _screen(vp, obj)[list(indices), :2]
    return (scr[:, 0].min() - pad, scr[:, 1].min() - pad,
            scr[:, 0].max() + pad, scr[:, 1].max() + pad)


# -- what a marker looks like ------------------------------------------------

def _extent(pts):
    """(width, height) of some world points once they are on the screen."""
    return np.ptp(pts[:, 0]), np.ptp(pts[:, 1])


def test_a_marker_keeps_its_shape_seen_from_the_side(vp):
    """The old cross was world X and Y, so a front view flattened it."""
    vp.camera.set_standard_view("front")
    vp.camera.distance = 40.0
    pts = np.array([[0.0, 0.0, 0.0]])
    right, up = vp.camera.right_up()
    half = cv_marker_size(pts, vp.camera, 800, 600, CV_MARK_PX)
    quad = cv_marker_quads(pts, right, up, half)
    scr = vp.camera.project(quad, 800, 600)
    w, h = _extent(scr)
    assert w == pytest.approx(2 * CV_MARK_PX, abs=0.5)
    assert h == pytest.approx(2 * CV_MARK_PX, abs=0.5)


def test_a_marker_is_the_same_size_however_far_off_it_is(vp):
    """Near and far points get the same square, not a big one and a speck."""
    vp.camera.projection = "perspective"
    vp.camera.target = np.zeros(3)
    vp.camera.distance = 50.0
    right, up = vp.camera.right_up()
    fwd = vp.camera.target - vp.camera.position
    fwd = fwd / np.linalg.norm(fwd)
    pts = np.stack([vp.camera.position + fwd * 20.0,
                    vp.camera.position + fwd * 90.0])
    half = cv_marker_size(pts, vp.camera, 800, 600, CV_MARK_PX)
    assert half[1] > half[0] * 2, "the far one needs a bigger world size"
    quads = cv_marker_quads(pts, right, up, half).reshape(2, 6, 3)
    for one in quads:
        w, h = _extent(vp.camera.project(one, 800, 600))
        assert w == pytest.approx(2 * CV_MARK_PX, abs=0.6)
        assert h == pytest.approx(2 * CV_MARK_PX, abs=0.6)


def test_a_marker_is_a_solid_square_with_a_border_round_it(vp):
    pts = np.zeros((3, 3))
    right, up = vp.camera.right_up()
    half = np.full(3, 0.5)
    assert len(cv_marker_quads(pts, right, up, half)) == 3 * 6
    assert len(cv_marker_outline(pts, right, up, half)) == 3 * 8


def test_control_points_are_not_drawn_in_the_colour_of_the_curve():
    """White markers on a white curve are markers you cannot see."""
    assert min(theme.CONTROL_POINT[:3]) < 0.7, "still near-white"
    assert theme.CONTROL_POINT[:3] != theme.SELECTION_COLOR[:3]


def test_the_drawing_uses_the_screen_facing_markers():
    src = inspect.getsource(Viewport._draw_control_points)
    assert "cv_marker_quads" in src
    assert "theme.CONTROL_POINT" in src
    assert "np.eye(3" not in src, "still building arms from world axes"


# -- what a band catches -----------------------------------------------------

def test_a_band_round_some_vertices_takes_exactly_those(vp):
    obj = _polyline(vp)
    band = _band_round(vp, obj, [1, 2])
    assert vp._band_pick(*band, False, Qt.KeyboardModifier.NoModifier) is None
    assert sorted(vp.selection.subobjects_of(obj.id, "cv")) == [1, 2]


def test_dragging_the_band_the_other_way_takes_them_too(vp):
    """A point has no extent, so crossing and window are the same thing."""
    obj = _polyline(vp)
    x0, y0, x1, y1 = _band_round(vp, obj, [0, 1])
    vp._band_pick(x1, y1, x0, y0, True, Qt.KeyboardModifier.NoModifier)
    assert sorted(vp.selection.subobjects_of(obj.id, "cv")) == [0, 1]


def test_taking_points_lets_go_of_the_curve_they_belong_to(vp):
    obj = _polyline(vp)
    vp.selection.set([obj.id])
    vp._band_pick(*_band_round(vp, obj, [3]),
                  False, Qt.KeyboardModifier.NoModifier)
    assert vp.selection.ids == []
    assert vp.selection.subobjects_of(obj.id, "cv") == [3]


def test_shift_adds_to_the_points_already_held(vp):
    obj = _polyline(vp)
    vp._band_pick(*_band_round(vp, obj, [0]),
                  False, Qt.KeyboardModifier.NoModifier)
    vp._band_pick(*_band_round(vp, obj, [2, 3]),
                  False, Qt.KeyboardModifier.ShiftModifier)
    assert sorted(vp.selection.subobjects_of(obj.id, "cv")) == [0, 2, 3]


def test_ctrl_takes_points_back_out_again(vp):
    obj = _polyline(vp)
    vp._band_pick(*_band_round(vp, obj, [0, 1, 2, 3]),
                  False, Qt.KeyboardModifier.NoModifier)
    vp._band_pick(*_band_round(vp, obj, [1, 2]),
                  False, Qt.KeyboardModifier.ControlModifier)
    assert sorted(vp.selection.subobjects_of(obj.id, "cv")) == [0, 3]


def test_a_band_that_catches_no_points_still_catches_objects(vp):
    obj = _polyline(vp)
    box = vp.scene.add(g.make_box((100.0, 100.0, 0.0), 5.0, 5.0, 5.0))
    band = _band_round(vp, obj, [0, 1, 2, 3])
    band = (band[0], band[1] - 400.0, band[2], band[3] - 300.0)
    ids = vp._band_pick(*band, True, Qt.KeyboardModifier.NoModifier)
    assert ids is not None, "it took points it never caught"
    assert box.id not in ids and obj.id not in ids


def test_a_band_never_takes_the_points_of_a_curve_with_points_off(vp):
    obj = _polyline(vp)
    vp.cv_enabled.clear()
    ids = vp._band_pick(*_band_round(vp, obj, [1, 2]),
                        True, Qt.KeyboardModifier.NoModifier)
    assert ids == [obj.id]
    assert vp.selection.subobjects == []
