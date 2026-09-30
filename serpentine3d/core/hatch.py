"""A hatch in the model: a planar region filled with a pattern (#33).

A layout has had hatches for a long time, in paper millimetres. This is the
same idea as an object in the model: the region is an ordinary planar face,
holes and all, and the pattern is drawn over it by the same `hatch_region`
the sheets use, in the plane of the face.

Like the text object it is a compound whose contents are real geometry, so
drawing, picking, bounds and STEP export need nothing new; what it adds is
the pattern, kept as data so that moving, turning, scaling, copying and
saving a hatch give back a hatch rather than a heap of lines.
"""

from __future__ import annotations

import json
import math
import struct

import numpy as np
from OCP.TopoDS import TopoDS_Compound

from . import geometry, occ

HATCH_TAG = b"SHCH\x01"
MAX_SEGMENTS = 20000      # past this the spacing is a mistake, not a hatch


class HatchShape(TopoDS_Compound):
    """One hatch: a planar region, a pattern, its angle and its spacing.

    `angle` is in degrees, measured in the hatch's own plane from its x
    axis, which the command takes from the construction plane: 45 on the
    Top plane means 45 degrees from world X. `spacing` is the distance
    between lines in model units, and scales with the hatch.
    """

    def __init__(self, region, pattern: str = "lines", angle: float = 45.0,
                 spacing: float = 1.0, xdir=None):
        region = _one_face(region)
        normal = np.asarray(geometry.face_normal(region), float)
        normal /= np.linalg.norm(normal) or 1.0
        frame = _frame_for(region, normal, xdir)
        self._initialize(region, pattern, angle, spacing, frame)

    def _initialize(self, region, pattern, angle, spacing, frame):
        from .layout import HATCH_PATTERNS
        pattern = str(pattern).lower()
        if pattern not in HATCH_PATTERNS:
            raise geometry.GeometryError(f"Unknown hatch pattern: {pattern}")
        spacing = float(spacing)
        if pattern != "solid" and not (math.isfinite(spacing) and spacing > 0):
            raise geometry.GeometryError("Hatch spacing must be positive")
        region = _one_face(region)
        super().__init__()
        self._region = region
        self._pattern = pattern
        self._angle = float(angle)
        self._spacing = spacing
        self._frame = tuple(tuple(float(v) for v in row) for row in frame)
        self._segments = ([] if pattern == "solid"
                          else _pattern_segments(region, frame, pattern,
                                                 self._angle, spacing))
        brep = _assemble(region, pattern, self._segments)
        self.TShape(brep.TShape())
        self.Location(brep.Location())
        self.Orientation(brep.Orientation())

    @classmethod
    def _from_parts(cls, region, pattern, angle, spacing, frame):
        out = cls.__new__(cls)
        out._initialize(region, pattern, angle, spacing, frame)
        return out

    # --- what it is ---------------------------------------------------------

    @property
    def pattern(self) -> str:
        return self._pattern

    @property
    def angle(self) -> float:
        return self._angle

    @property
    def spacing(self) -> float:
        return self._spacing

    @property
    def region(self):
        """The planar face the hatch fills, holes and all."""
        return self._region

    @property
    def frame(self) -> np.ndarray:
        return np.asarray(self._frame, float)

    def pattern_segments(self) -> list:
        """The pattern's lines in the world, as [((x,y,z), (x,y,z)), ...]."""
        return list(self._segments)

    # --- what it becomes ----------------------------------------------------

    def edited(self, **changes):
        """The same region with a different pattern, angle or spacing."""
        unknown = changes.keys() - {"pattern", "angle", "spacing"}
        if unknown:
            raise TypeError(f"Unknown hatch property: {', '.join(sorted(unknown))}")
        values = dict(pattern=self._pattern, angle=self._angle,
                      spacing=self._spacing)
        values.update(changes)
        return self._from_parts(self._region, values["pattern"],
                                values["angle"], values["spacing"],
                                self._frame)

    def transformed(self, matrix):
        """Move, turn or scale the region and its pattern together.

        The pattern keeps its angle in the hatch's own frame, so a turned
        hatch turns its lines with it, and its spacing grows with the
        region, so a scaled hatch is the same drawing at a new size.
        """
        m = np.asarray(matrix, float)
        frame = np.asarray(self._frame, float)
        x = m[:3, :3] @ frame[:3, 0]
        y = m[:3, :3] @ frame[:3, 1]
        sx, sy = float(np.linalg.norm(x)), float(np.linalg.norm(y))
        if sx < 1e-12 or sy < 1e-12:
            raise geometry.GeometryError("Hatch transform is degenerate")
        xn = x / sx
        y_in = y - np.dot(y, xn) * xn
        if np.linalg.norm(y_in) < 1e-12:
            raise geometry.GeometryError("Hatch transform is degenerate")
        yn = y_in / np.linalg.norm(y_in)
        new = np.eye(4)
        new[:3, 0], new[:3, 1], new[:3, 2] = xn, yn, np.cross(xn, yn)
        new[:3, 3] = (m @ np.append(frame[:3, 3], 1.0))[:3]
        region = geometry.apply_matrix(self._region, m)
        spacing = self._spacing * math.sqrt(sx * sy)
        return self._from_parts(region, self._pattern, self._angle, spacing,
                                new)

    def copy(self):
        return self._from_parts(geometry.copy_shape(self._region),
                                self._pattern, self._angle, self._spacing,
                                self._frame)

    def to_curves(self) -> list:
        """The boundary as ordinary closed curves, outer and holes."""
        wires = []
        exp = occ.TopExp_Explorer(self._region, occ.WIRE)
        while exp.More():
            wires.append(geometry.copy_shape(exp.Current()))
            exp.Next()
        return wires

    def snap_points(self) -> list:
        """The boundary's ends and middles and the region's centre; never
        the pattern's own lines, which would bury everything else."""
        out = []
        for edge in geometry.edges_of(self._region):
            ad = occ.edge_adaptor(edge)
            a, b = ad.FirstParameter(), ad.LastParameter()
            for t, kind in ((a, "end"), (b, "end"), ((a + b) / 2, "mid")):
                p = ad.Value(t)
                out.append(((p.X(), p.Y(), p.Z()), kind))
        out.append((tuple(geometry.centroid(self._region)), "center"))
        return out

    # --- as bytes -----------------------------------------------------------

    def to_bytes(self) -> bytes:
        header = json.dumps(dict(pattern=self._pattern, angle=self._angle,
                                 spacing=self._spacing,
                                 frame=self._frame)).encode("utf-8")
        return (HATCH_TAG + struct.pack("<I", len(header)) + header
                + geometry.shape_to_bytes(self._region))

    @classmethod
    def from_bytes(cls, data: bytes):
        start = len(HATCH_TAG)
        size, = struct.unpack("<I", data[start:start + 4])
        start += 4
        head = json.loads(data[start:start + size])
        region = geometry.shape_from_bytes(data[start + size:])
        return cls._from_parts(region, head["pattern"], head["angle"],
                               head["spacing"], head["frame"])


# --- the pieces -------------------------------------------------------------

def _one_face(shape):
    """The single face a region is, whatever it arrived wrapped in: a
    region with a hole comes out of the boolean as a compound of one face,
    and a copy comes back as a plain shape."""
    faces = geometry.faces_of(shape)
    if len(faces) != 1:
        raise geometry.GeometryError(
            f"A hatch fills one planar region, not {len(faces)}")
    return occ.to_face(faces[0])


def _frame_for(region, normal, xdir=None) -> np.ndarray:
    """A frame on the region's plane: x along `xdir` (or world X, or world Y
    where X stands square to the plane) laid into the plane."""
    frame = np.eye(4)
    for want in ([xdir] if xdir is not None else []) + [(1, 0, 0), (0, 1, 0)]:
        w = np.asarray(want, float)
        x = w - np.dot(w, normal) * normal
        if np.linalg.norm(x) > 1e-6:
            break
    x /= np.linalg.norm(x)
    frame[:3, 0] = x
    frame[:3, 1] = np.cross(normal, x)
    frame[:3, 2] = normal
    frame[:3, 3] = geometry.centroid(region)
    return frame


def _rings(region, frame) -> list:
    """Every loop of the region as a polygon in the frame's (x, y)."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRepTools import BRepTools_WireExplorer
    from OCP.GCPnts import GCPnts_QuasiUniformDeflection
    from OCP.TopAbs import TopAbs_REVERSED
    lo, hi = geometry.bbox(region)
    deflection = max(float(np.linalg.norm(np.subtract(hi, lo))) * 1e-4, 1e-7)
    inv = np.linalg.inv(np.asarray(frame, float))
    rings = []
    exp = occ.TopExp_Explorer(region, occ.WIRE)
    while exp.More():
        wire = occ.to_wire(exp.Current())
        exp.Next()
        pts = []
        walk = BRepTools_WireExplorer(wire, region)
        while walk.More():
            edge = walk.Current()
            walk.Next()
            ad = BRepAdaptor_Curve(edge)
            sample = GCPnts_QuasiUniformDeflection(
                ad, deflection, ad.FirstParameter(), ad.LastParameter())
            if sample.IsDone() and sample.NbPoints() >= 2:
                seq = [sample.Value(i) for i in range(1, sample.NbPoints() + 1)]
            else:
                seq = [ad.Value(ad.FirstParameter()), ad.Value(ad.LastParameter())]
            if edge.Orientation() == TopAbs_REVERSED:
                seq.reverse()
            for p in seq:
                q = (p.X(), p.Y(), p.Z())
                if not pts or math.dist(pts[-1], q) > deflection * 1e-3:
                    pts.append(q)
        if len(pts) >= 3:
            local = (inv @ np.column_stack([np.asarray(pts),
                                            np.ones(len(pts))]).T).T
            rings.append(local[:, :2])
    return rings


def _pattern_segments(region, frame, pattern, angle, spacing) -> list:
    from .layout import hatch_region
    rings = _rings(region, frame)
    if not rings:
        return []
    span = max(float(np.ptp(np.vstack(rings), axis=0).max()), 0.0)
    lines = (span / spacing) * (2 if pattern == "cross" else 1)
    if lines > MAX_SEGMENTS:
        raise geometry.GeometryError(
            f"A spacing of {spacing:g} would draw {int(lines):,} lines "
            "across this region; use a larger spacing")
    frame = np.asarray(frame, float)
    angles = [angle] + ([angle + 90.0] if pattern == "cross" else [])
    out = []
    for ang in angles:
        for a, b in hatch_region(rings, ang, spacing):
            wa = frame @ np.array([a[0], a[1], 0.0, 1.0])
            wb = frame @ np.array([b[0], b[1], 0.0, 1.0])
            out.append((tuple(float(v) for v in wa[:3]),
                        tuple(float(v) for v in wb[:3])))
    return out


def _assemble(region, pattern, segments):
    """The compound the hatch is: its face for a solid fill, its boundary
    and pattern lines for the rest."""
    from OCP.BRep import BRep_Builder
    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    if pattern == "solid":
        builder.Add(compound, region)
        return compound
    exp = occ.TopExp_Explorer(region, occ.WIRE)
    while exp.More():
        builder.Add(compound, exp.Current())
        exp.Next()
    for a, b in segments:
        if math.dist(a, b) > 1e-12:
            builder.Add(compound, geometry.make_line(a, b))
    return compound
