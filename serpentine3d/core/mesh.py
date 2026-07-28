"""Native mesh objects: fast triangle geometry without OCCT.

A MeshShape stands in for a TopoDS_Shape in the scene. Heavy imports
(scans, OBJ props, lidar) stay as meshes: instant display, no sewing.
Convert to exact BREP only when modelling operations need it."""

from __future__ import annotations

import numpy as np


class MeshShape:
    """Immutable triangle mesh. Transform methods return new instances."""

    __slots__ = ("vertices", "triangles")

    def __init__(self, vertices, triangles):
        self.vertices = np.ascontiguousarray(vertices, np.float64)
        self.triangles = np.ascontiguousarray(triangles, np.uint32)

    # -- interrogation --

    def IsNull(self) -> bool:          # TopoDS protocol compatibility
        return len(self.vertices) == 0

    def bbox(self):
        if not len(self.vertices):
            return ((0, 0, 0), (0, 0, 0))
        mn = self.vertices.min(axis=0)
        mx = self.vertices.max(axis=0)
        return (tuple(mn), tuple(mx))

    def area(self) -> float:
        v0 = self.vertices[self.triangles[:, 0]]
        v1 = self.vertices[self.triangles[:, 1]]
        v2 = self.vertices[self.triangles[:, 2]]
        return float(np.linalg.norm(np.cross(v1 - v0, v2 - v0),
                                    axis=1).sum() / 2)

    def volume(self) -> float:
        """Signed volume (meaningful for closed meshes)."""
        v0 = self.vertices[self.triangles[:, 0]]
        v1 = self.vertices[self.triangles[:, 1]]
        v2 = self.vertices[self.triangles[:, 2]]
        return float(abs(np.einsum("ij,ij->i", v0,
                                   np.cross(v1, v2)).sum() / 6))

    def centroid(self):
        return tuple(self.vertices.mean(axis=0)) if len(self.vertices) \
            else (0.0, 0.0, 0.0)

    # -- transforms --

    def transformed(self, matrix: np.ndarray) -> "MeshShape":
        """Apply a 4x4 (or 3x3) transform."""
        m = np.asarray(matrix, float)
        if m.shape == (3, 3):
            verts = self.vertices @ m.T
        else:
            verts = self.vertices @ m[:3, :3].T + m[:3, 3]
        tris = self.triangles
        # a reflecting transform flips winding
        if np.linalg.det(m[:3, :3]) < 0:
            tris = tris[:, ::-1].copy()
        return MeshShape(verts, tris)

    def translated(self, offset) -> "MeshShape":
        return MeshShape(self.vertices + np.asarray(offset, float),
                         self.triangles)

    def copy(self) -> "MeshShape":
        return MeshShape(self.vertices.copy(), self.triangles.copy())

    # -- display --

    def feature_edges(self, angle_deg: float = 30.0) -> np.ndarray:
        """Boundary + crease edges as (K,2,3) segments."""
        tris = self.triangles
        if not len(tris):
            return np.zeros((0, 2, 3), np.float32)
        edges = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]],
                                tris[:, [2, 0]]])
        tri_ids = np.tile(np.arange(len(tris)), 3)
        key = np.sort(edges, axis=1)
        order = np.lexsort((key[:, 1], key[:, 0]))
        key_sorted = key[order]
        tri_sorted = tri_ids[order]
        v0 = self.vertices[tris[:, 0]]
        v1 = self.vertices[tris[:, 1]]
        v2 = self.vertices[tris[:, 2]]
        n = np.cross(v1 - v0, v2 - v0)
        lens = np.linalg.norm(n, axis=1, keepdims=True)
        lens[lens < 1e-12] = 1
        n = n / lens
        cos_tol = np.cos(np.radians(angle_deg))

        # Walking the sorted edges in Python cost three iterations per
        # triangle, each calling into numpy — six and a half minutes on one
        # survey mesh, which is what left an import sitting at 98%. The runs
        # of equal edges are found by comparing neighbours instead, and every
        # run is then judged at once.
        total = len(key_sorted)
        changed = np.any(key_sorted[1:] != key_sorted[:-1], axis=1)
        starts = np.concatenate(([0], np.flatnonzero(changed) + 1))
        counts = np.diff(np.concatenate((starts, [total])))

        boundary = starts[counts == 1]           # an edge with one triangle
        shared = starts[counts == 2]
        # Anything shared by three or more is non-manifold: no single fold
        # angle to measure, so it is left alone rather than guessed at.
        dots = np.einsum("ij,ij->i", n[tri_sorted[shared]],
                         n[tri_sorted[shared + 1]])
        creases = shared[dots < cos_tol]

        keep = np.concatenate((boundary, creases))
        if not len(keep):
            return np.zeros((0, 2, 3), np.float32)
        keep.sort()                              # the order the loop produced
        return self.vertices[key_sorted[keep]].astype(np.float32)


def merge(meshes) -> MeshShape:
    """Concatenate meshes into one, re-basing each triangle's vertex indices.
    Used where several mesh pieces describe a single object and shouldn't
    arrive in the scene as separate things."""
    meshes = [m for m in meshes if len(m.vertices)]
    if not meshes:
        return MeshShape(np.zeros((0, 3)), np.zeros((0, 3), np.uint32))
    verts, tris, offset = [], [], 0
    for m in meshes:
        verts.append(m.vertices)
        tris.append(m.triangles + offset)
        offset += len(m.vertices)
    return MeshShape(np.concatenate(verts), np.concatenate(tris))


def mesh_to_display(mesh: MeshShape):
    """DisplayMesh for the viewport, with smooth normals + feature edges."""
    from .tessellate import DisplayMesh, _smooth_normals
    dm = DisplayMesh()
    if len(mesh.vertices):
        dm.vertices = mesh.vertices.astype(np.float32)
        dm.triangles = mesh.triangles.astype(np.uint32)
        dm.normals = _smooth_normals(mesh.vertices, mesh.triangles)
        dm.edge_segments = mesh.feature_edges()
        dm.face_of_triangle = np.zeros(len(mesh.triangles), np.int32)
        dm.curvature = np.zeros(len(mesh.vertices), np.float32)
    return dm


def mesh_from_brep(shape) -> MeshShape:
    """Tessellate a BREP into a native mesh."""
    from .tessellate import tessellate
    dm = tessellate(shape)
    return MeshShape(dm.vertices.astype(float), dm.triangles)


def brep_from_mesh(mesh: MeshShape):
    """Sew a mesh into a BREP shell (slow for big meshes)."""
    from ..fileio.obj import _shell_from_triangles
    from . import geometry
    shape = _shell_from_triangles(mesh.vertices,
                                  [tuple(t) for t in mesh.triangles])
    if shape is None:
        raise geometry.GeometryError("Mesh could not be converted")
    return shape
