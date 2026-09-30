"""A HATCH in a DXF arrives as a hatch, and one leaves as a HATCH (#33).

Asked for alongside model hatches: bring hatches in from .dxf files. The
importer skipped the HATCH entity altogether, so a drawing's fills simply
were not there.

A DXF hatch is a set of boundary paths (lines, arcs, ellipses, splines,
any of them nested as holes) and a pattern, written out line by line with
each line's angle and the offset to the next one. That is read as it is
written: the boundaries become the hatch's region, SOLID a solid fill, and
the pattern its angle and spacing, with two directions at right angles
making a cross. Dashes are not drawn, so a dashed pattern comes in as its
lines at the right angle and spacing.
"""

from __future__ import annotations

import math

import ezdxf
import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.hatch import HatchShape
from serpentine3d.core.scene import Scene
from serpentine3d.fileio.dxf import export_dxf, import_dxf

HOLE_AREA = math.pi * 4          # the round hole of radius 2


@pytest.fixture
def imported(tmp_path):
    def go(build):
        doc = ezdxf.new("R2010")
        build(doc.modelspace())
        path = tmp_path / "h.dxf"
        doc.saveas(path)
        scene = Scene()
        import_dxf(scene, str(path))
        return [o for o in scene.all() if o.kind == "hatch"]
    return go


def _square_with_hole(hatch, extrusion=None):
    hatch.paths.add_polyline_path([(0, 0), (10, 0), (10, 10), (0, 10)],
                                  is_closed=True)
    edges = hatch.paths.add_edge_path()
    edges.add_arc((5, 5), 2, 0, 360)
    return hatch


def test_a_line_pattern_comes_in_at_its_angle_and_spacing(imported):
    def build(m):
        h = m.add_hatch()
        h.set_pattern_fill("ANSI31", scale=2.0, angle=30.0)
        _square_with_hole(h)

    (h,) = imported(build)

    assert h.shape.pattern == "lines"
    assert h.shape.angle == pytest.approx(75.0), "ANSI31 is 45 degrees, turned 30"
    assert h.shape.spacing == pytest.approx(3.175 * 2)
    assert g.surface_area(h.shape) == pytest.approx(100 - HOLE_AREA, rel=1e-3)


def test_the_hole_is_a_hole(imported):
    def build(m):
        h = m.add_hatch()
        h.set_pattern_fill("ANSI31", scale=0.2)
        _square_with_hole(h)

    (h,) = imported(build)

    for a, b in h.shape.pattern_segments():
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        assert math.dist(mid, (5, 5)) > 2.0 - 1e-3


def test_a_solid_fill_comes_in_solid(imported):
    def build(m):
        h = m.add_hatch()
        h.set_solid_fill()
        _square_with_hole(h)

    (h,) = imported(build)

    assert h.shape.pattern == "solid"


def test_two_directions_at_right_angles_come_in_as_a_cross(imported):
    def build(m):
        h = m.add_hatch()
        h.set_pattern_fill("ANSI37", scale=1.0)
        _square_with_hole(h)

    (h,) = imported(build)

    assert h.shape.pattern == "cross"
    assert h.shape.spacing == pytest.approx(3.175)


def test_separate_islands_become_separate_hatches(imported):
    def build(m):
        h = m.add_hatch()
        h.set_solid_fill()
        h.paths.add_polyline_path([(0, 0), (4, 0), (4, 4), (0, 4)], is_closed=True)
        h.paths.add_polyline_path([(10, 0), (14, 0), (14, 4), (10, 4)],
                                  is_closed=True)

    assert len(imported(build)) == 2


def test_a_hatch_in_a_flipped_plane_lands_where_it_was_drawn(imported):
    """Extrusion -Z is common in DXF from mirrored work: its x runs the
    other way, so the square belongs at negative x."""
    def build(m):
        h = m.add_hatch(dxfattribs={"extrusion": (0, 0, -1)})
        h.set_solid_fill()
        h.paths.add_polyline_path([(0, 0), (10, 0), (10, 10), (0, 10)],
                                  is_closed=True)

    (h,) = imported(build)

    lo, hi = g.bbox(h.shape)
    assert (lo[0], hi[0]) == pytest.approx((-10.0, 0.0), abs=1e-6)


def test_other_entities_still_come_in_beside_it(tmp_path):
    doc = ezdxf.new("R2010")
    m = doc.modelspace()
    m.add_line((0, 0), (5, 5))
    h = m.add_hatch()
    h.set_solid_fill()
    h.paths.add_polyline_path([(0, 0), (4, 0), (4, 4)], is_closed=True)
    doc.saveas(tmp_path / "x.dxf")
    scene = Scene()

    import_dxf(scene, str(tmp_path / "x.dxf"))

    assert sorted(o.kind for o in scene.all()) == ["curve", "hatch"]


# --- and out again ----------------------------------------------------------

@pytest.mark.parametrize("pattern", ["lines", "cross", "solid"])
def test_a_hatch_goes_out_and_comes_back_the_same(tmp_path, pattern):
    curves = [g.make_polyline([(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)],
                              closed=True),
              g.make_circle((5, 5, 0), 2.0)]
    (face,) = g.planar_regions(curves)
    scene = Scene()
    scene.add(HatchShape(face, pattern, angle=30.0, spacing=0.8))
    path = str(tmp_path / "out.dxf")

    export_dxf(scene, path)
    back = Scene()
    import_dxf(back, path)

    hatches = [o.shape for o in back.all() if o.kind == "hatch"]
    assert len(hatches) == 1
    h = hatches[0]
    assert h.pattern == pattern
    if pattern != "solid":
        assert h.angle % 90 == pytest.approx(30.0)
        assert h.spacing == pytest.approx(0.8)
    assert g.surface_area(h) == pytest.approx(100 - HOLE_AREA, rel=2e-3)
