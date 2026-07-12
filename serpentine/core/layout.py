"""Paper-space layouts: sheets, detail views, and annotations.

Dimensions are millimetres of paper. A detail's scale is stored as the
denominator N of 1:N — one millimetre of paper shows N model units
(Serpentine treats one model unit as one millimetre for drafting).
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
    text: str = ""
    height: float = 4.0        # mm


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


@dataclass
class Leader:
    id: str = field(default_factory=_uid)
    points: list = field(default_factory=list)   # [[x,y], ...] arrow at [0]
    text: str = ""
    height: float = 3.5


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
