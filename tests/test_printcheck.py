"""printcheck: 3D-print readiness analysis on the tessellated mesh — TDD.

Checks that matter before a slice: watertight (closed, no holes), manifold
(no edge shared by >2 faces), no degenerate facets, downward overhang area
(needs supports), min wall thickness, and the print size.
"""

import numpy as np

from serpentine3d.core import geometry as g
from serpentine3d.core import printcheck


def test_solid_box_passes(tmp_path):
    box = g.make_box((0, 0, 0), 20, 20, 20)
    r = printcheck.analyze(box)
    assert r["watertight"] and r["manifold"]
    assert r["open_edges"] == 0 and r["nonmanifold_edges"] == 0
    assert r["degenerate"] == 0
    assert r["ok"]
    assert r["min_wall"] is None or r["min_wall"] > 5     # solid, not thin


def test_filleted_solid_is_print_ready():
    # regression: tessellation artifacts at fillet corners must NOT read as
    # holes/non-manifold on a valid B-rep solid.
    box = g.fillet_edges(g.make_box((0, 0, 0), 40, 25, 12), 3)
    r = printcheck.analyze(box)
    assert r["watertight"] and r["manifold"] and r["ok"]
    assert r["open_edges"] == 0 and r["degenerate"] == 0


def test_open_surface_not_watertight():
    disc = g.planar_face(g.make_circle((0, 0, 0), 5))     # single open face
    r = printcheck.analyze(disc)
    assert not r["watertight"]
    assert r["open_edges"] > 0
    assert not r["ok"]


def test_thin_plate_flags_thin_wall():
    plate = g.make_box((0, 0, 0), 40, 40, 0.6)
    r = printcheck.analyze(plate, wall_threshold=1.0)
    assert r["min_wall"] is not None
    assert r["min_wall"] < 1.0                            # ~0.6 mm plate
    assert r["thin"]


def test_overhang_ignores_flat_base_flags_real_overhangs():
    # a cube resting flat needs no supports (its base is on the bed);
    # a sphere floating above the plate overhangs heavily on its underside.
    cube = g.make_box((0, 0, 0), 10, 10, 10)
    assert printcheck.analyze(cube)["overhang_fraction"] < 0.05
    # a sphere above the bed: only the bottom 45° cap is steeper than 45°
    # from vertical, area = (1-cos45°)/2 ≈ 0.146 of the surface.
    sphere = g.make_sphere((0, 0, 20), 10)
    assert 0.10 < printcheck.analyze(sphere)["overhang_fraction"] < 0.20


def test_size_reported():
    box = g.make_box((0, 0, 0), 12, 34, 5)
    r = printcheck.analyze(box)
    assert np.allclose(sorted(r["size"]), [5, 12, 34], atol=0.05)
