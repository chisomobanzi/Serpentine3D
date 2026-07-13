"""Paper-space layouts: sheets, detail views, and annotations.

Dimensions are millimetres of paper. A detail's scale is stored as the
denominator N of 1:N — one millimetre of paper shows N model units
(Serpentine3D treats one model unit as one millimetre for drafting).
"""

from __future__ import annotations

import copy
import math
import uuid
from dataclasses import dataclass, field

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


def detail_project(detail, model_pt) -> tuple[float, float]:
    """Model-space point -> paper mm through a detail's camera."""
    import numpy as np
    from ..ui.layout_view import detail_direction
    d, right, up = detail_direction(detail)
    rel = np.asarray(model_pt, float) - np.asarray(detail.target, float)
    u = float(np.dot(rel, right)) / detail.scale_denom
    v = float(np.dot(rel, up)) / detail.scale_denom
    return detail.x + detail.w / 2 + u, detail.y + detail.h / 2 + v


def detail_unproject(detail, px: float, py: float) -> list:
    """Paper mm -> model-space point on the detail's view plane."""
    import numpy as np
    from ..ui.layout_view import detail_direction
    d, right, up = detail_direction(detail)
    u = (px - detail.x - detail.w / 2) * detail.scale_denom
    v = (py - detail.y - detail.h / 2) * detail.scale_denom
    return [float(c) for c in
            np.asarray(detail.target, float) + right * u + up * v]


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
    notes: list = field(default_factory=list)
    dims: list = field(default_factory=list)
    leaders: list = field(default_factory=list)
    hatches: list = field(default_factory=list)
    rdims: list = field(default_factory=list)
    adims: list = field(default_factory=list)
    scale_bars: list = field(default_factory=list)   # [x, y, scale_denom]
    title_block: dict = field(default_factory=dict)
    revisions: list = field(default_factory=list)    # [[rev, date, note]]

    def detail_at(self, px: float, py: float) -> DetailView | None:
        for d in reversed(self.details):        # topmost first
            if d.contains(px, py):
                return d
        return None

    def clone(self) -> "Layout":
        return copy.deepcopy(self)


# ------------------------------------------------------------- serialization

def layouts_to_json(layouts: list) -> list:
    out = []
    for lay in layouts:
        out.append({
            "id": lay.id, "name": lay.name,
            "paper_w": lay.paper_w, "paper_h": lay.paper_h,
            "margin": lay.margin,
            "details": [vars(d).copy() for d in lay.details],
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
