"""Picture frames travel with a native drawing instead of its source path."""

from __future__ import annotations

import base64
import json
import zipfile

import pytest
from PySide6.QtGui import QColor, QImage

from serpentine3d.commands.base import FileReq, OptionReq, PointReq
from serpentine3d.commands.view import cmd_pictureframe
from serpentine3d.core.cplane import CPlane
from serpentine3d.core.scene import Scene
from serpentine3d.fileio import native


class _PictureContext:
    def __init__(self, scene):
        self.scene = scene
        self.cplane = CPlane()
        self.messages = []

    def echo(self, message):
        self.messages.append(message)


def _write_png(path, colour):
    path.parent.mkdir(parents=True, exist_ok=True)
    image = QImage(3, 2, QImage.Format.Format_RGB32)
    image.fill(QColor(colour))
    assert image.save(str(path), "PNG")
    return path.read_bytes()


def _place_picture(scene, path, first=(1.0, 2.0, 3.0),
                   opposite=(11.0, 7.0, 3.0)):
    ctx = _PictureContext(scene)
    command = cmd_pictureframe(ctx)
    request = next(command)
    if isinstance(request, OptionReq):
        request = command.send("Add")
    assert isinstance(request, FileReq)
    assert isinstance(command.send(str(path)), PointReq)
    assert isinstance(command.send(first), PointReq)
    with pytest.raises(StopIteration):
        command.send(opposite)
    assert ctx.messages[-1].startswith("Picture frame placed")
    return scene.image_planes[-1]


def _embedded_bytes(plane):
    """Find the in-memory encoded image without prescribing its key name."""
    pending = [plane]
    while pending:
        value = pending.pop()
        if isinstance(value, (bytes, bytearray, memoryview)):
            return bytes(value)
        if isinstance(value, dict):
            pending.extend(value.values())
        elif isinstance(value, (list, tuple)):
            pending.extend(value)
    pytest.fail("picture frame kept only its source path, not its image bytes")


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _strings(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _strings(child)


def _referenced_member(plane_doc, members):
    references = set(_strings(plane_doc)).intersection(members)
    assert len(references) == 1, (
        "each picture frame must name exactly one portable archive member")
    return references.pop()


def _write_legacy_file(path, image_path):
    doc = {
        "format": "serpentine3d",
        "version": 2,
        "units": "mm",
        "image_planes": [{
            "path": str(image_path),
            "origin": [1.0, 2.0, 3.0],
            "u": [10.0, 0.0, 0.0],
            "v": [0.0, 5.0, 0.0],
            "alpha": 0.4,
        }],
        "layers": [],
        "objects": [],
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("document.json", json.dumps(doc))


def test_placing_a_picture_keeps_the_encoded_image_in_the_scene(tmp_path):
    source = tmp_path / "reference.png"
    original = _write_png(source, "tomato")

    plane = _place_picture(Scene(), source)
    source.unlink()

    encoded = _embedded_bytes(plane)
    assert encoded == original
    assert not QImage.fromData(encoded).isNull()


def test_native_file_stores_each_picture_as_a_separate_portable_member(
        tmp_path):
    first_path = tmp_path / "survey-a" / "reference.png"
    second_path = tmp_path / "survey-b" / "reference.png"
    first_bytes = _write_png(first_path, "red")
    second_bytes = _write_png(second_path, "blue")
    scene = Scene()
    first = _place_picture(scene, first_path)
    second = _place_picture(
        scene, second_path, first=(20.0, 30.0, 4.0),
        opposite=(28.0, 26.0, 4.0))
    first["alpha"] = 0.25
    second["alpha"] = 0.75

    drawing = tmp_path / "portable.serp"
    native.save_scene(scene, str(drawing))

    with zipfile.ZipFile(drawing) as archive:
        members = set(archive.namelist())
        document_bytes = archive.read("document.json")
        doc = json.loads(document_bytes)
        entries = doc["image_planes"]
        references = [_referenced_member(entry, members)
                      for entry in entries]
        payloads = [archive.read(reference) for reference in references]

    assert len(set(references)) == 2, \
        "duplicate source basenames collided in the native archive"
    assert payloads == [first_bytes, second_bytes]
    assert base64.b64encode(first_bytes) not in document_bytes
    assert base64.b64encode(second_bytes) not in document_bytes
    assert entries[0]["origin"] == [1.0, 2.0, 3.0]
    assert entries[0]["u"] == [10.0, 0.0, 0.0]
    assert entries[0]["v"] == pytest.approx([0.0, 20.0 / 3.0, 0.0])
    assert entries[0]["alpha"] == 0.25
    assert entries[1]["origin"] == [20.0, 30.0, 4.0]
    assert entries[1]["u"] == [8.0, 0.0, 0.0]
    assert entries[1]["v"] == pytest.approx([0.0, -16.0 / 3.0, 0.0])
    assert entries[1]["alpha"] == 0.75


def test_picture_loads_after_its_original_file_is_deleted(tmp_path):
    source = tmp_path / "reference.png"
    original = _write_png(source, "green")
    scene = Scene()
    _place_picture(scene, source)
    drawing = tmp_path / "drawing.serp"
    native.save_scene(scene, str(drawing))
    source.unlink()

    loaded = Scene()
    native.load_scene(loaded, str(drawing))

    assert len(loaded.image_planes) == 1
    plane = loaded.image_planes[0]
    assert plane["origin"] == [1.0, 2.0, 3.0]
    assert plane["u"] == [10.0, 0.0, 0.0]
    assert plane["v"] == pytest.approx([0.0, 20.0 / 3.0, 0.0])
    assert plane["alpha"] == 1.0
    encoded = _embedded_bytes(plane)
    assert encoded == original
    assert not QImage.fromData(encoded).isNull()


def test_an_embedded_picture_survives_a_second_save(tmp_path):
    source = tmp_path / "reference.png"
    original = _write_png(source, "gold")
    scene = Scene()
    _place_picture(scene, source)
    first_save = tmp_path / "first.serp"
    native.save_scene(scene, str(first_save))
    source.unlink()

    loaded = Scene()
    native.load_scene(loaded, str(first_save))
    second_save = tmp_path / "second.serp"
    native.save_scene(loaded, str(second_save))
    loaded_again = Scene()
    native.load_scene(loaded_again, str(second_save))

    assert _embedded_bytes(loaded_again.image_planes[0]) == original
    with zipfile.ZipFile(second_save) as archive:
        doc = json.loads(archive.read("document.json"))
        member = _referenced_member(doc["image_planes"][0],
                                    set(archive.namelist()))
        assert archive.read(member) == original


def test_a_legacy_path_only_picture_still_loads_from_its_external_file(
        tmp_path):
    source = tmp_path / "legacy.png"
    original = _write_png(source, "purple")
    drawing = tmp_path / "legacy.serp"
    _write_legacy_file(drawing, source)

    loaded = Scene()
    native.load_scene(loaded, str(drawing))

    plane = loaded.image_planes[0]
    assert plane["path"] == str(source)
    assert source.read_bytes() == original
    assert not QImage(str(source)).isNull()
    assert plane["origin"] == [1.0, 2.0, 3.0]
    assert plane["u"] == [10.0, 0.0, 0.0]
    assert plane["v"] == [0.0, 5.0, 0.0]
    assert plane["alpha"] == 0.4


def test_a_missing_legacy_picture_does_not_break_load_or_save(tmp_path):
    missing = tmp_path / "gone.png"
    legacy = tmp_path / "legacy.serp"
    _write_legacy_file(legacy, missing)

    loaded = Scene()
    native.load_scene(loaded, str(legacy))
    resaved = tmp_path / "resaved.serp"
    native.save_scene(loaded, str(resaved))
    loaded_again = Scene()
    native.load_scene(loaded_again, str(resaved))

    assert loaded_again.image_planes[0]["path"] == str(missing)
    assert loaded_again.image_planes[0]["origin"] == [1.0, 2.0, 3.0]
