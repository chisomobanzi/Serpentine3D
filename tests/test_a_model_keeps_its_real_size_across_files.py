"""A model keeps its real size on the way into and out of a file (#101).

An inch drawing wrote STEP with inch numbers and a millimetre label, so a
1 in cube arrived elsewhere as a 1 mm one. The other way, a 25.4 mm STEP
cube came into an inch drawing as 25.4 in, a Rhino file in inches came
into a millimetre drawing 25.4 times too small, and so did a .serp saved
in inches. Each format now says, or is told, what unit its numbers are in,
the way SketchUp's importer already was.
"""

import re

import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.deferred import DeferredShape
from serpentine3d.core.scene import Scene
from serpentine3d.fileio import export_file, import_file, native
from serpentine3d.scripting import Document

rhino3dm = pytest.importorskip("rhino3dm")


def _size(shape):
    """Edge lengths, to a part in a million: a brep read from a file
    carries its tolerance in its box, and scaling scales that too."""
    lo, hi = g.bbox(shape)
    return [round(b - a, 6) for a, b in zip(lo, hi)]


def _cube(side):
    return [pytest.approx(side, rel=1e-6)] * 3


def _sizes(scene):
    return [_size(o.shape) for o in scene.all()]


def _cube_scene(units, side):
    scene = Scene()
    scene.units = units
    scene.add(g.make_box((0, 0, 0), side, side, side), name="Cube")
    return scene


# -- STEP --------------------------------------------------------------

def test_an_inch_drawing_writes_step_in_inches(tmp_path):
    path = str(tmp_path / "inch.step")
    export_file(_cube_scene("in", 1.0), path)

    text = open(path, encoding="utf-8", errors="replace").read()
    assert "CONVERSION_BASED_UNIT('INCH'" in text
    back = Scene()
    import_file(back, path)
    assert _sizes(back) == [_cube(25.4)], \
        "A 1 in cube must arrive in a millimetre drawing as 25.4 mm"


def test_a_millimetre_drawing_still_writes_millimetres(tmp_path):
    path = str(tmp_path / "mm.step")
    export_file(_cube_scene("mm", 25.4), path)

    text = open(path, encoding="utf-8", errors="replace").read()
    assert re.search(r"SI_UNIT\(\s*\.MILLI\.\s*,\s*\.METRE\.\s*\)", text)
    assert "INCH" not in text.upper()


def test_a_millimetre_step_arrives_in_an_inch_drawing_at_its_size(tmp_path):
    path = str(tmp_path / "mm.step")
    export_file(_cube_scene("mm", 25.4), path)
    inch = Scene()
    inch.units = "in"
    notes = []

    import_file(inch, path, notes=notes)

    assert _sizes(inch) == [_cube(1.0)]
    assert notes and "millimetres" in notes[0] and "inches" in notes[0]


def test_a_step_in_the_drawings_own_unit_says_nothing(tmp_path):
    path = str(tmp_path / "mm.step")
    export_file(_cube_scene("mm", 25.4), path)
    back = Scene()
    notes = []

    import_file(back, path, notes=notes)

    assert _sizes(back) == [_cube(25.4)]
    assert notes == []


# -- Rhino -------------------------------------------------------------

def _rhino_file(tmp_path, unit, name="cube.3dm"):
    """A 1-unit cube shown and another on a switched-off layer, so the
    import defers it: both paths have to come out the same size."""
    model = rhino3dm.File3dm()
    model.Settings.ModelUnitSystem = unit
    shown = rhino3dm.Layer()
    shown.Name = "Shown"
    off = rhino3dm.Layer()
    off.Name = "Off"
    off.Visible = False
    for i, layer in enumerate((shown, off)):
        attrs = rhino3dm.ObjectAttributes()
        attrs.LayerIndex = model.Layers.Add(layer)
        attrs.Name = layer.Name
        box = rhino3dm.Box(rhino3dm.BoundingBox(3 * i, 0, 0, 3 * i + 1, 1, 1))
        model.Objects.AddBrep(rhino3dm.Brep.CreateFromBox(box), attrs)
    path = str(tmp_path / name)
    model.Write(path, 7)
    return path


def _item_sizes(items):
    out = {}
    for name, shape, _ in items:
        shapes = shape.shapes() if isinstance(shape, DeferredShape) else [shape]
        out[name] = [_size(s) for s in shapes]
    return out


def test_a_rhino_file_in_inches_arrives_at_its_real_size(tmp_path):
    path = _rhino_file(tmp_path, rhino3dm.UnitSystem.Inches)
    scene = Scene()
    notes = []

    import_file(scene, path, notes=notes)

    by_name = {o.name: o for o in scene.all()}
    assert not by_name["Off"].shape_ready, "Hidden objects still wait"
    assert _size(by_name["Shown"].shape) == _cube(25.4)
    assert _size(by_name["Off"].shape) == _cube(25.4)
    assert notes and "inches" in notes[0]


def test_the_parallel_reader_converts_units_too(tmp_path):
    from serpentine3d.fileio import rhino_parallel as rp
    path = _rhino_file(tmp_path, rhino3dm.UnitSystem.Inches)

    items = rp.import_3dm_parallel(path, workers=2, units="mm")

    assert _item_sizes(items) == {"Shown": [_cube(25.4)],
                                  "Off": [_cube(25.4)]}


def test_a_rhino_file_in_the_drawings_units_is_left_alone(tmp_path):
    path = _rhino_file(tmp_path, rhino3dm.UnitSystem.Feet)
    scene = Scene()
    scene.units = "ft"
    notes = []

    import_file(scene, path, notes=notes)

    assert _sizes(scene) == [_cube(1.0)] * 2
    assert notes == []


def test_an_inch_drawing_writes_a_rhino_file_in_inches(tmp_path):
    path = str(tmp_path / "inch.3dm")
    export_file(_cube_scene("in", 1.0), path)

    model = rhino3dm.File3dm.Read(path)
    assert model.Settings.ModelUnitSystem == rhino3dm.UnitSystem.Inches
    back = Scene()
    import_file(back, path)
    assert _sizes(back) == [_cube(25.4)]


# -- .serp merge --------------------------------------------------------

def test_an_inch_serp_merged_into_millimetres_keeps_its_size(tmp_path):
    inch = _cube_scene("in", 1.0)
    cube = inch.all()[0]
    inch.named_views["Corner"] = {
        "target": [1.0, 2.0, 3.0], "distance": 10.0, "azimuth": 30.0,
        "elevation": 20.0, "fov": 45.0, "sensor": None,
        "projection": "perspective"}
    inch.add_record("extrude", [cube.id], cube.id, direction=[0, 0, 1],
                    dist=2.0, cap=True)
    path = str(tmp_path / "inch.serp")
    native.save_scene(inch, path)
    mm = Scene()
    notes = []

    import_file(mm, path, notes=notes)

    assert _sizes(mm) == [_cube(25.4)]
    view = mm.named_views["Corner"]
    assert view["target"] == pytest.approx([25.4, 50.8, 76.2])
    assert view["distance"] == pytest.approx(254.0)
    assert view["azimuth"] == 30.0
    (record,) = mm.history_records
    assert record["params"]["dist"] == pytest.approx(50.8), \
        "A rebuild must extrude the distance it did before, in mm"
    assert notes and "inches" in notes[0]
    assert mm.units == "mm", "Merging never changes the drawing's units"


# -- saying so ----------------------------------------------------------

def test_the_import_command_says_it_converted(tmp_path):
    path = str(tmp_path / "inch.step")
    export_file(_cube_scene("in", 1.0), path)
    doc = Document()

    messages = doc.run("import", [path])

    assert any("Imported 1 object(s)" in m and "inches" in m
               and "millimetres" in m for m in messages), messages


# -- DXF -----------------------------------------------------------------

@pytest.mark.parametrize("units,code", [("mm", 4), ("in", 1), ("ft", 2)])
def test_a_dxf_says_the_unit_it_was_drawn_in(tmp_path, units, code):
    """ezdxf labels a new drawing metres unless told, so every DXF said
    metres, and Rhino opened a millimetre one 1000 times too big."""
    import ezdxf
    scene = Scene()
    scene.units = units
    scene.add(g.make_line((0, 0, 0), (1, 0, 0)), name="Edge")
    path = str(tmp_path / "edge.dxf")

    export_file(scene, path)

    assert ezdxf.readfile(path).header["$INSUNITS"] == code


@pytest.fixture
def window(monkeypatch, tmp_path):
    monkeypatch.setenv("SERP3D_CONFIG", str(tmp_path / "s.json"))
    monkeypatch.setenv("SERP3D_NO_RECOVER", "1")
    from serpentine3d.app import MainWindow
    w = MainWindow()
    yield w
    w.mark_saved()
    w.close()


def test_the_window_says_it_converted_on_import_and_open(window, tmp_path):
    path = str(tmp_path / "inch.step")
    export_file(_cube_scene("in", 1.0), path)

    window._import_path(path)
    window._open_path(path)

    history = window.command_line.echo_view.toPlainText().splitlines()
    assert any(line.startswith("Imported 1 object(s)")
               and "converted from inches to millimetres" in line
               for line in history), history
    assert any(line.startswith(f"Opened {path}")
               and "converted from inches to millimetres" in line
               for line in history), history
    # Open on anything but a .serp adds, as it always has.
    assert _sizes(window.scene) == [_cube(25.4)] * 2
