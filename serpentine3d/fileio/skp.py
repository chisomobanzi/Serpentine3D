"""SketchUp .skp files, read by OpenSKP (issue #42).

SketchUp's own reader is an SDK for Windows and Mac, so there was no way to
open a .skp on Linux. OpenSKP reads the format from its reverse-engineered
layout, in Python, on every platform. This turns what it reads into what a
SketchUp model is made of here.

A model is planar faces, gathered into groups and components that can be
placed many times over. What one placed at the top of the model holds,
everything nested inside it brought to where it sits, becomes an object
for each separate body, its faces joined into a polysurface and into a
solid where they close, and one for any stray edges; more than one and
they are grouped, so the lot selects together as it did in SketchUp. Faces
and edges loose at the top of the model are treated the same way, a tag at
a time. Tags come across as layers, and a material's colour as the
object's colour. SketchUp works in inches whatever its template says, so
sizes are converted.
"""

from __future__ import annotations

import os
import uuid
from collections import Counter

import numpy as np

from ..core import geometry
from ..utils.units import convert
from .progress import Progress

# SketchUp's default tag: Layer0 in the file, "Untagged" on screen
_UNTAGGED = ("", "Layer0")
_DEPTH_LIMIT = 64                  # a component can hold itself only in error


class SketchUpError(ValueError):
    """A .skp the reader could not make sense of."""


def import_skp(path: str, units: str = "mm",
               progress=None) -> list[tuple[str, object, dict]]:
    """(name, shape, meta) for each object the SketchUp model at `path` makes.

    The meta is what `fileio._layer_for` and the scene read: the layer
    with its colour and visibility, a colour, and whether it is shown.
    """
    from openskp import SkpFile
    report = progress or Progress()
    skp = SkpFile.open(path)
    try:
        model = skp.parse()
    except Exception as exc:
        raise SketchUpError(
            f"Could not read this SketchUp file ({exc}). Exporting it from "
            "SketchUp as OBJ, FBX or DXF and importing that works in the "
            "meantime.") from exc
    reader = _Reader(model, skp, convert(1.0, "in", units))
    report.tick(0.3, "Read the SketchUp model")

    items = []
    placed = [i for i in model.root.instances
              if reader.definition(i) is not None]
    for n, inst in enumerate(placed, 1):
        items.extend(reader.placed(inst))
        report.tick(0.3 + 0.65 * n / len(placed),
                    f"Built {n} of {len(placed)} groups and components")
    items.extend(reader.loose())
    report.tick(1.0, "")
    if not items:
        base = os.path.basename(path)
        raise SketchUpError(f"{base} holds no faces or edges to import.")
    return items


class _Reader:
    def __init__(self, model, skp, scale: float):
        self.model = model
        self.scale = scale
        # A face names its tag by number. OpenSKP keeps the table turning
        # that number into a name only in its parse results, so it is read
        # from there, and a face whose tag cannot be named is untagged.
        parsed = getattr(skp, "_parsed", None) or {}
        self.tag_names = parsed.get("layer_id_to_name", {}) or {}
        self.tags = {t.name: t for t in model.layers}
        self.materials = {m.id: m for m in model.materials}

    def definition(self, inst):
        d = self.model.definitions.get(inst.ref_idx)
        return None if d is None or d.is_image else d

    # ---------------------------------------------------------------- objects

    def placed(self, inst) -> list:
        """The objects a group or component placed at the top makes."""
        found = _Found()
        self._gather(self.definition(inst), _matrix(inst.matrix), found,
                     inst.material_id)
        name = inst.name or self.definition(inst).name or "SketchUp group"
        # A group is often left untagged with its faces tagged instead, and
        # then the faces say where it belongs.
        tag = inst.layer if inst.layer not in _UNTAGGED else found.main_tag()
        meta = self._tag_meta(tag)
        colour = self._colour(inst.material_id) or self._colour(
            found.main_material())
        if colour is not None:
            meta["color"] = colour
        if inst.hidden:
            meta["visible"] = False
        return found.items(name, meta)

    def loose(self):
        """Faces and edges at the top of the model, one object per tag."""
        by_tag: dict[str, _Found] = {}
        root = self.model.root
        used = _edges_in_faces(root)
        for face in root.faces.values():
            by_tag.setdefault(self._tag_of(face), _Found()).add_face(
                self._loops(root, face, np.eye(4)), face.material_id)
        for eid, edge in root.edges.items():
            if eid in used or edge.hidden:
                continue
            by_tag.setdefault(self._tag_of(edge), _Found()).add_segment(
                *self._edge(root, edge, np.eye(4)))
        out = []
        for tag, found in by_tag.items():
            meta = self._tag_meta(tag)
            colour = self._colour(found.main_material())
            if colour is not None:
                meta["color"] = colour
            out.extend(found.items(
                "Untagged" if tag in _UNTAGGED else tag, meta))
        return out

    # ------------------------------------------------------------ gathering

    def _gather(self, defn, matrix, found, inherited, depth=0):
        """Every face and loose edge of `defn` and of all placed in it,
        brought to where `matrix` puts them. A face with no material of
        its own wears what the group around it wears, as in SketchUp."""
        if depth > _DEPTH_LIMIT:
            return
        for face in defn.faces.values():
            found.add_face(self._loops(defn, face, matrix),
                           face.material_id or inherited, self._tag_of(face))
        used = _edges_in_faces(defn)
        for eid, edge in defn.edges.items():
            if eid not in used and not edge.hidden:
                found.add_segment(*self._edge(defn, edge, matrix))
        for inst in defn.instances:
            sub = self.definition(inst)
            # a hidden placement inside a group cannot stay hidden on its
            # own once the group is flattened into its bodies, so it is
            # left out
            if sub is None or inst.hidden:
                continue
            self._gather(sub, matrix @ _matrix(inst.matrix), found,
                         inst.material_id or inherited, depth + 1)

    def _loops(self, defn, face, matrix):
        loops = []
        for loop in face.loops:
            pts = []
            for eid, direction in loop:
                edge = defn.edges.get(eid)
                if edge is None:
                    continue
                vid = edge.v1_id if direction >= 0 else edge.v2_id
                pts.append(self._point(defn.vertices[vid], matrix))
            loops.append(pts)
        return loops

    def _tag_of(self, entity) -> str:
        """The tag a face or edge is on, by name; untagged if the file's
        number for it names nothing."""
        return (self.tag_names.get(entity.layer, "")
                if entity.layer is not None else "")

    def _edge(self, defn, edge, matrix):
        return (self._point(defn.vertices[edge.v1_id], matrix),
                self._point(defn.vertices[edge.v2_id], matrix))

    def _point(self, v, matrix):
        return (matrix @ np.array([v.x, v.y, v.z, 1.0]))[:3] * self.scale

    # ------------------------------------------------------ tags and colour

    def _tag_meta(self, tag: str) -> dict:
        if not tag or tag in _UNTAGGED:
            return {}
        t = self.tags.get(tag)
        meta = {"layer": tag}
        if t is not None:
            meta["layer_color"] = (t.color_r / 255.0, t.color_g / 255.0,
                                   t.color_b / 255.0)
            meta["layer_visible"] = not t.hidden
        return meta

    def _colour(self, material_id):
        m = self.materials.get(material_id)
        if m is None or not m.color:
            return None
        r, g, b = m.color[:3]
        return (r / 255.0, g / 255.0, b / 255.0)


class _Found:
    """What one object is being built from."""

    def __init__(self):
        self.faces = []
        self.segments = []
        self.materials = Counter()
        self.tags = Counter()

    def add_face(self, loops, material_id, tag: str = ""):
        self.faces.append(loops)
        if material_id is not None:
            self.materials[material_id] += 1
        if tag and tag not in _UNTAGGED:
            self.tags[tag] += 1

    def add_segment(self, a, b):
        if np.linalg.norm(b - a) > 1e-12:
            self.segments.append((a, b))

    def main_material(self):
        return self.materials.most_common(1)[0][0] if self.materials else None

    def main_tag(self) -> str:
        return self.tags.most_common(1)[0][0] if self.tags else ""

    def bodies(self) -> list:
        """Each separate body the faces make, a solid where it closes and
        facing out: SketchUp is happy with faces wound either way round,
        and a solid sewn from the wrong way round has a negative volume."""
        from OCP.BRepLib import BRepLib

        from ..core import occ
        faces = [f for f in (_face(loops) for loops in self.faces)
                 if f is not None]
        if not faces:
            return []
        out = []
        for piece in geometry.joined_pieces(geometry.join_surfaces(faces)):
            if piece.ShapeType() != occ.SOLID:
                piece = geometry.join_surfaces([piece])
            if piece.ShapeType() == occ.SOLID:
                BRepLib.OrientClosedSolid_s(occ.to_solid(piece))
            out.append(piece)
        return out

    def items(self, name: str, meta: dict) -> list:
        """(name, shape, meta) for each body and for the stray edges, all
        in one group when there is more than one of them."""
        made = [(name, body) for body in self.bodies()]
        if self.segments:
            made.append((f"{name} edges", geometry.make_compound(
                [geometry.make_line(tuple(a), tuple(b))
                 for a, b in self.segments])))
        if len(made) > 1:
            meta = dict(meta, group=uuid.uuid4().hex[:8])
        return [(n, shape, dict(meta)) for n, shape in made]


# ---------------------------------------------------------------- helpers

def _matrix(values) -> np.ndarray:
    """A placement's 4x4 from the 13 numbers SketchUp stores: the three
    rows of its rotation and scale, then the translation (in inches), then
    a scale OpenSKP's own conversion leaves alone, as this does."""
    m = np.eye(4)
    m[:3, :3] = np.asarray(values[:9], float).reshape(3, 3)
    m[:3, 3] = values[9:12]
    return m


def _edges_in_faces(defn) -> set:
    return {eid for face in defn.faces.values()
            for loop in face.loops for eid, _ in loop}


def _face(loops):
    """A planar face from its boundary and any holes, or None if the
    boundary is degenerate. SketchUp faces are flat by construction."""
    from OCP.ShapeFix import ShapeFix_Face

    from ..core.occ import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon, gp_Pnt
    wires = []
    for i, loop in enumerate(loops):
        pts = [p for j, p in enumerate(loop)
               if j == 0 or np.linalg.norm(p - loop[j - 1]) > 1e-9]
        if len(pts) > 1 and np.linalg.norm(pts[0] - pts[-1]) <= 1e-9:
            pts.pop()
        if len(pts) < 3:
            if i == 0:
                return None
            continue
        poly = BRepBuilderAPI_MakePolygon()
        for p in pts:
            poly.Add(gp_Pnt(float(p[0]), float(p[1]), float(p[2])))
        poly.Close()
        if not poly.IsDone():
            if i == 0:
                return None
            continue
        wires.append(poly.Wire())
    mk = BRepBuilderAPI_MakeFace(wires[0], True)
    if not mk.IsDone():
        return None
    for hole in wires[1:]:
        mk.Add(hole)
    fix = ShapeFix_Face(mk.Face())
    fix.Perform()
    return fix.Face()
