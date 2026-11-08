"""Contour, and Point On Curve."""

from __future__ import annotations

import numpy as np

from ... import geometry as g
from ...mesh import MeshShape
from . import COMPONENTS, Component
from ..kinds import GeometryGroup, HydraError, Port, Vector

MOST_CONTOURS = 2000        # the most levels one shape is cut at


def _contour(G, D, N, S=0.0):
    if D <= 0:
        raise HydraError("Distance must be more than 0")
    direction = np.asarray(N.components, float)
    if np.linalg.norm(direction) < 1e-12:
        raise HydraError("Direction has no length")
    direction /= np.linalg.norm(direction)
    if isinstance(G, GeometryGroup):
        raise HydraError("Contour cuts one shape at a time: ungroup it first")
    kind = g.shape_kind(G)
    if kind not in ("surface", "solid", "mesh"):
        raise HydraError("Contour cuts surfaces, solids and meshes, not "
                         f"{kind}s")
    low, high = G.bbox() if isinstance(G, MeshShape) else g.bbox(G)
    corners = np.array([[x, y, z] for x in (low[0], high[0])
                        for y in (low[1], high[1])
                        for z in (low[2], high[2])])
    along = corners @ direction
    if (along.max() - along.min()) / D > MOST_CONTOURS:
        raise HydraError(f"That makes more than {MOST_CONTOURS:,} contours: "
                         "take a larger distance")
    # at whole steps from the origin, as a map's contours are at round
    # heights, not from wherever the geometry happens to start
    first = np.floor(along.min() / D) * D
    levels = [level for level in np.arange(first, along.max() + D, D)
              if along.min() + 1e-6 < level < along.max() - 1e-6
              and not _skipped(level, S)]
    curves = []
    for level in levels:
        if isinstance(G, MeshShape):
            curves.extend(_mesh_cut(G, direction, level))
            continue
        try:
            curves.extend(g.section_curves(G, tuple(direction * level),
                                           tuple(direction)))
        except g.GeometryError:
            pass             # one sour level must not lose the others
    if not curves:
        raise HydraError("The distance is larger than the geometry: no "
                         "contour fits in it")
    return curves


def _skipped(level, every):
    """Whether a level is one Skip every leaves out: a whole multiple of
    it, as the major contours another Contour draws; none for 0."""
    if every <= 0:
        return False
    times = level / every
    return abs(times - round(times)) < 1e-6


def _mesh_cut(mesh, direction, level):
    """A triangle mesh cut by the plane `level` along `direction`, as
    polylines, closed where they meet themselves again."""
    side = mesh.vertices @ direction - level
    # a corner lying on the plane counts as just above it, so every
    # triangle the plane cuts has exactly two edges crossing it
    side[np.abs(side) < 1e-12] = 1e-12
    return _cut(mesh.vertices, mesh.triangles.astype(np.int64), side)


def _cut(vertices, triangles, side):
    above = side[triangles] > 0
    cut = triangles[above.any(axis=1) & ~above.all(axis=1)]
    if not len(cut):
        return []
    # each cut triangle gives one piece, between the two crossing edges;
    # an edge is named by its two corners, so neighbours share the name
    pieces = []
    for a, b, c in cut:
        ends = [tuple(sorted(e)) for e in ((a, b), (b, c), (c, a))
                if (side[e[0]] > 0) != (side[e[1]] > 0)]
        pieces.append(ends)
    at = {}
    for i, (e, f) in enumerate(pieces):
        at.setdefault(e, []).append(i)
        at.setdefault(f, []).append(i)

    def point(edge):
        i, j = edge
        t = side[i] / (side[i] - side[j])
        return tuple(vertices[i] + t * (vertices[j] - vertices[i]))

    used = [False] * len(pieces)
    curves = []
    # chains that end at the mesh's border first, so they are walked from
    # one end; the rest are rings
    order = sorted(range(len(pieces)), key=lambda i: min(
        len(at[pieces[i][0]]), len(at[pieces[i][1]])))
    for first in order:
        if used[first]:
            continue
        used[first] = True
        e, f = pieces[first]
        if len(at[f]) == 1:
            e, f = f, e                   # start from the border end
        chain = [e, f]
        while True:
            nxt = [i for i in at[chain[-1]] if not used[i]]
            if not nxt:
                break
            used[nxt[0]] = True
            a, b = pieces[nxt[0]]
            chain.append(b if a == chain[-1] else a)
        closed = len(chain) > 3 and chain[-1] == chain[0]
        points = [point(edge) for edge in (chain[:-1] if closed else chain)]
        if len(points) >= 2:
            curves.append(g.make_polyline(points, closed=closed))
    return curves


COMPONENTS["contour"] = Component(
    "contour", "Contour", "Curve",
    inputs=(Port("G", "geometry", label="Geometry",
                 description="The surfaces, solids or meshes to cut"),
            Port("D", "number", 1.0, label="Distance",
                 description="How far apart the contours are"),
            Port("N", "vector", Vector((0.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
                 label="Direction",
                 description="Which way the contours are spaced: square to "
                             "their planes, upwards (Z) unless set"),
            Port("S", "number", 0.0, label="Skip every",
                 description="Leaves out the heights that are a multiple of "
                             "it, such as every 5th, drawn by another "
                             "Contour; none unless set")),
    outputs=(Port("C", "curve", access="list", label="Curves",
                  description="The contour curves"),),
    icon="contour", solve=_contour,
    description="Cuts G, a Brep or a mesh, with planes D apart along N, as "
                "contour lines on a map: at whole steps of D from the "
                "origin, upwards (Z) by default")


def _point_on_curve(C, t):
    from OCP.BRepAdaptor import BRepAdaptor_CompCurve
    from OCP.GCPnts import GCPnts_AbscissaPoint
    from OCP.gp import gp_Pnt, gp_Vec
    from ... import occ
    if not 0 <= t <= 1:
        raise HydraError("t runs from 0, the start, to 1, the end")
    kind = C.ShapeType()
    if kind == occ.WIRE:
        adaptor = BRepAdaptor_CompCurve(occ.to_wire(C))
    elif kind == occ.EDGE:
        adaptor = occ.edge_adaptor(occ.to_edge(C))
    else:
        raise HydraError("Point On Curve takes one curve at a time")
    # t is a share of the length, not of the curve's own parameter, so 0.5
    # is the middle however the curve was drawn
    length = GCPnts_AbscissaPoint.Length_s(adaptor)
    at = GCPnts_AbscissaPoint(adaptor, t * length,
                              adaptor.FirstParameter()).Parameter()
    point, tangent = gp_Pnt(), gp_Vec()
    adaptor.D1(at, point, tangent)
    where = (point.X(), point.Y(), point.Z())
    if tangent.Magnitude() < 1e-12:
        raise HydraError("The curve has no direction there")
    tangent.Normalize()
    return (g.make_point(where),
            Vector(where, (where[0] + tangent.X(), where[1] + tangent.Y(),
                           where[2] + tangent.Z())))


COMPONENTS["point_on_curve"] = Component(
    "point_on_curve", "Point On Curve", "Curve",
    inputs=(Port("C", "curve", label="Curve",
                 description="The curve to find the point on"),
            Port("t", "number", 0.5, label="Where",
                 description="How far along: 0 the start, 1 the end, the "
                             "middle unless set")),
    outputs=(Port("P", "point", label="Point",
                  description="The point that far along"),
             Port("D", "vector", label="Direction",
                  description="Which way the curve runs there")),
    icon="pointoncurve", solve=_point_on_curve,
    description="The point t of the way along C, and the way the curve runs "
                "there: the middle unless set")
