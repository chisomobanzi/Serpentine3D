"""Shape tessellation: TopoDS_Shape -> numpy arrays for the GL viewport."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import occ, geometry
from .occ import (
    BRepMesh_IncrementalMesh, TopExp_Explorer, TopLoc_Location,
    GCPnts_TangentialDeflection, TopAbs_Orientation,
)


@dataclass
class DisplayMesh:
    """GPU-ready geometry for one scene object."""
    vertices: np.ndarray = field(
        default_factory=lambda: np.zeros((0, 3), np.float32))
    normals: np.ndarray = field(
        default_factory=lambda: np.zeros((0, 3), np.float32))
    triangles: np.ndarray = field(
        default_factory=lambda: np.zeros((0, 3), np.uint32))
    # edge polylines flattened to GL_LINES segment pairs: (K, 2, 3)
    edge_segments: np.ndarray = field(
        default_factory=lambda: np.zeros((0, 2, 3), np.float32))
    # isoparametric curves on curved faces (display only, not pickable)
    iso_segments: np.ndarray = field(
        default_factory=lambda: np.zeros((0, 2, 3), np.float32))
    # signed mean curvature per vertex (for curvature analysis display)
    curvature: np.ndarray = field(
        default_factory=lambda: np.zeros(0, np.float32))
    # sub-object topology maps: segment -> edge index, triangle -> face index
    edge_of_segment: np.ndarray = field(
        default_factory=lambda: np.zeros(0, np.int32))
    face_of_triangle: np.ndarray = field(
        default_factory=lambda: np.zeros(0, np.int32))

    @property
    def has_faces(self) -> bool:
        return len(self.triangles) > 0


def _deflection_for(shape) -> float:
    (mn, mx) = geometry.bbox(shape)
    diag = float(np.linalg.norm(np.subtract(mx, mn)))
    return max(diag * 0.002, 1e-4)


def _face_mesh(face) -> tuple | None:
    loc = TopLoc_Location()
    tri = occ.triangulation(face, loc)
    if tri is None:
        return None
    trsf = loc.Transformation()
    n = tri.NbNodes()
    verts = np.empty((n, 3), np.float64)
    for i in range(1, n + 1):
        p = tri.Node(i).Transformed(trsf)
        verts[i - 1] = (p.X(), p.Y(), p.Z())
    m = tri.NbTriangles()
    idx = np.empty((m, 3), np.uint32)
    for i in range(1, m + 1):
        t = tri.Triangle(i)
        idx[i - 1] = (t.Value(1) - 1, t.Value(2) - 1, t.Value(3) - 1)
    reversed_face = (face.Orientation()
                     == TopAbs_Orientation.TopAbs_REVERSED)
    if reversed_face:
        idx = idx[:, ::-1].copy()
    normals = _smooth_normals(verts, idx)
    curv = _vertex_curvature(face, tri, n, reversed_face)
    return verts.astype(np.float32), normals, idx, curv


def _vertex_curvature(face, tri, n: int, reversed_face: bool) -> np.ndarray:
    """Signed mean curvature at each triangulation vertex (0 on failure)."""
    curv = np.zeros(n, np.float32)
    if not tri.HasUVNodes():
        return curv
    try:
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.BRepLProp import BRepLProp_SLProps
        surf = BRepAdaptor_Surface(face)
        props = BRepLProp_SLProps(surf, 2, 1e-6)
        sign = -1.0 if reversed_face else 1.0
        for i in range(1, n + 1):
            uv = tri.UVNode(i)
            props.SetParameters(uv.X(), uv.Y())
            if props.IsCurvatureDefined():
                curv[i - 1] = sign * props.MeanCurvature()
    except Exception:
        pass
    return curv


def _smooth_normals(verts: np.ndarray, tris: np.ndarray) -> np.ndarray:
    """Area-weighted per-vertex normals."""
    normals = np.zeros_like(verts)
    if len(tris):
        v0, v1, v2 = (verts[tris[:, k]] for k in range(3))
        face_n = np.cross(v1 - v0, v2 - v0)
        for k in range(3):
            np.add.at(normals, tris[:, k], face_n)
    lens = np.linalg.norm(normals, axis=1, keepdims=True)
    lens[lens < 1e-12] = 1.0
    return (normals / lens).astype(np.float32)


def _edge_polyline(edge, deflection: float) -> np.ndarray | None:
    try:
        adaptor = occ.edge_adaptor(edge)
        disc = GCPnts_TangentialDeflection(adaptor, 0.25, deflection, 2)
        n = disc.NbPoints()
        if n < 2:
            return None
        pts = np.empty((n, 3), np.float32)
        for i in range(1, n + 1):
            p = disc.Value(i)
            pts[i - 1] = (p.X(), p.Y(), p.Z())
        return pts
    except Exception:
        return None


_ISO_FRACTIONS = (0.25, 0.5, 0.75)
_ISO_SAMPLES = 48


def _face_isocurves(face) -> list[np.ndarray]:
    """Isoparametric polylines on a curved face, clipped to its trims."""
    from ..core.occ import (
        BRepAdaptor_Surface, BRepTopAdaptor_FClass2d, TopAbs_State, gp_Pnt2d,
    )
    from OCP.GeomAbs import GeomAbs_SurfaceType

    surf = BRepAdaptor_Surface(face)
    if surf.GetType() == GeomAbs_SurfaceType.GeomAbs_Plane:
        return []
    u0, u1 = surf.FirstUParameter(), surf.LastUParameter()
    v0, v1 = surf.FirstVParameter(), surf.LastVParameter()
    if not all(np.isfinite([u0, u1, v0, v1])):
        return []
    classifier = BRepTopAdaptor_FClass2d(face, 1e-9)
    inside = (TopAbs_State.TopAbs_IN, TopAbs_State.TopAbs_ON)

    polylines = []
    for direction in ("u", "v"):
        for frac in _ISO_FRACTIONS:
            run = []
            for i in range(_ISO_SAMPLES + 1):
                t = i / _ISO_SAMPLES
                if direction == "u":
                    u = u0 + (u1 - u0) * frac
                    v = v0 + (v1 - v0) * t
                else:
                    u = u0 + (u1 - u0) * t
                    v = v0 + (v1 - v0) * frac
                if classifier.Perform(gp_Pnt2d(u, v)) in inside:
                    p = surf.Value(u, v)
                    run.append((p.X(), p.Y(), p.Z()))
                else:
                    if len(run) >= 2:
                        polylines.append(np.asarray(run, np.float32))
                    run = []
            if len(run) >= 2:
                polylines.append(np.asarray(run, np.float32))
    return polylines


def tessellate(shape, deflection: float | None = None) -> DisplayMesh:
    from .mesh import MeshShape, mesh_to_display
    if isinstance(shape, MeshShape):
        return mesh_to_display(shape)
    if deflection is None:
        deflection = _deflection_for(shape)
    if geometry.shape_kind(shape) != "curve":
        BRepMesh_IncrementalMesh(shape, deflection, False, 0.35, True)

    all_verts, all_norms, all_tris, all_curv, isos = [], [], [], [], []
    tri_face_ids = []
    offset = 0
    face_index = -1
    exp = TopExp_Explorer(shape, occ.FACE)
    while exp.More():
        face = occ.to_face(exp.Current())
        face_index += 1
        fm = _face_mesh(face)
        exp.Next()
        if fm is None:
            continue
        verts, norms, tris, curv = fm
        all_verts.append(verts)
        all_norms.append(norms)
        all_tris.append(tris + offset)
        all_curv.append(curv)
        tri_face_ids.append(np.full(len(tris), face_index, np.int32))
        offset += len(verts)
        try:
            for pts in _face_isocurves(face):
                isos.append(np.stack([pts[:-1], pts[1:]], axis=1))
        except Exception:
            pass

    segments = []
    seg_edge_ids = []
    for edge_index, edge in enumerate(geometry.edges_of(shape)):
        pts = _edge_polyline(edge, deflection)
        if pts is not None and len(pts) >= 2:
            seg = np.stack([pts[:-1], pts[1:]], axis=1)
            segments.append(seg)
            seg_edge_ids.append(np.full(len(seg), edge_index, np.int32))

    mesh = DisplayMesh()
    if all_verts:
        mesh.vertices = np.concatenate(all_verts)
        mesh.normals = np.concatenate(all_norms)
        mesh.triangles = np.concatenate(all_tris)
        mesh.curvature = np.concatenate(all_curv).astype(np.float32)
        mesh.face_of_triangle = np.concatenate(tri_face_ids)
    if segments:
        mesh.edge_segments = np.concatenate(segments).astype(np.float32)
        mesh.edge_of_segment = np.concatenate(seg_edge_ids)
    if isos:
        mesh.iso_segments = np.concatenate(isos).astype(np.float32)
    return mesh
