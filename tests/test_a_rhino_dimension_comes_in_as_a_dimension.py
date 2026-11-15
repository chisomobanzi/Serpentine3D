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
