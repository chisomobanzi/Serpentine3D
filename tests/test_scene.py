import numpy as np
import pytest

from serpentine.core import geometry as g
from serpentine.core.history import History
from serpentine.core.scene import Scene
from serpentine.core.tessellate import tessellate


def test_tessellate_solid():
    box = g.make_box((0, 0, 0), 10, 10, 10)
    mesh = tessellate(box)
    assert mesh.has_faces
    assert len(mesh.vertices) >= 8
    assert len(mesh.triangles) >= 12
    assert len(mesh.edge_segments) >= 12
    assert mesh.normals.shape == mesh.vertices.shape
    # normals are unit length
    lens = np.linalg.norm(mesh.normals, axis=1)
    assert np.allclose(lens, 1.0, atol=1e-5)


def test_tessellate_curve():
    circle = g.make_circle((0, 0, 0), 5)
    mesh = tessellate(circle)
    assert not mesh.has_faces
    assert len(mesh.edge_segments) > 8
    # all segment points lie on radius 5 in XY
    pts = mesh.edge_segments.reshape(-1, 3)
    radii = np.linalg.norm(pts[:, :2], axis=1)
    assert np.allclose(radii, 5.0, atol=0.05)


def test_tessellate_surface():
    line = g.make_line((0, 0, 0), (10, 0, 0))
    srf = g.extrude(line, (0, 0, 1), 5)
    mesh = tessellate(srf)
    assert mesh.has_faces


def test_scene_add_and_naming():
    scene = Scene()
    o1 = scene.add(g.make_line((0, 0, 0), (1, 0, 0)))
    o2 = scene.add(g.make_line((0, 0, 0), (2, 0, 0)))
    assert o1.name == "Curve 01"
    assert o2.name == "Curve 02"
    assert scene.get(o1.id) is o1
    assert scene.find_by_name("curve 02") is o2


def test_scene_visibility_and_layers():
    scene = Scene()
    obj = scene.add(g.make_box((0, 0, 0), 1, 1, 1))
    layer = scene.layers.create("Walls")
    scene.update(obj.id, layer_id=layer.id)
    assert len(scene.visible_objects()) == 1
    scene.layers.set_visible(layer.id, False)
    assert len(scene.visible_objects()) == 0
    scene.layers.set_visible(layer.id, True)
    scene.update(obj.id, visible=False)
    assert len(scene.visible_objects()) == 0


def test_scene_color_resolution():
    scene = Scene()
    obj = scene.add(g.make_box((0, 0, 0), 1, 1, 1))
    assert scene.color_of(obj) == scene.layers.current.color
    obj = scene.update(obj.id, color=(1.0, 0.0, 0.0))
    assert scene.color_of(obj) == (1.0, 0.0, 0.0)


def test_scene_bbox():
    scene = Scene()
    scene.add(g.make_box((0, 0, 0), 1, 1, 1))
    scene.add(g.make_box((5, 5, 5), 1, 1, 1))
    mn, mx = scene.bbox()
    assert mx == pytest.approx((6, 6, 6))


def test_undo_redo():
    scene = Scene()
    hist = History(scene)

    hist.checkpoint("add box")
    scene.add(g.make_box((0, 0, 0), 1, 1, 1), name="Box A")
    assert len(scene.all()) == 1

    hist.checkpoint("add sphere")
    scene.add(g.make_sphere((5, 0, 0), 1), name="Ball")
    assert len(scene.all()) == 2

    assert hist.undo() == "add sphere"
    assert len(scene.all()) == 1
    assert scene.all()[0].name == "Box A"

    assert hist.redo() == "add sphere"
    assert len(scene.all()) == 2

    hist.undo()
    hist.undo()
    assert len(scene.all()) == 0
    assert not hist.can_undo


def test_undo_survives_in_place_update():
    scene = Scene()
    hist = History(scene)
    obj = scene.add(g.make_box((0, 0, 0), 1, 1, 1), name="Original")
    hist.checkpoint("rename")
    scene.update(obj.id, name="Renamed")
    assert scene.get(obj.id).name == "Renamed"
    hist.undo()
    assert scene.get(obj.id).name == "Original"


def test_undo_layers():
    scene = Scene()
    hist = History(scene)
    hist.checkpoint("new layer")
    layer = scene.layers.create("Walls")
    assert scene.layers.find_by_name("Walls")
    hist.undo()
    assert scene.layers.find_by_name("Walls") is None
    hist.redo()
    assert scene.layers.find_by_name("Walls")


def test_replace_shape_invalidates_mesh():
    scene = Scene()
    obj = scene.add(g.make_box((0, 0, 0), 1, 1, 1))
    m1 = obj.mesh
    assert m1.has_faces
    obj2 = scene.replace_shape(obj.id, g.make_box((0, 0, 0), 2, 2, 2))
    assert obj2.mesh is not m1


def test_native_mesh_objects(tmp_path):
    import numpy as np
    from serpentine import fileio
    from serpentine.core.mesh import MeshShape, brep_from_mesh

    # unit cube mesh
    v = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
                  [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]], float)
    t = np.array([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7],
                  [0, 1, 5], [0, 5, 4], [2, 3, 7], [2, 7, 6],
                  [1, 2, 6], [1, 6, 5], [3, 0, 4], [3, 4, 7]], np.uint32)
    m = MeshShape(v, t)
    assert g.volume(m) == pytest.approx(1.0)
    assert g.surface_area(m) == pytest.approx(6.0)

    scene = Scene()
    obj = scene.add(m, name="Cube mesh")
    assert obj.kind == "mesh"
    dm = obj.mesh
    assert dm.has_faces and len(dm.edge_segments) == 12   # feature edges

    # transforms dispatch
    moved = g.translate(m, (5, 0, 0))
    assert g.bbox(moved)[0][0] == pytest.approx(5)
    rot = g.rotate(m, (0, 0, 0), (0, 0, 1), 90)
    assert g.volume(rot) == pytest.approx(1.0)
    mir = g.mirror(m, (0, 0, 0), (1, 0, 0))
    assert g.volume(mir) == pytest.approx(1.0)

    # native save/load round trip
    path = str(tmp_path / "meshes.serp")
    fileio.export_file(scene, path)
    loaded = Scene()
    fileio.import_file(loaded, path)
    assert loaded.all()[0].kind == "mesh"
    assert g.volume(loaded.all()[0].shape) == pytest.approx(1.0)

    # exports that tessellate work on meshes
    fileio.export_file(scene, str(tmp_path / "m.glb"))
    fileio.export_file(scene, str(tmp_path / "m.usda"))
    fileio.export_file(scene, str(tmp_path / "m.obj"))

    # to brep and back
    shell = brep_from_mesh(m)
    assert g.shape_kind(shell) in ("surface", "solid")


def test_obj_import_is_mesh(tmp_path):
    from serpentine import fileio
    p = str(tmp_path / "tri.obj")
    with open(p, "w") as f:
        f.write("o T\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
    scene = Scene()
    fileio.import_file(scene, p)
    assert scene.all()[0].kind == "mesh"
