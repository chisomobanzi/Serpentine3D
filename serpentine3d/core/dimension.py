"""A linear dimension in the model: two points measured along a direction,
drawn with its extension lines, dimension line, arrows and text."""

from __future__ import annotations

import json
import math
import struct

import numpy as np
from OCP.TopoDS import TopoDS_Compound

from . import geometry


DIMENSION_TAG = b"SDIM\x01"

ARROWS = ("arrow", "tick")

# Everything a dimension's look is made of, with what a new one starts from.
# Sizes are in model units; the gaps and overshoots follow the text height
# unless a file says otherwise.
STYLE_DEFAULTS = {
    "text_height": 2.5,
    "arrow_size": 2.5,
    "arrow": "arrow",
    "decimals": 2,
    "suffix": "",
    "text": "",              # empty: the measurement; "<>" stands for it
    "font_family": "sans",
    "length_factor": 1.0,    # what the measured length is multiplied by
    "extension_offset": None,   # gap between a point and its extension line
    "extension_beyond": None,   # how far it runs past the dimension line
    "text_gap": None,        # between the dimension line and the text
}


def _unit(v):
    v = np.asarray(v, float)
    n = float(np.linalg.norm(v))
    if not math.isfinite(n) or n < 1e-12:
        raise geometry.GeometryError("Dimension direction is degenerate")
    return v / n


def _reading_axes(u, n):
    """The dimension's direction turned, if need be, so its text reads left
    to right and upright on its plane, and the plane's normal turned to face
    the one looking at it: up for a plan, out of the screen for an
    elevation."""
    for ref in ((0., 0., 1.), (0., -1., 0.), (1., 0., 0.)):
        d = float(np.dot(n, ref))
        if abs(d) > 1e-9:
            if d < 0:
                n = -n
            break
    up = np.array([0., 0., 1.]) if abs(n[2]) < 0.999 else np.array([0., 1., 0.])
    right = np.cross(up, n)
    right = right / np.linalg.norm(right)
    if abs(n[2]) >= 0.999:
        right = np.array([1., 0., 0.]) if n[2] > 0 else np.array([-1., 0., 0.])
    above = np.cross(n, right)
    angle = math.atan2(float(np.dot(u, above)), float(np.dot(u, right)))
    if angle <= -math.pi / 2 + 1e-9 or angle > math.pi / 2 + 1e-9:
        u = -u
    return u, np.cross(n, u), n


class DimensionShape(TopoDS_Compound):
    """One linear dimension, selectable and drawn as the curves it is made
    of, and rebuilt from what it measures whenever it is edited or moved.

    `p1` and `p2` are the points measured, `at` a point the dimension line
    passes through, `direction` what it measures along (along p1 to p2 for
    an aligned dimension, a fixed axis for a horizontal or vertical one) and
    `normal` the plane it is drawn on.
    """

    def __init__(self, p1, p2, at, direction=None, normal=(0., 0., 1.),
                 **style):
        p1 = np.asarray(p1, float)
        p2 = np.asarray(p2, float)
        if direction is None:
            direction = p2 - p1
        n = _unit(normal)
        u = np.asarray(direction, float)
        u = _unit(u - n * float(np.dot(u, n)))
        self._initialize(p1, p2, np.asarray(at, float), u, n,
                         _style(style))

    def _initialize(self, p1, p2, at, u, n, style):
        self._p1 = tuple(float(v) for v in p1)
        self._p2 = tuple(float(v) for v in p2)
        self._at = tuple(float(v) for v in at)
        self._u = tuple(float(v) for v in u)
        self._n = tuple(float(v) for v in n)
        self._style = dict(style)
        brep = self._build()
        super().__init__()
        self.TShape(brep.TShape())
        self.Location(brep.Location())
        self.Orientation(brep.Orientation())
        self._brep = brep

    @classmethod
    def _from_parts(cls, p1, p2, at, u, n, style):
        out = cls.__new__(cls)
        out._initialize(np.asarray(p1, float), np.asarray(p2, float),
                        np.asarray(at, float), np.asarray(u, float),
                        np.asarray(n, float), style)
        return out

    # --- what it is ---------------------------------------------------------

    @property
    def p1(self):
        return self._p1

    @property
    def p2(self):
        return self._p2

    @property
    def at(self):
        return self._at

    @property
    def direction(self):
        return self._u

    @property
    def normal(self):
        return self._n

    @property
    def style(self) -> dict:
        return dict(self._style)

    def __getattr__(self, name):
        style = self.__dict__.get("_style")
        if style is not None and name in STYLE_DEFAULTS:
            return style[name]
        raise AttributeError(name)

    @property
    def measured(self) -> float:
        """The length it measures, its length factor applied."""
        d = np.subtract(self._p2, self._p1)
        return abs(float(np.dot(d, self._u))) * self._style["length_factor"]

    @property
    def measurement_text(self) -> str:
        value = self.measured
        decimals = int(self._style["decimals"])
        number = f"{value:.{decimals}f}"
        if number.startswith("-") and float(number) == 0:
            number = number[1:]
        suffix = self._style["suffix"]
        return f"{number} {suffix}" if suffix else number

    @property
    def label(self) -> str:
        """What its text says: the measurement, or what was typed over it,
        where "<>" in what was typed stands for the measurement."""
        typed = self._style["text"]
        if not typed:
            return self.measurement_text
        return typed.replace("<>", self.measurement_text)

    # --- drawing ------------------------------------------------------------

    def sizes(self):
        """(text height, arrow size, extension offset, extension beyond,
        text gap): what it is drawn at, the last three following the text
        height unless set."""
        s = self._style
        h = float(s["text_height"])
        return (h, float(s["arrow_size"]),
                h / 2 if s["extension_offset"] is None
                else float(s["extension_offset"]),
                h / 2 if s["extension_beyond"] is None
                else float(s["extension_beyond"]),
                h * 0.4 if s["text_gap"] is None else float(s["text_gap"]))

    def frame(self):
        """(origin, along, across, normal): the dimension line's start, its
        reading direction, the side its text is on, and its plane's
        normal."""
        u, v, n = _reading_axes(np.asarray(self._u), np.asarray(self._n))
        return np.asarray(self._at), u, v, n

    def _local(self):
        origin, u, v, _n = self.frame()

        def uv(p):
            d = np.asarray(p) - origin
            return float(np.dot(d, u)), float(np.dot(d, v))
        return uv(self._p1), uv(self._p2)

    def _build(self):
        from .text import text_curves
        origin, u, v, n = self.frame()
        (a_u, a_v), (b_u, b_v) = self._local()
        h, arrow, ext_off, ext_beyond, gap = self.sizes()

        def world(x, y):
            return tuple(origin + u * x + v * y)

        parts = []

        def line(p, q):
            if math.dist(p, q) > 1e-12:
                parts.append(geometry.make_line(world(*p), world(*q)))

        for pu, pv in ((a_u, a_v), (b_u, b_v)):
            side = math.copysign(1.0, -pv) if abs(pv) > 1e-12 else 0.0
            if side:
                start = pv + side * ext_off
                if (start - 0.0) * side < 0:
                    line((pu, start), (pu, side * ext_beyond))
        lo, hi = sorted((a_u, b_u))
        tick = self._style["arrow"] == "tick"
        over = ext_beyond if tick else 0.0
        line((lo - over, 0.0), (hi + over, 0.0))
        for end, out in ((lo, -1.0), (hi, 1.0)):
            if tick:
                t = arrow / 2
                line((end - t, -t), (end + t, t))
            elif arrow > 0:
                back = end - out * arrow
                w = arrow / 6
                parts.append(geometry.make_polyline(
                    [world(end, 0.0), world(back, w), world(back, -w)],
                    closed=True))

        text = self.label
        if text.strip():
            curves = text_curves(text, h, self._style["font_family"],
                                 alignment="center")
            place = np.eye(4)
            place[:3, 0] = u
            place[:3, 1] = v
            place[:3, 2] = n
            place[:3, 3] = world((lo + hi) / 2, gap)
            if curves:
                lettering = geometry.make_compound(curves)
                (_x0, y0, _), _ = geometry.bbox(lettering)
                shift = np.eye(4)
                shift[1, 3] = max(0.0, -y0)
                parts.append(geometry.apply_matrix(lettering, place @ shift))
        if not parts:
            raise geometry.GeometryError("Dimension has nothing to draw")
        return geometry.make_compound(parts)

    # --- editing ------------------------------------------------------------

    def edited(self, **changes):
        """The same dimension with some of its look changed, or its points:
        p1, p2 and at."""
        unknown = changes.keys() - STYLE_DEFAULTS.keys() - {"p1", "p2", "at"}
        if unknown:
            raise TypeError(
                f"Unknown dimension property: {', '.join(sorted(unknown))}")
        style = dict(self._style)
        style.update({k: v for k, v in changes.items() if k in STYLE_DEFAULTS})
        return self._from_parts(changes.get("p1", self._p1),
                                changes.get("p2", self._p2),
                                changes.get("at", self._at),
                                self._u, self._n, _style(style))

    def transformed(self, matrix):
        """Moved, turned or scaled: the points go where the transform takes
        them and the measurement follows; the text and arrows grow with a
        scale as lettering does."""
        m = np.asarray(matrix, float)
        if m.shape == (3, 4):
            m = np.vstack([m, [0., 0., 0., 1.]])
        a = m[:3, :3]

        def moved(p):
            return a @ np.asarray(p, float) + m[:3, 3]
        u = np.asarray(self._u)
        v = np.cross(np.asarray(self._n), u)
        u2, v2 = a @ u, a @ v
        n2 = np.cross(u2, v2)
        scale = float(np.linalg.norm(v2))
        if not np.isfinite(m).all() or scale < 1e-12 or \
                np.linalg.norm(n2) < 1e-12:
            raise geometry.GeometryError("Dimension transform is degenerate")
        style = dict(self._style)
        if not math.isclose(scale, 1.0, rel_tol=1e-12):
            for key in ("text_height", "arrow_size", "extension_offset",
                        "extension_beyond", "text_gap"):
                if style[key] is not None:
                    style[key] = float(style[key]) * scale
        return self._from_parts(moved(self._p1), moved(self._p2),
                                moved(self._at), _unit(u2), _unit(n2), style)

    def copy(self):
        return self._from_parts(self._p1, self._p2, self._at, self._u,
                                self._n, self._style)

    def snap_points(self):
        origin, u, _v, _n = self.frame()
        (a_u, _), (b_u, _) = self._local()
        ends = [tuple(origin + u * a_u), tuple(origin + u * b_u)]
        return ([(self._p1, "end"), (self._p2, "end")]
                + [(p, "end") for p in ends]
                + [(tuple(origin + u * (a_u + b_u) / 2), "mid")])

    def to_curves(self):
        """Its lines, arrows and lettering as ordinary curves."""
        from . import occ
        out = []
        it = occ.TopoDS_Iterator(self._brep)
        while it.More():
            part = it.Value()
            if part.ShapeType() == occ.COMPOUND:
                inner = occ.TopoDS_Iterator(part)
                while inner.More():
                    out.append(geometry.copy_shape(inner.Value()))
                    inner.Next()
            else:
                out.append(geometry.copy_shape(part))
            it.Next()
        return out

    # --- saving -------------------------------------------------------------

    def to_bytes(self):
        header = json.dumps(dict(p1=self._p1, p2=self._p2, at=self._at,
                                 u=self._u, n=self._n, style=self._style),
                            ensure_ascii=False).encode("utf-8")
        return DIMENSION_TAG + struct.pack("<I", len(header)) + header

    @classmethod
    def from_bytes(cls, data):
        start = len(DIMENSION_TAG)
        size, = struct.unpack("<I", data[start:start + 4])
        header = json.loads(data[start + 4:start + 4 + size])
        return cls._from_parts(header["p1"], header["p2"], header["at"],
                               header["u"], header["n"],
                               _style(header.get("style", {})))


def _style(values: dict) -> dict:
    unknown = values.keys() - STYLE_DEFAULTS.keys()
    if unknown:
        raise TypeError(
            f"Unknown dimension property: {', '.join(sorted(unknown))}")
    style = dict(STYLE_DEFAULTS)
    style.update(values)
    for key in ("text_height", "arrow_size", "length_factor"):
        value = float(style[key])
        if not math.isfinite(value) or value < 0 or \
                (key != "arrow_size" and value == 0):
            raise geometry.GeometryError(f"Dimension {key.replace('_', ' ')} "
                                         "must be positive")
        style[key] = value
    style["decimals"] = max(0, min(8, int(style["decimals"])))
    style["suffix"] = str(style["suffix"]).strip()      # set off by a space
    style["text"] = str(style["text"])
    style["font_family"] = str(style["font_family"] or "sans")
    if style["arrow"] not in ARROWS:
        style["arrow"] = "arrow"
    return style
