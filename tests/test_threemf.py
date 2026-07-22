"""3MF export (the modern 3D-printing container) — TDD.

3MF is an OPC (zip) package: [Content_Types].xml, _rels/.rels and the mesh
XML at 3D/3dmodel.model. We check the package is well-formed, the geometry
round-trips through the XML, and units / multi-object structure are right.
"""

import xml.etree.ElementTree as ET
import zipfile

import numpy as np

from serpentine3d.core import geometry as g
from serpentine3d.fileio import threemf

_NS = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"


def _read(path):
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        root = ET.fromstring(z.read("3D/3dmodel.model"))
    verts = np.array([[float(v.get("x")), float(v.get("y")), float(v.get("z"))]
                      for v in root.iter(f"{_NS}vertex")], float)
    objs = list(root.iter(f"{_NS}object"))
    items = list(root.iter(f"{_NS}item"))
    return names, root, verts, objs, items


def test_3mf_is_valid_opc_package(tmp_path):
    box = g.make_box((0, 0, 0), 10, 20, 30)
    p = str(tmp_path / "b.3mf")
    threemf.export_3mf([("box", box, (1.0, 0.0, 0.0))], p)
    assert zipfile.is_zipfile(p)
    names, *_ = _read(p)
    for part in ("[Content_Types].xml", "_rels/.rels", "3D/3dmodel.model"):
        assert part in names


def test_3mf_geometry_roundtrips(tmp_path):
    box = g.make_box((0, 0, 0), 10, 20, 30)
    p = str(tmp_path / "b.3mf")
    threemf.export_3mf([("box", box)], p)
    _, _, verts, objs, items = _read(p)
    assert len(objs) == 1 and len(items) == 1
    lo, hi = verts.min(axis=0), verts.max(axis=0)
    assert np.allclose(lo, [0, 0, 0], atol=0.02)
    assert np.allclose(hi, [10, 20, 30], atol=0.02)


def test_3mf_units_and_multiobject(tmp_path):
    a = g.make_box((0, 0, 0), 4, 4, 4)
    b = g.make_sphere((20, 0, 0), 5)
    p = str(tmp_path / "m.3mf")
    threemf.export_3mf([("a", a), ("b", b)], p, unit="inch")
    _, root, _, objs, items = _read(p)
    assert root.get("unit") == "inch"
    assert len(objs) == 2 and len(items) == 2


def test_3mf_via_export_file_uses_scene_units(tmp_path):
    from serpentine3d import fileio
    from serpentine3d.core.scene import Scene
    sc = Scene()
    sc.units = "cm"
    sc.add(g.make_box((0, 0, 0), 6, 6, 6), name="cube")
    p = str(tmp_path / "s.3mf")
    fileio.export_file(sc, p)
    _, root, verts, objs, _ = _read(p)
    assert root.get("unit") == "centimeter"        # mapped from scene.units
    assert len(objs) == 1
    lo, hi = verts.min(axis=0), verts.max(axis=0)
    assert np.allclose(hi - lo, [6, 6, 6], atol=0.02)
