"""A solid measures its true volume and area, whatever its faces are made of.

Reported (#104): a bow limb from Rhino imported as a valid solid whose
volume read 0.81% low, while its area, and a fine mesh of it, were right.

OpenCascade's default integration takes a fixed number of sample points
across each face, chosen from the face's boundary curves and from one
direction of its surface, never the other. A NURBS face made of many spans
in that other direction got 8 points across 16 spans of the limb's side
and read 12% short. The area integral looks both ways, which is why the
area came out right; on surfaces with more spans than the limb's it is out
too, by up to 0.8% on the openNURBS samples.

The same blind spot reads Serpentine's own extrusions and revolves off, a
ring by 1.5%, and the crease split from #34 broke a NURBS face that is
closed both ways: a ring scaled to an oval read half its volume.

A face of many spans is now integrated with OpenCascade's adaptive method,
which takes its points span by span; a face that is one smooth piece keeps
the default, which is exact there. Swept faces are converted to NURBS
first, so that the adaptive method can see their spans, and a NURBS face
closed both ways is no longer split at its creases. The answers below come
from the profile alone, by Green's theorem or Pappus, with no surface
integration in them.
"""

from __future__ import annotations

import math

import pytest
import rhino3dm as r3
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.BRepBuilderAPI import (BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace,
                                BRepBuilderAPI_MakeWire, BRepBuilderAPI_NurbsConvert)
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
from OCP.Geom import Geom_BSplineCurve
from OCP.TColgp import TColgp_Array1OfPnt
from OCP.TColStd import TColStd_Array1OfInteger, TColStd_Array1OfReal
from OCP.gp import gp_Pnt, gp_Vec

from serpentine3d.core import geometry as g
from serpentine3d.fileio.rhino import import_3dm

# Gauss-Legendre, 8 points
_GAUSS = [(-0.9602898564975363, 0.1012285362903763), (-0.7966664774136267, 0.2223810344533745),
          (-0.5255324099163290, 0.3137066458778873), (-0.1834346424956498, 0.3626837833783620),
          (0.1834346424956498, 0.3626837833783620), (0.5255324099163290, 0.3137066458778873),
          (0.7966664774136267, 0.2223810344533745), (0.9602898564975363, 0.1012285362903763)]


def _along(curve, f, t0=None, t1=None, pieces=16):
    """The integral of f(point, derivative) dt along a Geom curve: eight
    Gauss points on each sixteenth of each knot span, which is exact to the
    last digit for anything smooth on a span."""
    t0 = curve.FirstParameter() if t0 is None else t0
    t1 = curve.LastParameter() if t1 is None else t1
    cuts = {t0, t1}
    if hasattr(curve, "NbKnots"):
        cuts |= {curve.Knot(i) for i in range(1, curve.NbKnots() + 1)
                 if t0 < curve.Knot(i) < t1}
    cuts = sorted(cuts)
    total = 0.0
    for a, b in zip(cuts, cuts[1:]):
        for j in range(pieces):
            lo, hi = a + (b - a) * j / pieces, a + (b - a) * (j + 1) / pieces
            h = (hi - lo) / 2
            for x, w in _GAUSS:
                p, d = gp_Pnt(), gp_Vec()
                curve.D1(lo + h * (x + 1), p, d)
                total += f(p, d) * w * h
    return total


def _curve_of(edge):
    c = BRepAdaptor_Curve(edge)
    return BRep_Tool.Curve_s(edge, 0.0, 0.0), c.FirstParameter(), c.LastParameter()


def _plan(curve):
    """Area, centroid and perimeter of a closed curve in the XY plane."""
    area = _along(curve, lambda p, d: 0.5 * (p.X() * d.Y() - p.Y() * d.X()))
    mx = _along(curve, lambda p, d: 0.5 * p.X() * p.X() * d.Y())
    my = _along(curve, lambda p, d: -0.5 * p.Y() * p.Y() * d.X())
    length = _along(curve, lambda p, d: d.Magnitude())
    return abs(area), (mx / area, my / area), length


def _turned(curve, t0=None, t1=None):
    """What a curve in the XZ plane sweeps turned once round Z: Pappus'
    volume term (the region's first moment about the axis) and its area."""
    moment = _along(curve, lambda p, d: 0.5 * p.X() * p.X() * d.Z(), t0, t1)
    area = _along(curve, lambda p, d: p.X() * d.Magnitude(), t0, t1)
    return 2 * math.pi * moment, 2 * math.pi * area


def _closed_cubic(n, wobble):
    """A closed cubic B-spline of n spans, round with waves on it."""
    poles = TColgp_Array1OfPnt(1, n)
    for i in range(n):
        t = 2 * math.pi * i / n
        r = 10 + wobble * math.sin(5 * t) + 0.5 * wobble * math.cos(2 * t)
        poles.SetValue(i + 1, gp_Pnt(r * math.cos(t), r * math.sin(t), 0))
    knots = TColStd_Array1OfReal(1, n + 1)
    mults = TColStd_Array1OfInteger(1, n + 1)
    for i in range(n + 1):
        knots.SetValue(i + 1, float(i))
        mults.SetValue(i + 1, 1)
    return Geom_BSplineCurve(poles, knots, mults, 3, True)


def _ring_profile(n):
    """A ring's cross-section, 14 from the axis, through n points."""
    return [(14.0 + 1.5 * math.cos(2 * math.pi * i / n) + 0.3 * math.sin(6 * math.pi * i / n),
             0.0, 2.5 * math.sin(2 * math.pi * i / n)) for i in range(n)]


def _ring(n):
    edge = g.make_interp_curve(_ring_profile(n), closed=True)
    curve, t0, t1 = _curve_of(edge)
    volume, area = _turned(curve, t0, t1)
    return g.revolve(g.planar_face(edge), (0, 0, 0), (0, 0, 1), 360.0), abs(volume), abs(area)


HEIGHT = 7.0


def test_a_solid_from_a_rhino_file_measures_its_true_volume(tmp_path):
    """The reporter's path: a fluted column made in Rhino, its side one NURBS
    of 32 spans, saved, imported, measured. Main read it 0.2% low."""
    pts = []
    for i in range(32):
        t = 2 * math.pi * i / 32
        r = 10 + 2.5 * math.sin(11 * t)
        pts.append(r3.Point3d(r * math.cos(t), r * math.sin(t), 0.0))
    profile = r3.Curve.CreateControlPointCurve(pts + [pts[0]], 3)
    brep = r3.Extrusion.Create(profile, HEIGHT, True).ToBrep(False)
    model = r3.File3dm()
    model.Settings.ModelUnitSystem = r3.UnitSystem.Millimeters
    model.Objects.AddBrep(brep)
    path = str(tmp_path / "extruded.3dm")
    assert model.Write(path, 8)
    # the profile's area, by Green's theorem on Rhino's own curve
    nc = profile.ToNurbsCurve()
    knots = sorted({nc.Knots[i] for i in range(len(nc.Knots))})
    area = 0.0
    for a, b in zip(knots, knots[1:]):
        h = (b - a) / 2
        for x, w in _GAUSS:
            p, d = nc.DerivativeAt(a + h * (x + 1), 1)
            area += 0.5 * (p.X * d.Y - p.Y * d.X) * w * h
    [(_, shape, _)] = import_3dm(path)
    assert g.shape_kind(shape) == "solid"
    assert g.volume(shape) == pytest.approx(abs(area) * HEIGHT, rel=1e-6)


@pytest.fixture(scope="module")
def nurbs_prism():
    """The kind of solid a .3dm import gives: every face NURBS, the side
    one surface of 23 spans round and one up."""
    curve = _closed_cubic(23, 3.0)
    wire = BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(curve).Edge()).Wire()
    face = BRepBuilderAPI_MakeFace(wire, True).Face()
    prism = BRepPrimAPI_MakePrism(face, gp_Vec(0, 0, HEIGHT)).Shape()
    return BRepBuilderAPI_NurbsConvert(prism, True).Shape(), _plan(curve)


def test_a_nurbs_solid_of_many_spans_measures_its_true_volume(nurbs_prism):
    shape, (area, _, _) = nurbs_prism
    assert g.volume(shape) == pytest.approx(area * HEIGHT, rel=1e-6)


def test_a_nurbs_solid_of_many_spans_measures_its_true_area(nurbs_prism):
    shape, (area, _, length) = nurbs_prism
    assert g.surface_area(shape) == pytest.approx(length * HEIGHT + 2 * area, rel=1e-6)


def test_a_nurbs_solid_of_many_spans_finds_its_true_centre(nurbs_prism):
    shape, (_, (cx, cy), _) = nurbs_prism
    assert g.centroid(shape) == pytest.approx((cx, cy, HEIGHT / 2), abs=1e-6)


def test_an_extrusion_measures_its_true_volume_and_area():
    """Extrude, in Serpentine, of a closed curve through 30 points."""
    pts = [(10 * math.cos(t) + 2 * math.sin(3 * t + 0.4), 10 * math.sin(t) + 0.8 * math.cos(5 * t), 0.0)
           for t in (2 * math.pi * i / 30 for i in range(30))]
    edge = g.make_interp_curve(pts, closed=True)
    curve, _, _ = _curve_of(edge)
    area, _, length = _plan(curve)
    solid = g.extrude(edge, (0, 0, 1), 12.0, cap=True)
    assert g.volume(solid) == pytest.approx(area * 12.0, rel=1e-6)
    assert g.surface_area(solid) == pytest.approx(length * 12.0 + 2 * area, rel=1e-6)


def test_a_revolved_ring_measures_its_true_volume_and_area():
    """Revolve, in Serpentine, of a closed cross-section through 12 points."""
    ring, volume, area = _ring(12)
    assert g.volume(ring) == pytest.approx(volume, rel=1e-6)
    assert g.surface_area(ring) == pytest.approx(area, rel=1e-6)


def test_a_ring_scaled_to_an_oval_keeps_its_volume():
    """Scaling one way turns every face into NURBS, closed both ways: the
    crease split cut that face wrong and the oval read half its volume."""
    ring, volume, _ = _ring(8)
    oval = g.scale(ring, (0, 0, 0), 1.0, factors=(1.2, 1.0, 1.0))
    assert g.volume(oval) == pytest.approx(1.2 * volume, rel=1e-6)


def test_a_vase_measures_its_true_volume():
    """Revolve of an open profile closed by the axis: one curved face, two
    flat ones."""
    pts = [(abs(3.0 + 2.0 * math.sin(1.3 * i) + 0.15 * i * i) + 1.0, 0.0, 2.0 * i) for i in range(14)]
    top, bottom = (0.0, 0.0, pts[-1][2]), (0.0, 0.0, pts[0][2])
    side = g.make_interp_curve(pts)
    wire = g.join_curves([side, g.make_line(pts[-1], top), g.make_line(top, bottom),
                          g.make_line(bottom, pts[0])])
    vase = g.revolve(g.planar_face(wire), (0, 0, 0), (0, 0, 1), 360.0)
    curve, t0, t1 = _curve_of(side)
    volume, side_area = _turned(curve, t0, t1)
    discs = math.pi * (pts[0][0] ** 2 + pts[-1][0] ** 2)
    assert g.volume(vase) == pytest.approx(abs(volume), rel=1e-6)
    assert g.surface_area(vase) == pytest.approx(abs(side_area) + discs, rel=1e-6)


def test_a_band_of_one_creased_curve_scaled_keeps_its_volume():
    """A ring band whose cross-section is one curve with corners in it,
    revolved and scaled: a NURBS face closed both ways with creases, the
    one the split could not cut. Integrated whole, the corners cost a few
    parts in a million."""
    poly = [(12.0, 0, -1.5), (13.5, 0, -2.0), (15.0, 0, -1.0), (15.2, 0, 1.0), (13.5, 0, 2.2),
            (12.0, 0, 1.5)]
    loop = poly + [poly[0]]
    poles = TColgp_Array1OfPnt(1, len(loop))
    for i, q in enumerate(loop, 1):
        poles.SetValue(i, gp_Pnt(*q))
    knots = TColStd_Array1OfReal(1, len(loop))
    mults = TColStd_Array1OfInteger(1, len(loop))
    for i in range(len(loop)):
        knots.SetValue(i + 1, float(i))
        mults.SetValue(i + 1, 2 if i in (0, len(loop) - 1) else 1)
    edge = BRepBuilderAPI_MakeEdge(Geom_BSplineCurve(poles, knots, mults, 1)).Edge()
    band = g.revolve(g.planar_face(edge), (0, 0, 0), (0, 0, 1), 360.0)
    # Pappus on the polygon, exactly: x is linear along each side
    moment = sum(0.5 * (z2 - z1) * (x1 * x1 + x1 * x2 + x2 * x2) / 3
                 for (x1, _, z1), (x2, _, z2) in zip(loop, loop[1:]))
    scaled = g.scale(band, (0, 0, 0), 1.0, factors=(1.0, 1.0, 1.5))
    assert g.volume(scaled) == pytest.approx(1.5 * abs(2 * math.pi * moment), rel=1e-5)


def test_a_wavy_strip_measures_its_true_area():
    """A strip pulled straight from a zigzag of a profile, two spans across,
    as an openNURBS sample has one: its area is its length times the
    profile's. The adaptive integration takes its points across a span from
    its tolerance alone, never refining there, and the 6 it takes at 1e-6
    left this 4e-4 out; main's one rule across both spans, 7e-5."""
    from OCP.Geom import Geom_BSplineSurface
    from OCP.TColgp import TColgp_Array2OfPnt
    profile = [(-25.0, 0.0), (-25.0, 3.0), (-22.0, 0.0), (-19.0, 3.0), (-19.0, 0.0)]
    length = 20.0
    poles = TColgp_Array2OfPnt(1, len(profile), 1, 2)
    for i, (x, z) in enumerate(profile, 1):
        poles.SetValue(i, 1, gp_Pnt(x, 0.0, z))
        poles.SetValue(i, 2, gp_Pnt(x, length, z))
    uknots, umults = TColStd_Array1OfReal(1, 3), TColStd_Array1OfInteger(1, 3)
    for i, (k, m) in enumerate(((0.0, 4), (1.0, 1), (2.0, 4)), 1):
        uknots.SetValue(i, k)
        umults.SetValue(i, m)
    vknots, vmults = TColStd_Array1OfReal(1, 2), TColStd_Array1OfInteger(1, 2)
    for i, k in enumerate((0.0, length), 1):
        vknots.SetValue(i, k)
        vmults.SetValue(i, 2)
    surface = Geom_BSplineSurface(poles, uknots, vknots, umults, vmults, 3, 1)
    strip = BRepBuilderAPI_MakeFace(surface, 1e-7).Face()
    curve = surface.VIso(0.0)
    assert g.surface_area(strip) == pytest.approx(
        length * _along(curve, lambda p, d: d.Magnitude()), rel=3e-5)


@pytest.mark.parametrize("make, volume, area", [
    (lambda: g.make_cone((0, 0, 0), 3.0, 1.0, 5.0), math.pi * 5 / 3 * (9 + 3 + 1),
     math.pi * (9 + 1) + math.pi * 4 * math.hypot(5.0, 2.0)),
    (lambda: g.make_torus((0, 0, 0), 20.0, 4.0), 2 * math.pi ** 2 * 20 * 16,
     4 * math.pi ** 2 * 20 * 4),
], ids=["cone", "torus"])
def test_a_round_solid_still_measures_exactly(make, volume, area):
    shape = make()
    assert g.volume(shape) == pytest.approx(volume, rel=1e-9)
    assert g.surface_area(shape) == pytest.approx(area, rel=1e-9)
