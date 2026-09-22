"""A scan saved by the Mica engine opens, keeps its colours, and saves back.

The file a scan session leaves behind is a .serp: the same document a
drawing is, with the points in binary members under blobs/ and the camera
trajectories and session record as plain JSON beside them
(protocol/SERP-SESSION-RECORD.md in the Mica repository). A reader that
loses the colours, the layer, the trajectories or the session on the way
through has turned a record into a picture. A reader that opens a file
written for a newer version and fails deep inside a loop with a KeyError
has told the user nothing.

Files with no point clouds must keep writing version 2: nothing older
than this reader should notice this feature exists.
"""

from __future__ import annotations

import json
import zipfile

import numpy as np
import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.pointcloud import PointCloudShape
from serpentine3d.core.scene import Scene
from serpentine3d.fileio import export_file, import_file, native


def _cloud(n: int = 500, seed: int = 1, colour: bool = True,
           levels: bool = True) -> PointCloudShape:
    rng = np.random.default_rng(seed)
    xyz = rng.random((n, 3), dtype=np.float32) * np.float32(3.0)
    rgb = (rng.random((n, 3)) * 255).astype(np.uint8) if colour else None
    conf = rng.random(n, dtype=np.float32)
    level = rng.integers(0, 3, n).astype(np.uint8) if levels else None
    return PointCloudShape(xyz, rgb, conf, level,
                           provenance={"backbone": "lingbot",
                                       "scale": "metric"})


def _doc(path) -> dict:
    with zipfile.ZipFile(path) as z:
        return json.loads(z.read("document.json"))


def _meta(path) -> dict:
    with zipfile.ZipFile(path) as z:
        return json.loads(z.read("meta.json"))


# --- the object ------------------------------------------------------------

def test_a_point_cloud_added_to_a_scene_has_kind_pointcloud_and_reports_its_count():
    scene = Scene()
    obj = scene.add(_cloud(321), name="Scan")
    assert obj.kind == "pointcloud"
    assert obj.shape.count == 321
    assert g.shape_kind(obj.shape) == "pointcloud"


def test_a_point_cloud_measures_its_own_box():
    cloud = PointCloudShape([[0, 0, 0], [2, 3, 4], [1, 1, 1]])
    assert cloud.bbox() == ((0.0, 0.0, 0.0), (2.0, 3.0, 4.0))
    scene = Scene()
    obj = scene.add(cloud)
    assert obj.bbox() == ((0.0, 0.0, 0.0), (2.0, 3.0, 4.0))


def test_moving_a_point_cloud_moves_every_point_and_keeps_its_colours():
    cloud = _cloud(50)
    moved = g.translate(cloud, (1.0, 2.0, 3.0))
    assert np.allclose(moved.xyz, cloud.xyz + np.float32([1, 2, 3]))
    assert np.array_equal(moved.rgb, cloud.rgb)
    assert np.array_equal(moved.level, cloud.level)
    assert moved.provenance == cloud.provenance


def test_a_subset_by_level_keeps_the_coarse_points_only():
    cloud = _cloud(300)
    coarse = cloud.subset(0)
    assert coarse.count == int((cloud.level == 0).sum())
    assert (coarse.level == 0).all()
    assert _cloud(10, levels=False).subset(0).count == 10


def test_subsampling_keeps_an_even_fraction():
    cloud = _cloud(1000)
    thin = cloud.subsampled(0.25)
    assert thin.count == 250
    assert thin.rgb is not None and len(thin.rgb) == 250


def test_a_point_cloud_survives_the_shape_byte_round_trip_undo_and_paste_use():
    cloud = _cloud(64)
    back = g.shape_from_bytes(g.shape_to_bytes(cloud))
    assert np.array_equal(back.xyz, cloud.xyz)
    assert np.array_equal(back.rgb, cloud.rgb)
    assert np.array_equal(back.conf, cloud.conf)
    assert np.array_equal(back.level, cloud.level)


# --- the file ----------------------------------------------------------------

def test_saving_a_scene_with_a_point_cloud_writes_version_3_with_blobs_and_reloads_the_same(tmp_path):
    scene = Scene()
    layer = scene.layers.create("Scan", (0.2, 0.8, 0.3))
    cloud = _cloud(400)
    obj = scene.add(cloud, name="Kitchen", layer_id=layer.id)
    scene.update(obj.id, visible=False)
    path = str(tmp_path / "scan.serp")
    native.save_scene(scene, path)

    doc = _doc(path)
    assert doc["version"] == 3
    assert doc["requires"] == "0.9.0"
    assert doc["objects"] == [], "clouds live in their own list"
    entry = doc["pointclouds"][0]
    assert entry["count"] == 400
    assert entry["visible"] is False
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        for key in ("xyz", "rgb", "conf", "level"):
            assert entry["blobs"][key] in names
        raw = np.frombuffer(z.read(entry["blobs"]["xyz"]), "<f4")
        assert np.array_equal(raw.reshape(-1, 3), cloud.xyz)
    meta = _meta(path)
    assert meta["version"] == 3
    assert meta["pointclouds"] == 1 and meta["points"] == 400

    back = Scene()
    native.load_scene(back, path)
    got = back.all()
    assert len(got) == 1
    o = got[0]
    assert o.kind == "pointcloud"
    assert o.name == "Kitchen"
    assert back.layers.get(o.layer_id).name == "Scan"
    assert o.visible is False
    assert np.array_equal(o.shape.xyz, cloud.xyz)
    assert np.array_equal(o.shape.rgb, cloud.rgb)
    assert np.array_equal(o.shape.conf, cloud.conf)
    assert np.array_equal(o.shape.level, cloud.level)
    assert o.shape.provenance == cloud.provenance


def test_saving_a_scene_without_point_clouds_still_writes_version_2(tmp_path):
    scene = Scene()
    scene.add(g.make_line((0, 0, 0), (1, 0, 0)), name="Edge")
    path = str(tmp_path / "plain.serp")
    native.save_scene(scene, path)
    doc = _doc(path)
    assert doc["version"] == 2
    assert "requires" not in doc
    assert "pointclouds" not in doc
    assert "trajectories" not in doc
    meta = _meta(path)
    assert set(meta) == {"format", "version", "saved", "objects", "layouts"}
    with zipfile.ZipFile(path) as z:
        assert not any(n.startswith("blobs/") for n in z.namelist())


def test_loading_a_file_with_version_99_raises_the_needs_a_newer_serpentine_error(tmp_path):
    path = tmp_path / "future.serp"
    doc = {"format": "serpentine3d", "version": 99, "requires": "12.4.0",
           "layers": [], "objects": []}
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("meta.json", json.dumps({"format": "serpentine3d",
                                            "version": 99}))
        z.writestr("document.json", json.dumps(doc))
    scene = Scene()
    with pytest.raises(ValueError) as err:
        native.load_scene(scene, str(path))
    assert str(err.value) == "This file needs Serpentine3D 12.4.0 or newer"


def _spec_file(path, points: int = 200) -> tuple:
    """A v3 file written the way the engine writes one, straight from the
    spec with zipfile and numpy: nothing of Serpentine's own writer in it."""
    rng = np.random.default_rng(7)
    xyz = (rng.random((points, 3)) * 5).astype("<f4")
    rgb = (rng.random((points, 3)) * 255).astype(np.uint8)
    conf = rng.random(points).astype("<f4")
    level = rng.integers(0, 3, points).astype(np.uint8)
    frames = [{"t_ns": 1000 * i, "index": i,
               "c2w": [1.0, 0, 0, 0.1 * i, 0, 1.0, 0, 0,
                       0, 0, 1.0, 0, 0, 0, 0, 1.0],
               "vis": 0.9} for i in range(12)]
    pose_support = [
        {"t_ns": frame["t_ns"], "index": frame["index"],
         "status": "uncertain" if frame["index"] == 5 else "supported",
         "reasons": (["low_parallax"] if frame["index"] == 5 else []),
         "c2w": frame["c2w"]}
        for frame in frames
    ] + [{
        "t_ns": 12_000, "index": 12, "status": "untracked",
        "reasons": ["registration_failed"], "c2w": None,
    }]
    trajectories = [{
        "id": "traj-1", "name": "Wearer A", "layer": "scan", "visible": True,
        "stream": "stream-a",
        "intrinsics": [500.0, 0.0, 320.0, 0.0, 500.0, 240.0, 0.0, 0.0, 1.0],
        "image_size": [640, 480],
        "frames": frames,
        "pose_support": pose_support,
    }]
    session = {
        "id": "sess-42", "engine": "mica 0.3", "backbone": "lingbot-map",
        "backbone_licence": "Apache-2.0", "scale": "metric",
        "started": "2026-09-03T10:00:00", "ended": "2026-09-03T10:12:00",
        "streams": [{"id": "stream-a", "label": "A", "frames": 12,
                     "keyframes": 4, "visibility_min": 0.5,
                     "visibility_mean": 0.9}],
    }
    doc = {
        "format": "serpentine3d", "version": 3, "requires": "0.9.0",
        "units": "m",
        "layers": [
            {"id": "default", "name": "Default", "color": [0.8, 0.8, 0.8],
             "visible": True},
            {"id": "scan", "name": "Scan", "color": [0.1, 0.6, 0.9],
             "visible": True},
        ],
        "current_layer": "default",
        "objects": [],
        "pointclouds": [{
            "id": "pc-1", "name": "Room", "layer": "scan", "visible": False,
            "count": points,
            "bbox": [xyz.min(axis=0).tolist(), xyz.max(axis=0).tolist()],
            "blobs": {"xyz": "blobs/pc-1/xyz.f32",
                      "rgb": "blobs/pc-1/rgb.u8",
                      "conf": "blobs/pc-1/conf.f32",
                      "level": "blobs/pc-1/level.u8"},
            "provenance": {"session": "sess-42", "stream": "stream-a",
                           "backbone": "lingbot-map", "scale": "metric",
                           "created": "2026-09-03T10:12:00"},
        }],
        "trajectories": trajectories,
        "session": session,
    }
    meta = {"format": "serpentine3d", "version": 3,
            "saved": "2026-09-03T10:12:01", "objects": 0, "layouts": 0,
            "pointclouds": 1, "points": points, "trajectories": 1,
            "session": {"id": "sess-42", "engine": "mica 0.3",
                        "backbone": "lingbot-map"}}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("meta.json", json.dumps(meta))
        z.writestr("document.json", json.dumps(doc))
        z.writestr("blobs/pc-1/xyz.f32", xyz.tobytes())
        z.writestr("blobs/pc-1/rgb.u8", rgb.tobytes())
        z.writestr("blobs/pc-1/conf.f32", conf.tobytes())
        z.writestr("blobs/pc-1/level.u8", level.tobytes())
    return xyz, rgb, conf, level, trajectories, session


def test_a_v3_file_written_by_hand_from_the_spec_loads_and_round_trips_its_trajectories_and_session(tmp_path):
    path = str(tmp_path / "engine.serp")
    xyz, rgb, conf, level, trajectories, session = _spec_file(path)

    scene = Scene()
    opened = import_file(scene, path)
    assert opened == 2, "the scan and its visible camera route are scene objects"
    assert scene.units == "m"
    obj, = [item for item in scene.all() if item.kind == "pointcloud"]
    assert obj.kind == "pointcloud" and obj.name == "Room"
    assert scene.layers.get(obj.layer_id).name == "Scan"
    assert obj.visible is False
    assert np.array_equal(obj.shape.xyz, xyz)
    assert np.array_equal(obj.shape.rgb, rgb)
    assert np.array_equal(obj.shape.conf, conf)
    assert np.array_equal(obj.shape.level, level)
    assert obj.shape.provenance == {
        "session": "sess-42", "stream": "stream-a",
        "backbone": "lingbot-map", "scale": "metric",
        "created": "2026-09-03T10:12:00",
    }

    route, = [item for item in scene.all() if item.kind == "curve"]
    assert route.name == "Wearer A" and route.visible is True
    assert scene.layers.get(route.layer_id).name == "Scan"
    positions = [tuple(frame["c2w"][i] for i in (3, 7, 11))
                 for frame in trajectories[0]["frames"]]
    assert np.allclose(g.get_control_points(route.shape), positions)

    assert scene.trajectories == trajectories
    support = scene.trajectories[0]["pose_support"]
    assert {status: sum(item["status"] == status for item in support)
            for status in ("supported", "uncertain", "untracked")} == {
                "supported": 11, "uncertain": 1, "untracked": 1,
            }
    assert support[-1]["c2w"] is None
    assert support[-1]["reasons"] == ["registration_failed"]
    assert scene.session == session

    again = str(tmp_path / "again.serp")
    native.save_scene(scene, again)
    doc = _doc(again)
    assert doc["version"] == 3
    assert doc["trajectories"] == trajectories
    assert doc["session"] == session
    assert doc["pointclouds"][0]["provenance"]["session"] == "sess-42"
    assert _meta(again)["trajectories"] == 1
    assert _meta(again)["session"]["backbone"] == "lingbot-map"

    third = Scene()
    native.load_scene(third, again)
    assert third.trajectories == trajectories
    assert third.session == session
    cloud, = [item for item in third.all() if item.kind == "pointcloud"]
    assert np.array_equal(cloud.shape.rgb, rgb)


def test_a_mica_route_shows_uncertainty_and_breaks_at_an_untracked_pose(tmp_path):
    path = str(tmp_path / "route-with-gap.serp")
    _spec_file(path)
    with zipfile.ZipFile(path) as source:
        members = {name: source.read(name) for name in source.namelist()}
    doc = json.loads(members["document.json"])

    def pose_at(x):
        return [1.0, 0, 0, float(x), 0, 1.0, 0, 0,
                0, 0, 1.0, 0, 0, 0, 0, 1.0]

    valid_indices = [0, 1, 2, 3, 4, 5, 7, 8]
    trajectory = doc["trajectories"][0]
    trajectory["frames"] = [
        {"t_ns": 1000 * index, "index": index,
         "c2w": pose_at(index), "vis": 0.9}
        for index in valid_indices
    ]
    trajectory["pose_support"] = [
        {"t_ns": 1000 * index, "index": index,
         "status": ("untracked" if index == 6 else
                    "uncertain" if 2 <= index <= 4 else "supported"),
         "reasons": (["registration_failed"] if index == 6 else
                     ["weak_transition"] if 2 <= index <= 4 else []),
         "c2w": None if index == 6 else pose_at(index)}
        for index in range(9)
    ]
    expected_trajectory = json.loads(json.dumps(trajectory))
    members["document.json"] = json.dumps(doc).encode()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as target:
        for name, data in members.items():
            target.writestr(name, data)

    scene = Scene()
    opened = import_file(scene, path)
    routes = [item for item in scene.all() if item.kind == "curve"]
    assert opened == 1 + len(routes)
    assert routes and all(route.visible for route in routes)
    assert {scene.layers.get(route.layer_id).name for route in routes} == {"Scan"}
    assert scene.trajectories == [expected_trajectory]
    gap, = [item for item in scene.trajectories[0]["pose_support"]
            if item["index"] == 6]
    assert gap == {
        "t_ns": 6000, "index": 6, "status": "untracked",
        "reasons": ["registration_failed"], "c2w": None,
    }

    route_points = {
        route.id: np.asarray(g.get_control_points(route.shape), dtype=float)
        for route in routes
    }
    assert all(not ((points[:, 0] < 6).any() and (points[:, 0] > 6).any())
               for points in route_points.values()), \
        "a displayed route must stop at an untracked pose"

    uncertain = [route for route in routes
                 if "uncertain" in route.name.lower()]
    supported = [route for route in routes if route not in uncertain]
    assert uncertain, "the uncertain interval needs an identifiable route object"
    uncertain_x = {
        round(float(point[0]), 6)
        for route in uncertain for point in route_points[route.id]
    }
    assert {2.0, 3.0, 4.0}.issubset(uncertain_x)

    def appearance(route):
        colour = tuple(round(float(value), 6)
                       for value in scene.color_of(route))
        return colour, route.linetype

    assert supported
    assert ({appearance(route) for route in uncertain}
            .isdisjoint({appearance(route) for route in supported})), \
        "uncertain route geometry must look distinct from supported geometry"

    saved = str(tmp_path / "route-reopened.serp")
    native.save_scene(scene, saved)
    assert _doc(saved)["trajectories"] == [expected_trajectory]
    reopened = Scene()
    native.load_scene(reopened, saved)
    reopened_routes = [item for item in reopened.all() if item.kind == "curve"]
    assert len(reopened_routes) == len(routes)
    assert reopened.trajectories == [expected_trajectory]


def test_the_file_meta_says_how_many_points_without_loading_them(tmp_path):
    path = str(tmp_path / "engine.serp")
    _spec_file(path, points=333)
    meta = native.read_meta(path)
    assert meta["points"] == 333 and meta["pointclouds"] == 1


def test_a_new_scene_forgets_the_last_files_session(tmp_path):
    path = str(tmp_path / "engine.serp")
    _spec_file(path)
    scene = Scene()
    native.load_scene(scene, path)
    assert scene.session is not None
    scene.clear()
    assert scene.session is None and scene.trajectories == []


# --- PLY ---------------------------------------------------------------------

def test_ply_import_creates_a_point_cloud_and_ply_export_round_trips(tmp_path):
    scene = Scene()
    cloud = _cloud(250)
    scene.add(cloud, name="Scan")
    path = str(tmp_path / "scan.ply")
    assert export_file(scene, path) is None

    back = Scene()
    assert import_file(back, path) == 1
    obj = back.all()[0]
    assert obj.kind == "pointcloud"
    assert obj.name == "scan"
    assert np.array_equal(obj.shape.xyz, cloud.xyz)
    assert np.array_equal(obj.shape.rgb, cloud.rgb)
    assert np.allclose(obj.shape.conf, cloud.conf)
    assert np.array_equal(obj.shape.level, cloud.level)


def test_an_ascii_ply_from_another_tool_reads_too(tmp_path):
    path = tmp_path / "ascii.ply"
    path.write_text("\n".join([
        "ply", "format ascii 1.0", "comment made elsewhere",
        "element vertex 3",
        "property float x", "property float y", "property float z",
        "property uchar red", "property uchar green", "property uchar blue",
        "end_header",
        "0 0 0 255 0 0",
        "1 0 0 0 255 0",
        "0 1 2.5 0 0 255",
    ]) + "\n")
    scene = Scene()
    import_file(scene, str(path))
    cloud = scene.all()[0].shape
    assert cloud.count == 3
    assert np.allclose(cloud.xyz[2], [0, 1, 2.5])
    assert cloud.rgb.tolist() == [[255, 0, 0], [0, 255, 0], [0, 0, 255]]
    assert cloud.level is None


def test_a_ply_with_faces_is_refused_as_a_mesh_in_disguise(tmp_path):
    path = tmp_path / "mesh.ply"
    path.write_text("\n".join([
        "ply", "format ascii 1.0", "element vertex 3",
        "property float x", "property float y", "property float z",
        "element face 1", "property list uchar int vertex_indices",
        "end_header", "0 0 0", "1 0 0", "0 1 0", "3 0 1 2",
    ]) + "\n")
    with pytest.raises(ValueError, match="faces"):
        import_file(Scene(), str(path))


def test_exporting_a_scan_to_a_format_without_points_says_it_was_left_out(tmp_path):
    scene = Scene()
    scene.add(_cloud(30), name="Scan")
    scene.add(g.make_box((0, 0, 0), 1, 1, 1), name="Box")
    note = export_file(scene, str(tmp_path / "out.obj"))
    assert note and "point cloud" in note and "PLY" in note


# --- commands ----------------------------------------------------------------

def test_count_reports_points_as_well_as_objects(env):
    scene, selection, history, ctx, proc = env
    scene.add(_cloud(1234), name="Scan")
    scene.add(g.make_line((0, 0, 0), (1, 0, 0)), name="Edge")
    lines = []
    ctx.add_echo_listener(lines.append)
    proc.run("count")
    assert any("1× pointcloud" in line for line in lines)
    assert any("1,234" in line and "1 point cloud" in line for line in lines)
