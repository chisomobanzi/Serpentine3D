"""Construct Point, Vector, and Unit X, Y and Z."""

from __future__ import annotations

from ... import geometry as g
from . import COMPONENTS, Component
from ..kinds import HydraError, Port, Vector, coordinates


COMPONENTS["construct_point"] = Component(
    "construct_point", "Construct Point", "Vector",
    inputs=(Port("X", "number", 0.0, description="The point's X"),
            Port("Y", "number", 0.0, description="The point's Y"),
            Port("Z", "number", 0.0, description="The point's Z")),
    outputs=(Port("Point", "point", description="The point at X, Y, Z"),),
    icon="point",
    solve=lambda X, Y, Z: g.make_point((X, Y, Z)),
    description="A point from its X, Y and Z coordinates")


def _vector(A, B):
    vector = Vector(coordinates(A), coordinates(B))
    if vector.length < 1e-12:
        raise HydraError("A and B are the same point")
    return vector


COMPONENTS["vector"] = Component(
    "vector", "Vector", "Vector",
    inputs=(Port("A", "point", description="Where the vector starts"),
            Port("B", "point", description="Where the vector points to")),
    outputs=(Port("Vector", "vector",
                  description="The vector from A to B"),),
    icon="vector", solve=_vector,
    sets="Set Vector",
    description="The vector from point A to point B, shown as an arrow")


def _unit(key, axis, along):
    def solve(F):
        return Vector((0.0, 0.0, 0.0), tuple(F * a for a in along))
    COMPONENTS[key] = Component(
        key, f"Unit {axis}", "Vector",
        inputs=(Port("F", "number", 1.0, label="Factor",
                     description="How long it is; negative turns it round"),),
        outputs=(Port("V", "vector", description=f"Along {axis}, F long"),),
        icon=key.replace("_", ""), solve=solve,
        description=f"The vector along the {axis} axis, F long: 1 unless set")


_unit("unit_x", "X", (1.0, 0.0, 0.0))
_unit("unit_y", "Y", (0.0, 1.0, 0.0))
_unit("unit_z", "Z", (0.0, 0.0, 1.0))


COMPONENTS["deconstruct_point"] = Component(
    "deconstruct_point", "Deconstruct Point", "Vector",
    inputs=(Port("P", "point", label="Point",
                 description="The point to take apart"),),
    outputs=(Port("X", "number", description="The point's X"),
             Port("Y", "number", description="The point's Y"),
             Port("Z", "number", description="The point's Z, its height")),
    icon="deconstructpoint", solve=lambda P: tuple(coordinates(P)),
    description="A point's X, Y and Z")
