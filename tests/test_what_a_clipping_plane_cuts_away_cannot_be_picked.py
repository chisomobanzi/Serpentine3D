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


def _plane(scene, origin=(0, 0, 0), **clip):
    """The world XY plane, taking away everything above it."""
    points = np.asarray([(-60, -60, 0), (60, -60, 0),
                         (60, 60, 0), (-60, 60, 0)], dtype=np.float64)
    rect = g.planar_face(g.make_polyline(
        points + np.asarray(origin, dtype=np.float64), closed=True))
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
    return vp._eye().project(np.asarray([point], float), vp.width(),
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


@pytest.mark.parametrize("origin", [(0.0, 0.0, 0.0),
                                    (5_000_000.0, 5_000_000.0, 5_000_000.0)])
@pytest.mark.parametrize("behind", [1.0, 0.001])
def test_a_survey_translation_does_not_make_hidden_scan_samples_pickable(
        pane, origin, behind):
    origin = np.asarray(origin, dtype=np.float64)
    pane.camera.target = origin.copy()
    hidden = origin + np.array((20.0, 0.0, behind), dtype=np.float64)
    boundary = origin + np.array((-20.0, 0.0, 0.0), dtype=np.float64)
    cloud = pane.scene.add(PointCloudShape([hidden, boundary]), name="Scan")
    assert cloud.id in _click(pane, hidden)
    assert cloud.id in _band(pane, hidden)
    _plane(pane.scene, origin=origin)
    assert cloud.id not in _click(pane, hidden)
    assert cloud.id not in _band(pane, hidden)
    assert cloud.id in _click(pane, boundary)
    assert cloud.id in _band(pane, boundary)
    assert cloud.id in _band(pane, boundary, crossing=False)


def test_a_paused_plane_leaves_scan_samples_pickable(pane, cloud):
    _plane(pane.scene, enabled=False)
    assert cloud.id in _click(pane, ABOVE)
    assert cloud.id in _band(pane, ABOVE)


def test_an_entered_detail_picks_scan_samples_with_its_own_plane_switch(
        pane, cloud):
    from serpentine3d.core import clipping
    from serpentine3d.core.layout import DetailView, Layout
    from serpentine3d.ui.camera import STANDARD_VIEWS

    az, el = STANDARD_VIEWS["front"]
    detail = DetailView(x=20, y=40, w=180, h=150, azimuth=az,
                        elevation=el, target=[0.0, 0.0, 0.0], scale_denom=1)
    layout = Layout(name="Sheet")
    layout.details.append(detail)
    pane.scene.layouts.append(layout)
    pane.set_space(layout.id)
    pane.layout_view.fit()
    pane.layout_view.entered_detail = detail.id

    assert cloud.id in _click(pane, ABOVE)
    plane = _plane(pane.scene, off_in=[pane.view_key])
    assert cloud.id not in _click(pane, ABOVE), \
        "the detail is still cut when the plane is off in the model pane"
    assert cloud.id not in _band(pane, ABOVE)
    assert cloud.id in _click(pane, BELOW)
    clipping.switch(pane.scene, plane.id, detail.id, False)
    assert cloud.id in _click(pane, ABOVE)
    assert cloud.id in _band(pane, ABOVE)
