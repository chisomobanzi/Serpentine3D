"""Object snaps follow a transform, not just the shape under it.

A move rides on the object as a matrix, so every candidate — an end, an
intersection, a perpendicular foot, a scan sample — is only an answer at
the place the matrix puts it. The local shape stays where it was made.
"""

import numpy as np
import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.pointcloud import PointCloudShape
from serpentine3d.core.scene import Scene
from serpentine3d.core.snaps import SnapIndex, _intersections
from serpentine3d.ui.camera import Camera


def camera(view="top", target=(0.0, 0.0, 0.0), distance=60.0):
    cam = Camera()
    cam.set_standard_view(view)
    cam.target = np.asarray(target, float)
    cam.distance = distance
    return cam


def pixel(cam, point, size=(900, 700)):
    return cam.project(np.asarray([point], float), *size)[0, :2]


def hit(idx, cam, point, offset=(0, 0), size=(900, 700)):
    px, py = pixel(cam, point, size) + offset
    return idx.find(cam, px, py, *size)


def translation(x, y, z):
    m = np.eye(4)
    m[:3, 3] = (x, y, z)
    return m


def test_end_snap_of_a_moved_line_lands_where_it_stands():
    scene = Scene()
    line = scene.add(g.make_line((0, 0, 0), (10, 0, 0)))
    scene.set_transforms({line.id: translation(50.0, 0.0, 0.0)})
    cam = camera("top", target=(55.0, 0.0, 0.0))
    idx = SnapIndex(scene)
    # the endpoint is offered where the matrix stands the line, at
    # (60, 0, 0), not where the shape was drawn, at (10, 0, 0)
    got = hit(idx, cam, (60.0, 0.0, 0.0))
    assert got is not None and got[1] == "end"
    assert got[0] == pytest.approx((60.0, 0.0, 0.0), abs=1e-6)
    assert hit(idx, cam, (10.0, 0.0, 0.0)) is None


def test_mid_snap_of_a_rotated_line_follows_the_rotation():
    scene = Scene()
    line = scene.add(g.make_line((0, 0, 0), (10, 0, 0)))
    m = np.eye(4)
    c, s = np.cos(np.pi / 2), np.sin(np.pi / 2)
    m[:2, :2] = ((c, -s), (s, c))            # 90deg about Z, about the origin
    scene.set_transforms({line.id: m})
    cam = camera("top")
    idx = SnapIndex(scene)
    # the midpoint is (5,0,0) in the shape's own frame and (0,5,0)
    # where the rotation puts it
    got = hit(idx, cam, (0.0, 5.0, 0.0))
    assert got is not None and got[1] == "mid"
    assert got[0] == pytest.approx((0.0, 5.0, 0.0), abs=1e-6)


def test_intersection_snap_runs_in_world():
    scene = Scene()
    a = scene.add(g.make_line((0, 0, 0), (10, 0, 0)))
    b = scene.add(g.make_line((50, -5, 0), (50, 5, 0)))
    # locally the two lines are forty units apart; the matrix puts them
    # together at (50, 0, 0), where the only answer is one
    scene.set_transforms({a.id: translation(50.0, 0.0, 0.0)})
    pts = _intersections(scene.all())
    assert any(abs(p[0] - 50.0) < 1e-6 and abs(p[1]) < 1e-6 for p in pts)
    # and pulling the matrix back apart removes the answer again
    scene.set_transforms({a.id: translation(100.0, 0.0, 0.0)})
    assert _intersections(scene.all()) == []


def test_perp_foot_of_a_moved_curve_is_in_world():
    scene = Scene()
    line = scene.add(g.make_line((0, 0, 0), (10, 0, 0)))
    scene.set_transforms({line.id: translation(50.0, 0.0, 0.0)})
    idx = SnapIndex(scene)
    feet = idx._perp_feet(scene.visible_objects(), (55.0, 5.0, 0.0))
    assert any(abs(p[0] - 55.0) < 1e-6 and abs(p[1]) < 1e-6 for p in feet)


def test_near_snap_of_a_moved_solid_lands_where_it_stands():
    scene = Scene()
    box = scene.add(g.make_box((0, 0, 0), 2, 2, 2))
    scene.set_transforms({box.id: translation(30.0, 20.0, 0.0)})
    cam = camera("top", target=(31.0, 21.0, 0.0), distance=30.0)
    idx = SnapIndex(scene)
    for t in idx.types:
        idx.types[t] = t == "near"
    # aim at the middle of the front top edge, where the outline of the
    # box actually is, not at its face centre an edge away
    got = hit(idx, cam, (31.0, 20.0, 0.0))
    assert got is not None and got[1] == "near"
    x, y, z = got[0]
    assert x == pytest.approx(31.0, abs=1e-3)
    assert y == pytest.approx(20.0, abs=1e-3)
    assert -1e-3 <= z <= 2.0 + 1e-3
    # and the local frame, four units away in both axes, offers nothing
    assert hit(idx, cam, (1.0, 1.0, 0.0)) is None


def test_point_snap_of_a_moved_cloud_lands_where_it_stands():
    scene = Scene()
    cloud = scene.add(PointCloudShape([(10, 2, 7), (12, 9, 7)]))
    scene.set_transforms({cloud.id: translation(0.0, 100.0, 0.0)})
    cam = camera("right", target=(0.0, 105.5, 7.0))
    idx = SnapIndex(scene)
    got = hit(idx, cam, (10.0, 102.0, 7.0))
    assert got is not None and got[1] == "point"
    assert got[0] == pytest.approx((10.0, 102.0, 7.0), abs=1e-6)
    assert hit(idx, cam, (10.0, 2.0, 7.0)) is None
