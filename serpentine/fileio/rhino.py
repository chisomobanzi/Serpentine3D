"""Rhino .3dm import/export via rhino3dm.

Import: NURBS curves are converted exactly (poles/weights/knots); breps,
extrusions and NURBS surfaces come in as untrimmed NURBS faces; meshes are
sewn into shells. Layers (names/colors) are preserved both ways.

Export: curves as exact NURBS; surfaces and solids as meshes (render
meshes — Rhino re-imports them fine; exact BREP export goes via STEP).
"""

from __future__ import annotations

import numpy as np
import rhino3dm as r3

from ..core import geometry, occ
from ..core.occ import (
    BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, Geom_BSplineCurve,
    TColStd_Array1OfInteger, TColStd_Array1OfReal, TColgp_Array1OfPnt,
    gp_Pnt,
)
from ..core.tessellate import tessellate
from .obj import _shell_from_triangles


# ------------------------------------------------------------------ knots

def _rhino_knots_to_occ(knots: list[float]):
    """Rhino knot list -> (distinct knots, multiplicities) with clamped ends."""
    distinct, mults = [], []
    for k in knots:
        if distinct and abs(k - distinct[-1]) < 1e-12:
            mults[-1] += 1
        else:
            distinct.append(k)
            mults.append(1)
    mults[0] += 1        # Rhino omits the superfluous end knots
    mults[-1] += 1
    return distinct, mults


def _occ_knots_to_rhino(distinct: list[float], mults: list[int]) -> list[float]:
    out = []
    for i, (k, m) in enumerate(zip(distinct, mults)):
        count = m - 1 if i in (0, len(distinct) - 1) else m
        out.extend([k] * count)
    return out


# ------------------------------------------------------------------ curves

def _r3_curve_to_shape(curve: r3.Curve):
    nc = curve if isinstance(curve, r3.NurbsCurve) else curve.ToNurbsCurve()
    n = len(nc.Points)
    degree = nc.Degree
    knots = [nc.Knots[i] for i in range(len(nc.Knots))]
    distinct, mults = _rhino_knots_to_occ(knots)

    clamped = (sum(mults) == n + degree + 1
               and mults[0] == degree + 1 and mults[-1] == degree + 1)
    if not clamped:
        # periodic or exotic curve: sample and interpolate
        t0, t1 = nc.Domain.T0, nc.Domain.T1
        samples = max(32, n * 4)
        pts = []
        for i in range(samples + 1):
            p = nc.PointAt(t0 + (t1 - t0) * i / samples)
            pts.append((p.X, p.Y, p.Z))
        if nc.IsClosed:
            return geometry.make_interp_curve(pts[:-1], closed=True)
        return geometry.make_interp_curve(pts)

    poles = TColgp_Array1OfPnt(1, n)
    weights = TColStd_Array1OfReal(1, n)
    rational = nc.IsRational
    for i in range(n):
        cp = nc.Points[i]     # rhino stores homogeneous (premultiplied) coords
        w = cp.W if rational and cp.W > 1e-12 else 1.0
        poles.SetValue(i + 1, gp_Pnt(cp.X / w, cp.Y / w, cp.Z / w))
        weights.SetValue(i + 1, w)
    k_arr = TColStd_Array1OfReal(1, len(distinct))
    m_arr = TColStd_Array1OfInteger(1, len(distinct))
    for i, (k, m) in enumerate(zip(distinct, mults), start=1):
        k_arr.SetValue(i, float(k))
        m_arr.SetValue(i, int(m))
    bs = Geom_BSplineCurve(poles, weights, k_arr, m_arr, degree, False)
    return BRepBuilderAPI_MakeEdge(bs).Edge()


def _shape_to_r3_curve(shape) -> r3.NurbsCurve | None:
    try:
        bs = geometry._edge_bspline(shape)
    except geometry.GeometryError:
        return None
    n = bs.NbPoles()
    degree = bs.Degree()
    # (dimension, rational, order, count) — the 2-arg ctor is non-rational
    nc = r3.NurbsCurve(3, True, degree + 1, n)
    for i in range(n):
        p = bs.Pole(i + 1)
        w = bs.Weight(i + 1)
        nc.Points[i] = r3.Point4d(p.X() * w, p.Y() * w, p.Z() * w, w)
    distinct = [bs.Knot(i + 1) for i in range(bs.NbKnots())]
    mults = [bs.Multiplicity(i + 1) for i in range(bs.NbKnots())]
    rhino_knots = _occ_knots_to_rhino(distinct, mults)
    if len(rhino_knots) != len(nc.Knots):
        return None
    for i, k in enumerate(rhino_knots):
        nc.Knots[i] = k
    return nc


# ---------------------------------------------------------------- surfaces

def _r3_surface_to_face(srf: r3.Surface):
    ns = srf if isinstance(srf, r3.NurbsSurface) else srf.ToNurbsSurface()
    from OCP.Geom import Geom_BSplineSurface
    from OCP.TColgp import TColgp_Array2OfPnt
    from OCP.TColStd import TColStd_Array2OfReal

    cu, cv = ns.Points.CountU, ns.Points.CountV
    du, dv = ns.Degree(0), ns.Degree(1)
    ku = [ns.KnotsU[i] for i in range(len(ns.KnotsU))]
    kv = [ns.KnotsV[i] for i in range(len(ns.KnotsV))]
    u_distinct, u_mults = _rhino_knots_to_occ(ku)
    v_distinct, v_mults = _rhino_knots_to_occ(kv)
    if (sum(u_mults) != cu + du + 1 or sum(v_mults) != cv + dv + 1):
        return None    # periodic surface; skip exact conversion

    poles = TColgp_Array2OfPnt(1, cu, 1, cv)
    weights = TColStd_Array2OfReal(1, cu, 1, cv)
    for i in range(cu):
        for j in range(cv):
            cp = ns.Points.GetControlPoint(i, j)   # homogeneous coords
            w = cp.W if cp.W > 1e-12 else 1.0
            poles.SetValue(i + 1, j + 1,
                           gp_Pnt(cp.X / w, cp.Y / w, cp.Z / w))
            weights.SetValue(i + 1, j + 1, w)

    def arr1(vals, integer=False):
        a = (TColStd_Array1OfInteger if integer
             else TColStd_Array1OfReal)(1, len(vals))
        for i, v in enumerate(vals, start=1):
            a.SetValue(i, int(v) if integer else float(v))
        return a

    surf = Geom_BSplineSurface(
        poles, weights, arr1(u_distinct), arr1(v_distinct),
        arr1(u_mults, True), arr1(v_mults, True), du, dv, False, False)
    return BRepBuilderAPI_MakeFace(surf, 1e-6).Face()


def _r3_mesh_to_shape(mesh: r3.Mesh):
    verts = np.array([[v.X, v.Y, v.Z] for v in mesh.Vertices], float)
    tris = []
    for i in range(len(mesh.Faces)):
        f = mesh.Faces[i]
        a, b, c, d = f[0], f[1], f[2], f[3]
        tris.append((a, b, c))
        if d != c:
            tris.append((a, c, d))
    return _shell_from_triangles(verts, tris)


# -------------------------------------------------------------------- breps

def _brep_edges_to_occ(brep) -> list:
    edges = []
    for i in range(len(brep.Edges)):
        try:
            shape = _r3_curve_to_shape(brep.Edges[i].ToNurbsCurve())
            edges.append(shape)
        except Exception:
            continue
    return edges


def _split_face_by_edges(face, edges: list) -> list:
    """Split an untrimmed face with on-surface edges; [] if nothing cut."""
    from ..core.occ import BRepAlgoAPI_Splitter, TopTools_ListOfShape
    if not edges:
        return []
    args = TopTools_ListOfShape()
    args.Append(face)
    tools = TopTools_ListOfShape()
    for e in edges:
        tools.Append(e)
    sp = BRepAlgoAPI_Splitter()
    sp.SetArguments(args)
    sp.SetTools(tools)
    sp.SetFuzzyValue(1e-6)
    sp.Build()
    if not sp.IsDone():
        return []
    pieces = geometry.faces_of(sp.Shape())
    return pieces if len(pieces) > 1 else []


def _classify_by_mesh(pieces: list, mesh_shape, tol: float) -> list:
    """Keep split pieces whose centroid lies on the reference mesh."""
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from ..core.occ import BRepBuilderAPI_MakeVertex, gp_Pnt
    kept = []
    for piece in pieces:
        try:
            cx, cy, cz = geometry.centroid(piece)
            v = BRepBuilderAPI_MakeVertex(gp_Pnt(cx, cy, cz)).Vertex()
            d = BRepExtrema_DistShapeShape(v, mesh_shape)
            if d.IsDone() and d.Value() < tol:
                kept.append(piece)
        except Exception:
            continue
    return kept


def _wire_trimmed_planar(face, edges: list):
    """Exact trim for planar faces whose edges form closed wires."""
    from ..core.occ import BRepBuilderAPI_MakeFace
    try:
        wires = []
        remaining = list(edges)
        while remaining:
            wire = geometry.join_curves([remaining.pop(0)])
            # greedy grow
            grown = True
            while grown:
                grown = False
                for e in list(remaining):
                    try:
                        wire = geometry.join_curves([wire, e])
                        remaining.remove(e)
                        grown = True
                    except geometry.GeometryError:
                        continue
            wires.append(wire)
        closed = [w for w in wires if geometry.is_closed_curve(w)]
        if not closed:
            return None
        # largest loop is the boundary; the rest are holes
        closed.sort(key=lambda w: -geometry.curve_length(w))
        mk = BRepBuilderAPI_MakeFace(
            geometry.occ.to_wire(geometry.to_wire(closed[0])), True)
        if not mk.IsDone():
            return None
        from ..core.occ import TopAbs_Orientation
        for hole in closed[1:]:
            w = geometry.occ.to_wire(geometry.to_wire(hole))
            mk.Add(geometry.occ.to_wire(w.Reversed()))
        if not mk.IsDone():
            return None
        return mk.Face()
    except Exception:
        return None


def _import_brep(brep) -> list:
    """Faces of a Rhino brep as OCC faces, recovering trims when possible."""
    occ_edges = _brep_edges_to_occ(brep)
    faces = []
    for fi in range(len(brep.Faces)):
        rface = brep.Faces[fi]
        try:
            face = _r3_surface_to_face(rface.ToNurbsSurface())
        except Exception:
            face = None
        if face is None:
            mesh = _face_mesh_shape(rface)
            if mesh is not None:
                faces.append(mesh)
            continue

        pieces = _split_face_by_edges(face, occ_edges)
        if pieces:
            # trimmed face: resolve which pieces are real
            (mn, mx) = geometry.bbox(face)
            import numpy as np
            tol = max(float(np.linalg.norm(np.subtract(mx, mn))) * 0.02,
                      1e-4)
            resolved = None
            mesh = _face_mesh_shape(rface)
            if mesh is not None:
                kept = _classify_by_mesh(pieces, mesh, tol)
                if kept:
                    resolved = kept
            if resolved is None and rface.IsPlanar() \
                    and len(brep.Faces) == 1:
                exact = _wire_trimmed_planar(face, occ_edges)
                if exact is not None:
                    resolved = [exact]
            if resolved is None:
                resolved = [mesh] if mesh is not None else [face]
            faces.extend(resolved)
        else:
            faces.append(face)

    faces = [f for f in faces if f is not None and not f.IsNull()]
    if not faces:
        return []
    if len(faces) == 1:
        return faces
    from ..core.occ import BRepBuilderAPI_Sewing
    sew = BRepBuilderAPI_Sewing(1e-6)
    for f in faces:
        sew.Add(f)
    sew.Perform()
    return [sew.SewedShape()]


def _face_mesh_shape(rface):
    """The face's render mesh as a sewn OCC shell (None if absent)."""
    try:
        mesh = rface.GetMesh(r3.MeshType.Any)
        if mesh is None or len(mesh.Vertices) == 0:
            return None
        return _r3_mesh_to_shape(mesh)
    except Exception:
        return None


# ------------------------------------------------------------------- import

def import_3dm(path: str) -> list[tuple[str, object, dict]]:
    """Returns [(name, shape, {layer, color})]."""
    model = r3.File3dm.Read(path)
    if model is None:
        raise IOError(f"Could not read 3dm file: {path}")

    layers = {}
    for i in range(len(model.Layers)):
        layer = model.Layers[i]
        c = layer.Color
        layers[layer.Index] = {
            "name": layer.Name,
            "color": (c[0] / 255.0, c[1] / 255.0, c[2] / 255.0),
        }

    out = []
    counter = 0
    for obj in model.Objects:
        geo = obj.Geometry
        shapes = []
        if isinstance(geo, r3.Curve):
            try:
                shapes = [_r3_curve_to_shape(geo)]
            except Exception:
                shapes = []
        elif isinstance(geo, r3.Extrusion):
            brep = geo.ToBrep(True)
            if brep:
                geo = brep
        if isinstance(geo, r3.Brep):
            shapes = _import_brep(geo)
        elif isinstance(geo, (r3.NurbsSurface, r3.Surface)) \
                and not isinstance(geo, r3.Brep):
            try:
                face = _r3_surface_to_face(geo)
                shapes = [face] if face is not None else []
            except Exception:
                shapes = []
        elif isinstance(geo, r3.Mesh):
            shape = _r3_mesh_to_shape(geo)
            shapes = [shape] if shape is not None else []

        for shape in shapes:
            if shape is None or shape.IsNull():
                continue
            counter += 1
            name = obj.Attributes.Name or f"3dm object {counter:02d}"
            meta = layers.get(obj.Attributes.LayerIndex, {})
            out.append((name, shape, meta))
    return out


# ------------------------------------------------------------------- export

def export_3dm(scene, path: str, only_ids: list | None = None):
    model = r3.File3dm()
    layer_index = {}
    for layer in scene.layers.all():
        rl = r3.Layer()
        rl.Name = layer.name
        rl.Color = (int(layer.color[0] * 255), int(layer.color[1] * 255),
                    int(layer.color[2] * 255), 255)
        idx = model.Layers.Add(rl)
        layer_index[layer.id] = idx

    objs = scene.all()
    if only_ids:
        objs = [o for o in objs if o.id in only_ids]
    for obj in objs:
        attrs = r3.ObjectAttributes()
        attrs.Name = obj.name
        attrs.LayerIndex = layer_index.get(obj.layer_id, 0)
        if obj.kind == "curve":
            exported = False
            for edge in geometry.edges_of(obj.shape):
                nc = _shape_to_r3_curve(edge)
                if nc is not None:
                    model.Objects.AddCurve(nc, attrs)
                    exported = True
            if exported:
                continue
        mesh = tessellate(obj.shape)
        if not mesh.has_faces:
            continue
        rm = r3.Mesh()
        for v in mesh.vertices:
            rm.Vertices.Add(float(v[0]), float(v[1]), float(v[2]))
        for t in mesh.triangles:
            rm.Faces.AddFace(int(t[0]), int(t[1]), int(t[2]))
        rm.Normals.ComputeNormals()
        model.Objects.AddMesh(rm, attrs)

    if not model.Write(path, 8):
        raise IOError(f"Could not write 3dm file: {path}")
