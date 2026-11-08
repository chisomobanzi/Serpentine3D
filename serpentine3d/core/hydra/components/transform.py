"""Move and Rotate, and Group and Ungroup."""

from __future__ import annotations

import math

from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS_Shape
from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec

from ... import geometry as g
from . import COMPONENTS, Component
from ..kinds import GeometryGroup, HydraError, Port, Vector, coordinates


def _rotate(Origin, Geometry, Angle):
    if isinstance(Geometry, GeometryGroup):
        return GeometryGroup(tuple(_rotate(Origin, shape, Angle)
                                   for shape in Geometry.shapes))
    center = Origin if isinstance(Origin, tuple) else coordinates(Origin)
    if not isinstance(Geometry, TopoDS_Shape):
        return g.rotate(Geometry, center, (0.0, 0.0, 1.0), Angle)
    # Moved rather than copied: the result shares its surfaces with what
    # was rotated, so the preview meshes it once and only turns the mesh
    # while a slider is dragged.
    turn = gp_Trsf()
    turn.SetRotation(gp_Ax1(gp_Pnt(*center), gp_Dir(0.0, 0.0, 1.0)),
                     math.radians(Angle))
    return Geometry.Moved(TopLoc_Location(turn))


def _move(G, V):
    if isinstance(G, GeometryGroup):
        return GeometryGroup(tuple(_move(shape, V) for shape in G.shapes))
    if not isinstance(G, TopoDS_Shape):
        return g.translate(G, V.components)
    # Moved, not copied, for the reason Rotate is
    shift = gp_Trsf()
    shift.SetTranslation(gp_Vec(*V.components))
    return G.Moved(TopLoc_Location(shift))


COMPONENTS["move"] = Component(
    "move", "Move", "Transform",
    inputs=(Port("G", "geometry", description="The geometry to move"),
            Port("V", "vector", Vector((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
                 description="How far, and which way, to move it")),
    outputs=(Port("G", "geometry", description="The moved geometry"),),
    icon="move", solve=_move,
    description="Move geometry G along vector V")


COMPONENTS["rotate"] = Component(
    "rotate", "Rotate", "Transform",
    inputs=(Port("Origin", "point", (0.0, 0.0, 0.0),
                 description="The point the vertical axis runs through"),
            Port("Geometry", "geometry", description="The geometry to turn"),
            Port("Angle", "number", 0.0,
                 description="How far to turn it, in degrees")),
    outputs=(Port("Geometry", "geometry",
                  description="The turned geometry"),),
    icon="rotate", solve=_rotate,
    description="Rotate geometry about a vertical axis through Origin, by "
                "Angle in degrees")


def _group(G):
    if not G:
        raise HydraError("There is nothing to group")
    return GeometryGroup(tuple(G))


COMPONENTS["group"] = Component(
    "group", "Group", "Transform",
    inputs=(Port("G", "geometry", access="list", label="Geometry",
                 description="What to keep together"),),
    outputs=(Port("G", "geometry", label="Group",
                  description="One group: moved as one, and cast as one of "
                              "the model's groups"),),
    icon="group", solve=_group,
    description="Keeps geometry together, as a contour with its label: "
                "moved and turned as one, cast as one of the model's groups")


COMPONENTS["ungroup"] = Component(
    "ungroup", "Ungroup", "Transform",
    inputs=(Port("G", "geometry", label="Group",
                 description="The group to take apart"),),
    outputs=(Port("G", "geometry", access="list", label="Geometry",
                  description="What it kept together, one by one"),),
    icon="ungroup",
    solve=lambda G: list(G.shapes) if isinstance(G, GeometryGroup) else [G],
    description="Takes a group apart into what it kept together")
