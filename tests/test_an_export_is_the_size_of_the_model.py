"""A glTF, USD or FBX export comes out the size the model is.

glTF measures in metres, always. The exporter wrote document units straight
into it, so a 20 mm ring opened in Blender 20 m across, and a phone showing
it in AR would have stood a ring the size of a house on the table. USD says
how long its unit is in `metersPerUnit`, and that said a millimetre whatever
the document was in, so an inch model came in 25.4 times too small. FBX says
it in `UnitScaleFactor`, and that said a metre, so the ring came in 20 m
across from FBX as well.

So the glTF is written in metres, and the USD and the FBX say what the
document's unit really is.
"""

from __future__ import annotations

import json
import re
import struct

import numpy as np
import pytest

from serpentine3d import fileio
from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene
from serpentine3d.fileio import fbx
from serpentine3d.utils.units import UNITS, convert


def _box_scene(units: str) -> Scene:
    scene = Scene()
    scene.units = units
    scene.add(g.make_box((0, 0, 0), 10, 20, 30), name="Block")
    return scene


def _read_glb(path) -> tuple[dict, bytes]:
    with open(path, "rb") as f:
        f.read(12)
        jlen, _ = struct.unpack("<II", f.read(8))
        doc = json.loads(f.read(jlen))
        blen, _ = struct.unpack("<II", f.read(8))
        return doc, f.read(blen)


def _positions(doc: dict, binary: bytes) -> tuple[dict, np.ndarray]:
    acc = doc["accessors"][doc["meshes"][0]["primitives"][0]
                           ["attributes"]["POSITION"]]
    view = doc["bufferViews"][acc["bufferView"]]
    data = np.frombuffer(binary, np.float32, acc["count"] * 3,
                         view["byteOffset"]).reshape(-1, 3)
    return acc, data


@pytest.mark.parametrize("units", UNITS)
def test_a_glb_is_in_metres_whatever_the_document_is_in(units, tmp_path):
    path = tmp_path / "block.glb"
    fileio.export_file(_box_scene(units), str(path))
    acc, verts = _positions(*_read_glb(path))

    m = convert(1.0, units, "m")
    # Y-up: the box's 30 of height becomes glTF's Y, its 20 of depth -Z.
    # Float32 holds about seven digits, so the check is relative; a wrong
    # unit is out by 25 times or more.
    lo, hi = np.array([0, 0, -20]) * m, np.array([10, 30, 0]) * m
    near = {"rel": 1e-6, "abs": 1e-9}
    assert verts.min(axis=0) == pytest.approx(lo, **near)
    assert verts.max(axis=0) == pytest.approx(hi, **near)
    # The bounds a reader trusts without reading the data say the same
    assert acc["min"] == pytest.approx(list(lo), **near)
    assert acc["max"] == pytest.approx(list(hi), **near)


@pytest.mark.parametrize("units", UNITS)
def test_a_usd_says_how_long_its_unit_is(units, tmp_path):
    path = tmp_path / "block.usda"
    fileio.export_file(_box_scene(units), str(path))
    text = path.read_text(encoding="utf-8")

    stated = re.search(r"metersPerUnit\s*=\s*([0-9.eE+-]+)", text)
    assert stated, "the stage does not say how long its unit is"
    assert float(stated.group(1)) == pytest.approx(convert(1.0, units, "m"))

    # The points stay in document units: the unit says how long they are
    points = re.search(r"point3f\[\] points = \[(.*?)\]\n", text).group(1)
    xyz = np.array(re.findall(r"\(([^)]*)\)", points),
                   dtype=object)
    coords = np.array([[float(c) for c in p.split(",")] for p in xyz])
    assert coords.max(axis=0) == pytest.approx([10, 20, 30])


def _declared(data: bytes, prop: str) -> float:
    """A number a binary FBX declares among its GlobalSettings."""
    def s(text):
        return b"S" + struct.pack("<I", len(text)) + text.encode()
    entry = s(prop) + s("double") + s("Number") + s("")
    at = data.index(entry) + len(entry)
    assert data[at:at + 1] == b"D", f"{prop} is not written as a double"
    return struct.unpack("<d", data[at + 1:at + 9])[0]


@pytest.mark.parametrize("units", UNITS)
def test_an_fbx_says_how_long_its_unit_is(units, tmp_path):
    path = tmp_path / "block.fbx"
    fileio.export_file(_box_scene(units), str(path))
    data = path.read_bytes()

    # FBX counts its unit in centimetres
    cm = convert(1.0, units, "cm")
    assert _declared(data, "UnitScaleFactor") == pytest.approx(cm)
    assert _declared(data, "OriginalUnitScaleFactor") == pytest.approx(cm)

    # The vertices stay in document units: the unit says how long they are
    (_, mesh), = fbx.import_fbx(str(path))
    assert mesh.vertices.max(axis=0) == pytest.approx([10, 20, 30])
