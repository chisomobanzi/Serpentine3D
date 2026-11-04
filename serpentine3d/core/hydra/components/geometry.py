"""Point, Curve, Brep and Mesh: model objects of their kind, set by
picking them."""

from __future__ import annotations

from . import COMPONENTS, Component
from ..kinds import Port


COMPONENTS_PLURAL = {"point": "points", "curve": "curves",
                     "brep": "breps", "mesh": "meshes"}


def _geometry(key, title, short, kinds, icon, description):
    COMPONENTS[key] = Component(key, title, "Geometry",
                                outputs=(Port(title, key, description=(
                                    f"The {COMPONENTS_PLURAL[key]} picked "
                                    "in the model")),), picks=kinds,
                                icon=icon, sets=f"Set {short}",
                                description=description)


# One component for each thing a Grasshopper user reaches for. Line,
# polyline, arc and circle are all one curve, as they are in the model, and
# surfaces, polysurfaces and solids are all one Brep.
_geometry("point", "Point", "Pt", ("point",), "point",
          "Points picked in the model")


_geometry("curve", "Curve", "Crv", ("curve",), "curve",
          "Curves picked in the model: lines, polylines, arcs, circles and "
          "free curves alike")


_geometry("brep", "Brep", "Brep", ("surface", "solid"), "box",
          "Surfaces, polysurfaces and solids picked in the model")


_geometry("mesh", "Mesh", "Mesh", ("mesh",), "mesh",
          "Meshes picked in the model")
