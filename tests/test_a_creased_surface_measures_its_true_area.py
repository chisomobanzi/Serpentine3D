"""A surface with creases in it measures its true area and volume.

Found on the openNURBS DinerMug while chasing #34: the mug's body read
30,852 in area against 38,845 in the render mesh Rhino stores for it. The
body is one surface whose profile is a chain of patches meeting at creases,
every interior knot at full multiplicity, and OpenCascade's default
integration samples a face as one smooth piece. Across a crease it cannot:
the sample points fall mostly in the long parameter spans and miss the
short ones where the shape changes. On the surface below it reads 98% low,
or 24% high once the same surface is converted to NURBS; volumes were off
by as much as double.

Area, volume and centroid now split a face at its creases before they
integrate, which puts each piece back on the smooth ground the method is
exact on. A face with no crease is left as it is and costs nothing extra.
"""

from __future__ import annotations

import math

import pytest
from OCP.BRepBuilderAPI import (BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace,
                                BRepBuilderAPI_MakeWire, BRepBuilderAPI_NurbsConvert)
from OCP.BRepPrimAPI import BRepPrimAPI_MakeRevol
from OCP.Geom import Geom_BSplineCurve
from OCP.TColgp import TColgp_Array1OfPnt
from OCP.TColStd import TColStd_Array1OfInteger, TColStd_Array1OfReal
from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt

from serpentine3d.core import geometry as g
from serpentine3d.core import occ

# radius, height: a zigzag whose big swings sit in short parameter spans,
# as the mug's middle does, with long spans carrying the short end pieces
PROFILE = [(4.0, 0.0), (4.5, 0.5), (12.0, 4.0), (3.0, 8.0),
           (12.0, 12.0), (4.5, 15.5), (4.0, 16.0)]
KNOTS = [0.0, 20.0, 20.5, 21.0, 21.5, 22.0, 42.0]
AXIS = gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1))
SEGMENTS = list(zip(PROFILE, PROFILE[1:]))

AREA = sum(math.pi * (r1 + r2) * math.hypot(r2 - r1, z2 - z1)
           for (r1, z1), (r2, z2) in SEGMENTS)
VOLUME = sum(math.pi * (z2 - z1) * (r1 * r1 + r1 * r2 + r2 * r2) / 3
             for (r1, z1), (r2, z2) in SEGMENTS)


def _moment_z():
    """pi * integral of z r(z)^2 dz: a cubic on each segment, so Simpson's
    rule is exact."""
    total = 0.0
    for (r1, z1), (r2, z2) in SEGMENTS:
        def f(t):
            z, r = z1 + t * (z2 - z1), r1 + t * (r2 - r1)
            return z * r * r
        total += math.pi * (z2 - z1) * (f(0) + 4 * f(0.5) + f(1)) / 6
    return total


def _profile_edge():
    poles = TColgp_Array1OfPnt(1, len(PROFILE))
    for i, (r, z) in enumerate(PROFILE, 1):
        poles.SetValue(i, gp_Pnt(r, 0, z))
    knots = TColStd_Array1OfReal(1, len(KNOTS))
    mults = TColStd_Array1OfInteger(1, len(KNOTS))
    for i, k in enumerate(KNOTS, 1):
        knots.SetValue(i, k)
        mults.SetValue(i, 2 if i in (1, len(KNOTS)) else 1)
    curve = Geom_BSplineCurve(poles, knots, mults, 1)
    return BRepBuilderAPI_MakeEdge(curve).Edge()


def _creased_surface(nurbs):
    shape = BRepPrimAPI_MakeRevol(_profile_edge(), AXIS).Shape()
    return BRepBuilderAPI_NurbsConvert(shape, True).Shape() if nurbs else shape


def _creased_solid(nurbs):
    (r0, z0), (r1, z1) = PROFILE[0], PROFILE[-1]
    top, bottom = gp_Pnt(0, 0, z1), gp_Pnt(0, 0, z0)
    wire = BRepBuilderAPI_MakeWire(
        _profile_edge(),
        BRepBuilderAPI_MakeEdge(gp_Pnt(r1, 0, z1), top).Edge(),
        BRepBuilderAPI_MakeEdge(top, bottom).Edge())
    wire.Add(BRepBuilderAPI_MakeEdge(bottom, gp_Pnt(r0, 0, z0)).Edge())
    face = BRepBuilderAPI_MakeFace(wire.Wire(), True).Face()
    shape = BRepPrimAPI_MakeRevol(face, AXIS).Shape()
    return BRepBuilderAPI_NurbsConvert(shape, True).Shape() if nurbs else shape


KINDS = [False, True]
IDS = ["surface-of-revolution", "nurbs"]


@pytest.mark.parametrize("nurbs", KINDS, ids=IDS)
def test_a_creased_surface_has_its_true_area(nurbs):
    assert g.surface_area(_creased_surface(nurbs)) == pytest.approx(AREA, rel=1e-6)


@pytest.mark.parametrize("nurbs", KINDS, ids=IDS)
def test_a_creased_solid_has_its_true_volume(nurbs):
    assert g.volume(_creased_solid(nurbs)) == pytest.approx(VOLUME, rel=1e-6)


@pytest.mark.parametrize("nurbs", KINDS, ids=IDS)
def test_a_creased_solid_has_its_true_centre(nurbs):
    x, y, z = g.centroid(_creased_solid(nurbs))

    assert (x, y) == pytest.approx((0.0, 0.0), abs=1e-6)
    assert z == pytest.approx(_moment_z() / VOLUME, rel=1e-6)


# --- what was right stays right, and costs nothing more ---------------------

def test_smooth_shapes_are_measured_as_they_were():
    assert g.volume(g.make_box((0, 0, 0), 10, 20, 30)) == pytest.approx(6000.0)
    assert g.surface_area(g.make_sphere((0, 0, 0), 5.0)) == pytest.approx(
        4 * math.pi * 25, rel=1e-9)
    assert g.volume(g.make_cylinder((0, 0, 0), 2.0, 7.0)) == pytest.approx(
        math.pi * 4 * 7, rel=1e-9)


def test_a_shape_with_no_crease_is_not_split():
    """The split is paid only where it is needed."""
    box = g.make_box((0, 0, 0), 1, 2, 3)
    sphere = g.make_sphere((0, 0, 0), 1.0)

    assert occ.without_creases(box) is box
    assert occ.without_creases(sphere) is sphere
