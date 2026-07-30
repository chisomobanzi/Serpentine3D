"""Paper-space layouts: sheets, detail views, and annotations.

Dimensions are millimetres of paper. A detail's scale is stored as the
denominator N of 1:N — one millimetre of paper shows N model units
(Serpentine3D treats one model unit as one millimetre for drafting).
"""

from __future__ import annotations

import copy
import math
import uuid
from dataclasses import dataclass, field, replace

# landscape (width, height) in mm
PAPER_SIZES = {
    "A4": (297.0, 210.0),
    "A3": (420.0, 297.0),
    "A2": (594.0, 420.0),
    "A1": (841.0, 594.0),
    "A0": (1189.0, 841.0),
    "Letter": (279.4, 215.9),
    "Tabloid": (431.8, 279.4),
}

STANDARD_SCALES = [1, 2, 5, 10, 20, 50, 100, 200, 500]


def _uid() -> str:
    return uuid.uuid4().hex[:8]


@dataclass
class DetailView:
    id: str = field(default_factory=_uid)
    # rectangle on paper, mm, origin bottom-left of sheet
    x: float = 10.0
    y: float = 10.0
    w: float = 100.0
    h: float = 80.0
    # camera
    azimuth: float = math.radians(-90)      # top view default
    elevation: float = math.radians(89.9)
    target: list = field(default_factory=lambda: [0.0, 0.0, 0.0])
    perspective: bool = False
    scale_denom: float = 10.0               # 1:10
    perspective_distance: float = 60.0      # camera distance when perspective
    display_mode: str = "wireframe"         # wireframe|shaded|hidden|technical
    locked: bool = False
    show_border: bool = True
    show_label: bool = True
    section_offset: float | None = None   # cut plane distance from target

    def contains(self, px: float, py: float) -> bool:
        return (self.x <= px <= self.x + self.w
                and self.y <= py <= self.y + self.h)

    def scale_text(self) -> str:
        d = self.scale_denom
        if self.perspective:
            return "perspective"
        if d >= 1:
            return f"1:{d:g}"
        return f"{1 / d:g}:1"


@dataclass
class TextNote:
    id: str = field(default_factory=_uid)
    x: float = 0.0
    y: float = 0.0
    text: str = ""             # may contain newlines
    height: float = 4.0        # mm
    style: str = ""            # named style overrides height when set


@dataclass
class LinearDim:
    id: str = field(default_factory=_uid)
    x1: float = 0.0
    y1: float = 0.0
    x2: float = 0.0
    y2: float = 0.0
    offset: float = 8.0        # mm from the measured points
    text: str = ""             # empty -> auto (measured length)
    scale_denom: float = 1.0   # to express model-space length
    style: str = ""
    # associative anchors: model-space points seen through a detail.
    # When set, x/y are recomputed from the detail camera each draw.
    detail_id: str = ""
    m1: list | None = None     # [x, y, z]
    m2: list | None = None


@dataclass
class Leader:
    id: str = field(default_factory=_uid)
    points: list = field(default_factory=list)   # [[x,y], ...] arrow at [0]
    text: str = ""
    height: float = 3.5
    style: str = ""


@dataclass
class Hatch:
    id: str = field(default_factory=_uid)
    points: list = field(default_factory=list)   # closed polygon [[x,y],...]
    pattern: str = "lines"                       # solid | lines | cross
    angle: float = 45.0
    spacing: float = 3.0                         # mm


@dataclass
class RadialDim:
    id: str = field(default_factory=_uid)
    cx: float = 0.0
    cy: float = 0.0
    px: float = 0.0        # point on the circle (paper mm)
    py: float = 0.0
    diameter: bool = False
    scale_denom: float = 1.0
    text: str = ""
    style: str = ""


@dataclass
class AngularDim:
    id: str = field(default_factory=_uid)
    vx: float = 0.0        # vertex
    vy: float = 0.0
    x1: float = 0.0
    y1: float = 0.0
    x2: float = 0.0
    y2: float = 0.0
    radius: float = 15.0   # arc placement radius, mm


@dataclass
class PaperObject:
    """Geometry drawn on the paper itself, in millimetres.

    A real shape rather than a list of points, so that offset, trim, fillet
    and the rest work on a border or a detail bubble the same way they work on
    the model. Nothing here is seen through a detail: 100 means 100mm across
    the sheet.

    Keep every field but the shape immutable — the copy below is shallow, and
    a list or dict here would be shared between undo checkpoints.
    """
    id: str = field(default_factory=_uid)
    shape: object = None                 # a TopoDS shape in paper millimetres
    name: str = ""
    color: tuple | None = None           # None -> the sheet's default ink
    linetype: str = "Continuous"
    lineweight: float = 0.25             # millimetres, as on a drawing
    _plines: tuple | None = field(default=None, repr=False, compare=False)
    _pts: tuple | None = field(default=None, repr=False, compare=False)

    @property
    def polylines(self) -> list:
        """The shape as (N, 3) polylines, in paper millimetres.

        Polylines rather than loose segments, so that a dash pattern runs
        along a whole curve instead of restarting at every tessellation step.

        Keyed on the shape it measured rather than cleared by hand: a shape is
        changed here by swapping in a new one, so the answer expires by itself
        and there is no invalidation to forget at a call site — the same trick
        `SceneObject.bbox` uses.
        """
        cached = self._plines
        if cached is not None and cached[0] is self.shape:
            return cached[1]
        from . import geometry, hlr
        lines = hlr.edges_to_polylines(geometry.edges_of(self.shape))
        self._plines = (self.shape, lines)
        return lines

    @property
    def points(self) -> list:
        """The shape's free-standing points, in paper millimetres.

        A point object is the one thing on a sheet with no line work in it, so
        walking edges walks past it. Kept apart from `polylines` rather than
        folded in as a polyline of one, because everything reading polylines
        reads them as something to walk along: dashing them, measuring them,
        asking what a click landed near.

        Keyed on the shape the same way `polylines` is, and for the same reason.
        """
        cached = self._pts
        if cached is not None and cached[0] is self.shape:
            return cached[1]
        from . import geometry
        pts = geometry.free_points(self.shape)
        self._pts = (self.shape, pts)
        return pts

    def __deepcopy__(self, memo):
        """Copy for the undo stack, sharing the shape.

        `copy.deepcopy` of a TopoDS shape raises outright — it will not
        pickle — and there is nothing to gain by copying one: a shape is never
        edited in place, an edit replaces it, so two checkpoints can hold the
        same shape safely. The same bargain `SceneObject.clone` makes.

        It lives here rather than in `Layout.clone` because anything that
        copies a scene reaches a layout eventually, and the object that owns
        the shape is the one place that knows this.
        """
        twin = replace(self)
        memo[id(self)] = twin
        return twin


def hatch_lines(points: list, angle_deg: float,
                spacing: float) -> list:
    """Hatch segments filling a closed polygon (even-odd), as
    [((x0,y0),(x1,y1)), ...] in the same coordinates as `points`."""
    import numpy as np
    if len(points) < 3 or spacing <= 0:
        return []
    pts = np.asarray(points, float)
    a = math.radians(angle_deg)
    rot = np.array([[math.cos(-a), -math.sin(-a)],
                    [math.sin(-a), math.cos(-a)]])
    local = pts @ rot.T
    y0, y1 = local[:, 1].min(), local[:, 1].max()
    out = []
    inv = np.array([[math.cos(a), -math.sin(a)],
                    [math.sin(a), math.cos(a)]])
    y = y0 + spacing / 2
    n = len(local)
    while y < y1:
        xs = []
        for i in range(n):
            p, q = local[i], local[(i + 1) % n]
            if (p[1] > y) != (q[1] > y):
                t = (y - p[1]) / (q[1] - p[1])
                xs.append(p[0] + t * (q[0] - p[0]))
        xs.sort()
        for i in range(0, len(xs) - 1, 2):
            a2 = inv @ np.array([xs[i], y])
            b2 = inv @ np.array([xs[i + 1], y])
            out.append(((float(a2[0]), float(a2[1])),
                        (float(b2[0]), float(b2[1]))))
        y += spacing
    return out


DEFAULT_STYLES = {
    "Standard": {"text_height": 3.2, "arrow_size": 2.2, "dim_offset": 8.0},
    "Small":    {"text_height": 2.2, "arrow_size": 1.6, "dim_offset": 5.0},
    "Heading":  {"text_height": 6.0, "arrow_size": 2.2, "dim_offset": 8.0},
}


def _on_axis(v, tol: float = 5e-3):
    """`v` with components a whisker from 0 or ±1 rounded to them."""
    import numpy as np
    out = np.asarray(v, float).copy()
    near = np.abs(np.abs(out) - 1.0) < tol
    out[np.abs(out) < tol] = 0.0
    out[near] = np.sign(out[near])
    n = np.linalg.norm(out)
    return out / n if n > 1e-12 else np.asarray(v, float)


def detail_basis(detail):
    """The basis a detail's geometry is measured in: view dir, right, up.

    The named views are aimed 0.1 degrees off vertical so the camera basis
    never degenerates. Geometry must not inherit that lean — a line drawn in a
    top view has to come out level — so an axis the basis is within a whisker
    of is the axis it gets.
    """
    import numpy as np
    from ..ui.layout_view import detail_direction
    d, right, _up = detail_direction(detail)
    d, right = _on_axis(d), _on_axis(right)
    right = right - np.dot(right, d) * d
    n = np.linalg.norm(right)
    if n > 1e-12:
        right = right / n
    return d, right, np.cross(right, -d)


def detail_project(detail, model_pt) -> tuple[float, float]:
    """Model-space point -> paper mm through a detail's camera."""
    import numpy as np
    d, right, up = detail_basis(detail)
    rel = np.asarray(model_pt, float) - np.asarray(detail.target, float)
    u = float(np.dot(rel, right)) / detail.scale_denom
    v = float(np.dot(rel, up)) / detail.scale_denom
    return detail.x + detail.w / 2 + u, detail.y + detail.h / 2 + v


def detail_unproject(detail, px: float, py: float) -> list:
    """Paper mm -> model-space point on the detail's view plane."""
    import numpy as np
    d, right, up = detail_basis(detail)
    u = (px - detail.x - detail.w / 2) * detail.scale_denom
    v = (py - detail.y - detail.h / 2) * detail.scale_denom
    return [float(c) for c in
            np.asarray(detail.target, float) + right * u + up * v]


def detail_model_point(detail, px: float, py: float,
                       grid_step: float = 0.0) -> tuple:
    """The model point a detail shows at paper (px, py).

    Inside a detail you are drawing in the model, and the plane you draw on
    is the one the detail looks at — the same relationship the CPlane has to
    model space. Any grid snap therefore rounds in model units on that
    plane, because a round number here belongs to the geometry that gets
    built, not to the paper it is being viewed on.
    """
    if grid_step > 0:
        cx, cy = detail.x + detail.w / 2, detail.y + detail.h / 2
        u = round((px - cx) * detail.scale_denom / grid_step) * grid_step
        v = round((py - cy) * detail.scale_denom / grid_step) * grid_step
        px = cx + u / detail.scale_denom
        py = cy + v / detail.scale_denom
    return tuple(round(c, 9) for c in detail_unproject(detail, px, py))


def resolve_associative(layout):
    """Refresh paper coordinates of detail-anchored dimensions."""
    details = {d.id: d for d in layout.details}
    for dim in layout.dims:
        det = details.get(getattr(dim, "detail_id", ""))
        if det is None or dim.m1 is None or dim.m2 is None:
            continue
        dim.x1, dim.y1 = detail_project(det, dim.m1)
        dim.x2, dim.y2 = detail_project(det, dim.m2)
        dim.scale_denom = det.scale_denom


def _dist_seg(px, py, a, b) -> float:
    import numpy as np
    p = np.array([px, py], float)
    a = np.asarray(a, float)[:2]
    b = np.asarray(b, float)[:2]
    ab = b - a
    denom = float(ab @ ab)
    t = 0.0 if denom < 1e-12 else float(np.clip((p - a) @ ab / denom, 0, 1))
    return float(np.linalg.norm(p - (a + t * ab)))


def annotation_at(layout, px: float, py: float, tol: float = 2.0):
    """Topmost annotation near a paper point -> (kind, obj) or None.

    Kinds: note, leader, dim, rdim, adim, hatch (dims before hatches so
    outlines don't shadow them)."""
    for note in reversed(layout.notes):
        w = max(len(line) for line in (note.text or " ").split("\n")) \
            * note.height * 0.62
        h = note.height * (1 + (note.text or "").count("\n") * 1.6)
        if note.x - tol <= px <= note.x + w + tol \
                and note.y - tol <= py <= note.y + h + tol:
            return ("note", note)
    for dim in reversed(layout.dims):
        import numpy as np
        a = np.array([dim.x1, dim.y1])
        b = np.array([dim.x2, dim.y2])
        d = b - a
        n = np.linalg.norm(d)
        if n < 1e-9:
            continue
        nvec = np.array([-d[1], d[0]]) / n
        if _dist_seg(px, py, a + nvec * dim.offset,
                     b + nvec * dim.offset) <= tol:
            return ("dim", dim)
    for rd in reversed(layout.rdims):
        if _dist_seg(px, py, (rd.cx, rd.cy), (rd.px, rd.py)) <= tol:
            return ("rdim", rd)
    for ad in reversed(layout.adims):
        import math as _m
        r = _m.hypot(px - ad.vx, py - ad.vy)
        if abs(r - ad.radius) <= tol * 1.5:
            return ("adim", ad)
    for leader in reversed(layout.leaders):
        pts = leader.points
        for a, b in zip(pts[:-1], pts[1:]):
            if _dist_seg(px, py, a, b) <= tol:
                return ("leader", leader)
    for hatch in reversed(layout.hatches):
        if _point_in_poly(px, py, hatch.points):
            return ("hatch", hatch)
    return None


def paper_object_at(layout, px: float, py: float, tol: float = 2.0):
    """Topmost paper geometry near a paper point -> PaperObject or None.

    Picked by its ink, the way a curve is picked in the model: what a border
    encloses is the rest of the sheet, and a click in the middle of the page
    means the page.
    """
    for obj in reversed(layout.objects):        # drawn last, so on top
        for poly in obj.polylines:
            for a, b in zip(poly[:-1], poly[1:]):
                if _dist_seg(px, py, a, b) <= tol:
                    return obj
        # a point has no ink to be near, so being near the point is the test
        for p in obj.points:
            if math.hypot(px - float(p[0]), py - float(p[1])) <= tol:
                return obj
    return None


def paper_object_bounds(obj) -> tuple:
    """Paper-space bbox (x0, y0, x1, y1) of paper geometry.

    From the polylines rather than the shape's own bbox, so a curve is only as
    big as it draws and the answer follows the same cache a repaint uses.
    """
    xs, ys = [], []
    for poly in obj.polylines:
        for p in poly:
            xs.append(float(p[0]))
            ys.append(float(p[1]))
    for p in obj.points:
        xs.append(float(p[0]))
        ys.append(float(p[1]))
    if not xs:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(xs), min(ys), max(xs), max(ys))


def _seg_hits_rect(a, b, lo: tuple, hi: tuple) -> bool:
    """Does the segment a-b touch the axis-aligned rect? (Liang-Barsky.)"""
    x0, y0 = float(a[0]), float(a[1])
    dx, dy = float(b[0]) - x0, float(b[1]) - y0
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0 - lo[0]), (dx, hi[0] - x0),
                 (-dy, y0 - lo[1]), (dy, hi[1] - y0)):
        if p == 0.0:
            if q < 0.0:
                return False            # parallel to this edge and outside it
        else:
            r = q / p
            if p < 0.0:
                if r > t1:
                    return False
                t0 = max(t0, r)
            else:
                if r < t0:
                    return False
                t1 = min(t1, r)
    return True


def paper_object_crosses(obj, x0: float, y0: float,
                         x1: float, y1: float) -> bool:
    """Does any of the geometry's ink fall inside the paper rect?

    A crossing band asks what it touches, and a bounding box is the wrong
    answer for paper geometry: a border's box is the whole page, so a box test
    hands over the border for any band drawn anywhere inside it.
    """
    lo = (min(x0, x1), min(y0, y1))
    hi = (max(x0, x1), max(y0, y1))
    for poly in obj.polylines:
        for a, b in zip(poly[:-1], poly[1:]):
            if _seg_hits_rect(a, b, lo, hi):
                return True
    for p in obj.points:
        if (lo[0] <= float(p[0]) <= hi[0]
                and lo[1] <= float(p[1]) <= hi[1]):
            return True
    return False


def move_paper_object(obj, dx: float, dy: float):
    """Slide paper geometry across the sheet by millimetres.

    There is no x/y to add to — the shape *is* the position — so this replaces
    the shape, which is also the only edit a shared undo checkpoint allows.
    """
    from . import geometry
    obj.shape = geometry.translate(obj.shape, (dx, dy, 0.0))


def _point_in_poly(px: float, py: float, pts: list) -> bool:
    inside = False
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i][0], pts[i][1]
        x2, y2 = pts[(i + 1) % n][0], pts[(i + 1) % n][1]
        if (y1 > py) != (y2 > py):
            if px < x1 + (py - y1) / (y2 - y1) * (x2 - x1):
                inside = not inside
    return inside


def move_annotation(kind: str, obj, dx: float, dy: float):
    """Translate any annotation by paper millimetres."""
    if kind == "note":
        obj.x += dx
        obj.y += dy
    elif kind == "dim":
        obj.x1 += dx
        obj.y1 += dy
        obj.x2 += dx
        obj.y2 += dy
        if getattr(obj, "m1", None) is not None:
            obj.detail_id = ""          # moving by hand breaks the anchor
            obj.m1 = obj.m2 = None
    elif kind == "rdim":
        obj.cx += dx
        obj.cy += dy
        obj.px += dx
        obj.py += dy
    elif kind == "adim":
        obj.vx += dx
        obj.vy += dy
        obj.x1 += dx
        obj.y1 += dy
        obj.x2 += dx
        obj.y2 += dy
    elif kind in ("leader", "hatch"):
        obj.points = [[p[0] + dx, p[1] + dy] for p in obj.points]


MIN_DETAIL_MM = 5.0


def detail_corners(det) -> tuple:
    """The frame's four corners, anticlockwise from the bottom-left.

    A picked corner is named by its index here, so the order is part of the
    contract rather than a detail of how the grips get drawn.
    """
    return ((det.x, det.y), (det.x + det.w, det.y),
            (det.x + det.w, det.y + det.h), (det.x, det.y + det.h))


def nudge_detail_corners(det, indices, dx: float, dy: float):
    """Shift the named corners of a detail frame by paper millimetres.

    A corner is where two edges meet, so moving one on its own stretches the
    frame in both directions. Take the two corners of an edge and that edge
    travels; take all four and the whole detail does.
    """
    idx = set(indices)
    x0, y0 = det.x, det.y
    x1, y1 = det.x + det.w, det.y + det.h
    if idx & {0, 3}:
        x0 += dx
    if idx & {1, 2}:
        x1 += dx
    if idx & {0, 1}:
        y0 += dy
    if idx & {2, 3}:
        y1 += dy
    det.x, det.w = min(x0, x1), max(abs(x1 - x0), MIN_DETAIL_MM)
    det.y, det.h = min(y0, y1), max(abs(y1 - y0), MIN_DETAIL_MM)


def sheet_pools(layout) -> dict:
    """Where each kind of pickable thing on a sheet lives."""
    return {"note": layout.notes, "dim": layout.dims, "rdim": layout.rdims,
            "adim": layout.adims, "leader": layout.leaders,
            "hatch": layout.hatches, "object": layout.objects,
            "detail": layout.details}


def copy_sheet_item(layout, kind: str, obj):
    """Duplicate a sheet item onto a layout, and return the copy.

    Deep, and then given a fresh id. Deep because what the sheet holds is
    mostly plain data — a detail's target, a leader's points — and a copy
    sharing those would swing or drag both when either was touched. The id
    because it is the one field that must not be copied: a hidden-line cache,
    a saved file and a selection all tell two frames apart by it.

    The layout is where the copy goes, not where the original came from: a
    border copied on one sheet and a border pasted onto the next are the same
    act, and nothing about the original is needed to carry it out.

    The copy lands exactly on the original, since where it goes is the
    caller's question and not every kind moves the same way.
    """
    pool = sheet_pools(layout).get(kind)
    if pool is None:
        return None
    dup = copy.deepcopy(obj)
    dup.id = _uid()
    pool.append(dup)
    return dup


def delete_annotation(layout, kind: str, obj) -> bool:
    pool = {"note": layout.notes, "dim": layout.dims,
            "rdim": layout.rdims, "adim": layout.adims,
            "leader": layout.leaders, "hatch": layout.hatches}.get(kind)
    if pool and obj in pool:
        pool.remove(obj)
        return True
    return False


def annotation_bounds(kind: str, obj) -> tuple:
    """Rough paper-space bbox (x0, y0, x1, y1) of an annotation."""
    if kind == "note":
        lines = (obj.text or " ").split("\n")
        w = max(len(line) for line in lines) * obj.height * 0.62
        return (obj.x, obj.y - (len(lines) - 1) * obj.height * 1.6,
                obj.x + w, obj.y + obj.height)
    if kind == "dim":
        import numpy as np
        a = np.array([obj.x1, obj.y1])
        b = np.array([obj.x2, obj.y2])
        d = b - a
        n = np.linalg.norm(d)
        nvec = np.array([-d[1], d[0]]) / n if n > 1e-9 else np.zeros(2)
        pts = [a, b, a + nvec * obj.offset, b + nvec * obj.offset]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return (min(xs), min(ys), max(xs), max(ys))
    if kind == "rdim":
        return (min(obj.cx, obj.px), min(obj.cy, obj.py),
                max(obj.cx, obj.px), max(obj.cy, obj.py))
    if kind == "adim":
        r = obj.radius + 3
        return (obj.vx - r, obj.vy - r, obj.vx + r, obj.vy + r)
    pts = obj.points or [[0, 0]]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def enclosing_polygon(polylines: list, px: float, py: float):
    """Smallest closed polyline (paper coords) containing the point."""
    best = None
    best_area = None
    for poly in polylines:
        pts = [(p[0], p[1]) for p in poly]
        if len(pts) < 4:
            continue
        if abs(pts[0][0] - pts[-1][0]) > 0.5 \
                or abs(pts[0][1] - pts[-1][1]) > 0.5:
            continue
        if not _point_in_poly(px, py, pts[:-1]):
            continue
        area = 0.0
        for (x1, y1), (x2, y2) in zip(pts[:-1], pts[1:]):
            area += x1 * y2 - x2 * y1
        area = abs(area) / 2
        if best_area is None or area < best_area:
            best, best_area = pts[:-1], area
    return best


@dataclass
class Layout:
    id: str = field(default_factory=_uid)
    name: str = "Layout"
    paper_w: float = 420.0
    paper_h: float = 297.0
    margin: float = 10.0
    details: list = field(default_factory=list)
    objects: list = field(default_factory=list)      # PaperObject, paper mm
    notes: list = field(default_factory=list)
    dims: list = field(default_factory=list)
    leaders: list = field(default_factory=list)
    hatches: list = field(default_factory=list)
    rdims: list = field(default_factory=list)
    adims: list = field(default_factory=list)
    scale_bars: list = field(default_factory=list)   # [x, y, scale_denom]
    title_block: dict = field(default_factory=dict)
    revisions: list = field(default_factory=list)    # [[rev, date, note]]
    # per-kind name counters for `add`; not saved, because the names are, and
    # `add` skips past a name already on the sheet
    _counters: dict = field(default_factory=dict, repr=False, compare=False)

    def detail_at(self, px: float, py: float) -> DetailView | None:
        for d in reversed(self.details):        # topmost first
            if d.contains(px, py):
                return d
        return None

    def add(self, shape, name: str | None = None) -> PaperObject:
        """Put geometry on the paper, in millimetres.

        Named the way `Scene.add` names, from a counter rather than the length
        of the list, so a name is not handed out twice after a delete. The
        counter is not saved with the sheet, so it steps over the names that
        came back from a file.
        """
        from . import geometry
        kind = geometry.shape_kind(shape)
        if name is None:
            taken = {o.name for o in self.objects}
            n = self._counters.get(kind, 0)
            while True:
                n += 1
                name = f"{kind.capitalize()} {n:02d}"
                if name not in taken:
                    break
            self._counters[kind] = n
        obj = PaperObject(shape=shape, name=name)
        self.objects.append(obj)
        return obj

    def clone(self) -> "Layout":
        return copy.deepcopy(self)


# ------------------------------------------------------------- serialization

def _paper_object_to_json(obj) -> dict:
    """A paper shape as BREP text, the same way a model object is stored."""
    import base64

    from . import geometry
    return {
        "id": obj.id, "name": obj.name,
        "color": list(obj.color) if obj.color else None,
        "linetype": obj.linetype, "lineweight": obj.lineweight,
        "brep": base64.b64encode(
            geometry.shape_to_bytes(obj.shape)).decode("ascii"),
    }


def _paper_object_from_json(od: dict) -> PaperObject:
    import base64

    from . import geometry
    return PaperObject(
        id=od.get("id", _uid()), name=od.get("name", ""),
        color=tuple(od["color"]) if od.get("color") else None,
        linetype=od.get("linetype", "Continuous"),
        lineweight=float(od.get("lineweight", 0.25)),
        shape=geometry.shape_from_bytes(base64.b64decode(od["brep"])))


def layouts_to_json(layouts: list) -> list:
    out = []
    for lay in layouts:
        out.append({
            "id": lay.id, "name": lay.name,
            "paper_w": lay.paper_w, "paper_h": lay.paper_h,
            "margin": lay.margin,
            "details": [vars(d).copy() for d in lay.details],
            "objects": [_paper_object_to_json(o) for o in lay.objects],
            "notes": [vars(n).copy() for n in lay.notes],
            "dims": [vars(d).copy() for d in lay.dims],
            "leaders": [vars(x).copy() for x in lay.leaders],
            "hatches": [vars(x).copy() for x in lay.hatches],
            "rdims": [vars(x).copy() for x in lay.rdims],
            "adims": [vars(x).copy() for x in lay.adims],
            "scale_bars": [list(b) for b in lay.scale_bars],
            "title_block": dict(lay.title_block),
            "revisions": [list(r) for r in lay.revisions],
        })
    return out


def layouts_from_json(data: list) -> list:
    layouts = []
    for ld in data or []:
        lay = Layout(id=ld.get("id", _uid()), name=ld.get("name", "Layout"),
                     paper_w=ld.get("paper_w", 420.0),
                     paper_h=ld.get("paper_h", 297.0),
                     margin=ld.get("margin", 10.0))
        for dd in ld.get("details", []):
            lay.details.append(DetailView(**dd))
        for od in ld.get("objects", []):
            lay.objects.append(_paper_object_from_json(od))
        for nd in ld.get("notes", []):
            lay.notes.append(TextNote(**nd))
        for dd in ld.get("dims", []):
            lay.dims.append(LinearDim(**dd))
        for xd in ld.get("leaders", []):
            lay.leaders.append(Leader(**xd))
        for xd in ld.get("hatches", []):
            lay.hatches.append(Hatch(**xd))
        for xd in ld.get("rdims", []):
            lay.rdims.append(RadialDim(**xd))
        for xd in ld.get("adims", []):
            lay.adims.append(AngularDim(**xd))
        lay.scale_bars = [list(b) for b in ld.get("scale_bars", [])]
        lay.title_block = dict(ld.get("title_block", {}))
        lay.revisions = [list(r) for r in ld.get("revisions", [])]
        layouts.append(lay)
    return layouts


def parse_scale(text: str) -> float | None:
    """'1:50' -> 50, '2:1' -> 0.5, '50' -> 50."""
    text = text.strip().lower().replace(" ", "")
    if ":" in text:
        a, _, b = text.partition(":")
        try:
            a, b = float(a), float(b)
            if a <= 0 or b <= 0:
                return None
            return b / a
        except ValueError:
            return None
    try:
        v = float(text)
        return v if v > 0 else None
    except ValueError:
        return None
