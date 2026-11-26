"""Finer meshes for the faces a pane is zoomed in on (#168).

An object is meshed once, at a deflection of 0.2% of its size, which strays
about a pixel from the surface when the whole object fills the view. Zoom in
tenfold and it strays ten: the outline of a curved face turns into a polygon
beside an edge that is drawn smooth. Meshing everything finer up front would
pay for detail nobody zooms into, so instead a pane asks for it face by face,
once it has stopped moving.

`plan` says which faces the pane can see and how much finer each needs to be,
in levels that each halve the deflection, so a camera creeping inwards asks
for the same few meshes again rather than a new one per step. `refined` builds
the object's mesh with those faces swapped for finer ones. A face is meshed on
a copy of itself, never on the drawing's own shape: BRepMesh keeps what it
makes on the shape it was given, and the drawing's copy is the one every
export, section and print reads.

Faces are meshed one at a time and kept, so panning across an object meshes
only the faces that come into view. Two neighbours meshed apart can disagree
along their shared edge by up to the coarser one's deflection, which is less
than a pixel at that edge by construction, and the edge's own line is drawn
over it.

How far a face's mesh strays is estimated from the mesh itself (_Facts.sag),
not taken as the deflection it was asked for: a small round on a big object
is already meshed far finer than that by the limit on how far one facet may
turn from the next, and a flat face with straight edges does not stray at
all. Taking the deflection at its word remeshed thousands of such faces on a
cab body at twice zoom extents, for 600 triangles' difference.
"""

from __future__ import annotations

import math
import threading
from collections import OrderedDict
from dataclasses import dataclass

import numpy as np
from OCP.IMeshTools import IMeshTools_MeshAlgoType, IMeshTools_Parameters

from . import geometry, occ
from .occ import BRepBuilderAPI_Copy, BRepMesh_IncrementalMesh
from .tessellate import (_ISO_SAMPLES, DEFLECTION_FRACTION, FACE_ANGLE,
                         MIN_DEFLECTION, DisplayMesh, _deflection_for,
                         _edge_polyline, _face_mesh, _iso_lifts, _iso_runs)

# A face is meshed again once its mesh strays more than TRIGGER_PX pixels from
# the surface, and then finely enough to stray less than TARGET_PX. At zoom
# extents the first mesh strays one or two, and an outline a pixel or more
# off the curve shows its corners, so a round part is asked for even seen
# whole: on Rhino's phone and disk brake samples, about three seconds in the
# background and a few tens of thousands of triangles.
TRIGGER_PX = 1.0
TARGET_PX = 0.5
# Each level halves the deflection. Eleven of them reach a millionth of the
# object's size, finer than the float32 offsets a mesh is drawn from can hold.
MAX_LEVEL = 11
# The most triangles one object's finer faces may come to, by estimate. A
# halved deflection about doubles a curved face's triangles. A face is meshed
# whole at the level its nearest point needs, so up close a big one asks for
# far more than the corner of it in view; at two million a sphere took
# minutes. This many mesh and read back in about a second.
BUDGET = 250_000
# Finer faces kept for reuse, counted in triangles, across every pane.
KEPT_TRIANGLES = 4_000_000
# Along an edge a mesh strays by its deflection or, where that is looser
# than FACE_ANGLE allows, by this fraction of the edge's radius: one piece
# spans at most FACE_ANGLE of arc.
_ARC = 1.0 - math.cos(FACE_ANGLE / 2)
# Faces are drawn pushed back a hair so the lines on them win the depth test,
# which holds only while a line sags less than the face under it. A finer
# face's edges are drawn LINE_LEAD levels finer still, and its isocurves
# resampled to match, or they break into dashes behind it.
LINE_LEAD = 2
_MAX_ISO_SAMPLES = 4096


@dataclass(frozen=True)
class View:
    """What a pane shows, as far as meshing goes.

    `pixel` is the size of a pixel in world units: everywhere, in a parallel
    view, and per unit of depth in a perspective one.
    """
    view_proj: np.ndarray
    eye: np.ndarray
    forward: np.ndarray
    parallel: bool
    pixel: float
    near: float

    @classmethod
    def of(cls, camera, width: int, height: int) -> "View":
        """The view through a `ui.camera.Camera`, `width` by `height` px."""
        view_proj, eye, forward = camera._view_proj(width, height)
        tan = math.tan(math.radians(camera.fov) / 2)
        parallel = camera.projection == "parallel"
        pixel = 2.0 * tan / max(height, 1)
        if parallel:
            pixel *= camera.distance
        return cls(np.asarray(view_proj, float), np.asarray(eye, float),
                   np.asarray(forward, float), parallel, pixel,
                   float(camera.clip_planes()[0]))


class _Facts:
    """What `plan` and `refined` need to know about one mesh of one shape,
    worked out once: its deflection, each face's box and triangle count, and
    the faces and edges by the numbers the mesh uses for them."""

    def __init__(self, shape, base: DisplayMesh):
        self.deflection = _deflection_for(shape)
        n = int(base.face_of_triangle.max()) + 1 if len(base.triangles) else 0
        self.counts = np.bincount(base.face_of_triangle, minlength=n)
        self.boxes = np.full((n, 2, 3), np.nan)
        self.first_vertex = np.zeros(n, np.int64)
        if n:
            order = np.argsort(base.face_of_triangle, kind="stable")
            corners = base.vertices[base.triangles[order]]
            lo, hi = corners.min(axis=1), corners.max(axis=1)
            starts = np.flatnonzero(np.r_[True, np.diff(
                base.face_of_triangle[order]) != 0])
            faces = base.face_of_triangle[order][starts]
            pad = self.deflection
            self.boxes[faces, 0] = np.minimum.reduceat(lo, starts) - pad
            self.boxes[faces, 1] = np.maximum.reduceat(hi, starts) + pad
            # tessellate() lays each face's vertices out together, in face
            # order, so a face's run of them starts at its lowest index
            self.first_vertex[faces] = np.minimum.reduceat(
                base.triangles[order].min(axis=1), starts)
        self.valid = ~np.isnan(self.boxes[:, 0, 0])
        self._sag = None
        self._shape = shape
        self._faces = None
        self._edges = None
        self._edge_number = None

    @property
    def faces(self) -> list:
        if self._faces is None:
            self._faces = geometry.faces_of(self._shape)
        return self._faces

    @property
    def edges(self) -> list:
        if self._edges is None:
            self._edges = geometry.edges_of(self._shape)
            self._edge_number = {hash(e): i for i, e in enumerate(self._edges)}
        return self._edges

    def sag(self, base: DisplayMesh) -> np.ndarray:
        """How far each face's mesh in `base` strays from it, by estimate.

        Read off the mesh, not the surface, which would mean asking the
        kernel at every vertex. A facet edge whose two normals differ by an
        angle a spans an arc of that angle, and sags L * a / 8 below it,
        where L is its length across the bend: the part along the axis the
        normal turns about, down a cylinder say, bends nothing. Along a
        face's edges the mesh follows the edge as finely
        as the deflection and FACE_ANGLE ask, so it sags by the deflection
        or _ARC of the edge's radius, whichever is less; the radius is read
        off how the drawn edge turns.
        """
        if self._sag is not None:
            return self._sag
        n = len(self.boxes)
        sag = np.zeros(n)
        tri = base.triangles.astype(np.int64)
        if len(tri):
            v = base.local.astype(np.float64)
            normal = base.normals.astype(np.float64)
            a, b = tri, np.roll(tri, -1, axis=1)
            along = v[b] - v[a]                                 # (T, 3, 3)
            turn = np.arccos(np.clip((normal[a] * normal[b]).sum(axis=2),
                                     -1.0, 1.0))
            axis = np.cross(normal[a], normal[b])
            size = np.linalg.norm(axis, axis=2, keepdims=True)
            axis = np.divide(axis, size, out=np.zeros_like(axis),
                             where=size > 1e-12)
            across = along - (along * axis).sum(axis=2, keepdims=True) * axis
            length = np.linalg.norm(across, axis=2)
            np.maximum.at(sag, base.face_of_triangle,
                          (length * turn).max(axis=1) / 8)
        seg = base.local_edges.astype(np.float64)
        owner = base.edge_of_segment
        if len(seg) > 1:
            first, then = seg[:-1, 1] - seg[:-1, 0], seg[1:, 1] - seg[1:, 0]
            l0 = np.linalg.norm(first, axis=1)
            l1 = np.linalg.norm(then, axis=1)
            joined = ((owner[:-1] == owner[1:]) & (l0 > 0) & (l1 > 0)
                      & np.all(seg[1:, 0] == seg[:-1, 1], axis=1))
            with np.errstate(divide="ignore", invalid="ignore"):
                turn = np.arccos(np.clip((first * then).sum(axis=1)
                                         / (l0 * l1), -1.0, 1.0))
                radius = np.where(joined & (turn > 1e-6),
                                  (l0 + l1) / 2 / turn, np.inf)
            tightest = np.full(int(owner.max()) + 1, np.inf)
            np.minimum.at(tightest, owner[:-1], radius)
            edge_sag = np.where(np.isfinite(tightest),
                                np.minimum(self.deflection, _ARC * tightest),
                                0.0)
            for face in np.flatnonzero(self.valid):
                for edge in self.edges_of_face(face):
                    if edge < len(edge_sag):
                        sag[face] = max(sag[face], edge_sag[edge])
        self._sag = np.minimum(sag, self.deflection)
        return self._sag

    def edges_of_face(self, face: int) -> list[int]:
        """The numbers of a face's edges, as the mesh's segments carry them."""
        self.edges                              # noqa: B018 -- fills the map
        out = []
        for edge in geometry.edges_of(self.faces[face]):
            number = self._edge_number.get(hash(edge))
            if number is not None:
                out.append(number)
        return out


_lock = threading.Lock()
_facts: OrderedDict = OrderedDict()             # mesh uid -> _Facts
_pieces: OrderedDict = OrderedDict()            # (uid, face, level) -> arrays
_kept = 0                                       # triangles in _pieces
_lines: OrderedDict = OrderedDict()             # (uid, edge, level) -> points


def _facts_for(shape, base: DisplayMesh) -> _Facts:
    with _lock:
        facts = _facts.get(base.uid)
        if facts is not None:
            _facts.move_to_end(base.uid)
            return facts
    facts = _Facts(shape, base)
    with _lock:
        _facts[base.uid] = facts
        while len(_facts) > 64:
            _facts.popitem(last=False)
    return facts


def deflections(boxes: np.ndarray) -> np.ndarray:
    """What `tessellate` meshes a shape with each box (N, 2, 3) at."""
    diag = np.linalg.norm(boxes[:, 1] - boxes[:, 0], axis=1)
    return np.maximum(diag * DEFLECTION_FRACTION, MIN_DEFLECTION)


_PICKS = np.array([[i & 1, (i >> 1) & 1, (i >> 2) & 1] for i in range(8)])


def _pixels(boxes: np.ndarray, view: View,
            depth: np.ndarray | None = None) -> tuple:
    """(the size of a pixel at each box (N, 2, 3), whether it is out of view).

    A box is in view unless it is wholly outside one side of the view, which
    can only ever say yes to too much. The pixel is measured at `depth`, or
    by default at the box's nearest corner, where it is smallest.
    """
    corners = np.where(_PICKS[None, :, :] == 1, boxes[:, None, 1],
                       boxes[:, None, 0])                       # (N, 8, 3)
    clip = (np.concatenate([corners, np.ones(corners.shape[:2] + (1,))],
                           axis=2) @ view.view_proj.T)
    x, y, z, w = clip[..., 0], clip[..., 1], clip[..., 2], clip[..., 3]
    outside = ((x < -w).all(1) | (x > w).all(1) | (y < -w).all(1)
               | (y > w).all(1) | (z < -w).all(1) | (z > w).all(1))
    if depth is None:
        depth = ((corners - view.eye) @ view.forward).min(axis=1)
    pixel = (np.full(len(boxes), view.pixel) if view.parallel
             else view.pixel * np.maximum(depth, view.near))
    return pixel, outside


def strays(boxes: np.ndarray, deflection, view: View) -> np.ndarray:
    """How many pixels a mesh at `deflection` can stray inside each box
    (N, 2, 3) in `view`, or 0 for a box wholly out of it."""
    pixel, outside = _pixels(boxes, view)
    return np.where(outside, 0.0, deflection / pixel)


def plan(shape, base: DisplayMesh, view: View,
         budget: int = BUDGET) -> dict[int, int]:
    """{face: level} for the faces in `view` whose mesh strays too far."""
    if not len(base.triangles):
        return {}
    facts = _facts_for(shape, base)
    boxes = facts.boxes[facts.valid]
    if not len(boxes):
        return {}
    # The nearest corner of a round face's box stands well in front of the
    # face, so in perspective the face is measured at its nearest vertex.
    depth = None
    if not view.parallel:
        along = (base.vertices - view.eye) @ view.forward
        depth = np.minimum.reduceat(
            along, facts.first_vertex[facts.valid]) - facts.deflection
    pixel, outside = _pixels(boxes, view, depth)
    sag = facts.sag(base)[facts.valid]
    want = ~outside & (sag / pixel > TRIGGER_PX)
    levels = np.zeros(len(boxes), int)
    levels[want] = np.clip(np.ceil(np.log2(
        facts.deflection / (TARGET_PX * pixel[want]))), 1, MAX_LEVEL)
    counts = facts.counts[facts.valid]

    def estimate() -> float:
        # a face's triangles grow as its sag shrinks, from where it is now
        busy = levels > 0
        now = sag[busy] / (facts.deflection / 2.0 ** levels[busy])
        return float((counts[busy] * np.maximum(now, 1.0)).sum())
    while levels.max() > 0 and estimate() > budget:
        levels[levels == levels.max()] -= 1
    numbers = np.flatnonzero(facts.valid)
    return {int(numbers[i]): int(levels[i]) for i in np.flatnonzero(levels)}


def _piece(base: DisplayMesh, facts: _Facts, face: int, level: int):
    """One face meshed at `level`, as (vertices, normals, triangles,
    curvature, isocurve segments, their lifts onto these triangles), or
    None if it will not mesh. Kept for the next ask."""
    global _kept
    key = (base.uid, face, level)
    with _lock:
        if key in _pieces:
            _pieces.move_to_end(key)
            return _pieces[key]
    copy = occ.to_face(BRepBuilderAPI_Copy(facts.faces[face], True,
                                           False).Shape())
    BRepMesh_IncrementalMesh(copy, _parameters(facts.deflection / 2 ** level))
    piece = _face_mesh(copy)
    if piece is not None:
        # A chord's sag goes as the square of its length, so halving it
        # LINE_LEAD + level times takes 2 ** ((level + LINE_LEAD) / 2) as
        # many samples as the first mesh's isocurves had.
        samples = min(_MAX_ISO_SAMPLES, int(math.ceil(
            _ISO_SAMPLES * 2 ** ((level + LINE_LEAD) / 2))))
        try:
            runs = _iso_runs(copy, samples)
            lifts = _iso_lifts(copy, piece, runs)
        except Exception:                                   # noqa: BLE001
            runs, lifts = [], []
        isos, lift = ((np.concatenate([np.stack([r[:-1], r[1:]], axis=1)
                                       for r in rs]) if rs
                       else np.zeros((0, 2, 3)))
                      for rs in ([r[0] for r in runs], lifts))
        piece = (*piece, isos, lift)
    with _lock:
        _pieces[key] = piece
        _kept += len(piece[2]) if piece is not None else 0
        while _kept > KEPT_TRIANGLES and len(_pieces) > 1:
            _old, dropped = _pieces.popitem(last=False)
            _kept -= len(dropped[2]) if dropped is not None else 0
    return piece


def _parameters(deflection: float) -> IMeshTools_Parameters:
    """BRepMesh's settings for a finer face: tessellate's, but triangulated
    by Delabella, which met the same deflection on a fine sphere in 0.58 s
    where the default took 4.93."""
    p = IMeshTools_Parameters()
    p.Deflection = deflection
    p.Angle = FACE_ANGLE
    p.Relative = False
    p.InParallel = False
    p.MeshAlgo = IMeshTools_MeshAlgoType.IMeshTools_MeshAlgoType_Delabella
    return p


def _line(base: DisplayMesh, facts: _Facts, edge: int, level: int):
    key = (base.uid, edge, level)
    with _lock:
        if key in _lines:
            return _lines[key]
    pts = _edge_polyline(facts.edges[edge], facts.deflection / 2 ** level)
    with _lock:
        _lines[key] = pts
        while len(_lines) > 100_000:
            _lines.popitem(last=False)
    return pts


def refined(shape, base: DisplayMesh, levels: dict[int, int]) -> DisplayMesh:
    """`base` with each face in `levels` meshed again at its level, and the
    edges round those faces drawn to match. Faces and edges keep their
    numbers, so picking and highlighting read it as they read `base`."""
    if not levels:
        return base
    facts = _facts_for(shape, base)
    verts, norms, tris, curv, owners, isos, iso_owners = ([], [], [], [],
                                                          [], [], [])
    lifts = []
    offset = len(base.local)
    done = []
    for face, level in sorted(levels.items()):
        piece = _piece(base, facts, face, level)
        if piece is None:
            continue
        v, n, t, c, iso, lift = piece
        if len(iso):
            isos.append(iso)
            lifts.append(lift)
            iso_owners.append(np.full(len(iso), face, np.int32))
        verts.append(v)
        norms.append(n)
        tris.append(t.astype(np.int64) + offset)
        curv.append(c)
        owners.append(np.full(len(t), face, np.int32))
        offset += len(v)
        done.append(face)
    if not done:
        return base

    edge_level: dict[int, int] = {}
    for face in done:
        for edge in facts.edges_of_face(face):
            edge_level[edge] = max(edge_level.get(edge, 0),
                                   levels[face] + LINE_LEAD)
    segments, segment_owners = [], []
    for edge, level in sorted(edge_level.items()):
        pts = _line(base, facts, edge, level)
        if pts is not None and len(pts) >= 2:
            segments.append(np.stack([pts[:-1], pts[1:]], axis=1))
            segment_owners.append(np.full(len(pts) - 1, edge, np.int32))
    redrawn = sorted(int(o[0]) for o in segment_owners)

    keep = ~np.isin(base.face_of_triangle, done)
    out = DisplayMesh()
    out.origin = base.origin
    out._far = base.far
    out.local = np.concatenate([base.local,
                                base._offsets(np.concatenate(verts))])
    out.normals = np.concatenate([base.normals, *norms]).astype(np.float32)
    out.triangles = np.concatenate(
        [base.triangles[keep], *tris]).astype(np.uint32)
    out.face_of_triangle = np.concatenate(
        [base.face_of_triangle[keep], *owners]).astype(np.int32)
    out.curvature = np.concatenate(
        [base.curvature, *curv]).astype(np.float32)
    out.has_curvature = base.has_curvature
    kept = ~np.isin(base.edge_of_segment, redrawn)
    out.local_edges = np.concatenate(
        [base.local_edges[kept],
         *(base._offsets(s) for s in segments)]).astype(np.float32)
    out.edge_of_segment = np.concatenate(
        [base.edge_of_segment[kept], *segment_owners]).astype(np.int32)
    if len(base.face_of_iso) == len(base.local_isos):
        kept = ~np.isin(base.face_of_iso, done)
        out.local_isos = np.concatenate(
            [base.local_isos[kept],
             *(base._offsets(i) for i in isos)]).astype(np.float32)
        out.face_of_iso = np.concatenate(
            [base.face_of_iso[kept], *iso_owners]).astype(np.int32)
        held = (base.iso_lift if len(base.iso_lift) == len(base.local_isos)
                else np.zeros(base.local_isos.shape, np.float32))
        out.iso_lift = np.concatenate(
            [held[kept], *lifts]).astype(np.float32)
    else:
        out.local_isos = base.local_isos
        out.iso_lift = base.iso_lift
    out.local_points = base.local_points
    return out
