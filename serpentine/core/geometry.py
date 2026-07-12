"""Geometry construction and interrogation on top of the OCCT kernel.

Every builder takes plain Python tuples/floats and returns a TopoDS_Shape.
Points are (x, y, z) tuples throughout; vectors likewise.
"""

from __future__ import annotations

import math
import os
import tempfile

from . import occ
from .occ import (
    gp_Pnt, gp_Vec, gp_Dir, gp_Ax1, gp_Ax2, gp_Trsf, gp_GTrsf, gp_Circ,
    gp_Elips, gp_XYZ, gp_Mat,
    TopoDS_Shape, TopoDS_Compound, TopExp_Explorer, TopLoc_Location,
    BRep_Builder,
    BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire, BRepBuilderAPI_MakeFace,
    BRepBuilderAPI_MakeVertex, BRepBuilderAPI_Transform,
    BRepBuilderAPI_GTransform, BRepBuilderAPI_Copy,
    BRepPrimAPI_MakePrism, BRepPrimAPI_MakeRevol, BRepPrimAPI_MakeBox,
    BRepPrimAPI_MakeSphere, BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakeCone,
    BRepPrimAPI_MakeTorus,
    BRepAlgoAPI_Fuse, BRepAlgoAPI_Cut, BRepAlgoAPI_Common,
    BRepOffsetAPI_ThruSections, BRepOffsetAPI_MakePipe,
    GC_MakeArcOfCircle, GeomAPI_Interpolate, GeomAPI_PointsToBSpline,
    Geom_BSplineCurve,
    TColgp_Array1OfPnt, TColgp_HArray1OfPnt, TColStd_Array1OfReal,
    TColStd_Array1OfInteger,
    Bnd_Box, BRepCheck_Analyzer,
)

Point = tuple[float, float, float]


class GeometryError(Exception):
    """Raised when a geometric operation cannot be performed."""


def _pnt(p: Point) -> gp_Pnt:
    return gp_Pnt(float(p[0]), float(p[1]), float(p[2]))


def _vec(v: Point) -> gp_Vec:
    return gp_Vec(float(v[0]), float(v[1]), float(v[2]))


def _dir(v: Point) -> gp_Dir:
    try:
        return gp_Dir(float(v[0]), float(v[1]), float(v[2]))
    except Exception as exc:
        raise GeometryError(f"Invalid direction {v}: {exc}") from exc


def pnt_tuple(p: gp_Pnt) -> Point:
    return (p.X(), p.Y(), p.Z())


# --- curves -----------------------------------------------------------------

def make_line(p1: Point, p2: Point) -> TopoDS_Shape:
    if _pnt(p1).Distance(_pnt(p2)) < 1e-9:
        raise GeometryError("Line endpoints are coincident")
    return BRepBuilderAPI_MakeEdge(_pnt(p1), _pnt(p2)).Edge()


def make_polyline(points: list[Point], closed: bool = False) -> TopoDS_Shape:
    if len(points) < 2:
        raise GeometryError("Polyline needs at least 2 points")
    wire = BRepBuilderAPI_MakeWire()
    pts = [_pnt(p) for p in points]
    if closed and pts[0].Distance(pts[-1]) > 1e-9:
        pts.append(pts[0])
    for a, b in zip(pts, pts[1:]):
        if a.Distance(b) < 1e-9:
            continue
        wire.Add(BRepBuilderAPI_MakeEdge(a, b).Edge())
    if not wire.IsDone():
        raise GeometryError("Failed to build polyline")
    return wire.Wire()


def make_circle(center: Point, radius: float,
                normal: Point = (0, 0, 1)) -> TopoDS_Shape:
    if radius <= 0:
        raise GeometryError("Circle radius must be positive")
    ax = gp_Ax2(_pnt(center), _dir(normal))
    return BRepBuilderAPI_MakeEdge(gp_Circ(ax, float(radius))).Edge()


def make_arc_3pt(p1: Point, p2: Point, p3: Point) -> TopoDS_Shape:
    arc = GC_MakeArcOfCircle(_pnt(p1), _pnt(p2), _pnt(p3))
    if not arc.IsDone():
        raise GeometryError("Cannot fit an arc through these points")
    return BRepBuilderAPI_MakeEdge(arc.Value()).Edge()


def make_ellipse(center: Point, major_radius: float, minor_radius: float,
                 normal: Point = (0, 0, 1)) -> TopoDS_Shape:
    if minor_radius > major_radius:
        major_radius, minor_radius = minor_radius, major_radius
    if minor_radius <= 0:
        raise GeometryError("Ellipse radii must be positive")
    ax = gp_Ax2(_pnt(center), _dir(normal))
    return BRepBuilderAPI_MakeEdge(
        gp_Elips(ax, float(major_radius), float(minor_radius))).Edge()


def make_rectangle(corner1: Point, corner2: Point) -> TopoDS_Shape:
    """Axis-aligned rectangle in the world XY plane (z from corner1)."""
    x1, y1, z = corner1
    x2, y2, _ = corner2
    if abs(x2 - x1) < 1e-9 or abs(y2 - y1) < 1e-9:
        raise GeometryError("Degenerate rectangle")
    pts = [(x1, y1, z), (x2, y1, z), (x2, y2, z), (x1, y2, z)]
    return make_polyline(pts, closed=True)


def make_interp_curve(points: list[Point], closed: bool = False) -> TopoDS_Shape:
    """NURBS curve interpolated through the given points."""
    if len(points) < 2:
        raise GeometryError("Curve needs at least 2 points")
    arr = TColgp_HArray1OfPnt(1, len(points))
    for i, p in enumerate(points, start=1):
        arr.SetValue(i, _pnt(p))
    interp = GeomAPI_Interpolate(arr, closed, 1e-7)
    interp.Perform()
    if not interp.IsDone():
        raise GeometryError("Curve interpolation failed")
    return BRepBuilderAPI_MakeEdge(interp.Curve()).Edge()


def make_control_curve(control_points: list[Point], degree: int = 3,
                       closed: bool = False) -> TopoDS_Shape:
    """NURBS curve from explicit control points (uniform clamped knots)."""
    n = len(control_points)
    if n < 2:
        raise GeometryError("Need at least 2 control points")
    degree = max(1, min(degree, n - 1))
    poles = TColgp_Array1OfPnt(1, n)
    for i, p in enumerate(control_points, start=1):
        poles.SetValue(i, _pnt(p))
    n_knots = n - degree + 1
    knots = TColStd_Array1OfReal(1, n_knots)
    mults = TColStd_Array1OfInteger(1, n_knots)
    for i in range(1, n_knots + 1):
        knots.SetValue(i, float(i - 1) / (n_knots - 1) if n_knots > 1 else 0.0)
        mults.SetValue(i, degree + 1 if i in (1, n_knots) else 1)
    curve = Geom_BSplineCurve(poles, knots, mults, degree, False)
    return BRepBuilderAPI_MakeEdge(curve).Edge()


# --- wires / joining --------------------------------------------------------

def edges_of(shape) -> list:
    out, seen = [], set()
    exp = TopExp_Explorer(shape, occ.EDGE)
    while exp.More():
        e = exp.Current()
        # a wire visits shared edges twice; dedupe on TShape identity
        key = hash(e.TShape())
        if key not in seen:
            seen.add(key)
            out.append(occ.to_edge(e))
        exp.Next()
    return out


def faces_of(shape) -> list:
    out = []
    exp = TopExp_Explorer(shape, occ.FACE)
    while exp.More():
        out.append(occ.to_face(exp.Current()))
        exp.Next()
    return out


def to_wire(shape) -> TopoDS_Shape:
    """Promote an edge (or wire) to a wire."""
    st = shape.ShapeType()
    if st == occ.WIRE:
        return shape
    if st == occ.EDGE:
        mk = BRepBuilderAPI_MakeWire(occ.to_edge(shape))
        if not mk.IsDone():
            raise GeometryError("Failed to make wire from edge")
        return mk.Wire()
    raise GeometryError(f"Cannot convert {shape_kind(shape)} to wire")


def join_curves(shapes: list) -> TopoDS_Shape:
    """Join edges/wires into a single wire (must connect end-to-end)."""
    mk = BRepBuilderAPI_MakeWire()
    for s in shapes:
        st = s.ShapeType()
        if st == occ.EDGE:
            mk.Add(occ.to_edge(s))
        elif st == occ.WIRE:
            mk.Add(occ.to_wire(s))
        else:
            raise GeometryError("join expects curves")
    if not mk.IsDone():
        raise GeometryError("Curves do not connect end-to-end")
    return mk.Wire()


def is_closed_curve(shape) -> bool:
    st = shape.ShapeType()
    if st == occ.EDGE:
        ad = occ.edge_adaptor(occ.to_edge(shape))
        p0 = ad.Value(ad.FirstParameter())
        p1 = ad.Value(ad.LastParameter())
        return p0.Distance(p1) < 1e-7
    if st == occ.WIRE:
        return occ.to_wire(shape).Closed()
    return False


# --- surfaces ---------------------------------------------------------------

def extrude(shape, direction: Point, distance: float,
            cap: bool = False) -> TopoDS_Shape:
    """Extrude a curve into a surface (or a capped solid if closed+cap)."""
    d = _dir(direction)
    vec = gp_Vec(d.X(), d.Y(), d.Z()).Multiplied(float(distance))
    base = shape
    if cap and is_closed_curve(shape):
        base = planar_face(shape)
    result = BRepPrimAPI_MakePrism(base, vec)
    if not result.IsDone():
        raise GeometryError("Extrusion failed")
    return result.Shape()


def revolve(shape, axis_point: Point, axis_dir: Point,
            angle_deg: float = 360.0) -> TopoDS_Shape:
    ax = gp_Ax1(_pnt(axis_point), _dir(axis_dir))
    result = BRepPrimAPI_MakeRevol(shape, ax, math.radians(float(angle_deg)))
    if not result.IsDone():
        raise GeometryError("Revolve failed")
    return result.Shape()


def loft(profiles: list, solid: bool = False, ruled: bool = False) -> TopoDS_Shape:
    if len(profiles) < 2:
        raise GeometryError("Loft needs at least 2 profile curves")
    lofter = BRepOffsetAPI_ThruSections(solid, ruled, 1e-6)
    for p in profiles:
        lofter.AddWire(occ.to_wire(to_wire(p)))
    lofter.Build()
    if not lofter.IsDone():
        raise GeometryError("Loft failed")
    return lofter.Shape()


def sweep1(profile, rail) -> TopoDS_Shape:
    result = BRepOffsetAPI_MakePipe(occ.to_wire(to_wire(rail)), to_wire(profile))
    if not result.IsDone():
        raise GeometryError("Sweep failed")
    return result.Shape()


def planar_face(shape) -> TopoDS_Shape:
    """Planar surface from a closed planar curve."""
    if not is_closed_curve(shape):
        raise GeometryError("Curve must be closed to make a planar surface")
    wire = occ.to_wire(to_wire(shape))
    mk = BRepBuilderAPI_MakeFace(wire, True)
    if not mk.IsDone():
        raise GeometryError("Planar surface failed (curve may be non-planar)")
    return mk.Face()


def offset_curve(shape, distance: float) -> TopoDS_Shape:
    """Offset a planar curve by a distance (sign picks the side)."""
    from .occ import BRepOffsetAPI_MakeOffset, GeomAbs_JoinType
    wire = occ.to_wire(to_wire(shape))
    open_result = not is_closed_curve(shape)
    mk = BRepOffsetAPI_MakeOffset(wire, GeomAbs_JoinType.GeomAbs_Arc,
                                  open_result)
    mk.Perform(float(distance))
    if not mk.IsDone() or mk.Shape().IsNull():
        raise GeometryError("Offset failed (curve must be planar)")
    return mk.Shape()


def fillet_curves(edge_a, edge_b, radius: float,
                  near: Point) -> tuple:
    """Fillet two coplanar line/arc edges; returns (trimmed_a, arc, trimmed_b).

    `near` chooses the corner when the curves cross more than once.
    """
    from .occ import ChFi2d_FilletAPI, gp_Pln
    if radius <= 0:
        raise GeometryError("Fillet radius must be positive")
    ea, eb = occ.to_edge(edge_a), occ.to_edge(edge_b)
    # assume drafting plane = world XY at the corner's z
    plane = gp_Pln(_pnt((0, 0, near[2])), _dir((0, 0, 1)))
    api = ChFi2d_FilletAPI(ea, eb, plane)
    if not api.Perform(float(radius)):
        raise GeometryError("Fillet failed (radius too large or curves "
                            "not coplanar in XY)")
    ea_out = occ.TopoDS_Edge()
    eb_out = occ.TopoDS_Edge()
    arc = api.Result(_pnt(near), ea_out, eb_out)
    if arc.IsNull():
        raise GeometryError("Fillet produced no result near that corner")
    return ea_out, arc, eb_out


def explode(shape) -> list:
    """Decompose: wires -> edges, shells/solids -> faces, compounds -> parts."""
    kind = shape_kind(shape)
    if kind == "curve" and shape.ShapeType() == occ.WIRE:
        return [e for e in edges_of(shape)]
    if kind in ("surface", "solid"):
        parts = faces_of(shape)
        if len(parts) > 1:
            return parts
        return []
    if kind == "compound":
        from .occ import TopoDS_Iterator
        out = []
        it = TopoDS_Iterator(shape)
        while it.More():
            out.append(it.Value())
            it.Next()
        return out
    return []


# --- solids -----------------------------------------------------------------

def make_box(corner: Point, dx: float, dy: float, dz: float) -> TopoDS_Shape:
    if min(abs(dx), abs(dy), abs(dz)) < 1e-9:
        raise GeometryError("Degenerate box")
    x, y, z = corner
    x, dx = (x + dx, -dx) if dx < 0 else (x, dx)
    y, dy = (y + dy, -dy) if dy < 0 else (y, dy)
    z, dz = (z + dz, -dz) if dz < 0 else (z, dz)
    return BRepPrimAPI_MakeBox(_pnt((x, y, z)), dx, dy, dz).Shape()


def make_sphere(center: Point, radius: float) -> TopoDS_Shape:
    if radius <= 0:
        raise GeometryError("Sphere radius must be positive")
    return BRepPrimAPI_MakeSphere(_pnt(center), float(radius)).Shape()


def make_cylinder(base: Point, radius: float, height: float,
                  axis: Point = (0, 0, 1)) -> TopoDS_Shape:
    if radius <= 0 or height == 0:
        raise GeometryError("Cylinder needs positive radius and height")
    ax = gp_Ax2(_pnt(base), _dir(axis))
    return BRepPrimAPI_MakeCylinder(ax, float(radius), abs(float(height))).Shape()


def make_cone(base: Point, radius1: float, radius2: float, height: float,
              axis: Point = (0, 0, 1)) -> TopoDS_Shape:
    ax = gp_Ax2(_pnt(base), _dir(axis))
    return BRepPrimAPI_MakeCone(ax, float(radius1), float(radius2),
                                abs(float(height))).Shape()


def make_torus(center: Point, major_radius: float, minor_radius: float,
               axis: Point = (0, 0, 1)) -> TopoDS_Shape:
    ax = gp_Ax2(_pnt(center), _dir(axis))
    return BRepPrimAPI_MakeTorus(ax, float(major_radius),
                                 float(minor_radius)).Shape()


# --- booleans ---------------------------------------------------------------

def _boolean(op_cls, a, b, name: str) -> TopoDS_Shape:
    op = op_cls(a, b)
    op.Build()
    if not op.IsDone():
        raise GeometryError(f"Boolean {name} failed")
    result = op.Shape()
    if result.IsNull():
        raise GeometryError(f"Boolean {name} produced no geometry")
    return result


def boolean_union(a, b) -> TopoDS_Shape:
    return _boolean(BRepAlgoAPI_Fuse, a, b, "union")


def boolean_difference(a, b) -> TopoDS_Shape:
    return _boolean(BRepAlgoAPI_Cut, a, b, "difference")


def boolean_intersection(a, b) -> TopoDS_Shape:
    return _boolean(BRepAlgoAPI_Common, a, b, "intersection")


# --- transforms -------------------------------------------------------------

def _apply_trsf(shape, trsf: gp_Trsf, copy: bool = True) -> TopoDS_Shape:
    return BRepBuilderAPI_Transform(shape, trsf, copy).Shape()


def translate(shape, offset: Point) -> TopoDS_Shape:
    t = gp_Trsf()
    t.SetTranslation(_vec(offset))
    return _apply_trsf(shape, t)


def rotate(shape, axis_point: Point, axis_dir: Point,
           angle_deg: float) -> TopoDS_Shape:
    t = gp_Trsf()
    t.SetRotation(gp_Ax1(_pnt(axis_point), _dir(axis_dir)),
                  math.radians(float(angle_deg)))
    return _apply_trsf(shape, t)


def scale(shape, center: Point, factor: float,
          factors: Point | None = None) -> TopoDS_Shape:
    """Uniform scale, or non-uniform when `factors=(sx,sy,sz)` given."""
    if factors is None:
        if factor == 0:
            raise GeometryError("Scale factor cannot be zero")
        t = gp_Trsf()
        t.SetScale(_pnt(center), float(factor))
        return _apply_trsf(shape, t)
    sx, sy, sz = (float(f) for f in factors)
    if 0 in (sx, sy, sz):
        raise GeometryError("Scale factors cannot be zero")
    cx, cy, cz = center
    g = gp_GTrsf()
    g.SetVectorialPart(gp_Mat(sx, 0, 0, 0, sy, 0, 0, 0, sz))
    g.SetTranslationPart(gp_XYZ(cx - sx * cx, cy - sy * cy, cz - sz * cz))
    result = BRepBuilderAPI_GTransform(shape, g, True)
    if not result.IsDone():
        raise GeometryError("Non-uniform scale failed")
    return result.Shape()


def mirror(shape, plane_point: Point, plane_normal: Point) -> TopoDS_Shape:
    t = gp_Trsf()
    t.SetMirror(gp_Ax2(_pnt(plane_point), _dir(plane_normal)))
    return _apply_trsf(shape, t)


def copy_shape(shape) -> TopoDS_Shape:
    return BRepBuilderAPI_Copy(shape).Shape()


# --- interrogation ----------------------------------------------------------

def shape_kind(shape) -> str:
    """Classify as 'curve' | 'surface' | 'solid' | 'point' | 'compound'."""
    st = shape.ShapeType()
    if st in (occ.EDGE, occ.WIRE):
        return "curve"
    if st in (occ.FACE, occ.SHELL):
        return "surface"
    if st in (occ.SOLID, occ.COMPSOLID):
        return "solid"
    if st == occ.VERTEX:
        return "point"
    return "compound"


def bbox(shape) -> tuple[Point, Point]:
    box = Bnd_Box()
    occ.bbox_add(shape, box)
    if box.IsVoid():
        return ((0, 0, 0), (0, 0, 0))
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    return ((xmin, ymin, zmin), (xmax, ymax, zmax))


def curve_length(shape) -> float:
    return occ.linear_properties(shape).Mass()


def surface_area(shape) -> float:
    return occ.surface_properties(shape).Mass()


def volume(shape) -> float:
    return occ.volume_properties(shape).Mass()


def centroid(shape) -> Point:
    kind = shape_kind(shape)
    if kind == "solid":
        props = occ.volume_properties(shape)
    elif kind == "surface":
        props = occ.surface_properties(shape)
    else:
        props = occ.linear_properties(shape)
    return pnt_tuple(props.CentreOfMass())


def is_valid(shape) -> bool:
    return BRepCheck_Analyzer(shape).IsValid()


# --- serialization ----------------------------------------------------------

def shape_to_bytes(shape) -> bytes:
    fd, path = tempfile.mkstemp(suffix=".brep")
    os.close(fd)
    try:
        occ.brep_write(shape, path)
        with open(path, "rb") as f:
            return f.read()
    finally:
        os.unlink(path)


def shape_from_bytes(data: bytes) -> TopoDS_Shape:
    fd, path = tempfile.mkstemp(suffix=".brep")
    os.close(fd)
    try:
        with open(path, "wb") as f:
            f.write(data)
        return occ.brep_read(path)
    finally:
        os.unlink(path)


def make_compound(shapes: list) -> TopoDS_Shape:
    builder = BRep_Builder()
    comp = TopoDS_Compound()
    builder.MakeCompound(comp)
    for s in shapes:
        builder.Add(comp, s)
    return comp
