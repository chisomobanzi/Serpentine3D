"""Geometry construction and interrogation on top of the OCCT kernel.

Every builder takes plain Python tuples/floats and returns a TopoDS_Shape.
Points are (x, y, z) tuples throughout; vectors likewise.
"""

from __future__ import annotations

import math
import os
import tempfile

from . import occ
from .tolerance import tight, tol
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
    if _pnt(p1).Distance(_pnt(p2)) < tight():
        raise GeometryError("Line endpoints are coincident")
    return BRepBuilderAPI_MakeEdge(_pnt(p1), _pnt(p2)).Edge()


def make_polyline(points: list[Point], closed: bool = False) -> TopoDS_Shape:
    if len(points) < 2:
        raise GeometryError("Polyline needs at least 2 points")
    wire = BRepBuilderAPI_MakeWire()
    pts = [_pnt(p) for p in points]
    if closed and pts[0].Distance(pts[-1]) > tight():
        pts.append(pts[0])
    for a, b in zip(pts, pts[1:]):
        if a.Distance(b) < tight():
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
    interp = GeomAPI_Interpolate(arr, closed, tol() * 0.01)
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


def apply_matrix(shape, matrix):
    """Apply a 4x4 similarity transform (rotation + translation +
    uniform scale). OCCT's gp_Trsf cannot express shear/non-uniform."""
    import numpy as np
    from .mesh import MeshShape
    m = np.asarray(matrix, float)
    if isinstance(shape, MeshShape):
        return shape.transformed(m)
    trsf = gp_Trsf()
    trsf.SetValues(m[0, 0], m[0, 1], m[0, 2], m[0, 3],
                   m[1, 0], m[1, 1], m[1, 2], m[1, 3],
                   m[2, 0], m[2, 1], m[2, 2], m[2, 3])
    return BRepBuilderAPI_Transform(shape, trsf, True).Shape()


def curve_endpoints(shape) -> tuple[Point, Point]:
    """(start, end) of an open edge or wire."""
    st = shape.ShapeType()
    if st == occ.EDGE:
        ad = occ.edge_adaptor(occ.to_edge(shape))
        p0 = ad.Value(ad.FirstParameter())
        p1 = ad.Value(ad.LastParameter())
        return ((p0.X(), p0.Y(), p0.Z()), (p1.X(), p1.Y(), p1.Z()))
    if st == occ.WIRE:
        from OCP.BRep import BRep_Tool
        from OCP.TopExp import TopExp
        from OCP.TopoDS import TopoDS_Vertex
        v1, v2 = TopoDS_Vertex(), TopoDS_Vertex()
        TopExp.Vertices_s(occ.to_wire(shape), v1, v2)
        p0 = BRep_Tool.Pnt_s(v1)
        p1 = BRep_Tool.Pnt_s(v2)
        return ((p0.X(), p0.Y(), p0.Z()), (p1.X(), p1.Y(), p1.Z()))
    raise GeometryError("Not a curve")


def close_curve(shape) -> TopoDS_Shape:
    """Close an open curve with a straight segment start-to-end."""
    if is_closed_curve(shape):
        raise GeometryError("Curve is already closed")
    a, b = curve_endpoints(shape)
    import math
    if math.dist(a, b) < tol() * 0.1:
        raise GeometryError("Curve ends already coincide")
    return join_curves([shape, make_line(b, a)])


def is_closed_curve(shape) -> bool:
    st = shape.ShapeType()
    if st == occ.EDGE:
        ad = occ.edge_adaptor(occ.to_edge(shape))
        p0 = ad.Value(ad.FirstParameter())
        p1 = ad.Value(ad.LastParameter())
        return p0.Distance(p1) < tol() * 0.1
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
    lofter = BRepOffsetAPI_ThruSections(solid, ruled, tol() * 0.01)
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


def edge_chain(shape, edge_index: int, angle_tol_deg: float = 20.0) -> list:
    """Indices of edges forming a tangent-continuous chain with the given
    edge (shared vertices with aligned tangents)."""
    import numpy as np
    edges = edges_of(shape)
    if not (0 <= edge_index < len(edges)):
        raise GeometryError("Edge index out of range")

    def end_data(edge):
        ad = occ.edge_adaptor(edge)
        out = []
        for t in (ad.FirstParameter(), ad.LastParameter()):
            p = gp_Pnt()
            v = gp_Vec()
            ad.D1(t, p, v)
            tv = np.array([v.X(), v.Y(), v.Z()])
            n = np.linalg.norm(tv)
            out.append((np.array([p.X(), p.Y(), p.Z()]),
                        tv / n if n > 1e-12 else tv))
        return out

    data = [end_data(e) for e in edges]
    cos_tol = math.cos(math.radians(angle_tol_deg))
    chain = {edge_index}
    grew = True
    while grew:
        grew = False
        for i in chain.copy():
            for j in range(len(edges)):
                if j in chain:
                    continue
                for (pi, ti) in data[i]:
                    for (pj, tj) in data[j]:
                        if (np.linalg.norm(pi - pj) < tol()
                                and abs(float(np.dot(ti, tj))) > cos_tol):
                            chain.add(j)
                            grew = True
    return sorted(chain)


def fillet_edges(shape, radius, edges: list | None = None,
                 chamfer: bool = False) -> TopoDS_Shape:
    """Fillet (or chamfer) edges of a solid. edges=None means all edges.
    `radius` may be a single value or (r_start, r_end) for a variable
    fillet along each edge."""
    r_pair = None
    if isinstance(radius, (tuple, list)):
        r_pair = (float(radius[0]), float(radius[1]))
        if min(r_pair) <= 0:
            raise GeometryError("Radii must be positive")
    elif radius <= 0:
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
        if r_pair and not chamfer:
            mk.Add(r_pair[0], r_pair[1], e)
        elif r_pair:
            mk.Add(r_pair[0], r_pair[1], e)
        else:
            mk.Add(float(radius), e)
    mk.Build()
    if not mk.IsDone() or mk.Shape().IsNull():
        raise GeometryError(
            "Fillet failed — the radius is probably too large for "
            "the smallest edges; try a smaller value")
    return unwrap_compound(mk.Shape())


def face_normal(face) -> Point:
    """Outward normal of a (near-)planar face, respecting orientation."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_SurfaceType
    from OCP.TopAbs import TopAbs_Orientation
    surf = BRepAdaptor_Surface(face)
    if surf.GetType() != GeomAbs_SurfaceType.GeomAbs_Plane:
        raise GeometryError("Face is not planar")
    d = surf.Plane().Axis().Direction()
    n = (d.X(), d.Y(), d.Z())
    if face.Orientation() == TopAbs_Orientation.TopAbs_REVERSED:
        n = (-n[0], -n[1], -n[2])
    return n


def push_pull(shape, face_index: int, distance: float) -> TopoDS_Shape:
    """SketchUp-style push/pull: extrude a planar face of a solid outward
    (positive) or carve it inward (negative)."""
    faces = faces_of(shape)
    if not (0 <= face_index < len(faces)):
        raise GeometryError("Face index out of range")
    face = faces[face_index]
    n = face_normal(face)
    if abs(distance) < tight():
        raise GeometryError("Distance is zero")
    d = float(distance)
    vec = gp_Vec(n[0], n[1], n[2]).Multiplied(abs(d))
    if d < 0:
        vec = gp_Vec(-n[0], -n[1], -n[2]).Multiplied(abs(d))
    prism = BRepPrimAPI_MakePrism(face, vec).Shape()
    if d > 0:
        result = boolean_union(shape, prism)
    else:
        result = boolean_difference(shape, prism)
    return unwrap_compound(result)


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
    sew = BRepBuilderAPI_Sewing(tol())
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
    mk.PerformByJoin(shape, float(distance), tol())
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
                            -abs(float(thickness)), tol())
    if not mk.IsDone() or mk.Shape().IsNull():
        raise GeometryError("Shell failed (thickness may exceed the "
                            "solid's smallest feature)")
    return mk.Shape()


def patch_surface(curves: list, continuity: int = 0) -> TopoDS_Shape:
    """Patch/network surface filling the given boundary curves."""
    from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeFilling
    from OCP.GeomAbs import GeomAbs_Shape
    cont = (GeomAbs_Shape.GeomAbs_C0 if continuity == 0
            else GeomAbs_Shape.GeomAbs_C1)
    mk = BRepOffsetAPI_MakeFilling()
    n = 0
    for c in curves:
        for e in edges_of(c):
            mk.Add(e, cont, True)
            n += 1
    if n < 2:
        raise GeometryError("Patch needs at least 2 boundary edges")
    try:
        mk.Build()
    except Exception as exc:
        raise GeometryError(f"Patch failed: {exc}") from exc
    if not mk.IsDone():
        raise GeometryError("Patch failed — check that the curves form "
                            "a reasonable boundary")
    return unwrap_compound(mk.Shape())


def blend_curves(a, b, continuity: str = "tangent") -> TopoDS_Shape:
    """Blend curve between the nearest ends of two curves."""
    import numpy as np
    ends = []
    for shape in (a, b):
        edges = edges_of(shape)
        if not edges:
            raise GeometryError("Blend needs curves")
        ad0 = occ.edge_adaptor(edges[0])
        adN = occ.edge_adaptor(edges[-1])
        for ad, t in ((ad0, ad0.FirstParameter()),
                      (adN, adN.LastParameter())):
            p = ad.Value(t)
            v = gp_Vec()
            pnt = gp_Pnt()
            ad.D1(t, pnt, v)
            ends.append((np.array([p.X(), p.Y(), p.Z()]),
                         np.array([v.X(), v.Y(), v.Z()]),
                         t == ad.FirstParameter()))
    best = None
    for ea in ends[:2]:
        for eb in ends[2:]:
            d = float(np.linalg.norm(ea[0] - eb[0]))
            if best is None or d < best[0]:
                best = (d, ea, eb)
    _, (pa, ta, a_start), (pb, tb, b_start) = best
    # outgoing tangents: leaving curve a, entering curve b
    ta = -ta if a_start else ta
    tb = tb if b_start else -tb
    dist = float(np.linalg.norm(pb - pa))
    if dist < 1e-9:
        raise GeometryError("Curve ends coincide — nothing to blend")
    from OCP.Geom import Geom_BezierCurve
    if continuity == "position":
        return make_line(tuple(pa), tuple(pb))
    na = ta / (np.linalg.norm(ta) or 1.0)
    nb = tb / (np.linalg.norm(tb) or 1.0)
    poles = TColgp_Array1OfPnt(1, 4)
    poles.SetValue(1, _pnt(tuple(pa)))
    poles.SetValue(2, _pnt(tuple(pa + na * dist / 3)))
    poles.SetValue(3, _pnt(tuple(pb - nb * dist / 3)))
    poles.SetValue(4, _pnt(tuple(pb)))
    return BRepBuilderAPI_MakeEdge(Geom_BezierCurve(poles)).Edge()


def project_curve(curve, target, direction: Point) -> list:
    """Project a curve onto a surface along a direction."""
    from OCP.BRepProj import BRepProj_Projection
    wire = occ.to_wire(to_wire(curve))
    proj = BRepProj_Projection(wire, target, _dir(direction))
    out = []
    while proj.More():
        out.append(proj.Current())
        proj.Next()
    if not out:
        raise GeometryError("Projection missed the surface")
    return out


def pull_curve(curve, target) -> list:
    """Pull a curve onto a surface along the surface normals."""
    from OCP.BRepOffsetAPI import BRepOffsetAPI_NormalProjection
    proj = BRepOffsetAPI_NormalProjection(target)
    proj.Add(occ.to_wire(to_wire(curve)))
    proj.Build()
    if not proj.IsDone():
        raise GeometryError("Pull failed")
    edges = edges_of(proj.Projection())
    if not edges:
        raise GeometryError("Pull produced nothing (curve may not face "
                            "the surface)")
    return _curve_pieces(edges, [])


def make_helix(center: Point, radius: float, pitch: float, turns: float,
               ccw: bool = True) -> TopoDS_Shape:
    """Helical curve around the Z axis through `center`."""
    if radius <= 0 or pitch <= 0 or turns <= 0:
        raise GeometryError("Helix needs positive radius, pitch and turns")
    from OCP.Geom import Geom_CylindricalSurface
    from OCP.Geom2d import Geom2d_Line
    from OCP.gp import gp_Ax3, gp_Dir2d, gp_Pnt2d
    from OCP.BRepLib import BRepLib
    ax = gp_Ax3(_pnt(center), _dir((0, 0, 1)))
    surf = Geom_CylindricalSurface(ax, float(radius))
    sign = 1.0 if ccw else -1.0
    line2d = Geom2d_Line(gp_Pnt2d(0, 0), gp_Dir2d(sign * 2 * math.pi,
                                                  float(pitch)))
    length = math.hypot(2 * math.pi, pitch) * turns
    edge = BRepBuilderAPI_MakeEdge(line2d, surf, 0.0, length).Edge()
    BRepLib.BuildCurves3d_s(edge)
    return edge


def unroll_face(face) -> list:
    """Develop a planar/cylindrical/conical face flat onto world XY.

    Returns the developed boundary as curves (arc-length preserving)."""
    import numpy as np
    from OCP.BRepAdaptor import BRepAdaptor_Curve2d, BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_SurfaceType

    faces = faces_of(face)
    if len(faces) != 1:
        raise GeometryError("Unroll one face at a time (explode first)")
    f = faces[0]
    surf = BRepAdaptor_Surface(f)
    kind = surf.GetType()

    if kind == GeomAbs_SurfaceType.GeomAbs_Plane:
        def dev(u, v):
            return (u, v)
    elif kind == GeomAbs_SurfaceType.GeomAbs_Cylinder:
        r = surf.Cylinder().Radius()

        def dev(u, v):
            return (u * r, v)
    elif kind == GeomAbs_SurfaceType.GeomAbs_Cone:
        cone = surf.Cone()
        half = cone.SemiAngle()
        r_ref = cone.RefRadius()
        sin_h = math.sin(half)
        if abs(sin_h) < 1e-12:
            raise GeometryError("Degenerate cone")

        def dev(u, v):
            # slant distance from apex; flat angle compresses by sin(half)
            s = r_ref / sin_h + v
            theta = u * sin_h
            return (s * math.sin(theta), -s * math.cos(theta))
    else:
        raise GeometryError(
            "Only planar, cylindrical and conical faces can be unrolled "
            "exactly (this face is freeform)")

    out = []
    for edge in edges_of(f):
        try:
            c2d = BRepAdaptor_Curve2d(occ.to_edge(edge), f)
        except Exception:
            continue
        t0, t1 = c2d.FirstParameter(), c2d.LastParameter()
        pts = []
        for i in range(65):
            t = t0 + (t1 - t0) * i / 64
            uv = c2d.Value(t)
            x, y = dev(uv.X(), uv.Y())
            pts.append((x, y, 0.0))
        # drop duplicate consecutive points
        clean = [pts[0]]
        for p in pts[1:]:
            if math.dist(p, clean[-1]) > 1e-9:
                clean.append(p)
        if len(clean) >= 2:
            out.append(make_polyline(clean))
    if not out:
        raise GeometryError("Unroll produced no boundary curves")
    return out


def extend_curve(shape, length: float, end: str = "end") -> TopoDS_Shape:
    """Extend a curve tangentially past its start or end (line extension)."""
    import numpy as np
    if length <= 0:
        raise GeometryError("Extension length must be positive")
    edges = edges_of(shape)
    if not edges:
        raise GeometryError("Not a curve")
    edge = edges[-1] if end != "start" else edges[0]
    ad = occ.edge_adaptor(edge)
    t = ad.LastParameter() if end != "start" else ad.FirstParameter()
    p = gp_Pnt()
    v = gp_Vec()
    ad.D1(t, p, v)
    tangent = np.array([v.X(), v.Y(), v.Z()])
    n = np.linalg.norm(tangent)
    if n < 1e-12:
        raise GeometryError("Degenerate tangent at the curve end")
    tangent = tangent / n * float(length)
    if end == "start":
        tangent = -tangent
    start_pt = (p.X(), p.Y(), p.Z())
    tip = (p.X() + tangent[0], p.Y() + tangent[1], p.Z() + tangent[2])
    ext = make_line(start_pt, tip)
    return join_curves([shape, ext])


def match_curve(a, b, continuity: str = "tangent") -> TopoDS_Shape:
    """Move the end of curve `a` to meet the nearest end of curve `b`
    with position (G0) or tangent (G1) continuity. Returns the new a."""
    import numpy as np
    bs = _edge_bspline(a)
    ends_a = []
    for t, is_start in ((bs.FirstParameter(), True),
                        (bs.LastParameter(), False)):
        p = gp_Pnt()
        v = gp_Vec()
        bs.D1(t, p, v)
        ends_a.append((np.array([p.X(), p.Y(), p.Z()]), is_start))
    bsb = _edge_bspline(b)
    ends_b = []
    for t, is_start in ((bsb.FirstParameter(), True),
                        (bsb.LastParameter(), False)):
        p = gp_Pnt()
        v = gp_Vec()
        bsb.D1(t, p, v)
        ends_b.append((np.array([p.X(), p.Y(), p.Z()]),
                       np.array([v.X(), v.Y(), v.Z()]), is_start))
    best = None
    for (pa, a_start) in ends_a:
        for (pb, tb, b_start) in ends_b:
            d = float(np.linalg.norm(pa - pb))
            if best is None or d < best[0]:
                best = (d, a_start, pb, tb, b_start)
    _, a_start, pb, tb, b_start = best
    n = bs.NbPoles()
    if n < 2:
        raise GeometryError("Curve has too few control points")
    end_i = 1 if a_start else n
    next_i = 2 if a_start else n - 1
    bs.SetPole(end_i, _pnt(tuple(pb)))
    if continuity == "tangent":
        # direction of travel continuing out of b through the joint
        t_join = tb / (np.linalg.norm(tb) or 1.0)
        if b_start:
            t_join = -t_join
        cur = bs.Pole(next_i)
        dist = float(np.linalg.norm(
            np.array([cur.X(), cur.Y(), cur.Z()]) - pb)) or 1.0
        if a_start:      # a leaves the joint along t_join
            bs.SetPole(next_i, _pnt(tuple(pb + t_join * dist)))
        else:            # a arrives at the joint along t_join
            bs.SetPole(next_i, _pnt(tuple(pb - t_join * dist)))
    return BRepBuilderAPI_MakeEdge(bs).Edge()


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
            if BRepExtrema_DistShapeShape(v, c).Value() < tol():
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
    mk = BRepBuilderAPI_MakeFace(bs, tol())
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
    from .mesh import MeshShape
    if isinstance(shape, MeshShape):
        return shape.translated(offset)
    t = gp_Trsf()
    t.SetTranslation(_vec(offset))
    return _apply_trsf(shape, t)


def rotate(shape, axis_point: Point, axis_dir: Point,
           angle_deg: float) -> TopoDS_Shape:
    from .mesh import MeshShape
    if isinstance(shape, MeshShape):
        import numpy as np
        a = np.asarray(axis_dir, float)
        a = a / np.linalg.norm(a)
        ang = math.radians(float(angle_deg))
        K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]],
                      [-a[1], a[0], 0]])
        R = np.eye(3) + math.sin(ang) * K + (1 - math.cos(ang)) * (K @ K)
        o = np.asarray(axis_point, float)
        m = np.eye(4)
        m[:3, :3] = R
        m[:3, 3] = o - R @ o
        return shape.transformed(m)
    t = gp_Trsf()
    t.SetRotation(gp_Ax1(_pnt(axis_point), _dir(axis_dir)),
                  math.radians(float(angle_deg)))
    return _apply_trsf(shape, t)


def _gtransform(shape, gtrsf) -> TopoDS_Shape:
    """Non-uniform (gp_GTrsf) transform, made safe against a known OCCT
    crash: BRepBuilderAPI_GTransform on a shape that already carries a
    triangulation (from a prior tessellation) silently produces faces
    with NULL surfaces, and any later OCCT call on them segfaults.
    Strip the triangulation first, then reject a degenerate result."""
    from OCP.BRepTools import BRepTools
    BRepTools.Clean_s(shape)
    result = BRepBuilderAPI_GTransform(shape, gtrsf, True)
    if not result.IsDone():
        raise GeometryError("Non-uniform transform failed")
    out = result.Shape()
    if _has_null_surface(out):
        raise GeometryError("Non-uniform transform produced degenerate "
                            "geometry")
    return out


def _has_null_surface(shape) -> bool:
    from OCP.BRep import BRep_Tool
    exp = TopExp_Explorer(shape, occ.FACE)
    while exp.More():
        if BRep_Tool.Surface_s(occ.to_face(exp.Current())) is None:
            return True
        exp.Next()
    return False


def scale(shape, center: Point, factor: float,
          factors: Point | None = None) -> TopoDS_Shape:
    """Uniform scale, or non-uniform when `factors=(sx,sy,sz)` given."""
    from .mesh import MeshShape
    if isinstance(shape, MeshShape):
        import numpy as np
        f = np.asarray(factors if factors is not None
                       else (factor, factor, factor), float)
        if np.any(np.abs(f) < 1e-12):
            raise GeometryError("Scale factor cannot be zero")
        c = np.asarray(center, float)
        m = np.eye(4)
        m[:3, :3] = np.diag(f)
        m[:3, 3] = c - f * c
        return shape.transformed(m)
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
    gt = gp_GTrsf()
    gt.SetVectorialPart(gp_Mat(sx, 0, 0, 0, sy, 0, 0, 0, sz))
    gt.SetTranslationPart(gp_XYZ(cx - sx * cx, cy - sy * cy, cz - sz * cz))
    return _gtransform(shape, gt)


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
    gt = gp_GTrsf()
    gt.SetVectorialPart(gp_Mat(*m.flatten()))
    gt.SetTranslationPart(gp_XYZ(*t))
    return _gtransform(shape, gt)


def mirror(shape, plane_point: Point, plane_normal: Point) -> TopoDS_Shape:
    from .mesh import MeshShape
    if isinstance(shape, MeshShape):
        import numpy as np
        n = np.asarray(plane_normal, float)
        n = n / np.linalg.norm(n)
        o = np.asarray(plane_point, float)
        R = np.eye(3) - 2 * np.outer(n, n)
        m = np.eye(4)
        m[:3, :3] = R
        m[:3, 3] = o - R @ o
        return shape.transformed(m)
    t = gp_Trsf()
    t.SetMirror(gp_Ax2(_pnt(plane_point), _dir(plane_normal)))
    return _apply_trsf(shape, t)


def copy_shape(shape) -> TopoDS_Shape:
    from .mesh import MeshShape
    if isinstance(shape, MeshShape):
        return shape.copy()
    return BRepBuilderAPI_Copy(shape).Shape()


# --- interrogation ----------------------------------------------------------

def shape_kind(shape) -> str:
    """Classify as 'curve' | 'surface' | 'solid' | 'mesh' | 'point' |
    'compound'.

    Compounds are classified by their contents when uniform: a compound of
    solids behaves as a solid, of curves as a curve, and so on."""
    from .mesh import MeshShape
    if isinstance(shape, MeshShape):
        return "mesh"
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
    from .mesh import MeshShape
    if isinstance(shape, MeshShape):
        return shape.bbox()
    box = Bnd_Box()
    occ.bbox_add(shape, box)
    if box.IsVoid():
        return ((0, 0, 0), (0, 0, 0))
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    return ((xmin, ymin, zmin), (xmax, ymax, zmax))


def curve_length(shape) -> float:
    return occ.linear_properties(shape).Mass()


def surface_area(shape) -> float:
    from .mesh import MeshShape
    if isinstance(shape, MeshShape):
        return shape.area()
    return occ.surface_properties(shape).Mass()


def volume(shape) -> float:
    from .mesh import MeshShape
    if isinstance(shape, MeshShape):
        return shape.volume()
    return occ.volume_properties(shape).Mass()


def centroid(shape) -> Point:
    from .mesh import MeshShape
    if isinstance(shape, MeshShape):
        return shape.centroid()
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


# --- daily-driver batch: points, pipe, borders, untrim, edgesrf, isocurves ---

def make_point(p: Point) -> TopoDS_Shape:
    """A point object (vertex)."""
    from .occ import BRepBuilderAPI_MakeVertex
    return BRepBuilderAPI_MakeVertex(_pnt(p)).Vertex()


def point_coords(shape) -> Point:
    from OCP.BRep import BRep_Tool
    p = BRep_Tool.Pnt_s(occ.to_vertex(shape))
    return (p.X(), p.Y(), p.Z())


def pipe(rail, radius: float, cap: bool = True) -> TopoDS_Shape:
    """Tube of the given radius around a rail curve."""
    if radius <= 0:
        raise GeometryError("Pipe radius must be positive")
    from OCP.BRepAdaptor import BRepAdaptor_CompCurve
    from OCP.BRepBuilderAPI import BRepBuilderAPI_TransitionMode
    from .occ import BRepOffsetAPI_MakePipeShell, gp_Vec

    wire = occ.to_wire(to_wire(rail))
    ad = BRepAdaptor_CompCurve(wire)
    p0, tan = gp_Pnt(), gp_Vec()
    ad.D1(ad.FirstParameter(), p0, tan)
    if tan.Magnitude() < 1e-12:
        raise GeometryError("Cannot find rail direction")
    profile = make_circle((p0.X(), p0.Y(), p0.Z()), radius,
                          (tan.X(), tan.Y(), tan.Z()))
    ps = BRepOffsetAPI_MakePipeShell(wire)
    ps.SetTransitionMode(
        BRepBuilderAPI_TransitionMode.BRepBuilderAPI_RoundCorner)
    ps.Add(occ.to_wire(to_wire(profile)), False, False)
    ps.Build()
    if not ps.IsDone():
        raise GeometryError("Pipe failed on this rail")
    if cap:
        ps.MakeSolid()  # caps planar ends; harmless no-op when impossible
    return ps.Shape()


def free_boundaries(shape) -> list:
    """Naked boundary wires of a surface/polysurface (empty for solids)."""
    from .occ import ShapeAnalysis_FreeBounds
    fb = ShapeAnalysis_FreeBounds(shape)
    wires = []
    for comp in (fb.GetClosedWires(), fb.GetOpenWires()):
        if comp is None or comp.IsNull():
            continue
        exp = TopExp_Explorer(comp, occ.WIRE)
        while exp.More():
            wires.append(occ.to_wire(exp.Current()))
            exp.Next()
    return wires


def untrim(shape, holes_only: bool = True) -> TopoDS_Shape:
    """Remove trims from a single face.

    holes_only keeps the outer boundary and drops interior holes; otherwise
    the face is rebuilt over the surface's natural bounds (infinite
    directions clamped to the current trimmed range)."""
    faces = faces_of(shape)
    if len(faces) != 1:
        raise GeometryError("Untrim works on a single face")
    face = faces[0]
    from OCP.BRep import BRep_Tool
    from OCP.BRepTools import BRepTools
    surf = BRep_Tool.Surface_s(face)
    if holes_only:
        outer = BRepTools.OuterWire_s(face)
        mk = BRepBuilderAPI_MakeFace(surf, outer)
        if not mk.IsDone():
            raise GeometryError("Untrim failed")
        return mk.Face()
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAdaptor import GeomAdaptor_Surface
    ga = GeomAdaptor_Surface(surf)
    ba = BRepAdaptor_Surface(face)

    def _rng(nat_lo, nat_hi, trim_lo, trim_hi):
        big = 1e50
        return (nat_lo if abs(nat_lo) < big else trim_lo,
                nat_hi if abs(nat_hi) < big else trim_hi)

    u1, u2 = _rng(ga.FirstUParameter(), ga.LastUParameter(),
                  ba.FirstUParameter(), ba.LastUParameter())
    v1, v2 = _rng(ga.FirstVParameter(), ga.LastVParameter(),
                  ba.FirstVParameter(), ba.LastVParameter())
    mk = BRepBuilderAPI_MakeFace(surf, u1, u2, v1, v2, 1e-7)
    if not mk.IsDone():
        raise GeometryError("Untrim failed")
    return mk.Face()


def _order_loop(curves: list) -> list:
    """Order and orient single-edge curves head-to-tail (greedy chaining)."""
    bs = [_edge_bspline(c) for c in curves]
    ends = []
    for b in bs:
        p0, p1 = b.StartPoint(), b.EndPoint()
        ends.append(((p0.X(), p0.Y(), p0.Z()), (p1.X(), p1.Y(), p1.Z())))
    diag = 0.0
    for (s, e) in ends:
        diag = max(diag, abs(s[0]) + abs(s[1]) + abs(s[2]),
                   abs(e[0]) + abs(e[1]) + abs(e[2]))
    tol = max(diag * 1e-6, 1e-7)

    def _d(a, b):
        return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5

    ordered = [bs[0]]
    tail = ends[0][1]
    remaining = list(range(1, len(bs)))
    while remaining:
        found = None
        for i in remaining:
            s, e = ends[i]
            if _d(tail, s) < tol:
                found, rev = i, False
                break
            if _d(tail, e) < tol:
                found, rev = i, True
                break
        if found is None:
            raise GeometryError("Curves do not connect end-to-end")
        b = bs[found]
        if rev:
            b.Reverse()
        s, e = ends[found]
        tail = s if rev else e
        ordered.append(b)
        remaining.remove(found)
    return ordered


def edge_surface(curves: list) -> TopoDS_Shape:
    """Coons-style surface from 2, 3 or 4 connected boundary curves."""
    from OCP.GeomFill import GeomFill_BSplineCurves, GeomFill_FillingStyle
    n = len(curves)
    if n not in (2, 3, 4):
        raise GeometryError("EdgeSrf needs 2, 3 or 4 curves")
    style = GeomFill_FillingStyle.GeomFill_CoonsStyle
    if n == 2:
        b1, b2 = _edge_bspline(curves[0]), _edge_bspline(curves[1])
        s10, s20 = b1.StartPoint(), b2.StartPoint()
        e1, e2 = b1.EndPoint(), b2.EndPoint()
        if (s10.Distance(s20) + e1.Distance(e2)
                > s10.Distance(e2) + e1.Distance(s20)):
            b2.Reverse()
        fill = GeomFill_BSplineCurves(b1, b2, style)
    else:
        bs = _order_loop(curves)
        tail = bs[-1].EndPoint()
        head = bs[0].StartPoint()
        if tail.Distance(head) > 1e-5 * max(1.0, tail.XYZ().Modulus()):
            raise GeometryError("Curves do not form a closed loop")
        for b in bs:  # Coons fill needs degree >= 2
            if b.Degree() < 3:
                b.IncreaseDegree(3)
        fill = GeomFill_BSplineCurves(*bs, style)
    surf = fill.Surface()
    mk = BRepBuilderAPI_MakeFace(surf, 1e-6)
    if not mk.IsDone():
        raise GeometryError("EdgeSrf failed to build the surface")
    return mk.Face()


def iso_curve(shape, point: Point, along: str = "u") -> TopoDS_Shape:
    """Isoparametric curve through `point`, running along U or V."""
    faces = faces_of(shape)
    if len(faces) != 1:
        raise GeometryError("Pick a single surface")
    face = faces[0]
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.ShapeAnalysis import ShapeAnalysis_Surface
    surf = BRep_Tool.Surface_s(face)
    uv = ShapeAnalysis_Surface(surf).ValueOfUV(_pnt(point), 1e-6)
    ba = BRepAdaptor_Surface(face)
    if along.lower() == "u":
        curve = surf.VIso(uv.Y())
        lo, hi = ba.FirstUParameter(), ba.LastUParameter()
    else:
        curve = surf.UIso(uv.X())
        lo, hi = ba.FirstVParameter(), ba.LastVParameter()
    if curve is None:
        raise GeometryError("No isocurve at this point")
    return BRepBuilderAPI_MakeEdge(curve, lo, hi).Edge()


def tween_curves(curve_a, curve_b, count: int = 1,
                 samples: int = 64) -> list:
    """`count` intermediate curves blended between two curves."""
    if count < 1:
        raise GeometryError("Tween needs at least 1 intermediate curve")
    pa = sample_curve(curve_a, samples)
    pb = sample_curve(curve_b, samples)

    def _d(p, q):
        return sum((x - y) ** 2 for x, y in zip(p, q)) ** 0.5

    # orient b to run the same way as a
    if (_d(pa[0], pb[0]) + _d(pa[-1], pb[-1])
            > _d(pa[0], pb[-1]) + _d(pa[-1], pb[0])):
        pb = pb[::-1]
    closed = is_closed_curve(curve_a) and is_closed_curve(curve_b)
    out = []
    for i in range(1, count + 1):
        t = i / (count + 1)
        pts = [tuple(a + (b - a) * t for a, b in zip(p, q))
               for p, q in zip(pa, pb)]
        if closed:
            out.append(make_interp_curve(pts[:-1], closed=True))
        else:
            out.append(make_interp_curve(pts))
    return out


def smooth_curve(shape, strength: float = 0.2, iterations: int = 5):
    """Laplacian-smooth a curve's control points (endpoints stay put)."""
    strength = min(max(float(strength), 0.0), 1.0)
    bs = _edge_bspline(shape)
    n = bs.NbPoles()
    if n < 3:
        return copy_shape(shape)
    periodic = bs.IsPeriodic()
    seam = (not periodic
            and bs.StartPoint().Distance(bs.EndPoint()) < 1e-9)

    def _blend(p, a, b):
        return gp_Pnt(p.X() + ((a.X() + b.X()) / 2 - p.X()) * strength,
                      p.Y() + ((a.Y() + b.Y()) / 2 - p.Y()) * strength,
                      p.Z() + ((a.Z() + b.Z()) / 2 - p.Z()) * strength)

    for _ in range(max(1, int(iterations))):
        poles = [bs.Pole(i) for i in range(1, n + 1)]
        if periodic:
            for i in range(n):
                bs.SetPole(i + 1, _blend(poles[i], poles[(i - 1) % n],
                                         poles[(i + 1) % n]))
        else:
            for i in range(1, n - 1):
                bs.SetPole(i + 1, _blend(poles[i], poles[i - 1],
                                         poles[i + 1]))
            if seam:
                # coincident end poles move together across the seam
                p = _blend(poles[0], poles[n - 2], poles[1])
                bs.SetPole(1, p)
                bs.SetPole(n, p)
    return BRepBuilderAPI_MakeEdge(bs).Edge()
