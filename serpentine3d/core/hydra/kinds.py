"""What flows along Hydra's wires: the kinds of data, which input
takes which output, and how a value is said."""

from __future__ import annotations

import math
from dataclasses import dataclass

from OCP.TopoDS import TopoDS_Shape

from .. import geometry as g


class HydraError(Exception):
    pass


@dataclass(frozen=True)
class Port:
    name: str
    # point | curve | brep | mesh | geometry | number | vector | any
    kind: str
    # what an input without a wire stands for; None means it needs one
    default: object = None
    # "item": the component works on one item at a time; "list": it gets a
    # branch's whole list in one go, as List Item's L does
    access: str = "item"
    # an input that may be left empty: its component then works without it
    optional: bool = False
    # what the port is for, said in its tooltip
    description: str = ""
    # what it takes or gives, said first in its tooltip; by its kind if
    # left out
    label: str = ""

    @property
    def what(self) -> str:
        return self.label or _WHAT.get(self.kind, self.kind.title())


_WHAT = {"number": "Number", "point": "Point", "vector": "Vector",
         "geometry": "Geometry", "curve": "Curve", "brep": "Brep",
         "mesh": "Mesh", "any": "Data", "boolean": "Boolean"}


# Which outputs an input takes: a geometry input any geometry, a point
# input points alone, a number input numbers alone.
_TAKES = {"geometry": ("point", "curve", "brep", "mesh", "geometry"),
          "point": ("point",), "vector": ("vector",),
          # a boolean counts as 1 or 0, as in Grasshopper
          "number": ("number", "boolean"), "boolean": ("boolean", "number")}


def takes(input_kind: str, output_kind: str) -> bool:
    # what may carry anything is let in, and its items are checked when the
    # component works on them; an input of any kind lets everything in
    if "any" in (input_kind, output_kind):
        return True
    # geometry of any kind, as a pipeline or a Move hands on, may hold just
    # what a point, curve, brep or mesh input asks for: let in and checked
    if output_kind == "geometry" and input_kind in _SHAPE_KINDS:
        return True
    return output_kind in _TAKES.get(input_kind, (input_kind,))


# what each kind of geometry input takes, among the model's kinds
_SHAPE_KINDS = {"point": ("point",), "curve": ("curve",),
                "brep": ("surface", "solid"), "mesh": ("mesh",)}


@dataclass(frozen=True)
class GeometryGroup:
    """Geometry kept together, as Grasshopper's Group makes it: moved and
    turned as one, and cast as one of the model's groups."""
    shapes: tuple

    def flat(self) -> list:
        """Its shapes, those of groups inside it among them."""
        out = []
        for shape in self.shapes:
            out.extend(shape.flat() if isinstance(shape, GeometryGroup)
                       else [shape])
        return out


def shapes_in(values) -> list:
    """The shapes among the values, a group's opened out."""
    out = []
    for value in values:
        if isinstance(value, GeometryGroup):
            out.extend(value.flat())
        elif is_shape(value):
            out.append(value)
    return out


def is_shape(value) -> bool:
    from ..mesh import MeshShape
    return isinstance(value, (TopoDS_Shape, MeshShape))


def fits(kind: str, value) -> bool:
    """Whether an item can be used where `kind` is asked for."""
    if kind == "any":
        return True
    if kind == "number":
        return isinstance(value, (int, float)) or (
            isinstance(value, str) and _as_number(value) is not None)
    if kind == "boolean":
        return isinstance(value, (bool, int, float))
    if kind == "vector":
        return isinstance(value, Vector)
    if kind == "point":
        return isinstance(value, tuple) or (
            isinstance(value, TopoDS_Shape) and g.shape_kind(value) == "point")
    if kind in _SHAPE_KINDS:
        return is_shape(value) and g.shape_kind(value) in _SHAPE_KINDS[kind]
    return is_shape(value) or isinstance(value, GeometryGroup)


def _as_number(value):
    """Text that reads as a number, as that number; None if it does not."""
    try:
        return float(value.strip().replace(",", "."))
    except (AttributeError, ValueError):
        return None


def coerce(kind: str, value):
    """An item made what a port asks for, where it can be: text into a
    number. Everything else as it is."""
    if kind in ("number", "boolean") and isinstance(value, str):
        number = _as_number(value)
        return value if number is None else number
    return value


def said_of(value) -> str:
    """What an item is, for a message saying it does not fit."""
    if isinstance(value, str):
        return "text"
    if isinstance(value, (int, float)):
        return "a number"
    if isinstance(value, Vector):
        return "a vector"
    if isinstance(value, tuple):
        return "a point"
    if isinstance(value, GeometryGroup):
        return "a group"
    if is_shape(value):
        return {"point": "a point", "curve": "a curve", "surface": "a brep",
                "solid": "a brep", "mesh": "a mesh"}.get(
                    g.shape_kind(value), "geometry")
    return "geometry"


GEOMETRY_KINDS = ("point", "curve", "brep", "mesh", "geometry")


def coordinates(point) -> tuple:
    """A point's coordinates, whether a point object or a set of three."""
    if isinstance(point, (tuple, list)):
        return tuple(float(c) for c in point)
    from ..occ import BRep_Tool, TopoDS
    p = BRep_Tool.Pnt_s(TopoDS.Vertex_s(point))
    return (p.X(), p.Y(), p.Z())


@dataclass(frozen=True)
class Vector:
    """A direction and a length, kept with the place it was drawn from so
    the preview can show it there, as an arrow from start to end."""
    start: tuple
    end: tuple

    @property
    def components(self) -> tuple:
        return tuple(b - a for a, b in zip(self.start, self.end))

    @property
    def length(self) -> float:
        return math.sqrt(sum(c * c for c in self.components))


def arrow(start, end):
    """A line from start to end with a head at the end, as one shape."""
    d = [b - a for a, b in zip(start, end)]
    length = math.sqrt(sum(c * c for c in d))
    if length < 1e-12:
        raise HydraError("The two points of a vector are the same point")
    d = [c / length for c in d]
    # the head opens in the plane of the arrow and the vertical, or of the
    # arrow and X when it points straight up or down
    up = (0.0, 0.0, 1.0) if abs(d[2]) < 0.99 else (1.0, 0.0, 0.0)
    side = [d[1] * up[2] - d[2] * up[1], d[2] * up[0] - d[0] * up[2],
            d[0] * up[1] - d[1] * up[0]]
    norm = math.sqrt(sum(c * c for c in side))
    side = [c / norm for c in side]
    head = length * 0.15
    barbs = [tuple(e - dc * head + sc * head * k * 0.5
                   for e, dc, sc in zip(end, d, side)) for k in (1, -1)]
    return g.make_compound([g.make_line(start, end)]
                           + [g.make_line(b, end) for b in barbs])


def format_number(value: float, decimals: int) -> str:
    return f"{value:.{decimals}f}"


def number_text(value: float) -> str:
    """A number as a label writes it: no trailing zeros, no float noise,
    5 and not 5.0, 0.3 and not 0.30000000000000004."""
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def as_text(value) -> str:
    """Anything as text: a number as number_text writes it."""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        return number_text(value)
    return describe_item(value)


def describe_item(value) -> str:
    """One item, as a tooltip lists it."""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        return f"{value:g}"
    if isinstance(value, Vector):
        return "Vector " + ", ".join(f"{c:g}" for c in value.components)
    if isinstance(value, tuple):
        return "Point " + ", ".join(f"{c:g}" for c in value)
    if isinstance(value, GeometryGroup):
        return f"Group of {len(value.shapes)}"
    if isinstance(value, TopoDS_Shape) and g.shape_kind(value) == "point":
        return "Point " + ", ".join(f"{c:g}" for c in coordinates(value))
    kind = g.shape_kind(value) if is_shape(value) else type(value).__name__
    return {"solid": "Brep", "surface": "Brep", "curve": "Curve",
            "mesh": "Mesh", "compound": "Geometry"}.get(kind, kind.title())


def describe(values: list) -> str:
    """What an input holds, said briefly: the numbers or points themselves
    when there are a few, a count of objects otherwise."""
    if not values:
        return "nothing"
    if all(isinstance(v, (int, float)) for v in values):
        shown = ", ".join(f"{v:g}" for v in values[:5])
        return shown + (f" … ({len(values)})" if len(values) > 5 else "")
    if len(values) == 1:
        v = values[0]
        if isinstance(v, tuple):
            return ", ".join(f"{c:g}" for c in v)
        if isinstance(v, TopoDS_Shape) and g.shape_kind(v) == "point":
            return ", ".join(f"{c:g}" for c in coordinates(v))
        if isinstance(v, Vector):
            return ", ".join(f"{c:g}" for c in v.components)
    noun = "vector" if all(isinstance(v, Vector) for v in values) else "object"
    return f"{len(values)} {noun}" + ("" if len(values) == 1 else "s")


def kind_said(kind: str) -> str:
    return {"geometry": "geometry", "number": "numbers",
            "mesh": "meshes"}.get(kind, kind + "s")
