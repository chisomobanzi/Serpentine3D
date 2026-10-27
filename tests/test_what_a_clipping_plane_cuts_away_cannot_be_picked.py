"""A scan sample a clipping plane cut away cannot be picked.

A click where a clipping plane has taken a scan's points away selected
the scan all the same: the pick looked at every point, in sight or not.
It now looks only at the points the view's planes leave, for a click and
for a band alike, and a plane switched off in the view cuts nothing.
"""

from __future__ import annotations

import numpy as np
import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.pointcloud import PointCloudShape
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui.viewport import Viewport

SIZE = (900, 700)
ABOVE, BELOW = (10, 0, 8), (-10, 0, -8)


def _plane(scene, **clip):
    """The world XY plane, taking away everything above it."""
    rect = g.planar_face(g.make_polyline(
        [(-60, -60, 0), (60, -60, 0), (60, 60, 0), (-60, 60, 0)],
        closed=True))
    obj = scene.add(rect, name="Clip")
    scene.update(obj.id, clip_plane={"enabled": True, **clip})
    return obj


@pytest.fixture
def pane(_qapp):
    scene = Scene()
    vp = Viewport(scene, SelectionManager(scene))
    vp.resize(*SIZE)
    vp.set_view("front")
    vp.camera.target = np.zeros(3)
    vp.camera.distance = 80.0
    return vp


@pytest.fixture
def cloud(pane):
    return pane.scene.add(PointCloudShape([ABOVE, BELOW]), name="Scan")


def _px(vp, point):
    return vp.camera.project(np.asarray([point], float), vp.width(),
                             vp.height())[0, :2]


def _click(vp, point):
    return vp.pick_objects(*_px(vp, point))


def _band(vp, point, crossing=True):
    x, y = _px(vp, point)
    return vp._box_pick(x - 10, y - 10, x + 10, y + 10, crossing)


def test_a_click_where_the_plane_took_the_points_away_picks_nothing(
        pane, cloud):
    assert cloud.id in _click(pane, ABOVE)
    _plane(pane.scene)
    assert cloud.id not in _click(pane, ABOVE)
    assert cloud.id in _click(pane, BELOW)


def test_a_band_over_points_cut_away_catches_nothing(pane, cloud):
    assert cloud.id in _band(pane, ABOVE)
    _plane(pane.scene)
    assert cloud.id not in _band(pane, ABOVE)
    assert cloud.id in _band(pane, BELOW)


def test_a_window_needs_only_the_points_left_in_sight(pane, cloud):
    assert cloud.id not in _band(pane, BELOW, crossing=False)
    _plane(pane.scene)
    assert cloud.id in _band(pane, BELOW, crossing=False)


def test_a_plane_switched_off_in_the_pane_leaves_the_points_pickable(
        pane, cloud):
    _plane(pane.scene, off_in=[pane.view_key])
    assert cloud.id in _click(pane, ABOVE)
