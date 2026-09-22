"""An ellipse in a DXF arrives as that ellipse (issue #28).

Reported as "export an ellipse from Rhino to DXF and it is not an ellipse
any more", with the tell that Serpentine's own DXF re-imports fine. That
asymmetry is the clue and not a contradiction: the exporter writes every
curve as a spline through 64 sampled points, so its ellipse comes back as
an interpolated look-alike and never exercises the code that was wrong.
Rhino writes the real thing, and the real thing was read carelessly.

A DXF can say "ellipse" two ways, and both were lossy:

  ELLIPSE  centre, a major-axis *vector*, a minor/major ratio, the plane's
           normal, and the parameters it is trimmed between. Only the
           vector's *length* was read, so every ellipse came back lying in
           world XY with its major axis along world X, and an elliptical
           arc came back whole.

  SPLINE   a NURBS curve, where a conic keeps its shape in the weights and
           its parameterisation in the knots. Both were dropped and a
           uniform knot vector invented, which turns an exact ellipse into
           a blob that misses it by half a unit in ten.
"""

from __future__ import annotations

import math

import ezdxf
import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene
from serpentine3d.fileio.dxf import import_dxf

MAJOR, MINOR = 10.0, 4.0


@pytest.fixture
def imported(tmp_path):
    """Write entities into a DXF, read it back, hand over the shapes."""
    def go(build):
        doc = ezdxf.new("R2010")
        build(doc.modelspace())
        path = tmp_path / "e.dxf"
        doc.saveas(path)
        scene = Scene()
        import_dxf(scene, str(path))
        return [o.shape for o in scene.all()]
    return go


def _extent(shape):
    lo, hi = g.bbox(shape)
    return tuple(round(hi[i] - lo[i], 3) for i in range(3))


def _off_the_ellipse(shape, a=MAJOR, b=MINOR, plane=("x", "y")):
    """How far the worst sampled point strays from the true ellipse."""
    axis = {"x": 0, "y": 1, "z": 2}
    i, j = axis[plane[0]], axis[plane[1]]
    return max(abs((p[i] / a) ** 2 + (p[j] / b) ** 2 - 1.0)
               for p in g.sample_curve(shape, 200))


# --- the ELLIPSE entity ----------------------------------------------------

def test_an_ellipse_keeps_the_direction_of_its_major_axis(imported):
    """Turned 30 degrees, it must not come back square to the world."""
    a = math.radians(30)
    major = (MAJOR * math.cos(a), MAJOR * math.sin(a), 0)

    shapes = imported(lambda m: m.add_ellipse((0, 0, 0), major_axis=major,
                                              ratio=MINOR / MAJOR))

    assert _extent(shapes[0]) == pytest.approx(
        (2 * math.hypot(MAJOR * math.cos(a), MINOR * math.sin(a)),
         2 * math.hypot(MAJOR * math.sin(a), MINOR * math.cos(a)),
         0.0), abs=1e-3)


def test_an_ellipse_stands_in_the_plane_it_was_drawn_in(imported):
    """Drawn upright in XZ, it must not land flat in XY."""
    shapes = imported(lambda m: m.add_ellipse(
        (0, 0, 0), major_axis=(MAJOR, 0, 0), ratio=MINOR / MAJOR,
        dxfattribs={"extrusion": (0, 1, 0)}))

    assert _extent(shapes[0]) == pytest.approx((20.0, 0.0, 8.0), abs=1e-3)


def test_an_elliptical_arc_stays_an_arc(imported):
    """Trimmed to half, it must not come back as the whole ellipse."""
    shapes = imported(lambda m: m.add_ellipse(
        (0, 0, 0), major_axis=(MAJOR, 0, 0), ratio=MINOR / MAJOR,
        start_param=0.0, end_param=math.pi))

    assert not g.is_closed_curve(shapes[0]), "a half ellipse is not closed"
    assert _extent(shapes[0]) == pytest.approx((20.0, 4.0, 0.0), abs=1e-3)


def test_a_whole_ellipse_is_a_closed_curve(imported):
    shapes = imported(lambda m: m.add_ellipse(
        (0, 0, 0), major_axis=(MAJOR, 0, 0), ratio=MINOR / MAJOR))

    assert g.is_closed_curve(shapes[0])
    assert _off_the_ellipse(shapes[0]) < 1e-6


def test_an_ellipse_off_the_origin_keeps_its_centre(imported):
    shapes = imported(lambda m: m.add_ellipse(
        (7, -3, 2), major_axis=(MAJOR, 0, 0), ratio=MINOR / MAJOR))

    lo, hi = g.bbox(shapes[0])
    centre = tuple((lo[i] + hi[i]) / 2 for i in range(3))
    assert centre == pytest.approx((7, -3, 2), abs=1e-6)


# --- the trim the importer leans on ----------------------------------------

def test_an_arc_is_measured_from_the_axis_it_was_given():
    quarter = g.make_ellipse_axis((0, 0, 0), (1, 0, 0), MAJOR, MINOR,
                                  start=0.0, end=math.pi / 2)

    ends = [tuple(round(v, 6) for v in p) for p in g.curve_endpoints(quarter)]
    assert (MAJOR, 0.0, 0.0) in ends
    assert (0.0, MINOR, 0.0) in ends


def test_an_arc_is_still_measured_from_it_when_it_is_the_short_axis():
    """gp_Elips wants the major radius first, so naming the short axis turns
    the frame a quarter. The trim has to turn with it or the arc comes out
    somewhere else entirely."""
    quarter = g.make_ellipse_axis((0, 0, 0), (1, 0, 0), MINOR, MAJOR,
                                  start=0.0, end=math.pi / 2)

    ends = [tuple(round(v, 6) for v in p) for p in g.curve_endpoints(quarter)]
    assert (MINOR, 0.0, 0.0) in ends, "t=0 is along the axis it was handed"
    assert (0.0, MAJOR, 0.0) in ends


def test_a_full_turn_asked_for_as_a_trim_is_just_the_ellipse():
    whole = g.make_ellipse_axis((0, 0, 0), (1, 0, 0), MAJOR, MINOR,
                                start=0.0, end=2 * math.pi)

    assert g.is_closed_curve(whole)


# --- an ellipse written as a NURBS curve -----------------------------------

def _rational_ellipse(m):
    """The textbook exact ellipse: degree 2, four quarters, weights sqrt2/2."""
    w = math.sqrt(2) / 2
    s = m.add_spline(degree=2, dxfattribs={"flags": 4})
    s.control_points = [(10, 0, 0), (10, 4, 0), (0, 4, 0), (-10, 4, 0),
                        (-10, 0, 0), (-10, -4, 0), (0, -4, 0), (10, -4, 0),
                        (10, 0, 0)]
    s.weights = [1, w, 1, w, 1, w, 1, w, 1]
    s.knots = [0, 0, 0, .25, .25, .5, .5, .75, .75, 1, 1, 1]


def test_a_rational_spline_ellipse_is_an_exact_ellipse(imported):
    shapes = imported(_rational_ellipse)

    assert _off_the_ellipse(shapes[0]) < 1e-6, (
        "the weights are what make those poles an ellipse")


# --- what already worked keeps working -------------------------------------

def test_a_plain_spline_still_imports(imported):
    """No weights, no knots: the old uniform-clamped reading is still right."""
    def build(m):
        s = m.add_spline(degree=3)
        s.control_points = [(0, 0, 0), (3, 5, 0), (7, -5, 0), (10, 0, 0)]

    shapes = imported(build)

    assert len(shapes) == 1
    assert g.curve_length(shapes[0]) > 10


def test_a_fitted_spline_still_imports(imported):
    shapes = imported(lambda m: m.add_spline(
        fit_points=[(0, 0, 0), (5, 5, 0), (10, 0, 0)]))

    assert len(shapes) == 1


def test_circles_arcs_and_lines_are_untouched(imported):
    def build(m):
        m.add_circle((0, 0, 0), 5)
        m.add_line((0, 0, 0), (1, 1, 0))
        m.add_arc((0, 0, 0), 5, 0, 90)

    assert len(imported(build)) == 3


def test_an_ellipse_survives_the_round_trip_through_our_own_exporter(tmp_path):
    """The half of the report that already worked, kept working."""
    from serpentine3d.fileio.dxf import export_dxf

    scene = Scene()
    scene.add(g.make_ellipse((0, 0, 0), MAJOR, MINOR))
    path = tmp_path / "out.dxf"
    export_dxf(scene, str(path))

    back = Scene()
    import_dxf(back, str(path))

    assert len(back.all()) == 1
    assert _off_the_ellipse(back.all()[0].shape) < 1e-3
