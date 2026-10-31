"""Delaunay, and a mesh made into flat triangles for the model."""

from __future__ import annotations

import numpy as np

from ... import geometry as g
from ...mesh import MeshShape
from . import COMPONENTS, Component
from ..kinds import HydraError, Port, coordinates


def _delaunay(P, Outline=None):
    from ...delaunay import (DelaunayError, inside_outline, triangulate,
                           unique_points)
    points = unique_points([coordinates(p) for p in P])
    try:
        faces = triangulate(points[:, :2])
    except DelaunayError as exc:
        raise HydraError(str(exc)) from exc
    if Outline is not None:
        if not g.is_closed_curve(Outline):
            raise HydraError("Outline must be a closed curve")
        from ...tessellate import tessellate
        rim = tessellate(Outline).edge_segments.reshape(-1, 2, 3)[:, :, :2]
        # a face stays when its middle, seen from above, is inside
        middles = points[faces][:, :, :2].mean(axis=1)
        faces = faces[inside_outline(middles, rim)]
        if not len(faces):
            raise HydraError("No face of the mesh is inside the outline")
        used, faces = np.unique(faces, return_inverse=True)
        points, faces = points[used], faces.reshape(-1, 3)
    return MeshShape(points, faces)


COMPONENTS["delaunay"] = Component(
    "delaunay", "Delaunay Mesh", "Mesh",
    inputs=(Port("P", "point", access="list", label="Points",
                 description="The points to mesh"),
            Port("Outline", "curve", optional=True, label="Closed curve",
                 description="Faces outside it are left out")),
    outputs=(Port("M", "mesh", label="Mesh",
                  description="The triangles between them"),),
    icon="delaunay", solve=_delaunay,
    description="A mesh of triangles through the points, seen from above: "
                "Delaunay, as Grasshopper's, in the XY plane, the points "
                "keeping their heights; with an Outline, only the faces "
                "inside it")


def faceted(mesh):
    """The mesh to be drawn in the model as flat triangles with every edge
    shown, as a terrain is, and as the graph's preview shows it."""
    return MeshShape(mesh.vertices.copy(), mesh.triangles.copy(),
                     faceted=True)
