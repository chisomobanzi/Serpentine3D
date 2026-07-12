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

    @property
    def has_faces(self) -> bool:
        return len(self.triangles) > 0


def _deflection_for(shape) -> float:
    (mn, mx) = geometry.bbox(shape)
    diag = float(np.linalg.norm(np.subtract(mx, mn)))
    return max(diag * 0.002, 1e-4)


def _face_mesh(face) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
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
    if face.Orientation() == TopAbs_Orientation.TopAbs_REVERSED:
        idx = idx[:, ::-1].copy()
    normals = _smooth_normals(verts, idx)
    return verts.astype(np.float32), normals, idx


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


def tessellate(shape, deflection: float | None = None) -> DisplayMesh:
    if deflection is None:
        deflection = _deflection_for(shape)
    if geometry.shape_kind(shape) != "curve":
        BRepMesh_IncrementalMesh(shape, deflection, False, 0.35, True)

    all_verts, all_norms, all_tris = [], [], []
    offset = 0
    exp = TopExp_Explorer(shape, occ.FACE)
    while exp.More():
        fm = _face_mesh(occ.to_face(exp.Current()))
        exp.Next()
        if fm is None:
            continue
        verts, norms, tris = fm
        all_verts.append(verts)
        all_norms.append(norms)
        all_tris.append(tris + offset)
        offset += len(verts)

    segments = []
    for edge in geometry.edges_of(shape):
        pts = _edge_polyline(edge, deflection)
        if pts is not None and len(pts) >= 2:
            seg = np.stack([pts[:-1], pts[1:]], axis=1)
            segments.append(seg)

    mesh = DisplayMesh()
    if all_verts:
        mesh.vertices = np.concatenate(all_verts)
        mesh.normals = np.concatenate(all_norms)
        mesh.triangles = np.concatenate(all_tris)
    if segments:
        mesh.edge_segments = np.concatenate(segments).astype(np.float32)
    return mesh
