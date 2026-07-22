"""STL import/export (mesh-based) — the 3D-printing interchange format.

TDD via round-trips. Export writes binary STL by default (what slicers
expect); import auto-detects binary vs ASCII. Shapes go out tessellated and
come back welded into a MeshShape, mirroring the OBJ/FBX path.
"""

import os
import struct

import numpy as np

from serpentine3d.core import geometry as g
from serpentine3d.core.mesh import MeshShape
from serpentine3d.fileio import stl


def _bbox(v):
    v = np.asarray(v, float)
    return v.min(axis=0), v.max(axis=0)


def _ntri(path):
    return struct.unpack("<I", open(path, "rb").read()[80:84])[0]


def test_export_is_binary_stl(tmp_path):
    # Slicers expect compact binary STL, so export defaults to binary.
    box = g.make_box((0, 0, 0), 10, 20, 30)
    p = str(tmp_path / "b.stl")
    stl.export_stl([("mybox", box)], p)
    assert os.path.getsize(p) > 0
    data = open(p, "rb").read()
    assert stl._is_binary(data)             # 84 + 50*ntri bytes exactly
    assert data[:5] != b"solid"             # binary header must not fake ASCII


def test_roundtrip_box_binary(tmp_path):
    box = g.make_box((0, 0, 0), 10, 20, 30)
    p = str(tmp_path / "b.stl")
    stl.export_stl([("mybox", box)], p)
    out = stl.import_stl(p)
    assert len(out) == 1
    name, mesh = out[0]
    assert isinstance(mesh, MeshShape)
    lo, hi = _bbox(mesh.vertices)
    assert np.allclose(lo, [0, 0, 0], atol=0.02)
    assert np.allclose(hi, [10, 20, 30], atol=0.02)
    assert len(mesh.triangles) >= 12        # a box -> at least 12 tris


def test_ascii_roundtrip(tmp_path):
    box = g.make_box((0, 0, 0), 4, 6, 8)
    p = str(tmp_path / "a.stl")
    stl.export_stl([("bx", box)], p, binary=False)
    assert open(p, "rb").read(5) == b"solid"
    assert not stl._is_binary(open(p, "rb").read())
    out = stl.import_stl(p)
    lo, hi = _bbox(out[0][1].vertices)
    assert np.allclose(hi - lo, [4, 6, 8], atol=0.02)


def test_merges_multiple_shapes(tmp_path):
    # STL is one triangle soup; several objects merge into a mesh spanning both.
    a = g.make_box((0, 0, 0), 4, 4, 4)
    b = g.make_box((20, 0, 0), 4, 4, 4)
    p = str(tmp_path / "m.stl")
    stl.export_stl([("a", a), ("b", b)], p)
    out = stl.import_stl(p)
    lo, hi = _bbox(out[0][1].vertices)
    assert np.allclose(lo[0], 0, atol=0.02)
    assert np.allclose(hi[0], 24, atol=0.02)     # spans both boxes


def test_scene_export_import_roundtrip(tmp_path):
    # exercise the fileio dispatch that the app's Import/Export menus use.
    from serpentine3d import fileio
    from serpentine3d.core.scene import Scene
    sc = Scene()
    sc.add(g.make_box((0, 0, 0), 12, 12, 12), name="cube")
    p = str(tmp_path / "s.stl")
    fileio.export_file(sc, p)
    assert stl._is_binary(open(p, "rb").read())
    sc2 = Scene()
    assert fileio.import_file(sc2, p) == 1
    lo, hi = _bbox(sc2.all()[0].shape.vertices)
    assert np.allclose(hi - lo, [12, 12, 12], atol=0.02)


def test_quality_presets_control_density(tmp_path):
    # print-quality control: finer presets tessellate curves into more facets.
    sph = g.make_sphere((0, 0, 0), 20)
    counts = {}
    for q in ("draft", "standard", "fine", "ultra"):
        p = str(tmp_path / f"{q}.stl")
        stl.export_stl([("s", sph)], p, quality=q)
        counts[q] = _ntri(p)
    assert counts["draft"] < counts["standard"] < counts["fine"] < counts["ultra"]


def test_explicit_deflection_overrides_quality(tmp_path):
    sph = g.make_sphere((0, 0, 0), 20)
    coarse = str(tmp_path / "c.stl")
    fine = str(tmp_path / "f.stl")
    stl.export_stl([("s", sph)], coarse, deflection=2.0)
    stl.export_stl([("s", sph)], fine, deflection=0.05)
    assert _ntri(fine) > _ntri(coarse)


def test_export_file_forwards_quality(tmp_path):
    # the app passes its quality picker through fileio.export_file(stl_quality=).
    from serpentine3d import fileio
    from serpentine3d.core.scene import Scene
    sc = Scene()
    sc.add(g.make_sphere((0, 0, 0), 15), name="ball")
    draft, fine = str(tmp_path / "d.stl"), str(tmp_path / "f.stl")
    fileio.export_file(sc, draft, stl_quality="draft")
    fileio.export_file(sc, fine, stl_quality="fine")
    assert _ntri(fine) > _ntri(draft)


def test_import_welds_shared_vertices(tmp_path):
    # a box's 8 corners are shared; the reader must weld, not leave 36 loose.
    box = g.make_box((0, 0, 0), 5, 5, 5)
    p = str(tmp_path / "w.stl")
    stl.export_stl([("bx", box)], p)
    mesh = stl.import_stl(p)[0][1]
    assert len(mesh.vertices) == 8
    assert len(mesh.triangles) == 12
