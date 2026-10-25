"""A drawing whose hatching 0.12.1 would lose says it needs 0.12.2.

0.12.1 opens a newer file and keeps what it knows of each hatch. It lets
the rest go without a word, and a save there loses it for good:
- a hatch's own colour and background, and a cut's background (#91);
- a cut in any pattern but none, Lines, Cross or Solid, which it fills
  with lines;
- the definitions of the patterns a drawing carries (#92).
So the writer says which release keeps them, as user text (version 6) did,
and 0.12.1 refuses the file by name instead. Hatching it can keep is
written as it always was.
"""

from __future__ import annotations

import json
import zipfile

import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.hatch import HatchShape
from serpentine3d.core.hatch_patterns import merge_into, parse_pat
from serpentine3d.core.layers import section_fill_dict
from serpentine3d.core.layout import Hatch, Layout
from serpentine3d.core.scene import Scene
from serpentine3d.fileio import native

ANSI31 = "*ANSI31, Iron\n45, 0,0, 0,.125\n"


def _saved(scene, tmp_path) -> tuple[dict, str]:
    path = str(tmp_path / "drawing.serp")
    native.save_scene(scene, path)
    with zipfile.ZipFile(path) as z:
        return json.loads(z.read("document.json")), path


def _hatch(scene, pattern="lines"):
    (face,) = g.planar_regions([g.make_polyline(
        [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)], closed=True)])
    return scene.add(HatchShape(face, pattern, spacing=1.0), name="Hatch")


def _box(scene):
    return scene.add(g.make_box((0, 0, 0), 10, 10, 10), name="Box")


def _asks_for_0122(doc):
    assert doc["requires"] == "0.12.2"
    # 0.12.1 reads up to version 6 and refuses anything newer by name.
    assert doc["version"] > 6


# -- what 0.12.1 would let go ---------------------------------------------------

def test_a_hatch_with_a_colour_of_its_own(tmp_path):
    scene = Scene()
    hatch = _hatch(scene)
    scene.update(hatch.id, hatch_style={"color": "#00aa00"})
    _asks_for_0122(_saved(scene, tmp_path)[0])


def test_a_hatch_with_a_background_of_its_own(tmp_path):
    scene = Scene()
    hatch = _hatch(scene)
    scene.update(hatch.id, hatch_style={"background": "none"})
    _asks_for_0122(_saved(scene, tmp_path)[0])


def test_a_layer_whose_cuts_have_a_background(tmp_path):
    scene = Scene()
    _box(scene)
    scene.layers.set_hatch_background("default", "#123456")
    _asks_for_0122(_saved(scene, tmp_path)[0])


@pytest.mark.parametrize("pattern", ["dots", "brick"])
def test_a_layer_cut_in_a_pattern_0121_never_had(tmp_path, pattern):
    scene = Scene()
    _box(scene)
    scene.layers.set_hatch("default", pattern)
    _asks_for_0122(_saved(scene, tmp_path)[0])


def test_an_objects_own_cut_with_a_background(tmp_path):
    scene = Scene()
    box = _box(scene)
    scene.update(box.id, section_fill=section_fill_dict(
        "cross", background="#ffffff"))
    _asks_for_0122(_saved(scene, tmp_path)[0])


def test_an_objects_own_cut_in_a_new_pattern(tmp_path):
    scene = Scene()
    box = _box(scene)
    scene.update(box.id, section_fill=section_fill_dict("squares"))
    _asks_for_0122(_saved(scene, tmp_path)[0])


def test_a_sheet_hatch_in_a_pattern_the_drawing_carries(tmp_path):
    scene = Scene()
    merge_into(scene.hatch_patterns, parse_pat(ANSI31))
    sheet = Layout(name="Sheet")
    sheet.hatches.append(Hatch(points=[[0, 0], [20, 0], [20, 20], [0, 20]],
                               pattern="ANSI31"))
    scene.layouts.append(sheet)
    doc, _path = _saved(scene, tmp_path)
    assert doc["hatch_patterns"], "the drawing should carry ANSI31"
    _asks_for_0122(doc)


def test_0121_refuses_it_by_name(tmp_path, monkeypatch):
    scene = Scene()
    hatch = _hatch(scene)
    scene.update(hatch.id, hatch_style={"color": "#00aa00"})
    _doc, path = _saved(scene, tmp_path)
    monkeypatch.setattr(native, "FORMAT_VERSION", 6)
    with pytest.raises(ValueError, match="0.12.2"):
        native.load_scene(Scene(), path)


# -- what it keeps ---------------------------------------------------------------

def test_hatching_0121_keeps_is_written_as_it_always_was(tmp_path):
    scene = Scene()
    _hatch(scene, "cross")
    box = _box(scene)
    scene.layers.set_hatch("default", "solid")
    scene.layers.set_hatch_background("default", "none")
    scene.update(box.id, section_fill=section_fill_dict("lines", angle=30.0))
    sheet = Layout(name="Sheet")
    sheet.hatches.append(Hatch(points=[[0, 0], [20, 0], [20, 20], [0, 20]],
                               pattern="cross"))
    scene.layouts.append(sheet)
    doc, _path = _saved(scene, tmp_path)
    assert doc["version"] <= 6
    assert doc.get("requires") != "0.12.2"


def test_a_hatch_by_layer_again_counts_as_none_of_its_own(tmp_path):
    scene = Scene()
    hatch = _hatch(scene)
    scene.update(hatch.id, hatch_style={"color": "#00aa00"})
    scene.update(hatch.id, hatch_style=None)
    doc, _path = _saved(scene, tmp_path)
    assert doc.get("requires") != "0.12.2"
