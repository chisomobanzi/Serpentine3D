"""Importing a .serp file adds its contents to the open scene.

Import of every other format adds to what is there, and `import_file` says it
returns the number of objects added. A .serp went through the same function
but loaded the way Open does: the scene was cleared first. Importing a
72-object file into an 83-object scene over the RPC bridge left 72 objects
and nothing of the modeller's own; only undo brought it back.

Open still replaces, which is what it is for. The two meant different things
and shared one call, so now they say which they mean.
"""

from __future__ import annotations

from serpentine3d import fileio
from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene
from serpentine3d.scripting import Document


def _file_with_two_boxes(tmp_path):
    doc = Document()
    doc.add(g.make_box((0, 0, 0), 1, 1, 1), name="Kit box", layer="Kit::Parts")
    doc.add(g.make_box((5, 0, 0), 1, 1, 1), name="Kit box", layer="Kit::Parts")
    hidden = doc.add(g.make_box((9, 0, 0), 1, 1, 1), name="Spare")
    hidden.visible = False
    path = tmp_path / "kit.serp"
    doc.save(str(path))
    return path


def _scene_of_my_own():
    scene = Scene()
    walls = scene.layers.create("Walls")
    mine = scene.add(g.make_box((0, 0, 0), 2, 2, 2), name="Mine",
                     layer_id=walls.id)
    scene.update(mine.id, visible=False)
    return scene, mine


def test_import_keeps_what_was_there_and_adds_the_file(tmp_path):
    path = _file_with_two_boxes(tmp_path)
    scene, mine = _scene_of_my_own()

    added = fileio.import_file(scene, str(path))

    assert added == 3
    assert len(scene.all()) == 4
    kept = scene.objects[mine.id]
    assert kept.name == "Mine" and kept.visible is False
    assert scene.layers.get(kept.layer_id).name == "Walls"


def test_imported_objects_keep_their_layers_and_state(tmp_path):
    path = _file_with_two_boxes(tmp_path)
    scene, _ = _scene_of_my_own()

    fileio.import_file(scene, str(path))

    boxes = [o for o in scene.all() if o.name == "Kit box"]
    assert len(boxes) == 2
    assert {scene.layers.full_path(o.layer_id) for o in boxes} == {"Kit::Parts"}
    spare = next(o for o in scene.all() if o.name == "Spare")
    assert spare.visible is False


def test_a_layer_the_scene_already_has_is_reused(tmp_path):
    path = _file_with_two_boxes(tmp_path)
    scene = Scene()
    kit = scene.layers.create("Kit")
    parts = scene.layers.create("Parts", parent=kit.id)

    fileio.import_file(scene, str(path))

    assert [la for la in scene.layers.all() if la.name == "Parts"] == [parts]
    boxes = [o for o in scene.all() if o.name == "Kit box"]
    assert {o.layer_id for o in boxes} == {parts.id}


def test_import_leaves_the_current_layer_alone(tmp_path):
    path = _file_with_two_boxes(tmp_path)
    scene, _ = _scene_of_my_own()
    walls = scene.layers.find_by_name("Walls")
    scene.layers.current_id = walls.id

    fileio.import_file(scene, str(path))

    assert scene.layers.current_id == walls.id


def test_open_still_replaces_the_scene(tmp_path):
    path = _file_with_two_boxes(tmp_path)
    scene, mine = _scene_of_my_own()

    fileio.import_file(scene, str(path), replace=True)

    assert mine.id not in scene.objects
    assert len(scene.all()) == 3


def test_the_import_command_adds_and_open_replaces(tmp_path):
    path = _file_with_two_boxes(tmp_path)

    doc = Document()
    doc.add(g.make_box((0, 0, 0), 2, 2, 2), name="Mine")
    doc.run("import", [str(path)])
    assert sorted(o.name for o in doc.objects()) == ["Kit box", "Kit box", "Mine", "Spare"]

    doc.run("open", [str(path)])
    assert sorted(o.name for o in doc.objects()) == ["Kit box", "Kit box", "Spare"]


def test_the_scripting_document_opens_and_imports_the_same_way(tmp_path):
    path = _file_with_two_boxes(tmp_path)
    doc = Document()
    doc.add(g.make_box((0, 0, 0), 2, 2, 2), name="Mine")

    assert doc.import_(str(path)) == 3
    assert len(doc.objects()) == 4

    doc.open(str(path))
    assert len(doc.objects()) == 3


def test_the_files_empty_layers_come_in_too(tmp_path):
    doc = Document()
    doc.scene.layers.create("Annotations")
    doc.add(g.make_box((0, 0, 0), 1, 1, 1), name="Part")
    path = tmp_path / "with-empty-layer.serp"
    doc.save(str(path))
    scene, _ = _scene_of_my_own()

    fileio.import_file(scene, str(path))

    assert scene.layers.find_by_name("Annotations") is not None


def test_history_records_follow_their_objects_to_new_ids(tmp_path):
    doc = Document()
    part = doc.add(g.make_box((0, 0, 0), 1, 1, 1), name="Part")
    doc.scene.history_records.append(
        {"command": "extrude", "inputs": [part.id], "output": part.id})
    path = tmp_path / "with-history.serp"
    doc.save(str(path))
    scene, _ = _scene_of_my_own()

    fileio.import_file(scene, str(path))

    imported = next(o for o in scene.all() if o.name == "Part")
    record, = scene.history_records
    assert record["inputs"] == [imported.id] and record["output"] == imported.id
