"""A file holding an origin names the first release that understands it.

Geometry far from the world's origin is written as float32 offsets from a
float64 origin, because four bytes cannot hold a millimetre at survey
coordinates any other way. A reader that knows nothing of that origin
reads the offsets as the coordinates themselves and puts the object at
the world's origin, with no word that anything is wrong, and a save from
there makes it stick: a mesh at (500,000, 6,200,000) opened in 0.12.0 and
came back at (-0.002, -0.002, 0).

So the writer says what the file needs, the way hatches (version 5) and
user text (version 6) did. Only when there is an origin in it: a drawing
near home is written as it always was, and still opens in every release
that could open it before.
"""

from __future__ import annotations

import json
import zipfile

import numpy as np
import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.mesh import MeshShape
from serpentine3d.core.pointcloud import PointCloudShape
from serpentine3d.core.scene import Scene
from serpentine3d.fileio import native


FAR = np.array([500000.0, 6200000.0, 0.0])
REVEAL = 0.004


def _mesh(at=FAR):
    verts = np.array([[0, 0, 0], [REVEAL, 0, 0], [REVEAL, REVEAL, 0],
                      [0, REVEAL, 0]], float) + at
    return MeshShape(verts, np.array([[0, 1, 2], [0, 2, 3]], np.uint32))


def _cloud(at=FAR):
    return PointCloudShape(np.array([[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]]) + at)


def _saved(scene, tmp_path, name="drawing.serp") -> dict:
    path = str(tmp_path / name)
    native.save_scene(scene, path)
    with zipfile.ZipFile(path) as z:
        return json.loads(z.read("document.json")), path


# -- what the file says ----------------------------------------------------

def test_a_far_mesh_asks_for_the_release_that_can_read_it(tmp_path):
    scene = Scene()
    scene.add(_mesh(), name="Far mesh")

    doc, _path = _saved(scene, tmp_path)

    assert doc["version"] == 7
    assert doc["requires"] == "0.12.2"


def test_a_far_scan_asks_for_it_too(tmp_path):
    scene = Scene()
    scene.add(_cloud(), name="Far scan")

    doc, _path = _saved(scene, tmp_path)

    assert doc["version"] == 7
    assert doc["requires"] == "0.12.2"


def test_a_far_mesh_inside_a_block_counts_as_well(tmp_path):
    """A block definition writes its shapes the same way, so an origin
    can reach the file without any object carrying one."""
    scene = Scene()
    scene.block_defs["b1"] = {"name": "Far block", "shapes": [_mesh()]}

    doc, _path = _saved(scene, tmp_path)

    assert doc["version"] == 7


def test_a_drawing_near_home_is_written_as_it_always_was(tmp_path):
    scene = Scene()
    scene.add(_mesh(at=np.zeros(3)), name="Near mesh")
    scene.add(g.make_box((0, 0, 0), 10, 10, 10), name="Box")

    doc, _path = _saved(scene, tmp_path)

    assert doc["version"] < 7
    assert "requires" not in doc or doc["requires"] != "0.12.2"


def test_a_picture_far_out_is_not_one_of_these(tmp_path):
    """A picture is a mesh by inheritance but writes itself its own way,
    with no offsets in it, so it has no reason to raise the bar."""
    from serpentine3d.core.picture import PictureShape

    scene = Scene()
    scene.add(PictureShape(dict(origin=list(FAR), u=[10, 0, 0],
                                v=[0, 10, 0], path="reference.png")))

    doc, _path = _saved(scene, tmp_path)

    assert doc["version"] < 7


# -- and what it does to a reader that cannot ------------------------------

def test_an_older_reader_is_turned_away_rather_than_misreading(
        tmp_path, monkeypatch):
    scene = Scene()
    scene.add(_mesh(), name="Far mesh")
    _doc, path = _saved(scene, tmp_path)

    monkeypatch.setattr(native, "FORMAT_VERSION", 6)
    older = Scene()
    kept = older.add(g.make_box((0, 0, 0), 1, 1, 1))
    with pytest.raises(ValueError, match="0.12.2"):
        native.load_scene(older, path)
    assert older.get(kept.id) is kept, "the drawing it had is left alone"


def test_this_reader_still_opens_it_where_it_was_put(tmp_path):
    scene = Scene()
    scene.add(_mesh(), name="Far mesh")
    _doc, path = _saved(scene, tmp_path)

    back = Scene()
    native.load_scene(back, path)

    vertices = back.all()[0].shape.vertices
    assert np.abs(vertices.min(axis=0) - FAR).max() < 1e-6
    span = vertices.max(axis=0) - vertices.min(axis=0)
    assert np.abs(span[:2] - REVEAL).max() < 1e-6
