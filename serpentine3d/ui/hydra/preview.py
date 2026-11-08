"""The graph's preview in the model viewports, meshed once per shape."""

from __future__ import annotations

import numpy as np


MESH_WIRES_UP_TO = 50000    # triangles a mesh may have to show all its edges


class PreviewMeshes:
    """The preview's triangles, segments and points, as the viewport's
    overlay draw takes them.

    Meshing is what a preview costs, so each shape is meshed once, without
    its placement, and only turned into place on every solve after. A
    rotated shape keeps its surfaces and changes only its placement, which
    is what makes dragging a slider into a Rotate run smoothly.
    """

    def __init__(self):
        self._kept: dict = {}

    def overlay(self, shapes):
        kept, parts = {}, ([], [], [])
        for shape in shapes:
            base, matrix = _unplaced(shape)
            key = hash(base) if matrix is not None else ("obj", id(shape))
            entry = self._kept.get(key) or kept.get(key)
            if entry is None or not _same(entry[0], base):
                entry = (base, _mesh_arrays(base))
            kept[key] = entry
            for part, arr in zip(parts, entry[1]):
                if len(arr):
                    part.append(arr if matrix is None
                                else arr @ matrix[:3, :3].T + matrix[:3, 3])
        self._kept = kept
        return tuple(np.concatenate(part) if part
                     else np.empty((0, 3), np.float32) for part in parts)


def _unplaced(shape):
    """An OCC shape without its placement, and the placement as a matrix;
    anything else as it is, with no matrix."""
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS_Shape
    if not isinstance(shape, TopoDS_Shape):
        return shape, None
    trsf = shape.Location().Transformation()
    matrix = np.array([[trsf.Value(r, c) for c in range(1, 5)]
                       for r in range(1, 4)] + [[0.0, 0.0, 0.0, 1.0]])
    return shape.Located(TopLoc_Location()), matrix


def _same(a, b):
    from OCP.TopoDS import TopoDS_Shape
    return a.IsEqual(b) if isinstance(a, TopoDS_Shape) else a is b


def _mesh_arrays(shape):
    from ...core.tessellate import tessellate
    empty = np.empty((0, 3))
    try:
        mesh = tessellate(shape)
    except Exception:                                      # noqa: BLE001
        return empty, empty, empty
    tris = (mesh.vertices[mesh.triangles.ravel()].astype(float)
            if len(mesh.triangles) else empty)
    segs = (mesh.edge_segments.reshape(-1, 3).astype(float)
            if len(mesh.edge_segments) else empty)
    wires = _mesh_wires(shape)
    if wires is not None:
        segs = wires
    points = mesh.points.astype(float) if len(mesh.points) else empty
    return tris, segs, points


def _mesh_wires(shape):
    """Every edge of a mesh's triangles, for a mesh small enough to show
    them all: the model shows a mesh's rim and creases only, which hides how
    a mesh Hydra made, a Delaunay one say, is triangulated. None for other
    shapes, and for a mesh as big as a scan."""
    from ...core.mesh import MeshShape
    if not isinstance(shape, MeshShape) or not (
            0 < len(shape.triangles) <= MESH_WIRES_UP_TO):
        return None
    tris = shape.triangles.astype(np.int64)
    edges = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]],
                            tris[:, [2, 0]]])
    edges = np.unique(np.sort(edges, axis=1), axis=0)
    return shape.vertices[edges].reshape(-1, 3).astype(float)
