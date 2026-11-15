"""Linear dimensions Rhino wrote come in as dimensions that measure (#124).

rhino3dm gives a dimension's plane, text and style but not its points, so
the import reads those from the object's openNURBS encoding. The fixture is
four real dimensions from McNeel's openNURBS examples, saved as Rhino 7 and
as Rhino 8 (tests/data/make_rhino_dimensions.py); the manifest says where
Rhino put each point.
"""

import json
from pathlib import Path

import numpy as np
import pytest

from serpentine3d import fileio
from serpentine3d.core.dimension import DimensionShape
from serpentine3d.core.scene import Scene

DATA = Path(__file__).parent / "data"
EXPECTED = json.loads(
    (DATA / "rhino_linear_dimensions.json").read_text())["dimensions"]


def _dims(version):
    scene = Scene()
    fileio.import_file(scene,
                       str(DATA / f"rhino_linear_dimensions_{version}.3dm"))
    return scene, [o.shape for o in scene.all()
                   if isinstance(o.shape, DimensionShape)]


def _matching(dim):
    def miss(e):
        return (np.linalg.norm(np.subtract(e["points"]["defpt1"], dim.p1))
                + np.linalg.norm(np.subtract(e["points"]["defpt2"], dim.p2)))
    best = min(EXPECTED, key=miss)
    assert miss(best) == pytest.approx(0.0, abs=1e-6), \
        "measures between the points Rhino measured"
    return best


@pytest.mark.parametrize("version", ["v7", "v8"])
def test_every_rhino_dimension_comes_in_measuring_what_rhino_measured(
        version):
    scene, dims = _dims(version)
    assert len(dims) == len(EXPECTED) == len(scene.all())
    assert {_matching(d)["name"] for d in dims} == \
        {e["name"] for e in EXPECTED}
    for dim in dims:
        want = _matching(dim)
        assert dim.measured == pytest.approx(want["measurement"], abs=1e-9)
        assert dim.label == want["text"], "says what Rhino said"


@pytest.mark.parametrize("version", ["v7", "v8"])
def test_its_line_is_where_rhino_drew_it(version):
    _scene, dims = _dims(version)
    assert len(dims) == len(EXPECTED)
    for dim in dims:
        want = _matching(dim)
        u = np.asarray(dim.direction, float)
        for name in ("arrowpt1", "arrowpt2", "dimline"):
            off = np.subtract(want["points"][name], dim.at)
            assert np.linalg.norm(off - np.dot(off, u) * u) == \
                pytest.approx(0.0, abs=1e-6), f"{want['name']} {name}"
        assert abs(np.dot(dim.normal, want["plane_x"])) < 1e-9
        assert abs(np.dot(dim.normal, want["plane_y"])) < 1e-9


def test_a_dimension_in_a_scaled_block_says_what_rhino_says():
    """Rhino shows a dimension inside a block with the block's own
    measurement, however the block is scaled: a drawing sheet placed at
    1/25 still reads 910, not 36.4. tests/data/make_rhino_dimension_in_block.py
    puts the 40.00 dimension in a block placed at 1/25 and at 2."""
    scene = Scene()
    fileio.import_file(scene,
                       str(DATA / "rhino_dimension_in_scaled_blocks.3dm"))
    dims = sorted((o.shape for o in scene.all()
                   if isinstance(o.shape, DimensionShape)),
                  key=lambda d: d.p1[0])
    assert len(dims) == 2
    assert [d.label for d in dims] == ["40.00", "40.00"]
    small, big = dims[1], dims[0]          # placed at x=500 and at y=500
    assert np.linalg.norm(np.subtract(small.p2, small.p1)) == \
        pytest.approx(40.0 / 25.0), "drawn where the block puts it"
    assert np.linalg.norm(np.subtract(big.p2, big.p1)) == pytest.approx(80.0)


# -- alternate units ----------------------------------------------------------

def _from_text(said, measured):
    """A dimension measuring `measured` with Rhino's text `said`."""
    from serpentine3d.fileio.rhino import _written_look
    return DimensionShape((0, 0, 0), (measured, 0, 0), (0, -10, 0),
                          **_written_look(said, measured))


def test_rhino_s_alternate_units_come_in_under_a_number_that_still_measures():
    """A style with alternate units below the line writes
    '910\\r\\n [2'-11 3/4"]'. The 910 is the measurement; what is in the
    brackets Rhino worked out from it."""
    dim = _from_text('910\r\n [2\'-11 3/4"]', 910.0)
    assert dim.label == '910\n[2\'-11 3/4"]'
    assert dim.style["text"] == "", "not typed over the number"
    beside = _from_text('910 [2\'-11 3/4"]', 910.0)
    assert beside.label == '910 [2\'-11 3/4"]', "on the line, as written"


def test_the_alternate_units_go_once_they_are_no_longer_true():
    """They were worked out for 910; scaled, the number follows and the
    old alternate would be wrong, so it is left off."""
    dim = _from_text('910\r\n [2\'-11 3/4"]', 910.0)
    big = dim.transformed(np.diag([2.0, 2.0, 2.0, 1.0]))
    assert big.label == "1820"


def test_a_suffix_and_alternate_units_both_come_through():
    dim = _from_text('910 mm\r\n[35.83"]', 910.0)
    assert dim.label == '910 mm\n[35.83"]'


def test_text_that_is_not_the_measurement_is_still_typed_text():
    dim = _from_text("SEE DETAIL\r\nA", 910.0)
    assert dim.label == "SEE DETAIL\nA"


def test_a_drawing_with_alternate_units_asks_for_the_release_that_keeps_them(
        tmp_path, monkeypatch):
    """0.13.0 reads a dimension's look through a fixed list and fails on a
    key it has never seen, partway into the load. So a drawing with
    alternate units asks for 0.13.1 up front, and one without is written as
    0.13.0 wrote it."""
    import json
    import zipfile

    from serpentine3d.fileio import native

    def saved(dim):
        scene = Scene()
        scene.add(dim)
        path = str(tmp_path / f"d{len(list(tmp_path.iterdir()))}.serp")
        native.save_scene(scene, path)
        with zipfile.ZipFile(path) as z:
            return json.loads(z.read("document.json")), path

    doc, path = saved(_from_text('910\r\n [2\'-11 3/4"]', 910.0))
    assert (doc["version"], doc["requires"]) == (10, "0.13.1")
    back = Scene()
    native.load_scene(back, path)
    (obj,) = back.all()
    assert obj.shape.label == '910\n[2\'-11 3/4"]'
    monkeypatch.setattr(native, "FORMAT_VERSION", 9)
    with pytest.raises(ValueError, match=r"0\.13\.1"):
        native.load_scene(Scene(), path)
    monkeypatch.undo()

    plain, plain_path = saved(_from_text("910", 910.0))
    assert (plain["version"], plain["requires"]) == (9, "0.13.0")
    monkeypatch.setattr(native, "FORMAT_VERSION", 9)
    native.load_scene(Scene(), plain_path)


def test_alternate_units_kept_only_in_a_block_definition_still_ask(tmp_path):
    import json
    import zipfile

    from serpentine3d.fileio import native
    scene = Scene()
    scene.block_defs["b1"] = {
        "name": "DIMMED",
        "shapes": [_from_text('910\r\n [2\'-11 3/4"]', 910.0)]}
    path = str(tmp_path / "block.serp")
    native.save_scene(scene, path)
    with zipfile.ZipFile(path) as z:
        doc = json.loads(z.read("document.json"))
    assert (doc["version"], doc["requires"]) == (10, "0.13.1")
