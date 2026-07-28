"""Native mesh objects: fast triangle geometry without OCCT.

A MeshShape stands in for a TopoDS_Shape in the scene. Heavy imports
(scans, OBJ props, lidar) stay as meshes: instant display, no sewing.
Convert to exact BREP only when modelling operations need it."""

from __future__ import annotations

import numpy as np

# The fold a mesh is read as meaning: sharper than this is an edge someone
# drew, gentler is one surface curving. The outline and the shading ask the
# same question, so they ask it the same way.
_CREASE_DEG = 30.0


class MeshShape:
    """Immutable triangle mesh. Transform methods return new instances."""

    __slots__ = ("vertices", "triangles", "normals")

    def __init__(self, vertices, triangles, normals=None):
        self.vertices = np.ascontiguousarray(vertices, np.float64)
        self.triangles = np.ascontiguousarray(triangles, np.uint32)
        # None, which is the usual case, means work the shading out from the
        # triangles at display time. A caller that knows better than the
        # geometry does — a format carrying its own vertex normals, or script
        # that wants a particular look — says so here and is believed.
        self.normals = None if normals is None \
            else np.ascontiguousarray(normals, np.float64)

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
        normals = self.normals
        if normals is not None:
            # A normal is a direction, so it turns but does not travel, and it
            # turns by the inverse transpose — under a squash the surface tilts
            # the other way from its points. A reflection then reverses it,
            # because the winding it belongs to has just been reversed too.
            linear = m[:3, :3]
            try:
                normals = normals @ np.linalg.inv(linear)
            except np.linalg.LinAlgError:
                normals = normals @ linear.T      # flattened: nothing to undo
            if np.linalg.det(linear) < 0:
                normals = -normals
            lens = np.linalg.norm(normals, axis=1, keepdims=True)
            lens[lens < 1e-12] = 1
            normals = normals / lens
        # a reflecting transform flips winding
        if np.linalg.det(m[:3, :3]) < 0:
            tris = tris[:, ::-1].copy()
        return MeshShape(verts, tris, normals)

    def translated(self, offset) -> "MeshShape":
        return MeshShape(self.vertices + np.asarray(offset, float),
                         self.triangles, self.normals)

    def copy(self) -> "MeshShape":
        return MeshShape(self.vertices.copy(), self.triangles.copy(),
                         None if self.normals is None else self.normals.copy())

    # -- display --

    def feature_edges(self, angle_deg: float = _CREASE_DEG,
                      welding=None) -> np.ndarray:
        """Boundary + crease edges as (K,2,3) segments.

        welding is _weld's answer, passed in by a caller that has already
        paid for it."""
        tris = self.triangles
        if not len(tris):
            return np.zeros((0, 2, 3), np.float32)
        # Two faces are neighbours when they meet in space, which is not the
        # same as sharing a vertex index. Rhino stores a mesh unwelded — four
        # unshared corners per quad — so matching by index finds nothing
        # shared and calls every triangle edge a boundary. One survey object
        # produced 9.9 million of them: a wireframe drawn over a solid surface,
        # and 238 MB of it uploaded to the card and redrawn every frame.
        verts = self.vertices
        points, canonical = _weld(verts) if welding is None else welding
        welded = canonical[tris]

        # An edge is its two endpoints, lower first so that a triangle and its
        # neighbour describe their shared edge the same way round. The pair
        # then folds into one number, because sorting on one key is a single
        # pass where sorting on two is two.
        ends = welded[:, [1, 2, 0]]
        low = np.minimum(welded, ends).T.ravel()
        high = np.maximum(welded, ends).T.ravel()
        tri_ids = np.tile(np.arange(len(tris)), 3)
        packed = low * len(points) + high
        # Welding can fold a sliver triangle onto itself. A segment running
        # from a point to that same point is nothing to draw.
        real = low != high
        if not real.all():
            packed, tri_ids = packed[real], tri_ids[real]
        if not len(packed):
            return np.zeros((0, 2, 3), np.float32)
        order = np.argsort(packed)
        key_sorted = packed[order]
        tri_sorted = tri_ids[order]
        v0 = verts[tris[:, 0]]
        v1 = verts[tris[:, 1]]
        v2 = verts[tris[:, 2]]
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
        changed = key_sorted[1:] != key_sorted[:-1]
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
        kept = key_sorted[keep]                  # unpacked only for the few
        return points[np.column_stack(divmod(kept, len(points)))] \
            .astype(np.float32)


def merge(meshes) -> MeshShape:
    """Concatenate meshes into one, re-basing each triangle's vertex indices.
    Used where several mesh pieces describe a single object and shouldn't
    arrive in the scene as separate things."""
    meshes = [m for m in meshes if len(m.vertices)]
    if not meshes:
        return MeshShape(np.zeros((0, 3)), np.zeros((0, 3), np.uint32))
    verts, tris, normals, offset = [], [], [], 0
    for m in meshes:
        verts.append(m.vertices)
        tris.append(m.triangles + offset)
        # A piece with none still owns its rows, or every piece after it would
        # shade with its neighbour's normals.
        normals.append(m.normals if m.normals is not None
                       else _smoothed(m.vertices, m.triangles))
        offset += len(m.vertices)
    return MeshShape(np.concatenate(verts), np.concatenate(tris),
                     np.concatenate(normals))


def _weld(vertices) -> tuple:
    """Which vertices stand at the same point: (points, canonical), where
    canonical[i] indexes the one point vertex i is a copy of.

    np.unique(axis=0) would say this in one line, but it compares whole rows
    and took 32 seconds on 6.6 million of them; sorting the three columns
    takes half of one. Coincident points land next to each other, and a point
    is new only when it differs from the one before it."""
    if not len(vertices):
        return vertices[:0], np.zeros(0, np.int64)
    order = np.lexsort((vertices[:, 2], vertices[:, 1], vertices[:, 0]))
    ranked = vertices[order]
    starts_run = np.empty(len(ranked), bool)
    starts_run[0] = True
    np.any(ranked[1:] != ranked[:-1], axis=1, out=starts_run[1:])
    canonical = np.empty(len(vertices), np.int64)
    canonical[order] = np.cumsum(starts_run) - 1
    return ranked[starts_run], canonical


# How many faces around one point are compared with each other. Six or eight
# is an ordinary vertex; past this the fan is only partly consulted, which
# softens one point rather than costing a pass over the mesh for each face.
_MAX_FAN = 16


def _corner_normals(vertices, triangles, canonical,
                    angle_deg: float = _CREASE_DEG) -> np.ndarray:
    """A normal for every corner of every triangle, (3T,3), worked out from
    the triangles alone.

    A corner takes the average of the faces meeting at its point — but only
    the ones lying within angle_deg of its own face. Averaging the rest would
    round off every edge the modeller meant to be sharp, and at the rim of a
    cylinder it would tilt the wall up towards the lid and draw a bright band
    round the top of it."""
    tris = triangles
    if not len(tris):
        return np.zeros((0, 3))

    # Gathering the corner positions costs half a gigabyte on a survey mesh,
    # so it is done once and both the face normals and the corner angles are
    # taken from it. In full precision: a cave is tens of thousands of units
    # across with centimetre triangles, and single precision has no digits
    # left for the difference.
    corner = vertices[tris]                      # T x 3 x 3
    sides = corner[:, [1, 2, 0]] - corner        # corner i towards the next
    face = np.cross(sides[:, 0], -sides[:, 2])   # (v1-v0) x (v2-v0)
    lens = np.linalg.norm(face, axis=1, keepdims=True)
    lens[lens < 1e-12] = 1
    face /= lens
    lens = np.linalg.norm(sides, axis=2, keepdims=True)
    lens[lens < 1e-12] = 1
    sides /= lens
    # Each face votes with the angle it occupies at the corner, not with one
    # vote per triangle. A quad split by its diagonal gives one of its
    # neighbours two triangles at a shared corner and the other one, and
    # counting triangles would lean the normal towards the busier side —
    # 2.5 degrees of it round a 24-sided tube. The angles add up to the same
    # corner however the quad was cut. At corner i the two edges are the one
    # leaving it and the one arriving, which is the previous side reversed.
    cos = -np.einsum("ijk,ijk->ij", sides, sides[:, [2, 0, 1]])
    angle = np.arccos(np.clip(cos, -1, 1)).ravel()
    del corner, sides

    # The corners, ordered so the ones standing at the same point sit next to
    # each other. Then "every corner and the one k places along" is a single
    # comparison for the whole mesh, and a handful of those covers every pair
    # in every fan — no per-vertex list to build and walk.
    #
    # Directions only from here, all of them about a unit long, so single
    # precision has plenty and the loop moves half as much memory.
    at = canonical[tris].ravel()
    order = np.argsort(at, kind="stable")
    at = at[order]
    own = np.repeat(face.astype(np.float32), 3, axis=0)[order]
    weighted = own * angle.astype(np.float32)[order, None]
    acc = weighted.copy()                        # a face always votes for itself
    cos_tol = np.cos(np.radians(angle_deg))
    for k in range(1, _MAX_FAN):
        together = at[:-k] == at[k:]
        if not together.any():                   # no fan is this wide
            break
        gentle = np.einsum("ij,ij->i", own[:-k], own[k:]) >= cos_tol
        both = together & gentle
        acc[:-k][both] += weighted[k:][both]
        acc[k:][both] += weighted[:-k][both]

    lens = np.linalg.norm(acc, axis=1, keepdims=True)
    lens[lens < 1e-12] = 1
    acc /= lens
    unsorted = np.empty_like(acc)
    unsorted[order] = acc
    return unsorted


def _shaded_normals(vertices, triangles, canonical,
                    angle_deg: float = _CREASE_DEG) -> np.ndarray:
    """The same, folded onto one normal per vertex.

    A vertex several faces share can only hold one, so across a crease this
    keeps the last face's answer. mesh_to_display splits such vertices; here
    there is nowhere to put the copies."""
    out = np.zeros((len(vertices), 3))           # zero, not whatever was there
    if len(triangles):
        out[triangles.ravel()] = _corner_normals(vertices, triangles,
                                                 canonical, angle_deg)
    return out


def _smoothed(vertices, triangles) -> np.ndarray:
    """Normals for a mesh that brought none, as unit float64 rows."""
    return _shaded_normals(vertices, triangles, _weld(vertices)[1])


def mesh_to_display(mesh: MeshShape):
    """DisplayMesh for the viewport, with smooth normals + feature edges."""
    from .tessellate import DisplayMesh
    dm = DisplayMesh()
    if len(mesh.vertices):
        verts = mesh.vertices
        tris = mesh.triangles
        # Finding which corners coincide is the expensive part of both the
        # shading and the outline, and it is the same answer, so it is found
        # once and lent to each.
        welding = _weld(verts)
        dm.edge_segments = mesh.feature_edges(welding=welding)

        if mesh.normals is not None and len(mesh.normals) == len(verts):
            normals = np.asarray(mesh.normals, np.float32)
            lens = np.linalg.norm(normals, axis=1, keepdims=True)
            lens[lens < 1e-12] = 1
            normals = normals / lens
        elif len(tris):
            corners = _corner_normals(verts, tris, welding[1])
            flat = tris.ravel()
            normals = np.zeros((len(verts), 3))
            normals[flat] = corners
            # A vertex shared across a crease is being asked to point two ways
            # at once, and only the last way asked survives. On a cube that
            # leaves four faces shading with a normal lying in their own plane,
            # which is to say black. The corners that lost are given vertices
            # of their own, at the same place, carrying their own normal.
            #
            # Only the ones that lost, and only where losing means a crease.
            # Two corners on a curving surface disagree by a fraction of a
            # degree, which nobody can see; and a duvet with a few folds in it
            # is still mostly duvet, so copying the whole mesh because part of
            # it creases doubled this file for nothing.
            agrees = np.einsum("ij,ij->i", normals[flat], corners)
            lost = np.flatnonzero(agrees < np.cos(np.radians(_CREASE_DEG)))
            if len(lost):
                indices = flat.astype(np.int64)
                indices[lost] = len(verts) + np.arange(len(lost))
                verts = np.concatenate([verts, verts[flat[lost]]])
                normals = np.concatenate([normals, corners[lost]])
                tris = indices.reshape(-1, 3)
            normals = normals.astype(np.float32)
        else:
            normals = np.zeros((len(verts), 3), np.float32)

        dm.vertices = verts.astype(np.float32)
        dm.triangles = tris.astype(np.uint32)
        dm.normals = normals
        dm.face_of_triangle = np.zeros(len(tris), np.int32)
        dm.curvature = np.zeros(len(verts), np.float32)
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
