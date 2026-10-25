"""A scan at survey coordinates is a scan, not a set of lines.

float32 steps 3cm at half a million units and a quarter of a metre at a
UTM northing. A cloud stored in absolute float32 out there has its points
snapped onto the grid's planes: 2000 samples spread over half a metre
came back as 98 distinct x values, which on screen is lines. The anchor
in the viewport cannot help, because the digits were gone before it saw
them.

So a cloud keeps its points as float32 offsets from a float64 origin near
it, which is what the container stores too: the blob stays float32 and
the entry carries the origin beside it. A cloud near the world's origin
has an origin of zero and is byte for byte what it always was.
"""

from __future__ import annotations

import numpy as np

from serpentine3d.core.geometry import shape_from_bytes, shape_to_bytes
from serpentine3d.core.pointcloud import PointCloudShape, cloud_to_display


FAR = np.array([500000.0, 4000000.0, 10.0])


def _far_cloud(n=2000, spread=0.5, seed=0):
    rng = np.random.default_rng(seed)
    pts = rng.normal(0.0, spread, (n, 3)) + FAR
    rgb = np.full((n, 3), 128, np.uint8)
    return PointCloudShape(pts, rgb), pts


# -- how a far cloud is held ----------------------------------------------

def test_a_far_scan_is_kept_about_an_origin_near_it():
    cloud, pts = _far_cloud()
    assert cloud.far
    assert np.abs(cloud.origin - FAR).max() < 2.0
    assert cloud.local.dtype == np.float32
    assert np.abs(cloud.local).max() < 10.0


def test_the_points_come_back_where_they_were_put():
    cloud, pts = _far_cloud()
    assert np.abs(cloud.xyz - pts).max() < 1e-5


def test_the_old_absolute_float32_lost_them():
    """The bug itself, in numbers: the grid swallows the spread."""
    _cloud, pts = _far_cloud()
    old = pts.astype(np.float32)
    assert len(np.unique(old[:, 1])) < len(pts) / 10, \
        "float32 holds this scan out here, so this test guards nothing"


def test_a_scan_near_home_carries_no_origin_at_all():
    cloud = PointCloudShape(np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]))
    assert not cloud.far
    assert np.array_equal(cloud.origin, np.zeros(3))
    assert cloud.xyz.dtype == np.float32
    assert cloud.xyz is cloud.local          # no copy on the common path


def test_count_and_bounds_read_the_world_not_the_offsets():
    cloud, pts = _far_cloud()
    assert cloud.count == len(pts)
    mn, mx = cloud.bbox()
    assert np.abs(np.asarray(mn) - pts.min(axis=0)).max() < 1e-5
    assert np.abs(np.asarray(mx) - pts.max(axis=0)).max() < 1e-5
    assert np.abs(np.asarray(cloud.centroid()) - pts.mean(axis=0)).max() < 1e-5


# -- transforms keep the origin with them ----------------------------------

def test_moving_a_far_scan_moves_its_origin_not_its_points():
    cloud, pts = _far_cloud()
    moved = cloud.translated((1.0, 2.0, 3.0))
    assert moved.far
    assert np.array_equal(moved.local, cloud.local)
    assert np.abs(moved.xyz - (pts + (1.0, 2.0, 3.0))).max() < 1e-5


def test_turning_a_far_scan_turns_it_about_its_own_middle():
    cloud, pts = _far_cloud()
    quarter = np.array([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
    turned = cloud.transformed(quarter)
    assert np.abs(turned.xyz - pts @ quarter.T).max() < 1e-4


def test_a_scan_brought_home_stops_carrying_an_origin():
    cloud, pts = _far_cloud()
    home = cloud.translated(-cloud.origin)
    assert not home.far
    assert np.abs(home.xyz - (pts - cloud.origin)).max() < 1e-5


def test_a_subset_of_a_far_scan_stays_where_it_was():
    cloud, pts = _far_cloud()
    half = cloud.subsampled(0.5)
    assert half.far and np.array_equal(half.origin, cloud.origin)
    assert np.abs(half.xyz - pts[::2][:len(half.local)]).max() < 10.0


def test_a_copy_is_the_same_scan():
    cloud, _pts = _far_cloud()
    twin = cloud.copy()
    assert np.array_equal(twin.local, cloud.local)
    assert np.array_equal(twin.origin, cloud.origin)


# -- what reaches the screen ----------------------------------------------

def test_the_display_mesh_is_in_world_coordinates_and_keeps_the_detail():
    cloud, pts = _far_cloud()
    dm = cloud_to_display(cloud)
    assert dm.is_cloud
    assert dm.vertices.dtype == np.float64
    assert np.abs(dm.vertices - pts).max() < 1e-5


def test_a_near_scans_display_mesh_is_the_float32_it_always_was():
    cloud = PointCloudShape(np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]))
    dm = cloud_to_display(cloud)
    assert dm.vertices.dtype == np.float32


def test_the_card_gets_small_numbers_that_still_hold_the_spread():
    from serpentine3d.ui import viewport as vp
    cloud, pts = _far_cloud()
    dm = cloud_to_display(cloud)
    anchor = vp.mesh_anchor(dm)
    assert anchor is not None
    rel = vp.rebased(dm.vertices, anchor)
    assert rel.dtype == np.float32
    spread = rel.astype(np.float64).max(axis=0) - rel.astype(np.float64).min(axis=0)
    true_spread = pts.max(axis=0) - pts.min(axis=0)
    assert np.abs(spread - true_spread).max() < 1e-4


# -- and through the session record ----------------------------------------

def test_an_undo_record_carries_the_origin_through():
    cloud, pts = _far_cloud(n=50)
    back = shape_from_bytes(shape_to_bytes(cloud))
    assert back.far
    assert np.array_equal(back.origin, cloud.origin)
    assert np.array_equal(back.local, cloud.local)
    assert np.abs(back.xyz - pts).max() < 1e-5


def test_a_far_scan_saved_and_reopened_is_still_a_scan(tmp_path):
    """The whole point of the origin living in the file: a quarter of a
    metre of rounding on save would put the lines straight back."""
    import json
    import zipfile

    from serpentine3d.core.scene import Scene
    from serpentine3d.fileio import native

    cloud, pts = _far_cloud(n=400)
    scene = Scene()
    scene.add(cloud, name="Station 1")
    path = str(tmp_path / "survey.serp")
    native.save_scene(scene, path)

    with zipfile.ZipFile(path) as z:
        doc = json.loads(z.read("document.json"))
        entry = doc["pointclouds"][0]
        assert np.abs(np.asarray(entry["origin"]) - cloud.origin).max() == 0.0
        raw = np.frombuffer(z.read(entry["blobs"]["xyz"]), "<f4")
        assert np.array_equal(raw.reshape(-1, 3), cloud.local)

    back = Scene()
    native.load_scene(back, path)
    shape = back.all()[0].shape
    assert shape.far
    assert np.array_equal(shape.origin, cloud.origin)
    assert np.abs(shape.xyz - pts).max() < 1e-5


def test_a_file_of_near_scans_carries_no_origin_field(tmp_path):
    import json
    import zipfile

    from serpentine3d.core.scene import Scene
    from serpentine3d.fileio import native

    scene = Scene()
    scene.add(PointCloudShape(np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])))
    path = str(tmp_path / "room.serp")
    native.save_scene(scene, path)
    with zipfile.ZipFile(path) as z:
        doc = json.loads(z.read("document.json"))
    assert "origin" not in doc["pointclouds"][0]


def test_an_old_file_without_an_origin_still_opens_where_it_was():
    """Its points are absolute, which is how they were written."""
    cloud = PointCloudShape(np.array([[2.0, 3.0, 4.0]], np.float32))
    assert not cloud.far
    assert np.array_equal(cloud.xyz, [[2.0, 3.0, 4.0]])


def test_a_record_of_a_near_scan_is_unchanged():
    cloud = PointCloudShape(np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]),
                            level=np.array([0, 1], np.uint8))
    back = shape_from_bytes(shape_to_bytes(cloud))
    assert not back.far
    assert np.array_equal(back.xyz, cloud.xyz)
    assert np.array_equal(back.level, cloud.level)
