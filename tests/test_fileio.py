import math
import os

import pytest

from serpentine3d import fileio
from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene


@pytest.fixture
def scene():
    s = Scene()
    s.add(g.make_box((0, 0, 0), 10, 10, 10), name="Box A")
    s.add(g.make_circle((20, 0, 0), 5), name="Profile")
    layer = s.layers.create("Set pieces", (0.9, 0.4, 0.2))
    s.add(g.make_sphere((0, 30, 0), 4), name="Ball", layer_id=layer.id)
    return s


def test_native_roundtrip(scene, tmp_path):
    path = str(tmp_path / "test.serp")
    fileio.export_file(scene, path)
    assert os.path.exists(path)

    loaded = Scene()
    fileio.import_file(loaded, path)
    assert len(loaded.all()) == 3
    names = {o.name for o in loaded.all()}
    assert names == {"Box A", "Profile", "Ball"}
    box = loaded.find_by_name("Box A")
    assert g.volume(box.shape) == pytest.approx(1000)
    ball = loaded.find_by_name("Ball")
    layer = loaded.layers.get(ball.layer_id)
    assert layer.name == "Set pieces"
    assert layer.color == pytest.approx((0.9, 0.4, 0.2))


def test_step_roundtrip(scene, tmp_path):
    path = str(tmp_path / "test.step")
    fileio.export_file(scene, path)
    assert os.path.exists(path)

    loaded = Scene()
    n = fileio.import_file(loaded, path)
    assert n >= 2   # solids survive; curve may or may not
    vols = sorted(g.volume(o.shape) for o in loaded.all()
                  if o.kind == "solid")
    assert vols[-1] == pytest.approx(1000, rel=1e-3)


def test_obj_export_import(scene, tmp_path):
    path = str(tmp_path / "test.obj")
    fileio.export_file(scene, path)
    text = open(path).read()
    assert "v " in text and "f " in text

    loaded = Scene()
    n = fileio.import_file(loaded, path)
    assert n >= 2   # box + sphere meshes (curve has no faces)
    mn, mx = loaded.bbox()
    assert mx[0] == pytest.approx(10, abs=0.5)


def test_export_selected_only(scene, tmp_path):
    path = str(tmp_path / "sel.step")
    box = scene.find_by_name("Box A")
    fileio.export_file(scene, path, only_ids=[box.id])
    loaded = Scene()
    fileio.import_file(loaded, path)
    assert len(loaded.all()) == 1


def test_unsupported_format(scene, tmp_path):
    with pytest.raises(ValueError):
        fileio.export_file(scene, str(tmp_path / "x.xyz"))


def test_3dm_roundtrip(tmp_path):
    import math as _m
    import rhino3dm as r3

    # build a 3dm file with rhino3dm directly (as Rhino would)
    model = r3.File3dm()
    layer = r3.Layer()
    layer.Name = "Rhino Layer"
    layer.Color = (200, 100, 50, 255)
    model.Layers.Add(layer)
    attrs = r3.ObjectAttributes()
    attrs.Name = "RhinoCircle"
    attrs.LayerIndex = 0
    circle = r3.Circle(r3.Point3d(0, 0, 0), 5.0)
    model.Objects.AddCurve(circle.ToNurbsCurve(), attrs)
    sphere = r3.Sphere(r3.Point3d(20, 0, 0), 3.0)
    model.Objects.AddSphere(sphere, None)
    path = str(tmp_path / "rhino_file.3dm")
    assert model.Write(path, 8)

    # import: circle must come in as an exact NURBS curve
    scene = Scene()
    n = fileio.import_file(scene, path)
    assert n >= 1
    circle_obj = scene.find_by_name("RhinoCircle")
    assert circle_obj is not None
    assert g.curve_length(circle_obj.shape) == pytest.approx(
        2 * _m.pi * 5, rel=1e-6)
    layer_names = {l.name for l in scene.layers.all()}
    assert "Rhino Layer" in layer_names


def test_3dm_export_and_reimport(scene, tmp_path):
    path = str(tmp_path / "out.3dm")
    fileio.export_file(scene, path)

    # verify with rhino3dm directly
    import rhino3dm as r3
    model = r3.File3dm.Read(path)
    assert model is not None
    geos = [o.Geometry for o in model.Objects]
    assert any(isinstance(gg, r3.Curve) for gg in geos)
    assert any(isinstance(gg, r3.Mesh) for gg in geos)

    # and re-import into serpentine3d
    loaded = Scene()
    n = fileio.import_file(loaded, path)
    assert n >= 3
    prof = loaded.find_by_name("Profile")
    assert prof is not None
    assert g.curve_length(prof.shape) == pytest.approx(
        g.curve_length(scene.find_by_name("Profile").shape), rel=1e-6)


def test_3dm_trimmed_planar_face(tmp_path):
    """CreateTrimmedPlane: a plane trimmed to a circle must import as a
    disc, not the whole rectangle."""
    import math as _m
    import rhino3dm as r3
    model = r3.File3dm()
    circle = r3.Circle(r3.Point3d(0, 0, 0), 5.0)
    plane = r3.Plane.WorldXY()
    brep = r3.Brep.CreateTrimmedPlane(plane, circle.ToNurbsCurve())
    assert brep is not None
    model.Objects.AddBrep(brep, None)
    path = str(tmp_path / "trimmed.3dm")
    assert model.Write(path, 8)

    scene = Scene()
    n = fileio.import_file(scene, path)
    assert n == 1
    obj = scene.all()[0]
    area = g.surface_area(obj.shape)
    assert area == pytest.approx(_m.pi * 25, rel=0.01)


def test_surface_control_points():
    circle = g.make_circle((0, 0, 0), 4)
    c2 = g.make_circle((0, 0, 8), 2)
    srf = g.loft([circle, c2])
    faces = [f for f in g.faces_of(srf)]
    pts, (nu, nv) = g.surface_control_points(faces[0])
    assert nu >= 2 and nv >= 2
    assert len(pts) == nu * nv
    moved = g.move_surface_control_point(faces[0], 0, (10, 10, 10))
    assert g.shape_kind(moved) == "surface"
    pts2, _ = g.surface_control_points(moved)
    assert pts2[0] == pytest.approx((10, 10, 10))


def test_dxf_roundtrip(scene, tmp_path):
    path = str(tmp_path / "out.dxf")
    fileio.export_file(scene, path)
    loaded = Scene()
    n = fileio.import_file(loaded, path)
    assert n >= 1                       # the circle curve at minimum
    curves = [o for o in loaded.all() if o.kind == "curve"]
    assert len(curves) >= 1
    assert g.curve_length(curves[0].shape) == pytest.approx(
        g.curve_length(scene.find_by_name("Profile").shape), rel=1e-3)


def test_svg_import(tmp_path):
    svg_path = str(tmp_path / "in.svg")
    with open(svg_path, "w") as f:
        f.write('''<svg xmlns="http://www.w3.org/2000/svg">
<circle cx="50" cy="50" r="20"/>
<rect x="0" y="0" width="30" height="20"/>
<path d="M 0 0 L 100 0 C 120 0 120 40 100 40"/>
</svg>''')
    scene = Scene()
    n = fileio.import_file(scene, svg_path)
    assert n >= 3
    kinds = {o.kind for o in scene.all()}
    assert kinds == {"curve"}


def test_glb_export(scene, tmp_path):
    import json, struct
    path = str(tmp_path / "out.glb")
    fileio.export_file(scene, path)
    with open(path, "rb") as f:
        magic, ver, total = struct.unpack("<III", f.read(12))
        assert magic == 0x46546C67 and ver == 2
        jlen, jtype = struct.unpack("<II", f.read(8))
        doc = json.loads(f.read(jlen))
    assert len(doc["meshes"]) == 2       # box + sphere (curve skipped)
    assert doc["asset"]["generator"] == "Serpentine3D"
    assert len(doc["materials"]) == 2


def test_usda_export(scene, tmp_path):
    path = str(tmp_path / "out.usda")
    fileio.export_file(scene, path)
    text = open(path).read()
    assert text.startswith("#usda 1.0")
    assert 'def Mesh' in text
    assert 'upAxis = "Z"' in text
    assert text.count("def Mesh") == 2


def test_obj_mtl_colors(scene, tmp_path):
    path = str(tmp_path / "colored.obj")
    box = scene.find_by_name("Box A")
    scene.update(box.id, color=(1.0, 0.0, 0.0))
    fileio.export_file(scene, path)
    assert "usemtl" in open(path).read()
    mtl = open(str(tmp_path / "colored.mtl")).read()
    assert "Kd 1 0 0" in mtl
