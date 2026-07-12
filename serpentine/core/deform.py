"""Space deformations: twist, bend, taper, flow.

Deformations act on NURBS control points (curves exactly as Rhino does;
surfaces face-by-face, then re-sewn). Control nets are refined first so
coarse geometry follows the deformation faithfully.
"""

from __future__ import annotations

import math

import numpy as np

from . import geometry, occ
from .tolerance import tol


# ------------------------------------------------------------ deform fields

def twist_fn(origin, axis, angle_deg: float, height: float):
    """Rotate points about `axis` by angle proportional to height along it."""
    o = np.asarray(origin, float)
    a = np.asarray(axis, float)
    a = a / np.linalg.norm(a)
    total = math.radians(angle_deg)

    def fn(p):
        p = np.asarray(p, float)
        h = float(np.dot(p - o, a))
        t = max(0.0, min(1.0, h / height)) if height else 0.0
        ang = total * t
        # Rodrigues rotation about the axis through origin
        v = p - o
        v_par = np.dot(v, a) * a
        v_perp = v - v_par
        w = np.cross(a, v_perp)
        rotated = (v_perp * math.cos(ang) + w * math.sin(ang) + v_par)
        return o + rotated
    return fn


def taper_fn(origin, axis, factor: float, height: float):
    """Scale radially towards the axis, 1.0 at the base to `factor` at
    `height` along the axis."""
    o = np.asarray(origin, float)
    a = np.asarray(axis, float)
    a = a / np.linalg.norm(a)

    def fn(p):
        p = np.asarray(p, float)
        h = float(np.dot(p - o, a))
        t = max(0.0, min(1.0, h / height)) if height else 0.0
        s = 1.0 + (factor - 1.0) * t
        v = p - o
        v_par = np.dot(v, a) * a
        v_perp = v - v_par
        return o + v_par + v_perp * s
    return fn


def bend_fn(origin, axis, angle_deg: float, length: float):
    """Bend: distance along `axis` becomes arc length on a circle.

    The region [0, length] along the axis bends by angle_deg; the bend
    happens in the plane containing the axis and world Z (or Y if the
    axis is vertical)."""
    o = np.asarray(origin, float)
    a = np.asarray(axis, float)
    a = a / np.linalg.norm(a)
    up = np.array([0.0, 0.0, 1.0])
    if abs(np.dot(a, up)) > 0.9:
        up = np.array([0.0, 1.0, 0.0])
    up = up - np.dot(up, a) * a
    up = up / np.linalg.norm(up)
    total = math.radians(angle_deg)
    if abs(total) < 1e-12 or length <= 0:
        return lambda p: np.asarray(p, float)
    radius = length / total

    def fn(p):
        p = np.asarray(p, float)
        v = p - o
        s = float(np.dot(v, a))          # distance along axis
        e = float(np.dot(v, up))         # elevation in the bend plane
        rest = v - s * a - e * up        # out-of-plane component
        t = max(0.0, min(1.0, s / length))
        ang = total * t
        overshoot = s - length * t       # beyond the bent region
        r = radius - e
        centre = o + up * radius
        dir_s = a * math.sin(ang) + up * (1 - math.cos(ang))
        pos = (centre - up * (r * math.cos(ang))
               + a * (r * math.sin(ang)))
        if overshoot:
            tangent = a * math.cos(ang) + up * math.sin(ang)
            pos = pos + tangent * overshoot
        return pos + rest
    return fn


def flow_fn(base_start, base_end, target_curve_shape):
    """Map the straight line base_start->base_end onto a target curve.

    x along the base line becomes arc length along the curve; the offset
    perpendicular to the base becomes offset in the curve's moving frame
    (rotation-minimising approximation)."""
    from .geometry import sample_curve
    p0 = np.asarray(base_start, float)
    p1 = np.asarray(base_end, float)
    base_dir = p1 - p0
    base_len = float(np.linalg.norm(base_dir))
    if base_len < 1e-12:
        raise geometry.GeometryError("Base line is degenerate")
    base_dir = base_dir / base_len
    base_up = np.array([0.0, 0.0, 1.0])
    if abs(np.dot(base_dir, base_up)) > 0.9:
        base_up = np.array([0.0, 1.0, 0.0])
    base_side = np.cross(base_dir, base_up)
    base_side /= np.linalg.norm(base_side)
    base_up = np.cross(base_side, base_dir)

    n_samples = 200
    pts = np.asarray(sample_curve(target_curve_shape, n_samples), float)
    # arc-length table
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    arc = np.concatenate([[0.0], np.cumsum(seg)])
    total_len = arc[-1]
    # rotation-minimising frames via double-reflection-lite (projection)
    tangents = np.gradient(pts, axis=0)
    tangents /= np.linalg.norm(tangents, axis=1, keepdims=True)
    sides = np.zeros_like(pts)
    ups = np.zeros_like(pts)
    ref = base_side
    for i in range(len(pts)):
        s = ref - np.dot(ref, tangents[i]) * tangents[i]
        n = np.linalg.norm(s)
        if n < 1e-9:
            s = np.cross(tangents[i], base_up)
            n = np.linalg.norm(s)
        s = s / n
        sides[i] = s
        ups[i] = np.cross(s, tangents[i])
        ref = s

    def fn(p):
        p = np.asarray(p, float)
        v = p - p0
        x = float(np.dot(v, base_dir))
        y = float(np.dot(v, base_side))
        z = float(np.dot(v, base_up))
        s_target = max(0.0, min(1.0, x / base_len)) * total_len
        i = int(np.searchsorted(arc, s_target))
        i = max(1, min(i, len(pts) - 1))
        f = ((s_target - arc[i - 1]) / (arc[i] - arc[i - 1])
             if arc[i] > arc[i - 1] else 0.0)
        base_pt = pts[i - 1] + (pts[i] - pts[i - 1]) * f
        side = sides[i - 1] + (sides[i] - sides[i - 1]) * f
        up = ups[i - 1] + (ups[i] - ups[i - 1]) * f
        # overshoot beyond the curve end continues along the last tangent
        over = (x / base_len) * total_len - s_target
        if over:
            base_pt = base_pt + tangents[i] * over
        return base_pt + side * y + up * z
    return fn


# --------------------------------------------------------------- application

def _refine_bspline_curve(bs, target: int = 24):
    """Insert knots until the curve has ~target poles."""
    while bs.NbPoles() < target:
        k0 = bs.FirstParameter()
        k1 = bs.LastParameter()
        existing = [bs.Knot(i + 1) for i in range(bs.NbKnots())]
        # insert midpoints of the largest spans
        spans = sorted(
            ((existing[i + 1] - existing[i], i)
             for i in range(len(existing) - 1)), reverse=True)
        if not spans or spans[0][0] < 1e-9:
            break
        _, i = spans[0]
        bs.InsertKnot((existing[i] + existing[i + 1]) / 2)
    return bs


def deform_curve(shape, fn) -> object:
    """Deform a curve object (all edges) through the space function."""
    edges = geometry.edges_of(shape)
    out = []
    for edge in edges:
        bs = geometry._edge_bspline(edge)
        _refine_bspline_curve(bs)
        for i in range(1, bs.NbPoles() + 1):
            p = bs.Pole(i)
            new = fn((p.X(), p.Y(), p.Z()))
            bs.SetPole(i, geometry._pnt(tuple(new)))
        out.append(geometry.BRepBuilderAPI_MakeEdge(bs).Edge())
    if len(out) == 1:
        return out[0]
    try:
        return geometry.join_curves(out)
    except geometry.GeometryError:
        return geometry.make_compound(out)


def deform_surface(shape, fn) -> object:
    """Deform surface/solid faces through the space function and re-sew."""
    from .occ import BRepBuilderAPI_MakeFace, BRepBuilderAPI_Sewing
    from OCP.Geom import Geom_BSplineSurface
    from OCP.GeomConvert import GeomConvert
    from .occ import BRep_Tool
    faces = geometry.faces_of(shape)
    if not faces:
        raise geometry.GeometryError("Nothing to deform")
    new_faces = []
    for face in faces:
        surf = BRep_Tool.Surface_s(face)
        if isinstance(surf, Geom_BSplineSurface):
            bs = surf.Copy()
        else:
            from OCP.BRepAdaptor import BRepAdaptor_Surface
            from OCP.Geom import Geom_RectangularTrimmedSurface
            ad = BRepAdaptor_Surface(face)
            trimmed = Geom_RectangularTrimmedSurface(
                surf, ad.FirstUParameter(), ad.LastUParameter(),
                ad.FirstVParameter(), ad.LastVParameter())
            bs = GeomConvert.SurfaceToBSplineSurface_s(trimmed)
        # refine both directions for fidelity
        for _ in range(40):
            if bs.NbUPoles() >= 16:
                break
            knots = [bs.UKnot(i + 1) for i in range(bs.NbUKnots())]
            spans = sorted(((knots[i + 1] - knots[i], i)
                            for i in range(len(knots) - 1)), reverse=True)
            if not spans or spans[0][0] < 1e-9:
                break
            _, i = spans[0]
            bs.InsertUKnot((knots[i] + knots[i + 1]) / 2, 1, 1e-9)
        for _ in range(40):
            if bs.NbVPoles() >= 16:
                break
            knots = [bs.VKnot(i + 1) for i in range(bs.NbVKnots())]
            spans = sorted(((knots[i + 1] - knots[i], i)
                            for i in range(len(knots) - 1)), reverse=True)
            if not spans or spans[0][0] < 1e-9:
                break
            _, i = spans[0]
            bs.InsertVKnot((knots[i] + knots[i + 1]) / 2, 1, 1e-9)
        for i in range(1, bs.NbUPoles() + 1):
            for j in range(1, bs.NbVPoles() + 1):
                p = bs.Pole(i, j)
                new = fn((p.X(), p.Y(), p.Z()))
                bs.SetPole(i, j, geometry._pnt(tuple(new)))
        mk = BRepBuilderAPI_MakeFace(bs, tol())
        if mk.IsDone():
            new_faces.append(mk.Face())
    if not new_faces:
        raise geometry.GeometryError("Deformation produced no faces")
    if len(new_faces) == 1:
        return new_faces[0]
    sew = BRepBuilderAPI_Sewing(tol() * 10)
    for f in new_faces:
        sew.Add(f)
    sew.Perform()
    return sew.SewedShape()


def deform_shape(shape, fn) -> object:
    if geometry.shape_kind(shape) == "curve":
        return deform_curve(shape, fn)
    return deform_surface(shape, fn)
