"""Separate objects in an OBJ file stay separate, even when they share a name.

The importer kept its faces in a dictionary keyed by name, so three headsets
exported as three objects called "Meta_Quest" came back as one, and three
tablets of 22 parts each came back as 22. Repeated names are ordinary in a
scene built from copies of the same part.

In OBJ an `o` line starts a new object whatever it is called. A `g` line names
a group, and going back to a group's name inside the same object adds to it.
"""

from __future__ import annotations

from serpentine3d.fileio import obj


def _write(tmp_path, text):
    path = tmp_path / "parts.obj"
    path.write_text(text)
    return str(path)


def test_three_objects_with_one_name_are_three_objects(tmp_path):
    path = _write(tmp_path, (
        "v 0 0 0\nv 1 0 0\nv 0 1 0\n"
        "o Headset\nf 1 2 3\n"
        "o Headset\nf 1 2 3\n"
        "o Headset\nf 1 2 3\n"))

    shapes = obj.import_obj(path)

    assert [name for name, _ in shapes] == ["Headset", "Headset", "Headset"]


def test_returning_to_a_group_inside_one_object_adds_to_it(tmp_path):
    path = _write(tmp_path, (
        "v 0 0 0\nv 1 0 0\nv 0 1 0\nv 1 1 0\n"
        "o Room\n"
        "g wall\nf 1 2 3\n"
        "g door\nf 2 4 3\n"
        "g wall\nf 1 2 4\n"))

    shapes = dict(obj.import_obj(path))

    assert sorted(shapes) == ["door", "wall"]
    assert len(shapes["wall"].triangles) == 2
    assert len(shapes["door"].triangles) == 1


def test_a_round_trip_keeps_every_object(tmp_path):
    from serpentine3d.core.mesh import MeshShape
    tri = MeshShape([[0, 0, 0], [1, 0, 0], [0, 1, 0]], [[0, 1, 2]])
    path = str(tmp_path / "copies.obj")

    obj.export_obj([("Tablet", tri), ("Tablet", tri.translated((5, 0, 0))),
                    ("Stand", tri)], path)

    assert [name for name, _ in obj.import_obj(path)] == ["Tablet", "Tablet", "Stand"]
