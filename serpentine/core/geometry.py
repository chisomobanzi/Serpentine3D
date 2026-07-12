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


def fillet_edges(shape, radius: float, edges: list | None = None,
                 chamfer: bool = False) -> TopoDS_Shape:
    """Fillet (or chamfer) edges of a solid. edges=None means all edges."""
    if radius <= 0:
        raise GeometryError("Radius must be positive")
    if chamfer:
        from OCP.BRepFilletAPI import BRepFilletAPI_MakeChamfer
        mk = BRepFilletAPI_MakeChamfer(shape)
    else:
        from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
        mk = BRepFilletAPI_MakeFillet(shape)
    targets = edges if edges is not None else edges_of(shape)
    if not targets:
        raise GeometryError("No edges to fillet")
    for e in targets:
        mk.Add(float(radius), e)
    mk.Build()
    if not mk.IsDone() or mk.Shape().IsNull():
        raise GeometryError(
            "Fillet failed — the radius is probably too large for "
            "the smallest edges; try a smaller value")
    return unwrap_compound(mk.Shape())


def cap_holes(shape) -> TopoDS_Shape:
    """Close planar openings of a surface/shell and solidify if possible."""
    from OCP.ShapeAnalysis import ShapeAnalysis_FreeBounds
    from .occ import (
        BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeSolid,
        BRepBuilderAPI_Sewing,
    )
    fb = ShapeAnalysis_FreeBounds(shape)
    closed = fb.GetClosedWires()
    caps = []
    if closed is not None and not closed.IsNull():
        exp = TopExp_Explorer(closed, occ.WIRE)
        while exp.More():
            wire = occ.to_wire(exp.Current())
            exp.Next()
            mk = BRepBuilderAPI_MakeFace(wire, True)
            if mk.IsDone():
                caps.append(mk.Face())
    if not caps:
        raise GeometryError("No closable planar openings found")
    sew = BRepBuilderAPI_Sewing(1e-6)
    sew.Add(shape)
    for f in caps:
        sew.Add(f)
    sew.Perform()
    sewn = sew.SewedShape()
    # try to promote the closed shell to a solid
    try:
        exp = TopExp_Explorer(sewn, occ.SHELL)
        if exp.More():
            solid_mk = BRepBuilderAPI_MakeSolid(occ.to_shell(exp.Current()))
            if solid_mk.IsDone():
                solid = solid_mk.Solid()
                if volume(solid) > 1e-12:
                    return solid
    except Exception:
        pass
    return sewn


def intersect_shapes(a, b) -> list:
    """Intersection curves between two shapes (surface/solid)."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
    sec = BRepAlgoAPI_Section(a, b)
    sec.Build()
    if not sec.IsDone():
        raise GeometryError("Intersection failed")
    edges = edges_of(sec.Shape())
    if not edges:
        raise GeometryError("The objects do not intersect")
    return _curve_pieces(edges, [])


def contour(shape, direction: Point = (0, 0, 1),
            spacing: float = 10.0) -> list[tuple[float, list]]:
    """Slice a shape into section curves at regular intervals.

    Returns [(offset_along_direction, [curves]), ...]."""
    import numpy as np
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
    from .occ import gp_Pln
    if spacing <= 0:
        raise GeometryError("Spacing must be positive")
    d = np.asarray(direction, float)
    d = d / np.linalg.norm(d)
    (mn, mx) = bbox(shape)
    corners = [np.array([x, y, z]) for x in (mn[0], mx[0])
               for y in (mn[1], mx[1]) for z in (mn[2], mx[2])]
    lo = min(float(np.dot(c, d)) for c in corners)
    hi = max(float(np.dot(c, d)) for c in corners)
    out = []
    level = lo + spacing
    while level < hi - 1e-6:
        plane = gp_Pln(_pnt(tuple(d * level)), _dir(tuple(d)))
        sec = BRepAlgoAPI_Section(shape, plane)
        sec.Build()
        if sec.IsDone():
            edges = edges_of(sec.Shape())
            if edges:
                out.append((level - lo, _curve_pieces(edges, [])))
        level += spacing
    if not out:
        raise GeometryError("No contours produced (check the spacing)")
    return out


def offset_surface(shape, distance: float) -> TopoDS_Shape:
    """Offset a surface/shell by a distance along its normals."""
    from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffsetShape
    mk = BRepOffsetAPI_MakeOffsetShape()
    mk.PerformByJoin(shape, float(distance), 1e-6)
    if not mk.IsDone() or mk.Shape().IsNull():
        raise GeometryError("Offset surface failed")
    return mk.Shape()


def shell_solid(shape, thickness: float) -> TopoDS_Shape:
    """Hollow a solid with a uniform wall thickness (negative = inward)."""
    from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeThickSolid
    from OCP.TopTools import TopTools_ListOfShape
    if shape_kind(shape) != "solid":
        raise GeometryError("Shell needs a closed solid")
    mk = BRepOffsetAPI_MakeThickSolid()
    mk.MakeThickSolidByJoin(shape, TopTools_ListOfShape(),
                            -abs(float(thickness)), 1e-6)
    if not mk.IsDone() or mk.Shape().IsNull():
        raise GeometryError("Shell failed (thickness may exceed the "
                            "solid's smallest feature)")
    return mk.Shape()


def sweep2(profile, rail1, rail2) -> TopoDS_Shape:
    """Sweep a profile along rail1, scaled/guided by rail2 (two-rail sweep)."""
    from .occ import BRepOffsetAPI_MakePipeShell
    spine = occ.to_wire(to_wire(rail1))
    aux = occ.to_wire(to_wire(rail2))
    ps = BRepOffsetAPI_MakePipeShell(spine)
    ps.SetMode(aux, True)          # curvilinear equivalence with aux rail
    ps.Add(occ.to_wire(to_wire(profile)))
    ps.Build()
    if not ps.IsDone():
        raise GeometryError("Two-rail sweep failed (check that rails run "
                            "the same direction and the profile touches "
                            "the first rail)")
    return ps.Shape()


def _curve_pieces(edges: list, cutters: list) -> list:
    """Group split edges into pieces, breaking chains at cut vertices."""
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape

    def on_cutter(p: gp_Pnt) -> bool:
        v = BRepBuilderAPI_MakeVertex(p).Vertex()
        for c in cutters:
            if BRepExtrema_DistShapeShape(v, c).Value() < 1e-6:
                return True
        return False

    # vertex key -> list of edge indices, skipping vertices on a cutter
    def vkey(p: gp_Pnt):
        return (round(p.X(), 6), round(p.Y(), 6), round(p.Z(), 6))

    links: dict = {}
    ends: list[list] = []
    for i, e in enumerate(edges):
        ad = occ.edge_adaptor(e)
        pts = [ad.Value(ad.FirstParameter()), ad.Value(ad.LastParameter())]
        ends.append(pts)
        for p in pts:
            if not on_cutter(p):
                links.setdefault(vkey(p), []).append(i)

    # union-find over edges connected through non-cut vertices
    parent = list(range(len(edges)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for idxs in links.values():
        for other in idxs[1:]:
            ra, rb = find(idxs[0]), find(other)
            if ra != rb:
                parent[rb] = ra

    groups: dict = {}
    for i in range(len(edges)):
        groups.setdefault(find(i), []).append(edges[i])
    out = []
    for group in groups.values():
        out.append(group[0] if len(group) == 1 else join_curves(group))
    return out


def split_shape(target, cutters: list) -> list:
    """Split a curve or surface by cutting objects; returns the pieces.

    Curves are cut by anything they intersect. Surfaces cut by curves use
    the curve extruded vertically (CPlane normal) as the cutting tool.
    """
    from .occ import BRepAlgoAPI_Splitter, TopTools_ListOfShape
    kind = shape_kind(target)

    tools = TopTools_ListOfShape()
    for c in cutters:
        tool = c
        if kind in ("surface", "solid") and shape_kind(c) == "curve":
            # extrude the cutter through the target's z-range
            (mn, mx) = bbox(target)
            (cmn, cmx) = bbox(c)
            z0 = min(mn[2], cmn[2]) - 1.0
            z1 = max(mx[2], cmx[2]) + 1.0
            moved = translate(c, (0, 0, z0 - cmn[2]))
            tool = extrude(moved, (0, 0, 1), (z1 - z0) + (cmx[2] - cmn[2]))
        tools.Append(tool)

    args = TopTools_ListOfShape()
    args.Append(target)
    splitter = BRepAlgoAPI_Splitter()
    splitter.SetArguments(args)
    splitter.SetTools(tools)
    splitter.Build()
    if not splitter.IsDone():
        raise GeometryError("Split failed")
    result = splitter.Shape()

    if kind == "curve":
        pieces = _curve_pieces(edges_of(result), cutters)
    elif kind in ("surface", "solid"):
        if kind == "solid":
            pieces = []
            exp = TopExp_Explorer(result, occ.SOLID)
            while exp.More():
                pieces.append(exp.Current())
                exp.Next()
            if not pieces:
                pieces = faces_of(result)
        else:
            pieces = faces_of(result)
    else:
        raise GeometryError("Can only split curves and surfaces")
    if len(pieces) < 2:
        raise GeometryError("Objects do not intersect — nothing to split")
    return pieces


# --- control points ---------------------------------------------------------

def _edge_bspline(shape):
    """The (single) edge's curve as a fresh Geom_BSplineCurve in world frame."""
    from .occ import GeomConvert
    from OCP.Geom import Geom_TrimmedCurve
    from OCP.GeomAbs import GeomAbs_CurveType
    edges = edges_of(shape)
    if shape_kind(shape) != "curve" or len(edges) != 1:
        raise GeometryError("Control points work on single curves "
                            "(explode polylines first)")
    edge = edges[0]
    ad = occ.edge_adaptor(edge)
    if ad.GetType() == GeomAbs_CurveType.GeomAbs_BSplineCurve:
        bs = ad.BSpline().Copy()      # OCP returns the derived type directly
    else:
        base = ad.Curve().Curve()
        trimmed = Geom_TrimmedCurve(base, ad.FirstParameter(),
                                    ad.LastParameter())
        bs = GeomConvert.CurveToBSplineCurve_s(trimmed)
        loc = edge.Location()
        if not loc.IsIdentity():
            bs.Transform(loc.Transformation())
    return bs


def get_control_points(shape) -> list[Point]:
    bs = _edge_bspline(shape)
    return [pnt_tuple(bs.Pole(i)) for i in range(1, bs.NbPoles() + 1)]


def _face_bspline_surface(shape):
    """The (single) face's surface as Geom_BSplineSurface in world frame."""
    from .occ import BRep_Tool, GeomConvert
    faces = faces_of(shape)
    if len(faces) != 1:
        raise GeometryError("Control points work on single-face surfaces "
                            "(explode polysurfaces first)")
    face = faces[0]
    surf = BRep_Tool.Surface_s(face)
    from OCP.Geom import Geom_BSplineSurface
    if isinstance(surf, Geom_BSplineSurface):
        return surf.Copy(), face
    try:
        return GeomConvert.SurfaceToBSplineSurface_s(surf), face
    except Exception as exc:
        raise GeometryError(
            f"Surface cannot be converted to NURBS: {exc}") from exc


def surface_control_points(shape) -> tuple[list[Point], tuple[int, int]]:
    """Control points of a single-face surface, row-major (u, then v)."""
    bs, _ = _face_bspline_surface(shape)
    nu, nv = bs.NbUPoles(), bs.NbVPoles()
    pts = []
    for i in range(1, nu + 1):
        for j in range(1, nv + 1):
            pts.append(pnt_tuple(bs.Pole(i, j)))
    return pts, (nu, nv)


def move_surface_control_point(shape, flat_index: int,
                               new_point: Point) -> TopoDS_Shape:
    """New surface with control point `flat_index` (u-major) moved.

    Trimmed faces lose their trims (the rebuilt face is natural-bounds).
    """
    bs, _ = _face_bspline_surface(shape)
    nu, nv = bs.NbUPoles(), bs.NbVPoles()
    if not (0 <= flat_index < nu * nv):
        raise GeometryError("Control point index out of range")
    i, j = divmod(flat_index, nv)
    bs.SetPole(i + 1, j + 1, _pnt(new_point))
    mk = BRepBuilderAPI_MakeFace(bs, 1e-6)
    if not mk.IsDone():
        raise GeometryError("Surface rebuild failed")
    return mk.Face()


def move_control_point(shape, index: int, new_point: Point) -> TopoDS_Shape:
    """Return a new curve with control point `index` (0-based) moved."""
    bs = _edge_bspline(shape)
    if not (0 <= index < bs.NbPoles()):
        raise GeometryError(f"Control point index {index} out of range")
    bs.SetPole(index + 1, _pnt(new_point))
    return BRepBuilderAPI_MakeEdge(bs).Edge()


def sample_curve(shape, count: int) -> list[Point]:
    """`count` points spaced uniformly by arc length along a curve/wire."""
    from OCP.BRepAdaptor import BRepAdaptor_CompCurve
    from OCP.GCPnts import GCPnts_UniformAbscissa
    if count < 2:
        raise GeometryError("Need at least 2 sample points")
    st = shape.ShapeType()
    if st == occ.WIRE:
        adaptor = BRepAdaptor_CompCurve(occ.to_wire(shape))
    elif st == occ.EDGE:
        adaptor = occ.edge_adaptor(occ.to_edge(shape))
    else:
        raise GeometryError("Not a curve")
    ua = GCPnts_UniformAbscissa(adaptor, int(count))
    if not ua.IsDone():
        raise GeometryError("Could not sample curve")
    pts = []
    for i in range(1, ua.NbPoints() + 1):
        p = adaptor.Value(ua.Parameter(i))
        pts.append((p.X(), p.Y(), p.Z()))
    return pts


def rebuild_curve(shape, point_count: int = 10,
                  degree: int = 3) -> TopoDS_Shape:
    """Rebuild a curve through `point_count` arc-length samples.

    Degree 3 interpolates through the samples; other degrees fit a
    least-squares approximation of that degree.
    """
    closed = is_closed_curve(shape)
    n = max(int(point_count), 3 if closed else 2)
    pts = sample_curve(shape, n + 1 if closed else n)
    if closed:
        pts = pts[:-1]
        return make_interp_curve(pts, closed=True)
    if degree == 3:
        return make_interp_curve(pts)
    from OCP.GeomAPI import GeomAPI_PointsToBSpline
    from OCP.GeomAbs import GeomAbs_Shape
    arr = TColgp_Array1OfPnt(1, len(pts))
    for i, p in enumerate(pts, start=1):
        arr.SetValue(i, _pnt(p))
    cont = (GeomAbs_Shape.GeomAbs_C0 if degree < 2
            else GeomAbs_Shape.GeomAbs_C1)
    fit = GeomAPI_PointsToBSpline(arr, degree, degree, cont, 1e-4)
    if not fit.IsDone():
        raise GeometryError("Rebuild failed")
    return BRepBuilderAPI_MakeEdge(fit.Curve()).Edge()


def curvature_at(shape, near_point: Point) -> dict:
    """Curvature of a curve at the point closest to `near_point`."""
    from OCP.BRepLProp import BRepLProp_CLProps
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    edges = edges_of(shape)
    if not edges:
        raise GeometryError("Not a curve")
    v = BRepBuilderAPI_MakeVertex(_pnt(near_point)).Vertex()
    best = None
    for edge in edges:
        dist = BRepExtrema_DistShapeShape(v, edge)
        if dist.IsDone() and (best is None or dist.Value() < best[0]):
            best = (dist.Value(), edge, dist.PointOnShape2(1))
    _, edge, pt = best
    ad = occ.edge_adaptor(edge)
    # locate the parameter of the closest point by dense sampling refinement
    t0, t1 = ad.FirstParameter(), ad.LastParameter()
    samples = 256
    best_t, best_d = t0, float("inf")
    for i in range(samples + 1):
        t = t0 + (t1 - t0) * i / samples
        d = ad.Value(t).Distance(pt)
        if d < best_d:
            best_d, best_t = d, t
    props = BRepLProp_CLProps(ad, best_t, 2, 1e-9)
    k = props.Curvature()
    return {
        "point": pnt_tuple(ad.Value(best_t)),
        "curvature": k,
        "radius": (1.0 / k) if k > 1e-12 else float("inf"),
    }


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


def scale_along_axis(shape, center: Point, axis: Point,
                     factor: float) -> TopoDS_Shape:
    """Non-uniform scale by `factor` along an arbitrary unit axis."""
    import numpy as np
    if abs(factor) < 1e-9:
        raise GeometryError("Scale factor cannot be zero")
    a = np.asarray(axis, float)
    a = a / np.linalg.norm(a)
    m = np.eye(3) + (float(factor) - 1.0) * np.outer(a, a)
    c = np.asarray(center, float)
    t = c - m @ c
    g = gp_GTrsf()
    g.SetVectorialPart(gp_Mat(*m.flatten()))
    g.SetTranslationPart(gp_XYZ(*t))
    result = BRepBuilderAPI_GTransform(shape, g, True)
    if not result.IsDone():
        raise GeometryError("Axis scale failed")
    return result.Shape()


def mirror(shape, plane_point: Point, plane_normal: Point) -> TopoDS_Shape:
    t = gp_Trsf()
    t.SetMirror(gp_Ax2(_pnt(plane_point), _dir(plane_normal)))
    return _apply_trsf(shape, t)


def copy_shape(shape) -> TopoDS_Shape:
    return BRepBuilderAPI_Copy(shape).Shape()


# --- interrogation ----------------------------------------------------------

def shape_kind(shape) -> str:
    """Classify as 'curve' | 'surface' | 'solid' | 'point' | 'compound'.

    Compounds are classified by their contents when uniform: a compound of
    solids behaves as a solid, of curves as a curve, and so on."""
    st = shape.ShapeType()
    if st in (occ.EDGE, occ.WIRE):
        return "curve"
    if st in (occ.FACE, occ.SHELL):
        return "surface"
    if st in (occ.SOLID, occ.COMPSOLID):
        return "solid"
    if st == occ.VERTEX:
        return "point"
    kinds = set()
    from .occ import TopoDS_Iterator
    it = TopoDS_Iterator(shape)
    while it.More():
        kinds.add(shape_kind(it.Value()))
        it.Next()
    if len(kinds) == 1:
        return kinds.pop()
    return "compound"


def unwrap_compound(shape) -> TopoDS_Shape:
    """Strip single-child compound wrappers (some OCCT ops add them)."""
    from .occ import TopoDS_Iterator
    while shape.ShapeType() == occ.COMPOUND:
        it = TopoDS_Iterator(shape)
        children = []
        while it.More():
            children.append(it.Value())
            it.Next()
        if len(children) != 1:
            break
        shape = children[0]
    return shape


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
