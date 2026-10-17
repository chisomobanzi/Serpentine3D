"""Every kind of geometry, modelled and written out at survey coordinates.

The float32 story is told in test_far_geometry_keeps_its_precision.py and
test_a_far_scan_keeps_its_precision.py; this is the sweep that says it is
told everywhere. One 4mm feature on a model 360,000 units from the world's
origin, through each kind of shape, each way out of the program, and the
machinery that measures and picks: wherever it comes back a grid node
instead of a feature, something along the way cast to float32 or wrote too
few digits.

A millimetre at 300,000 units is 13 significant digits, which is inside
float64 and outside float32, so a path that keeps doubles passes these by
a wide margin, and one that does not fails them outright rather than by a
little. Formats whose own numbers are float32 (binary STL, glTF positions)
are checked for what they can hold: the shape, with where it stands moved
into the part of the format that can carry it.
"""

from __future__ import annotations

import numpy as np
import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.mesh import MeshShape
from serpentine3d.core.pointcloud import PointCloudShape
from serpentine3d.core.scene import Scene
from serpentine3d.core.tessellate import tessellate
from serpentine3d.fileio import export_file, import_file


FAR = np.array([300000.0, 200000.0, 0.0])
SIZE = 20.0             # the block the feature sits on
REVEAL = 0.004          # 4mm, well under float32's grid out at FAR


def _far_block(size=SIZE):
    return g.make_box(tuple(FAR), size, size, size)


def _span(points) -> np.ndarray:
    pts = np.asarray(points, float).reshape(-1, 3)
    return pts.max(axis=0) - pts.min(axis=0)


# -- the kernel ------------------------------------------------------------

def test_a_solid_far_out_keeps_its_size_and_volume():
    box = _far_block()
    mn, mx = g.bbox(box)
    assert np.abs(_span([mn, mx]) - SIZE).max() < 1e-6
    assert abs(g.volume(box) - SIZE ** 3) < 1e-3


def test_a_boolean_far_out_cuts_what_it_was_given():
    box = _far_block()
    hole = g.make_box(tuple(FAR + (5.0, 5.0, -1.0)), 2.0, 2.0, SIZE + 2.0)
    cut = g.boolean_difference(box, hole)
    assert abs(g.volume(cut) - (SIZE ** 3 - 2.0 * 2.0 * SIZE)) < 1e-3


def test_a_millimetre_fillet_far_out_is_a_millimetre_fillet():
    box = _far_block()
    edges = g.edges_of(box)
    rounded = g.fillet_edges(box, REVEAL, edges=[edges[0]])
    assert len(g.edges_of(rounded)) > len(edges)
    # A fillet removes a sliver along one edge; at 4mm that is a few
    # millionths of the block, which is only a number at all if the
    # kernel kept its digits out here.
    lost = SIZE ** 3 - g.volume(rounded)
    expected = (1 - np.pi / 4) * REVEAL ** 2 * SIZE
    assert abs(lost - expected) < expected * 0.05


def test_a_far_curve_measures_the_length_it_was_given():
    circle = g.make_circle(tuple(FAR), REVEAL, (0.0, 0.0, 1.0))
    assert abs(g.curve_length(circle) - 2 * np.pi * REVEAL) < 1e-9


# -- what the display is handed -------------------------------------------

def test_every_shape_kind_tessellates_without_losing_the_feature():
    reveal = g.make_box(tuple(FAR), REVEAL, REVEAL, REVEAL)
    mesh_shape = MeshShape(
        np.array([[0, 0, 0], [REVEAL, 0, 0], [REVEAL, REVEAL, 0]], float)
        + FAR, np.array([[0, 1, 2]], np.uint32))
    cloud = PointCloudShape(np.array([[0.0, 0.0, 0.0],
                                      [REVEAL, REVEAL, REVEAL]]) + FAR)
    for name, shape, want in (("solid", reveal, REVEAL),
                              ("mesh", mesh_shape, REVEAL),
                              ("cloud", cloud, REVEAL)):
        mesh = tessellate(shape)
        got = _span(mesh.vertices)
        assert np.abs(got[:2] - want).max() < 1e-7, name


def test_a_far_solid_and_a_near_one_give_the_same_shape():
    """The same box modelled at home and out at survey coordinates comes
    back the same to a micron, which is the whole claim in one line."""
    far = tessellate(g.make_box(tuple(FAR), REVEAL, REVEAL, REVEAL))
    near = tessellate(g.make_box((0.0, 0.0, 0.0), REVEAL, REVEAL, REVEAL))
    assert np.abs(_span(far.vertices) - _span(near.vertices)).max() < 1e-9


def test_text_and_a_hatch_are_drawn_where_they_were_put():
    """Both are built as curves about a point someone chose, so both read
    the model's own coordinates wherever that point is."""
    from serpentine3d.core.hatch import HatchShape
    from serpentine3d.core.text_object import TextShape

    label = TextShape("A", 2.0, origin=tuple(FAR))
    marks = tessellate(label)
    drawn = np.concatenate([marks.vertices.reshape(-1, 3),
                            marks.edge_segments.reshape(-1, 3)])
    assert np.abs(drawn.min(axis=0)[:2] - FAR[:2]).max() < 4.0

    square = [g.make_polyline([tuple(FAR), tuple(FAR + (4, 0, 0)),
                               tuple(FAR + (4, 4, 0)), tuple(FAR + (0, 4, 0))],
                              closed=True)]
    (face,) = g.planar_regions(square)
    hatch = HatchShape(face, "lines", angle=0.0, spacing=1.0)
    segs = hatch.pattern_segments()
    assert len(segs) == 4
    for a, b in segs:
        assert abs(float(a[1]) - float(b[1])) < 1e-9       # level lines
        assert abs(float(b[0]) - float(a[0]) - 4.0) < 1e-6  # full width


# -- measuring, snapping, picking ------------------------------------------

def test_the_camera_frames_a_far_model_and_projects_it_steadily():
    from serpentine3d.ui.camera import Camera
    box = _far_block()
    cam = Camera()
    cam.zoom_extents(g.bbox(box), 1.6)
    assert np.abs(cam.target - (FAR + SIZE / 2)).max() < SIZE
    corner = (FAR + (SIZE, SIZE, SIZE))[None, :]
    on_screen = cam.project(corner, 1600, 1000)
    assert np.isfinite(on_screen).all()
    assert 0 <= on_screen[0, 0] <= 1600 and 0 <= on_screen[0, 1] <= 1000


def test_a_ray_hits_a_far_triangle_where_it_should():
    from serpentine3d.utils.math3d import ray_triangle_hits
    tri = np.array([[[0.0, 0.0, 0.0], [REVEAL, 0.0, 0.0],
                     [0.0, REVEAL, 0.0]]]) + FAR
    origin = FAR + (REVEAL / 4, REVEAL / 4, 5.0)
    hits = ray_triangle_hits(origin, np.array([0.0, 0.0, -1.0]),
                             tri[:, 0], tri[:, 1], tri[:, 2])
    assert np.isfinite(hits).any()
    assert abs(float(np.nanmin(hits[np.isfinite(hits)])) - 5.0) < 1e-6


def test_snapping_to_a_far_scan_answers_in_world_coordinates():
    from serpentine3d.core.snaps import SnapIndex
    from serpentine3d.ui.camera import Camera
    pts = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]) + FAR
    scene = Scene()
    obj = scene.add(PointCloudShape(pts), name="Station")
    cam = Camera()
    cam.zoom_extents(obj.shape.bbox(), 1.6)
    screen = cam.project(pts[:1], 800, 600)
    engine = SnapIndex(scene)
    hit = engine._cloud_point(obj, cam, float(screen[0, 0]),
                              float(screen[0, 1]), 800, 600, 12.0)
    assert hit is not None
    assert np.abs(np.asarray(hit) - pts[0]).max() < 1e-3


def test_a_detail_on_a_sheet_shows_a_far_feature_at_its_scale():
    """A sheet reaches the model through its detail's camera, which is
    where the model's own numbers are last seen."""
    from serpentine3d.core.layout import DetailView
    from serpentine3d.ui.layout_view import DetailEye

    detail = DetailView(target=list(FAR), scale_denom=2.0)
    eye = DetailEye(None, detail)
    paper = eye.to_paper(np.array([FAR, FAR + (REVEAL, 0.0, 0.0)]))
    assert abs(abs(paper[1, 0] - paper[0, 0]) - REVEAL / 2.0) < 1e-9


# -- out of the program and back in ----------------------------------------

def _round_trip(tmp_path, suffix, shape, name="Block"):
    scene = Scene()
    scene.add(shape, name=name)
    path = str(tmp_path / f"far{suffix}")
    export_file(scene, path)
    back = Scene()
    import_file(back, path)
    objs = back.all()
    assert objs, f"nothing came back from {suffix}"
    return objs


@pytest.mark.parametrize("suffix", [".serp", ".step", ".obj", ".fbx"])
def test_a_far_feature_survives_the_round_trip(tmp_path, suffix):
    """A 4mm box 360,000 units out, written and read back."""
    shape = g.make_box(tuple(FAR), REVEAL, REVEAL, REVEAL)
    objs = _round_trip(tmp_path, suffix, shape)
    span = _span(tessellate(objs[0].shape).vertices)
    assert np.abs(span - REVEAL).max() < 1e-6, f"{suffix} came back {span}"


@pytest.mark.parametrize("suffix", [".3dm", ".stl"])
def test_a_single_precision_format_says_what_it_will_do(tmp_path, suffix):
    """A Rhino mesh's vertices and an STL's floats are float32 whatever we
    hand them, so a far model is rounded there however careful this
    program is. The export says so rather than quietly flattening it."""
    scene = Scene()
    scene.add(g.make_box(tuple(FAR), REVEAL, REVEAL, REVEAL), name="Reveal")
    note = export_file(scene, str(tmp_path / f"far{suffix}"))
    assert note and "single precision" in note and "STEP" in note


@pytest.mark.parametrize("suffix", [".3dm", ".stl"])
def test_the_same_formats_say_nothing_about_a_model_at_home(tmp_path, suffix):
    scene = Scene()
    scene.add(g.make_box((0.0, 0.0, 0.0), 10.0, 10.0, 10.0), name="Block")
    assert export_file(scene, str(tmp_path / f"near{suffix}")) is None


def test_a_far_mesh_object_survives_the_native_file(tmp_path):
    """Mesh objects go into .serp as their own blob, which was float32."""
    verts = np.array([[0, 0, 0], [REVEAL, 0, 0], [REVEAL, REVEAL, 0],
                      [0, REVEAL, 0]], float) + FAR
    mesh = MeshShape(verts, np.array([[0, 1, 2], [0, 2, 3]], np.uint32))
    objs = _round_trip(tmp_path, ".serp", mesh, name="Scan mesh")
    back = objs[0].shape.vertices
    assert np.abs(back - verts).max() < 1e-6


def test_a_far_model_exports_to_text_formats_with_enough_digits(tmp_path):
    """OBJ and 3MF write the model's own coordinates as text, and six or
    eight significant digits put a survey model on a decimetre grid. (USD
    writes its points relative instead, since its point3f is float32
    whatever the text says; see the placement test below.)"""
    shape = g.make_box(tuple(FAR), REVEAL, REVEAL, REVEAL)
    scene = Scene()
    scene.add(shape, name="Reveal")
    for suffix in (".obj", ".3mf"):
        path = str(tmp_path / f"far{suffix}")
        export_file(scene, path)
        if suffix == ".3mf":
            import zipfile
            with zipfile.ZipFile(path) as z:
                text = z.read("3D/3dmodel.model").decode("utf-8")
        else:
            text = open(path, encoding="utf-8").read()
        numbers = [float(tok.strip("(),\"x=yz<vertex/>"))
                   for tok in text.replace(",", " ").split()
                   if tok.strip("(),\"x=yz<vertex/>").replace(".", "")
                   .replace("-", "").replace("e", "").isdigit()]
        near_far = [v for v in numbers if abs(v - FAR[0]) < 1.0]
        assert near_far, f"{suffix} wrote no x coordinate near the model"
        # The feature is 4mm wide, so the written values must differ by
        # that much rather than all landing on the same number.
        assert max(near_far) - min(near_far) > REVEAL * 0.9, \
            f"{suffix} rounded the feature away"


def test_a_far_mesh_in_a_glb_keeps_its_shape_and_is_placed_by_its_node(
        tmp_path):
    """glTF positions are float32 by the spec, so a far mesh is written
    about its own origin with the node carrying where it stands."""
    import json
    import struct

    shape = g.make_box(tuple(FAR), REVEAL, REVEAL, REVEAL)
    scene = Scene()
    scene.add(shape, name="Reveal")
    path = str(tmp_path / "far.glb")
    export_file(scene, path)
    with open(path, "rb") as f:
        data = f.read()
    length = struct.unpack("<I", data[12:16])[0]
    doc = json.loads(data[20:20 + length])
    node = doc["nodes"][0]
    assert "translation" in node, "a far mesh was left at absolute float32"
    # Y-up: the model's x and y become x and -z.
    assert abs(node["translation"][0] - FAR[0]) < 1.0
    acc = doc["accessors"][0]
    span = np.asarray(acc["max"]) - np.asarray(acc["min"])
    assert np.abs(np.sort(span)[-2:] - REVEAL).max() < 1e-6


def test_a_far_mesh_in_a_usda_is_placed_by_a_translate_op(tmp_path):
    """USD's point3f is float32 like glTF's positions, so a far mesh is
    written about its own origin with a double3 op saying where it is."""
    scene = Scene()
    scene.add(g.make_box(tuple(FAR), REVEAL, REVEAL, REVEAL), name="Reveal")
    path = str(tmp_path / "far.usda")
    export_file(scene, path)
    text = open(path, encoding="utf-8").read()
    assert "xformOp:translate" in text, "a far mesh was left at absolute point3f"
    op = text.split("xformOp:translate = (")[1].split(")")[0]
    assert abs(float(op.split(",")[0]) - FAR[0]) < 1.0
    first = text.split("point3f[] points = [(")[1].split(")")[0]
    assert abs(float(first.split(",")[0])) < 1.0


def test_a_usda_at_home_has_no_placement(tmp_path):
    scene = Scene()
    scene.add(g.make_box((0.0, 0.0, 0.0), 10.0, 10.0, 10.0), name="Block")
    path = str(tmp_path / "near.usda")
    export_file(scene, path)
    assert "xformOp" not in open(path, encoding="utf-8").read()


def test_a_far_curve_survives_dxf(tmp_path):
    """DXF carries the model's own coordinates, which is what a survey
    drawing is exchanged in."""
    circle = g.make_circle(tuple(FAR), REVEAL, (0.0, 0.0, 1.0))
    objs = _round_trip(tmp_path, ".dxf", circle, name="Reveal")
    assert abs(g.curve_length(objs[0].shape) - 2 * np.pi * REVEAL) < 1e-7


def test_a_far_scan_exports_to_ply_and_comes_back(tmp_path):
    pts = np.array([[0.0, 0.0, 0.0], [REVEAL, REVEAL, REVEAL]]) + FAR
    scene = Scene()
    scene.add(PointCloudShape(pts), name="Station")
    path = str(tmp_path / "far.ply")
    export_file(scene, path)
    back = Scene()
    import_file(back, path)
    got = back.all()[0].shape
    assert np.abs(got.xyz - pts).max() < 1e-6
