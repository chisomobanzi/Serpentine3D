"""A hatch in the model: a planar region filled with a pattern (#33).

A layout has had hatches for a long time, in paper millimetres. This is the
same idea as an object in the model: the region is an ordinary planar face,
holes and all, and the pattern is drawn over it by the same `hatch_region`
the sheets use, in the plane of the face.

Like the text object it is a compound whose contents are real geometry, so
drawing, picking, bounds and STEP export need nothing new; what it adds is
the pattern, kept as data so that moving, turning, scaling, copying and
saving a hatch give back a hatch rather than a heap of lines.

A pattern loaded from a .pat file (#92) travels inside the hatch, families
and all, so a hatch copied into another drawing, or opened where the
pattern was never loaded, is still drawn the way it was.
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
                 spacing: float = 1.0, xdir=None, definition=None):
        region = _one_face(region)
        normal = np.asarray(geometry.face_normal(region), float)
        normal /= np.linalg.norm(normal) or 1.0
        frame = _frame_for(region, normal, xdir)
        self._initialize(region, pattern, angle, spacing, frame, definition)

    def _initialize(self, region, pattern, angle, spacing, frame,
                    definition=None):
        from .hatch_patterns import BUILTIN, is_builtin, is_legacy
        pattern = str(pattern).strip()
        if is_builtin(pattern):
            pattern = pattern.lower()
            definition = None if is_legacy(pattern) else BUILTIN[pattern]
        elif definition is None or definition.key != pattern.lower():
            raise geometry.GeometryError(f"Unknown hatch pattern: {pattern}")
        solid = pattern == "solid" or bool(definition and definition.solid)
        spacing = float(spacing)
        if not solid and not (math.isfinite(spacing) and spacing > 0):
            raise geometry.GeometryError("Hatch spacing must be positive")
        region = _one_face(region)
        super().__init__()
        self._region = region
        self._pattern = pattern
        self._definition = definition
        self._angle = float(angle)
        self._spacing = spacing
        self._frame = tuple(tuple(float(v) for v in row) for row in frame)
        lines, circles, self._dots = (
            ([], [], []) if solid
            else _pattern_segments(region, frame, pattern, self._angle,
                                   spacing, definition))
        self._lines = lines
        self._segments = lines + circles
        brep = _assemble(region, solid, self._segments)
        self.TShape(brep.TShape())
        self.Location(brep.Location())
        self.Orientation(brep.Orientation())

    @classmethod
    def _from_parts(cls, region, pattern, angle, spacing, frame,
                    definition=None):
        out = cls.__new__(cls)
        out._initialize(region, pattern, angle, spacing, frame, definition)
        return out

    # --- what it is ---------------------------------------------------------

    @property
    def pattern(self) -> str:
        return self._pattern

    @property
    def definition(self):
        """The HatchPattern a pattern from a .pat file is, or None for
        Lines, Cross and Solid."""
        return self._definition

    @property
    def solid(self) -> bool:
        return self._pattern == "solid" or bool(
            self._definition and self._definition.solid)

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

    def line_segments(self) -> list:
        """The pattern's lines without its dots' circles."""
        return list(self._lines)

    def dots(self) -> list:
        """The pattern's dots as [((x, y, z), radius), ...]: drawn among
        `pattern_segments` as small circles, and here for a sheet to fill
        them, which reads better than a circle a pixel or two across."""
        return list(self._dots)

    def pattern_segments(self) -> list:
        """The pattern's lines in the world, as [((x,y,z), (x,y,z)), ...]."""
        return list(self._segments)

    # --- what it becomes ----------------------------------------------------

    def edited(self, **changes):
        """The same region with a different pattern, angle or spacing. A
        pattern from a .pat file comes with its `definition`."""
        unknown = changes.keys() - {"pattern", "angle", "spacing",
                                    "definition"}
        if unknown:
            raise TypeError(f"Unknown hatch property: {', '.join(sorted(unknown))}")
        values = dict(pattern=self._pattern, angle=self._angle,
                      spacing=self._spacing, definition=self._definition)
        if "pattern" in changes and "definition" not in changes:
            values["definition"] = None
        values.update(changes)
        return self._from_parts(self._region, values["pattern"],
                                values["angle"], values["spacing"],
                                self._frame, values["definition"])

    def with_region(self, region):
        """The same hatch over a different region, as a trim leaves.

        The frame comes along unchanged, so the pattern of a cut hatch
        stays where it was drawn: the pieces' lines line up with each
        other across the cut instead of each restarting at its own corner.
        """
        return self._from_parts(region, self._pattern, self._angle,
                                self._spacing, self._frame, self._definition)

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
                                new, self._definition)

    def copy(self):
        return self._from_parts(geometry.copy_shape(self._region),
                                self._pattern, self._angle, self._spacing,
                                self._frame, self._definition)

    def drawn(self):
        """What is drawn of the hatch: its pattern's lines, or for a solid
        fill the face. Not its boundary, which Rhino and AutoCAD do not
        draw either; that is the curves round it (#92)."""
        if self.solid:
            return self._region
        return _assemble(self._region, False, self._segments, outline=False)

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
        head = dict(pattern=self._pattern, angle=self._angle,
                    spacing=self._spacing, frame=self._frame)
        if self._definition is not None:
            head["definition"] = self._definition.to_dict()
        header = json.dumps(head).encode("utf-8")
        return (HATCH_TAG + struct.pack("<I", len(header)) + header
                + geometry.shape_to_bytes(self._region))

    @classmethod
    def from_bytes(cls, data: bytes):
        start = len(HATCH_TAG)
        size, = struct.unpack("<I", data[start:start + 4])
        start += 4
        head = json.loads(data[start:start + size])
        region = geometry.shape_from_bytes(data[start + size:])
        definition = None
        if head.get("definition"):
            from .hatch_patterns import HatchPattern
            definition = HatchPattern.from_dict(head["definition"])
        return cls._from_parts(region, head["pattern"], head["angle"],
                               head["spacing"], head["frame"], definition)


# --- the pieces -------------------------------------------------------------

class HatchGroup(TopoDS_Compound):
    """Several hatches as one shape, for a window to ghost while a command
    asks about them: a pick of several regions is one question."""

    def __init__(self, hatches):
        from OCP.BRep import BRep_Builder
        super().__init__()
        builder = BRep_Builder()
        builder.MakeCompound(self)
        for hatch in hatches:
            builder.Add(self, hatch)
        self.hatches = list(hatches)
        self.solid = bool(hatches) and all(h.solid for h in hatches)

    def drawn(self):
        """What is drawn of every hatch in it, as `HatchShape.drawn`."""
        from OCP.BRep import BRep_Builder
        builder = BRep_Builder()
        out = TopoDS_Compound()
        builder.MakeCompound(out)
        for hatch in self.hatches:
            builder.Add(out, hatch.drawn())
        return out


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
    deflection = max(float(np.linalg.norm(np.subtract(hi, lo))) * 1e-5, 1e-7)
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


def _pattern_segments(region, frame, pattern, angle, spacing,
                      definition=None) -> tuple:
    """(lines, circles, dots) of the pattern in the world: its lines, the
    sides of the small circle each dot is drawn as, and the dots again as
    (centre, radius), for a sheet that fills them."""
    from .hatch_patterns import dot_ring, fill_segments, segment_estimate
    rings = _rings(region, frame)
    if not rings:
        return [], [], []
    if definition is not None:
        lines = segment_estimate(rings, definition, spacing)
        what = "segments"
    else:
        span = max(float(np.ptp(np.vstack(rings), axis=0).max()), 0.0)
        lines = (span / spacing) * (2 if pattern == "cross" else 1)
        what = "lines"
    if lines > MAX_SEGMENTS:
        raise geometry.GeometryError(
            f"A spacing of {spacing:g} would draw {int(lines):,} {what} "
            "across this region; use a larger spacing")
    frame = np.asarray(frame, float)

    def world(p):
        return tuple(float(v) for v in
                     (frame @ np.array([p[0], p[1], 0.0, 1.0]))[:3])

    lines, circles, marks = [], [], []
    shortest = geometry.tight()
    segs, dots = fill_segments(rings, definition, pattern, angle, spacing,
                               dots=True)
    for a, b in segs:
        # a dash the boundary cuts to a sliver is no edge the kernel takes
        if math.dist(a, b) >= shortest:
            lines.append((world(a), world(b)))
    for centre, radius in dots:
        marks.append((world(centre), radius))
        for a, b in dot_ring(centre, radius):
            if math.dist(a, b) >= shortest:
                circles.append((world(a), world(b)))
    return lines, circles, marks


def _assemble(region, solid, segments, outline=True):
    """The compound the hatch is: its face, then its pattern's lines.

    The face is the fill of a solid one and the background of the rest,
    which is drawn only when there is one (#91); it is also what a click
    inside a hatch picks, as in Rhino, and what its bounds and snaps are
    taken from. Its edges are the hatch's boundary, which is not drawn.
    `outline` False leaves the face out of a line hatch: what a sheet's
    hidden-line pass is given to draw."""
    from OCP.BRep import BRep_Builder
    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    if solid or outline:
        builder.Add(compound, region)
    if solid:
        return compound
    for a, b in segments:
        if math.dist(a, b) >= geometry.tight():
            builder.Add(compound, geometry.make_line(a, b))
    return compound
