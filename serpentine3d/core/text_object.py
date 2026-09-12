"""Editable model lettering with cached, portable outline geometry."""

from __future__ import annotations

import json
import math
import struct

import numpy as np
from OCP.TopoDS import TopoDS_Compound

from . import geometry, occ


TEXT_TAG = b"STXT\x01"


class TextShape(TopoDS_Compound):
    """One selectable text label, also usable by ordinary BREP operations.

    Typography edits return a new object. The placement frame retains rotation,
    mirroring and stretching; its Y axis has unit length so ``height`` remains
    the physical cap height after scaling. Cached contours let saved labels
    display identically even on a machine without the original font.
    """

    def __init__(self, text: str, height: float, font_family: str = "sans", *,
                 font_style: str = "", alignment: str = "left",
                 origin=(0., 0., 0.)):
        from .text import text_curves

        frame = np.eye(4)
        frame[:3, 3] = origin
        curves = text_curves(text, height, font_family,
                             font_style=font_style, alignment=alignment)
        brep = geometry.apply_matrix(geometry.make_compound(curves), frame)
        self._initialize(text, height, font_family, font_style, alignment,
                         frame, brep)

    def _initialize(self, text, height, font_family, font_style, alignment,
                    frame, brep):
        super().__init__()
        self.TShape(brep.TShape())
        self.Location(brep.Location())
        self.Orientation(brep.Orientation())
        self._text = str(text)
        self._height = float(height)
        self._font_family = str(font_family)
        self._font_style = str(font_style)
        self._alignment = str(alignment)
        self._frame = tuple(tuple(float(v) for v in row) for row in frame)
        self._brep = brep

    @classmethod
    def _from_geometry(cls, typography, frame, brep):
        result = cls.__new__(cls)
        result._initialize(**typography, frame=frame, brep=brep)
        return result

    @property
    def text(self):
        return self._text

    @property
    def height(self):
        return self._height

    @property
    def font_family(self):
        return self._font_family

    @property
    def font_style(self):
        return self._font_style

    @property
    def alignment(self):
        return self._alignment

    @property
    def origin(self):
        return tuple(row[3] for row in self._frame[:3])

    @property
    def plane_normal(self):
        """Unit normal of the transformed plane carrying the lettering."""
        frame = np.asarray(self._frame, dtype=float)
        normal = np.cross(frame[:3, 0], frame[:3, 1])
        length = float(np.linalg.norm(normal))
        if not math.isfinite(length) or length < 1e-12:
            raise geometry.GeometryError("Text plane is degenerate")
        return tuple(normal / length)

    def _typography(self):
        return dict(text=self.text, height=self.height,
                    font_family=self.font_family, font_style=self.font_style,
                    alignment=self.alignment)

    def edited(self, **typography):
        """Rebuild lettering at its current placement, preserving prior states."""
        from .text import text_curves

        values = self._typography()
        unknown = typography.keys() - values.keys()
        if unknown:
            raise TypeError(f"Unknown text property: {', '.join(sorted(unknown))}")
        values.update(typography)
        curves = text_curves(**values)
        brep = geometry.apply_matrix(geometry.make_compound(curves), self._frame)
        return self._from_geometry(values, self._frame, brep)

    def transformed(self, matrix):
        """Transform cached geometry and its typography frame together."""
        matrix = np.asarray(matrix, dtype=float)
        frame = matrix @ np.asarray(self._frame)
        height_scale = float(np.linalg.norm(frame[:3, 1]))
        if not np.isfinite(frame).all() or height_scale < 1e-12:
            raise geometry.GeometryError("Text transform is degenerate")
        if math.isclose(height_scale, 1., rel_tol=1e-12):
            height_scale = 1.
        frame[:3, :3] /= height_scale
        values = self._typography()
        values["height"] *= height_scale
        brep = geometry.apply_matrix(self._brep, matrix)
        return self._from_geometry(values, frame, brep)

    def copy(self):
        return self._from_geometry(self._typography(), self._frame,
                                   geometry.copy_shape(self._brep))

    def snap_points(self):
        """Insertion point and oriented visible bounds in world space."""
        frame = np.asarray(self._frame, dtype=float)
        local = geometry.apply_matrix(self._brep, np.linalg.inv(frame))
        lo, hi = geometry.bbox(local)
        x0, y0 = lo[:2]
        x1, y1 = hi[:2]
        corners = np.array([
            [x0, y0, 0., 1.], [x1, y0, 0., 1.],
            [x1, y1, 0., 1.], [x0, y1, 0., 1.],
        ])
        mids = (corners + np.roll(corners, -1, axis=0)) / 2.
        center = corners.mean(axis=0)

        def mapped(points, kind):
            return [(tuple((frame @ point)[:3]), kind) for point in points]

        return ([(self.origin, "point")]
                + mapped(corners, "end")
                + mapped(mids, "mid")
                + mapped([center], "center"))

    def to_curves(self):
        """Independent ordinary wires, retaining separate letter counters."""
        wires = []
        explorer = occ.TopExp_Explorer(self._brep, occ.WIRE)
        while explorer.More():
            wires.append(geometry.copy_shape(explorer.Current()))
            explorer.Next()
        return wires

    def to_bytes(self):
        header = json.dumps(dict(typography=self._typography(), frame=self._frame),
                            ensure_ascii=False).encode("utf-8")
        return (TEXT_TAG + struct.pack("<I", len(header)) + header
                + geometry.shape_to_bytes(self._brep))

    @classmethod
    def from_bytes(cls, data):
        start = len(TEXT_TAG)
        size, = struct.unpack("<I", data[start:start + 4])
        start += 4
        header = json.loads(data[start:start + size])
        brep = geometry.shape_from_bytes(data[start + size:])
        return cls._from_geometry(header["typography"], header["frame"], brep)


def output_shapes(text: TextShape, output: str, depth: float = 1.) -> list:
    """Turn editable lettering into ordinary geometry on its stored plane."""
    if output == "editable":
        return [text]
    if output not in ("curves", "surface", "solid"):
        raise geometry.GeometryError(f"Unknown text output: {output}")
    curves = text.to_curves()
    if output == "curves":
        return curves
    if output == "surface":
        return geometry.planar_regions(curves)
    if output == "solid":
        if not math.isfinite(depth) or depth <= 0:
            raise geometry.GeometryError("Text solid depth must be positive")
        return geometry.extrude_profiles(
            curves, text.plane_normal, float(depth), cap=True)
