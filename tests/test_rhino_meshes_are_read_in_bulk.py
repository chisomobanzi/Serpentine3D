"""A Rhino mesh is read from its file in one go, not a vertex at a time.

rhino3dm has no bulk accessor, so a mesh was read one Python object per
vertex and per face. The meshes an import puts off reading, those on hidden
layers, are read when the drawing is first saved: for one film set, 13
million vertices and two minutes. A .3dm keeps a mesh's faces as a packed
array and its vertices as a compressed buffer, so they are read from the
file, and must come out exactly as the per-element read gave them.
"""
from pathlib import Path

import numpy as np
import pytest
import rhino3dm as r3

from serpentine3d.fileio import rhino, rhino_mesh_records as records

DATA = Path(__file__).parent / "data"


def _one_at_a_time(mesh):
    verts = np.array([[v.X, v.Y, v.Z] for v in mesh.Vertices], float)
    faces = np.array([tuple(f) for f in mesh.Faces], np.int64).reshape(-1, 4)
    return verts, faces


def _strip(count):
    """`count` vertices in a wavy strip, triangles and quads between them."""
    mesh = r3.Mesh()
    for i in range(count):
        mesh.Vertices.Add(i * 0.37, (i % 2) * 1.5, np.sin(i * 0.1))
    for i in range(0, count - 3, 2):
        if i % 4:
            mesh.Faces.AddFace(i, i + 1, i + 3, i + 2)
        else:
            mesh.Faces.AddFace(i, i + 1, i + 2)
    return mesh


@pytest.fixture
def strips(tmp_path):
    """A file of three meshes, small enough for byte, short and int
    indices, with a line between two of them."""
    model = r3.File3dm()
    model.Objects.AddMesh(_strip(40))
    model.Objects.AddLine(r3.Point3d(0, 0, 0), r3.Point3d(1, 0, 0))
    model.Objects.AddMesh(_strip(3000))
    model.Objects.AddMesh(_strip(70000))
    path = str(tmp_path / "strips.3dm")
    assert model.Write(path, 8)
    return path


def _every_mesh_matches(path):
    model = r3.File3dm.Read(path)
    meshes = 0
    for index, obj in enumerate(model.Objects):
        found = records.mesh_arrays_at(path, index)
        if not isinstance(obj.Geometry, r3.Mesh):
            assert found is None, index
            continue
        meshes += 1
        assert found is not None, index
        verts, faces = found
        want_verts, want_faces = _one_at_a_time(obj.Geometry)
        np.testing.assert_array_equal(verts, want_verts)
        np.testing.assert_array_equal(faces, want_faces)
    return meshes


def test_meshes_read_from_the_file_as_they_do_element_by_element(strips):
    assert _every_mesh_matches(strips) == 3


def test_a_file_rhino_wrote_reads_the_same_way():
    """McNeel's openNURBS example meshes, among breps, curves and text."""
    assert _every_mesh_matches(str(DATA / "rhino_layout_page.3dm")) == 7


def test_a_file_too_old_to_follow_is_left_to_rhino3dm(tmp_path):
    model = r3.File3dm()
    model.Objects.AddMesh(_strip(40))
    path = str(tmp_path / "v4.3dm")
    assert model.Write(path, 4)
    assert records.mesh_arrays_at(path, 0) is None


def test_a_file_that_changed_since_it_was_scanned_is_scanned_again(strips):
    first = records.mesh_arrays_at(strips, 0)
    model = r3.File3dm()
    model.Objects.AddMesh(_strip(300))
    assert model.Write(strips, 8)
    again = records.mesh_arrays_at(strips, 0)
    assert len(again[0]) == 300 != len(first[0])


def test_the_converted_mesh_is_the_same_either_way(strips):
    model = r3.File3dm.Read(strips)
    mesh = model.Objects[3].Geometry
    fast = rhino._r3_mesh_to_shape(mesh,
                                   arrays=records.mesh_arrays_at(strips, 3))
    slow = rhino._r3_mesh_to_shape(mesh)
    np.testing.assert_array_equal(fast.vertices, slow.vertices)
    np.testing.assert_array_equal(fast.triangles, slow.triangles)


def test_arrays_for_some_other_mesh_are_not_used(strips):
    model = r3.File3dm.Read(strips)
    mesh = model.Objects[3].Geometry
    wrong = records.mesh_arrays_at(strips, 2)
    shape = rhino._r3_mesh_to_shape(mesh, arrays=wrong)
    assert len(shape.vertices) == 70000


def test_a_mesh_put_off_by_the_import_is_read_from_the_file(tmp_path,
                                                            monkeypatch):
    """A mesh on a hidden layer is read when something first asks for it,
    as a save does; it comes from the file, not a vertex at a time."""
    model = r3.File3dm()
    layer = r3.Layer()
    layer.Name = "Scans"
    layer.Visible = False
    index = model.Layers.Add(layer)
    attrs = r3.ObjectAttributes()
    attrs.LayerIndex = index
    model.Objects.AddMesh(_strip(3000), attrs)
    path = str(tmp_path / "hidden.3dm")
    assert model.Write(path, 8)
    want = _one_at_a_time(r3.File3dm.Read(path).Objects[0].Geometry)

    (item,) = rhino.import_3dm(path)
    shape = item[1]

    def one_at_a_time(*_args, **_kw):
        raise AssertionError("read a vertex at a time")
    monkeypatch.setattr(rhino, "_reporting", one_at_a_time)
    (mesh,) = shape.shapes()
    np.testing.assert_array_equal(mesh.vertices, want[0])
    assert len(mesh.triangles) == 1499 + 749


def test_hidden_meshes_read_in_parallel_do_not_reopen_the_file(
        tmp_path, monkeypatch):
    """The parallel reader leaves a hidden mesh as its index in the file.
    Reading it later needs only the mesh's own record, not the whole file
    read again by rhino3dm, which took nine seconds of a film set's save."""
    from serpentine3d.fileio import rhino_parallel as rp
    model = r3.File3dm()
    layer = r3.Layer()
    layer.Name = "Scans"
    layer.Visible = False
    attrs = r3.ObjectAttributes()
    attrs.LayerIndex = model.Layers.Add(layer)
    for count in (3000, 40):
        model.Objects.AddMesh(_strip(count), attrs)
    model.Objects.AddLine(r3.Point3d(0, 0, 0), r3.Point3d(1, 0, 0))
    path = str(tmp_path / "hidden.3dm")
    assert model.Write(path, 8)
    want = _one_at_a_time(r3.File3dm.Read(path).Objects[0].Geometry)

    items = rp.import_3dm_parallel(path, workers=2)
    deferred = [shape for _name, shape, _meta in items
                if hasattr(shape, "shapes")]
    assert len(deferred) == 2

    def no_reading(*_args, **_kw):
        raise AssertionError("the whole file read again")
    monkeypatch.setattr(r3.File3dm, "Read", no_reading)
    (mesh,) = deferred[0].shapes()
    np.testing.assert_array_equal(mesh.vertices, want[0])
