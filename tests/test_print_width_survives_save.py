"""A layer's print width has to outlive the save, native or 3dm.

Print width is a layer attribute like colour or the display lineweight, so
saving a drawing and opening it again has to bring it back. A file written
before print width existed has none, and that reads back as the device
default, the same as a fresh layer.

Rhino keeps the same field on its layers as PlotWeight, in millimetres, so
a 3dm carries it in and out: a layer plotted at 0.5mm in Rhino imports at
0.5mm here, and one set here exports so Rhino reads it the same.
"""

from __future__ import annotations

import json

import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.layers import DEFAULT_LAYER_ID
from serpentine3d.core.scene import Scene
from serpentine3d.fileio import native

r3 = pytest.importorskip("rhino3dm")


def _round_trip_native(scene, tmp_path):
    path = str(tmp_path / "doc.serp3d")
    native.save_scene(scene, path)
    out = Scene()
    native.load_scene(out, path)
    return out


def test_native_save_keeps_the_print_width(tmp_path):
    scene = Scene()
    lid = scene.layers.create("Heavy").id
    scene.layers.set_print_width(lid, 0.8)
    out = _round_trip_native(scene, tmp_path)
    assert out.layers.find_by_name("Heavy").print_width == 0.8


def test_an_older_file_without_print_width_reads_as_default(tmp_path):
    """The field is younger than the format, so a file predating it is legal
    and its layers plot at the device default."""
    scene = Scene()
    scene.layers.set_color(DEFAULT_LAYER_ID, (0.5, 0.5, 0.5))
    path = str(tmp_path / "old.serp3d")
    native.save_scene(scene, path)
    # strip the field back out, the way a file written before it would read
    doc = json.loads((tmp_path / "old.serp3d").read_bytes()
                     if path.endswith(".json") else _extract_document(path))
    for ld in doc["layers"]:
        ld.pop("print_width", None)
    _rewrite_document(path, doc)
    out = Scene()
    native.load_scene(out, path)
    assert out.layers.get(DEFAULT_LAYER_ID).print_width == 0.0


def test_3dm_export_writes_plot_weight(tmp_path):
    scene = Scene()
    lid = scene.layers.create("Plot").id
    scene.layers.set_print_width(lid, 0.35)
    scene.add(g.make_box((0.0, 0.0, 0.0), 1.0, 1.0, 1.0), layer_id=lid)
    from serpentine3d.fileio import rhino
    path = str(tmp_path / "out.3dm")
    rhino.export_3dm(scene, path)
    model = r3.File3dm.Read(path)
    weights = {model.Layers[i].Name: model.Layers[i].PlotWeight
               for i in range(len(model.Layers))}
    assert weights["Plot"] == pytest.approx(0.35)


def test_read_layers_carries_plot_weight():
    from serpentine3d.fileio import rhino
    model = r3.File3dm()
    layer = r3.Layer()
    layer.Name = "Fine"
    layer.PlotWeight = 0.13
    model.Layers.Add(layer)
    read = rhino.read_layers(model)
    idx = next(i for i, d in read.items() if d["name"] == "Fine")
    assert read[idx]["print_width"] == pytest.approx(0.13)


def test_read_layers_treats_no_plot_as_default():
    """Rhino's -1 PlotWeight is a pen that does not plot; we have no such
    thing, so it comes in as the device default rather than a negative."""
    from serpentine3d.fileio import rhino
    model = r3.File3dm()
    layer = r3.Layer()
    layer.Name = "NoPlot"
    layer.PlotWeight = -1.0
    model.Layers.Add(layer)
    read = rhino.read_layers(model)
    idx = next(i for i, d in read.items() if d["name"] == "NoPlot")
    assert read[idx]["print_width"] == 0.0


# -- helpers for the backward-compat test: reach into the container ----------

def _extract_document(path: str) -> str:
    import zipfile
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            return z.read("document.json").decode("utf-8")
    with open(path, encoding="utf-8") as f:
        return f.read()


def _rewrite_document(path: str, doc: dict):
    import zipfile
    payload = json.dumps(doc)
    if zipfile.is_zipfile(path):
        import shutil
        tmp = path + ".tmp"
        with zipfile.ZipFile(path) as zin, \
                zipfile.ZipFile(tmp, "w") as zout:
            for item in zin.namelist():
                data = payload.encode("utf-8") if item == "document.json" \
                    else zin.read(item)
                zout.writestr(item, data)
        shutil.move(tmp, path)
    else:
        with open(path, "w", encoding="utf-8") as f:
            f.write(payload)
