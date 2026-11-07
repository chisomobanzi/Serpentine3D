"""What a clipping plane takes away cannot be snapped to.

A clipping plane hides the half of the model it cuts away, and nothing
you cannot see should catch the cursor: not the end of a curve, not the
corner of a solid, not a point, a scan sample or the outline of a mesh.
A curve the plane cuts through still snaps along the part left in sight,
and where the plane cuts through a curve, the edge of a solid or of a
mesh is an intersection, offered under Int like any other. The planes are the ones cutting the view you pick in, so a plane
switched off in a pane leaves everything there snapping as before.
"""

from __future__ import annotations

import numpy as np
import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.mesh import MeshShape
from serpentine3d.core.pointcloud import PointCloudShape
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.core.snaps import SNAP_TYPES, SnapIndex
from serpentine3d.ui.camera import Camera
from serpentine3d.ui.viewport import Viewport, clip_equation

SIZE = (900, 700)
# The world XY plane, taking away everything above it.
CUT_ABOVE = [clip_equation((0, 0, 0), (0, 0, 1))]


def _front():
    cam = Camera()
    cam.set_standard_view("front")
    cam.target = np.zeros(3)
    cam.distance = 80.0
    return cam


def _find(index, cam, point, clip=CUT_ABOVE, offset=(0, 0)):
    px, py = cam.project(np.asarray([point], float), *SIZE)[0, :2] + offset
    return index.find(cam, px, py, *SIZE, clip=clip)


def _only(*kinds):
    return {k: k in kinds for k in SNAP_TYPES}


def test_the_end_of_a_curve_above_the_plane_does_not_snap():
    scene, cam = Scene(), _front()
    scene.add(g.make_line((0, 0, -10), (0, 0, 10)))
    index = SnapIndex(scene)
    assert _find(index, cam, (0, 0, 10), clip=())[1] == "end"
    assert _find(index, cam, (0, 0, 10)) is None
    below = _find(index, cam, (0, 0, -10))
    assert below[1] == "end"
    assert below[0] == pytest.approx((0, 0, -10))


def test_a_point_and_a_solid_above_the_plane_do_not_snap():
    scene, cam = Scene(), _front()
    scene.add(g.make_point((-15, 0, 6)))
    scene.add(g.make_box((5, -2, 2), 8, 4, 8))
    index = SnapIndex(scene)
    assert _find(index, cam, (-15, 0, 6), clip=())[1] == "point"
    assert _find(index, cam, (-15, 0, 6)) is None
    assert _find(index, cam, (5, -2, 10), clip=())[1] == "end"
    assert _find(index, cam, (5, -2, 10)) is None
    assert _find(index, cam, (9, -2, 2)) is None


def test_a_corner_lying_in_the_plane_still_snaps():
    scene, cam = Scene(), _front()
    scene.add(g.make_box((5, -2, 0), 8, 4, 8))
    hit = _find(SnapIndex(scene), cam, (5, -2, 0))
    assert hit is not None and hit[1] == "end"


def test_an_intersection_above_the_plane_does_not_snap():
    scene, cam = Scene(), _front()
    scene.add(g.make_line((-10, 0, 5), (10, 0, 5)))
    scene.add(g.make_line((0, 0, -5), (0, 0, 15)))
    index = SnapIndex(scene)
    index.types = _only("int")
    assert _find(index, cam, (0, 0, 5), clip=())[1] == "int"
    assert _find(index, cam, (0, 0, 5)) is None


def test_near_slides_only_along_what_is_left_in_sight():
    scene, cam = Scene(), _front()
    scene.add(g.make_line((-10, 0, -10), (10, 0, 10)))
    index = SnapIndex(scene)
    index.types = _only("near")
    assert _find(index, cam, (5, 0, 5), clip=())[1] == "near"
    assert _find(index, cam, (5, 0, 5)) is None
    hit = _find(index, cam, (-5, 0, -5))
    assert hit[1] == "near"
    assert hit[0] == pytest.approx((-5, 0, -5), abs=0.5)
    # The cursor just above the cut: what it lands on is the cut end.
    hit = _find(index, cam, (0.2, 0, 0.2))
    assert hit is not None and hit[0][2] <= 1e-6


def test_an_apparent_crossing_above_the_plane_does_not_snap():
    scene, cam = Scene(), _front()
    scene.add(g.make_line((-10, -5, 5), (10, -5, 5)))
    scene.add(g.make_line((0, 5, -5), (0, 5, 15)))
    index = SnapIndex(scene)
    index.types = _only("appint")
    assert _find(index, cam, (0, 0, 5), clip=())[1] == "appint"
    assert _find(index, cam, (0, 0, 5)) is None


def test_scan_samples_above_the_plane_do_not_snap():
    scene, cam = Scene(), _front()
    scene.add(PointCloudShape([(3, 0, 4), (3, 4, -4)]))
    index = SnapIndex(scene)
    assert _find(index, cam, (3, 0, 4), clip=())[1] == "point"
    assert _find(index, cam, (3, 0, 4)) is None
    hit = _find(index, cam, (3, 4, -4))
    assert hit[1] == "point"
    assert hit[0] == pytest.approx((3, 4, -4))


def test_the_outline_of_a_mesh_above_the_plane_does_not_snap():
    scene, cam = Scene(), _front()
    scene.add(MeshShape([[0, 0, 2], [10, 0, 2], [10, 0, 9], [0, 0, 9]],
                        [[0, 1, 2], [0, 2, 3]]))
    index = SnapIndex(scene)
    index.types = _only("near")
    assert _find(index, cam, (10, 0, 5), clip=())[1] == "near"
    assert _find(index, cam, (10, 0, 5)) is None


# --- where the plane cuts through ---------------------------------------------

def test_where_the_plane_cuts_a_curve_snaps_as_an_intersection():
    scene, cam = Scene(), _front()
    scene.add(g.make_line((-4, 0, -10), (16, 0, 10)))
    index = SnapIndex(scene)
    index.types = _only("int")
    assert _find(index, cam, (6, 0, 0), clip=()) is None
    hit = _find(index, cam, (6, 0, 0), offset=(4, -3))
    assert hit[1] == "int"
    assert hit[0] == pytest.approx((6, 0, 0), abs=1e-6)


def test_where_the_plane_cuts_the_edges_of_a_solid_snaps():
    scene, cam = Scene(), _front()
    scene.add(g.make_box((5, -2, -4), 8, 4, 8))
    index = SnapIndex(scene)
    index.types = _only("int")
    hit = _find(index, cam, (13, -2, 0))
    assert hit[1] == "int"
    assert hit[0] == pytest.approx((13, -2, 0), abs=1e-6)


def test_where_the_plane_cuts_the_edges_of_a_mesh_snaps():
    scene, cam = Scene(), _front()
    scene.add(MeshShape([[0, 0, -4], [10, 0, -4], [10, 0, 6], [0, 0, 6]],
                        [[0, 1, 2], [0, 2, 3]]))
    index = SnapIndex(scene)
    index.types = _only("int")
    hit = _find(index, cam, (10, 0, 0))
    assert hit[1] == "int"
    assert hit[0] == pytest.approx((10, 0, 0), abs=1e-6)


def test_a_cut_cut_away_by_another_plane_does_not_snap():
    scene, cam = Scene(), _front()
    scene.add(g.make_line((-4, 0, -10), (16, 0, 10)))
    index = SnapIndex(scene)
    index.types = _only("int")
    cut_right = clip_equation((0, 0, 0), (1, 0, 0))
    assert _find(index, cam, (6, 0, 0), clip=[*CUT_ABOVE, cut_right]) is None


# --- in a pane ---------------------------------------------------------------

def _plane(scene, **clip):
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


def _pick(vp, point):
    px, py = vp.camera.project(np.asarray([point], float), vp.width(),
                               vp.height())[0, :2]
    vp.world_point_at(px, py)
    return vp._active_snap


def test_a_pane_a_plane_cuts_does_not_snap_to_what_it_cut_away(pane):
    pane.scene.add(g.make_line((20, 0, -10), (20, 0, 10)))
    assert _pick(pane, (20, 0, 10))[1] == "end"
    plane = _plane(pane.scene)
    assert _pick(pane, (20, 0, 10)) is None
    assert _pick(pane, (20, 0, -10))[1] == "end"
    pane.scene.update(plane.id, visible=False)
    assert _pick(pane, (20, 0, 10)) is None, \
        "a hidden plane still cuts, so it still keeps the snap away"
    pane.scene.update(plane.id, clip_plane={"enabled": False})
    assert _pick(pane, (20, 0, 10))[1] == "end"


def test_a_plane_switched_off_in_the_pane_leaves_it_snapping(pane):
    pane.scene.add(g.make_line((20, 0, -10), (20, 0, 10)))
    _plane(pane.scene, off_in=[pane.view_key])
    assert _pick(pane, (20, 0, 10))[1] == "end"
