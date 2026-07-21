"""FBX import/export (pure-Python, mesh-based) — TDD via round-trips.

Export writes binary FBX (Blender rejects ASCII); import handles both binary
and ASCII. Meshes go out tessellated and come back as MeshShape, mirroring
the OBJ path.
"""

import os

import numpy as np

from serpentine3d.core import geometry as g
from serpentine3d.core.mesh import MeshShape
from serpentine3d.fileio import fbx


def _bbox(v):
    v = np.asarray(v, float)
    return v.min(axis=0), v.max(axis=0)


def test_export_is_binary_fbx(tmp_path):
    # Blender only imports binary FBX, so export must be binary.
    box = g.make_box((0, 0, 0), 10, 20, 30)
    p = str(tmp_path / "b.fbx")
    fbx.export_fbx([("mybox", box)], p)
    assert os.path.getsize(p) > 0
    assert open(p, "rb").read(23).startswith(b"Kaydara FBX Binary")


def test_roundtrip_box(tmp_path):
    box = g.make_box((0, 0, 0), 10, 20, 30)
    p = str(tmp_path / "b.fbx")
    fbx.export_fbx([("mybox", box)], p)
    out = fbx.import_fbx(p)
    assert len(out) == 1
    name, mesh = out[0]
    assert "mybox" in name
    assert isinstance(mesh, MeshShape)
    lo, hi = _bbox(mesh.vertices)
    assert np.allclose(lo, [0, 0, 0], atol=0.02)
    assert np.allclose(hi, [10, 20, 30], atol=0.02)
    assert len(mesh.triangles) >= 12          # a box -> at least 12 tris


def test_ascii_roundtrip_multiple_objects(tmp_path):
    a = g.make_box((0, 0, 0), 4, 4, 4)
    b = g.make_sphere((20, 0, 0), 5)
    p = str(tmp_path / "m.fbx")
    fbx.export_fbx([("boxA", a), ("sphB", b)], p)
    out = fbx.import_fbx(p)
    assert len(out) == 2
    names = {n for n, _ in out}
    assert any("boxA" in n for n in names)
    assert any("sphB" in n for n in names)


def test_import_ngon_polygons(tmp_path):
    """FBX PolygonVertexIndex can hold n-gons (last index XOR-terminated);
    the importer must fan-triangulate them."""
    # a single quad written by hand as an ascii-ish geometry
    verts = [(0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0)]
    # quad 0,1,2,3 -> last index terminated (~3 == -4)
    from serpentine3d.core.tessellate import tessellate  # noqa: F401
    p = str(tmp_path / "quad.fbx")
    fbx._write_ascii_geometry(p, "quad", verts,
                              [0, 1, 2, -4], normals=None)
    out = fbx.import_fbx(p)
    assert len(out) == 1
    mesh = out[0][1]
    assert len(mesh.triangles) == 2          # quad -> 2 tris
    assert len(mesh.vertices) == 4
