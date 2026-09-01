"""A tree of layers is still a tree after saving, and after opening a 3dm.

The model can hold a layer under a layer; a file that flattens it back on
the way out would make the feature worthless. Both formats have to carry
the shape: our own, which has to keep reading files written before layers
had parents, and Rhino's, where the hierarchy is the point.

The 3dm side also settles the bug that started this. An architect's file
had Walls::Interior and Roof::Interior, and the importer read only a
layer's leaf name, so the second Interior was taken for the first and half
the drawing arrived on the wrong layer, wearing the wrong colour (#6).
Rhino writes a layer's parent as a guid and can spell its full path, so
there is no reason to guess from a name that two branches are allowed to
share.
"""

from __future__ import annotations

import json

import pytest

r3 = pytest.importorskip("rhino3dm")

from serpentine3d.core import geometry as g                    # noqa: E402
from serpentine3d.core.scene import Scene                      # noqa: E402
from serpentine3d.fileio import import_file, native            # noqa: E402
from serpentine3d.fileio import rhino                          # noqa: E402


def _round_trip_native(scene, tmp_path):
    path = str(tmp_path / "doc.serp3d")
    native.save_scene(scene, path)
    out = Scene()
    native.load_scene(out, path)
    return out


def _box(scene, layer_id, x=0.0):
    return scene.add(g.make_box((x, 0.0, 0.0), 1.0, 1.0, 1.0),
                     layer_id=layer_id)


# -- our own format --

def test_a_saved_sublayer_comes_back_under_its_parent(tmp_path):
    scene = Scene()
    walls = scene.layers.create("Walls")
    scene.layers.create("Interior", parent=walls.id)
    out = _round_trip_native(scene, tmp_path)
    assert out.layers.find_by_path("Walls::Interior") is not None


def test_a_saved_branch_keeps_its_whole_depth(tmp_path):
    scene = Scene()
    walls = scene.layers.create("Walls")
    inner = scene.layers.create("Interior", parent=walls.id)
    scene.layers.create("Trim", parent=inner.id)
    out = _round_trip_native(scene, tmp_path)
    deep = out.layers.find_by_path("Walls::Interior::Trim")
    assert deep is not None
    assert [la.name for la in out.layers.ancestors(deep.id)] == \
        ["Interior", "Walls"]


def test_two_saved_branches_can_share_a_leaf_name(tmp_path):
    scene = Scene()
    walls = scene.layers.create("Walls")
    roof = scene.layers.create("Roof")
    under_walls = scene.layers.create("Interior", parent=walls.id)
    under_roof = scene.layers.create("Interior", parent=roof.id)
    _box(scene, under_walls.id)
    _box(scene, under_roof.id, x=10.0)
    out = _round_trip_native(scene, tmp_path)
    a = out.layers.find_by_path("Walls::Interior")
    b = out.layers.find_by_path("Roof::Interior")
    assert a is not None and b is not None and a.id != b.id
    assert {o.layer_id for o in out.all()} == {a.id, b.id}


def test_a_saved_sublayer_keeps_its_own_switch(tmp_path):
    """Off under an on parent: the child's own switch is its own."""
    scene = Scene()
    walls = scene.layers.create("Walls")
    inner = scene.layers.create("Interior", parent=walls.id)
    scene.layers.set_visible(inner.id, False)
    out = _round_trip_native(scene, tmp_path)
    back = out.layers.find_by_path("Walls::Interior")
    assert back.visible is False
    assert out.layers.get(back.parent).visible is True


def test_a_file_written_before_layers_had_parents_reads_flat(tmp_path):
    """The field is younger than the format, so it may not be there."""
    scene = Scene()
    scene.layers.create("Walls")
    scene.layers.create("Roof")
    path = str(tmp_path / "old.serp3d")
    native.save_scene(scene, path)
    doc = json.loads(_document(path))
    for ld in doc["layers"]:
        ld.pop("parent", None)
    _rewrite(path, doc)
    out = Scene()
    native.load_scene(out, path)
    assert all(la.parent is None for la in out.layers.all())


# -- Rhino's format, coming in --

def _rhino_file(tmp_path, name="tree.3dm"):
    """Walls::Interior and Roof::Interior, a box on each.

    The pair from the report: one leaf name, two branches, and nothing but
    the parent to tell them apart.
    """
    model = r3.File3dm()
    made = {}
    for branch, colour in (("Walls", (200, 0, 0, 255)),
                           ("Roof", (0, 0, 200, 255))):
        top = r3.Layer()
        top.Name = branch
        top_i = model.Layers.Add(top)
        leaf = r3.Layer()
        leaf.Name = "Interior"
        leaf.Color = colour
        leaf.ParentLayerId = model.Layers[top_i].Id
        made[branch] = model.Layers.Add(leaf)
    for n, (branch, leaf_i) in enumerate(made.items()):
        lo = r3.Point3d(n * 20.0, 0.0, 0.0)
        hi = r3.Point3d(n * 20.0 + 10, 10.0, 10.0)
        attrs = r3.ObjectAttributes()
        attrs.LayerIndex = leaf_i
        attrs.Name = f"{branch}-box"
        model.Objects.AddBrep(r3.Brep.CreateFromBox(r3.Box(
            r3.BoundingBox(lo, hi))), attrs)
    path = tmp_path / name
    model.Write(str(path), 8)
    return str(path)


def test_read_layers_carries_the_full_path():
    model = r3.File3dm()
    top = r3.Layer()
    top.Name = "Walls"
    top_i = model.Layers.Add(top)
    leaf = r3.Layer()
    leaf.Name = "Interior"
    leaf.ParentLayerId = model.Layers[top_i].Id
    leaf_i = model.Layers.Add(leaf)
    read = rhino.read_layers(model)
    assert read[model.Layers[leaf_i].Index]["path"] == "Walls::Interior"
    assert read[model.Layers[top_i].Index]["path"] == "Walls"


def test_the_same_leaf_name_in_two_branches_no_longer_collides(tmp_path):
    scene = Scene()
    import_file(scene, _rhino_file(tmp_path))
    walls = scene.layers.find_by_path("Walls::Interior")
    roof = scene.layers.find_by_path("Roof::Interior")
    assert walls is not None and roof is not None, \
        "one of the two Interior layers was taken for the other"
    assert walls.id != roof.id
    by_name = {o.name: o.layer_id for o in scene.all()}
    assert by_name["Walls-box"] == walls.id
    assert by_name["Roof-box"] == roof.id


def test_an_imported_layer_that_shared_a_name_keeps_its_own_colour(tmp_path):
    scene = Scene()
    import_file(scene, _rhino_file(tmp_path))
    walls = scene.layers.find_by_path("Walls::Interior")
    roof = scene.layers.find_by_path("Roof::Interior")
    assert walls.color[0] > walls.color[2], "Walls::Interior lost its red"
    assert roof.color[2] > roof.color[0], "Roof::Interior lost its blue"


def test_an_imported_parent_holds_its_children(tmp_path):
    scene = Scene()
    import_file(scene, _rhino_file(tmp_path))
    walls = scene.layers.find_by_name("Walls")
    assert walls is not None, "the parent layer was never made"
    assert [la.name for la in scene.layers.children(walls.id)] == ["Interior"]


def test_a_parent_switched_off_in_the_file_arrives_switched_off(tmp_path):
    """The parent holds nothing itself, so only the file says it is off.

    Rhino switches a parent off by switching its children off too, and
    keeps each layer's own switch on the side. Reading only the children
    would leave the parent looking on above a row of off children, which
    is not what the file says and not what Rhino shows.
    """
    model = r3.File3dm()
    top = r3.Layer()
    top.Name = "Reference"
    top.Visible = False
    top_i = model.Layers.Add(top)
    leaf = r3.Layer()
    leaf.Name = "Survey"
    leaf.Visible = False            # Rhino cascades the switch
    leaf.SetPersistentVisibility(True)   # the layer's own switch is on
    leaf.ParentLayerId = model.Layers[top_i].Id
    leaf_i = model.Layers.Add(leaf)
    attrs = r3.ObjectAttributes()
    attrs.LayerIndex = leaf_i
    attrs.Name = "survey-box"
    model.Objects.AddBrep(r3.Brep.CreateFromBox(r3.Box(r3.BoundingBox(
        r3.Point3d(0, 0, 0), r3.Point3d(1, 1, 1)))), attrs)
    path = str(tmp_path / "ref.3dm")
    model.Write(path, 8)

    scene = Scene()
    import_file(scene, path)
    survey = scene.layers.find_by_path("Reference::Survey")
    assert survey is not None
    assert scene.layers.get(survey.parent).visible is False, \
        "the parent came in switched on"
    assert scene.layers.is_visible(survey.id) is False
    assert scene.visible_objects() == []


def test_the_branch_survives_the_trip_between_processes(tmp_path):
    """The importer that runs on a real drawing is the parallel one.

    Layers are resolved inside a worker, so the branch has to be picklable
    and has to come back the same as the plain reader's. A file big enough
    to be worth splitting is exactly the sort with a layer tree in it.
    """
    from serpentine3d.fileio import rhino_parallel as rp
    path = _rhino_file(tmp_path, "parallel.3dm")
    serial = rhino.import_3dm(path)
    parallel = rp.import_3dm_parallel(path, workers=2)
    assert [m["layer_chain"] for _, _, m in parallel] == \
        [m["layer_chain"] for _, _, m in serial]
    assert [rung["path"] for rung in serial[0][2]["layer_chain"]] \
        == ["Walls", "Walls::Interior"]


# -- Rhino's format, going out --

def test_export_writes_a_layer_under_its_parent(tmp_path):
    scene = Scene()
    walls = scene.layers.create("Walls")
    inner = scene.layers.create("Interior", parent=walls.id)
    _box(scene, inner.id)
    path = str(tmp_path / "out.3dm")
    rhino.export_3dm(scene, path)
    model = r3.File3dm.Read(path)
    paths = {model.Layers[i].FullPath for i in range(len(model.Layers))}
    assert "Walls::Interior" in paths


def test_a_tree_exported_and_read_back_keeps_its_shape(tmp_path):
    scene = Scene()
    walls = scene.layers.create("Walls")
    roof = scene.layers.create("Roof")
    under_walls = scene.layers.create("Interior", parent=walls.id)
    under_roof = scene.layers.create("Interior", parent=roof.id)
    _box(scene, under_walls.id)
    _box(scene, under_roof.id, x=10.0)
    path = str(tmp_path / "out.3dm")
    rhino.export_3dm(scene, path)

    back = Scene()
    import_file(back, path)
    a = back.layers.find_by_path("Walls::Interior")
    b = back.layers.find_by_path("Roof::Interior")
    assert a is not None and b is not None and a.id != b.id
    assert {o.layer_id for o in back.all()} == {a.id, b.id}


def test_a_child_exported_before_its_parent_still_finds_it(tmp_path):
    """Layer order is the order they were made, which a move can undo."""
    scene = Scene()
    orphan = scene.layers.create("Interior")
    walls = scene.layers.create("Walls")
    scene.layers.set_parent(orphan.id, walls.id)
    _box(scene, orphan.id)
    path = str(tmp_path / "out.3dm")
    rhino.export_3dm(scene, path)
    model = r3.File3dm.Read(path)
    paths = {model.Layers[i].FullPath for i in range(len(model.Layers))}
    assert "Walls::Interior" in paths


# -- helpers for the backward-compatible read --

def _document(path: str) -> str:
    import zipfile
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            return z.read("document.json").decode("utf-8")
    with open(path, encoding="utf-8") as f:
        return f.read()


def _rewrite(path: str, doc: dict):
    import shutil
    import zipfile
    payload = json.dumps(doc)
    if zipfile.is_zipfile(path):
        tmp = path + ".tmp"
        with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w") as zout:
            for item in zin.namelist():
                zout.writestr(item, payload.encode("utf-8")
                              if item == "document.json" else zin.read(item))
        shutil.move(tmp, path)
    else:
        with open(path, "w", encoding="utf-8") as f:
            f.write(payload)
