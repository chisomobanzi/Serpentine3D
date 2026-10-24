"""Hatch patterns as families of lines, the way a .pat file has them (#92).

Every hatch pattern in the industry is the same thing written down a few
ways: some families of parallel lines, each at an angle, through an origin,
the next line of the family a step along and a step across from the last,
and drawn as a run of dashes, gaps and dots or whole. AutoCAD's .pat
files, a DXF HATCH's pattern and a Rhino file's hatch pattern table all
say exactly that, so one `HatchPattern` holds a pattern from any of them.

Lines, Cross and Solid are the app's own and are drawn as they always were.
A pattern from a file joins them in the drawing's own library, by name,
and is drawn by `pattern_segments` here.

A pattern's size is its spacing, as with Lines: the distance between the
rows of its closest family. A brick at a spacing of 2.5 mm has courses
2.5 mm high, whatever unit the file it came from was written in, and a
pattern changed from Lines to ANSI31 keeps the look it had.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

# The app's own fills, always there, in the order they are offered: one of
# each basic form, the way Rhino's defaults are, and none that is another
# turned or scaled. Lines, Cross and Solid keep the drawing they always
# had, which centres the lines on the region (LEGACY); the rest are drawn
# from their families like a pattern from a file.
BUILTIN_NAMES = ("lines", "cross", "solid", "dash", "dots", "plus",
                 "squares", "triangles", "brick")
LEGACY = ("lines", "cross", "solid")

# A dot in a dash run is drawn as a small circle this wide across, against
# the hatch's spacing, so a screen, a plot and a model hatch all have a
# round mark to show rather than a fleck of a line.
DOT_FRACTION = 0.1
DOT_SIDES = 12


class PatternError(ValueError):
    """A .pat file, or a pattern in one, that cannot be read."""


@dataclass(frozen=True)
class PatternLine:
    """One family of parallel lines.

    `angle` in degrees; `origin` the point the first line runs through;
    `offset` the step from one line to the next, measured along the line
    and across it, the way a .pat file's delta-x and delta-y are; `dashes`
    the run each line repeats, a dash positive, a gap negative and a dot
    0, or empty for a whole line.
    """
    angle: float
    origin: tuple = (0.0, 0.0)
    offset: tuple = (0.0, 1.0)
    dashes: tuple = ()

    def to_list(self) -> list:
        return [self.angle, list(self.origin), list(self.offset),
                list(self.dashes)]

    @classmethod
    def from_list(cls, data) -> "PatternLine":
        angle, origin, offset, *rest = data
        return cls(float(angle), _pair(origin), _pair(offset),
                   tuple(float(d) for d in (rest[0] if rest else ())))


@dataclass(frozen=True)
class HatchPattern:
    """A named pattern: its families of lines, or a solid fill."""
    name: str
    description: str = ""
    lines: tuple = field(default=())
    solid: bool = False

    @property
    def key(self) -> str:
        return self.name.lower()

    @property
    def row_spacing(self) -> float:
        """The distance between the rows of its closest family, in the
        pattern's own units: what a spacing of 1 scales it to."""
        rows = [abs(ln.offset[1]) for ln in self.lines
                if abs(ln.offset[1]) > 1e-12]
        return min(rows) if rows else 1.0

    def to_dict(self) -> dict:
        return {"name": self.name, "description": self.description,
                "solid": self.solid,
                "lines": [ln.to_list() for ln in self.lines]}

    @classmethod
    def from_dict(cls, data: dict) -> "HatchPattern":
        return cls(str(data["name"]), str(data.get("description", "")),
                   tuple(PatternLine.from_list(ln)
                         for ln in data.get("lines", ())),
                   bool(data.get("solid", False)))


BUILTIN = {
    "lines": HatchPattern("lines", "Parallel lines",
                          (PatternLine(0.0),)),
    "cross": HatchPattern("cross", "Lines both ways",
                          (PatternLine(0.0), PatternLine(90.0))),
    "solid": HatchPattern("solid", "Solid fill", solid=True),
    # a whole line, then a dashed one between
    "dash": HatchPattern("dash", "Lines and dashed lines between", (
        PatternLine(0.0, (0.0, 0.0), (0.0, 1.0)),
        PatternLine(0.0, (0.0, 0.5), (0.0, 1.0), (0.5, -0.5)))),
    "dots": HatchPattern("dots", "A grid of dots", (
        PatternLine(0.0, (0.0, 0.0), (0.0, 1.0), (0.0, -1.0)),)),
    "plus": HatchPattern("plus", "Plus signs", (
        PatternLine(0.0, (-0.125, 0.0), (0.0, 1.0), (0.25, -0.75)),
        PatternLine(90.0, (0.0, -0.125), (0.0, 1.0), (0.25, -0.75)))),
    "squares": HatchPattern("squares", "Steps of squares", (
        PatternLine(0.0, (0.0, 0.0), (0.0, 1.0), (1.0, -1.0)),
        PatternLine(90.0, (0.0, 0.0), (0.0, 1.0), (1.0, -1.0)))),
    "triangles": HatchPattern("triangles", "Lines three ways", (
        PatternLine(0.0), PatternLine(60.0), PatternLine(120.0))),
    "brick": HatchPattern("brick", "Running bond", (
        PatternLine(0.0, (0.0, 0.0), (0.0, 1.0)),
        PatternLine(90.0, (0.0, 0.0), (1.0, 1.0), (1.0, -1.0)))),
}


def is_builtin(name) -> bool:
    return str(name or "").strip().lower() in BUILTIN_NAMES


def is_legacy(name) -> bool:
    """Lines, Cross and Solid: drawn the way they always were, with no
    definition of their own to carry."""
    return str(name or "").strip().lower() in LEGACY


def same_pattern(a: HatchPattern, b: HatchPattern, tol: float = 1e-6) -> bool:
    """Whether two patterns draw the same at the same spacing: the same
    families, each measured in rows of its own pattern, so one written in
    inches and one in millimetres are the same pattern."""
    if a.solid or b.solid:
        return a.solid and b.solid
    if len(a.lines) != len(b.lines):
        return False

    def norm(p):
        r = p.row_spacing
        return sorted((round(ln.angle % 360.0, 6),
                       tuple(v / r for v in ln.origin),
                       tuple(v / r for v in ln.offset),
                       tuple(d / r for d in ln.dashes)) for ln in p.lines)

    for x, y in zip(norm(a), norm(b)):
        if x[0] != y[0] or len(x[3]) != len(y[3]):
            return False
        flat_x = (*x[1], *x[2], *x[3])
        flat_y = (*y[1], *y[2], *y[3])
        if any(abs(u - v) > tol for u, v in zip(flat_x, flat_y)):
            return False
    return True


def _pair(values) -> tuple:
    x, y = values
    return (float(x), float(y))


# --- .pat files -------------------------------------------------------------

def parse_pat(text: str) -> list:
    """Every pattern in the text of a .pat file, in the order written.

    A header is `*NAME, description`; each line after it, up to the next
    header, is `angle, x, y, delta-x, delta-y` and the dash run. Comments
    start with a semicolon, Revit's `;%TYPE=MODEL` among them, and blank
    lines are nothing. A header with no lines under it is SOLID, the one
    pattern acad.pat spells that way, and is a solid fill.
    """
    patterns = []
    name = None
    description = ""
    lines: list = []

    def close():
        if name is None:
            return
        solid = not lines
        if solid and name.lower() != "solid":
            raise PatternError(f"Pattern {name} has no lines")
        patterns.append(HatchPattern(name, description, tuple(lines), solid))

    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        if line.startswith("*"):
            close()
            head, _, desc = line[1:].partition(",")
            name, description, lines = head.strip(), desc.strip(), []
            if not name:
                raise PatternError(f"Line {number}: a pattern with no name")
            continue
        if name is None:
            raise PatternError(f"Line {number}: a line before any *NAME")
        try:
            values = [float(v) for v in line.split(",") if v.strip()]
        except ValueError:
            raise PatternError(f"Line {number}: not a list of numbers: "
                               f"{raw.strip()}") from None
        if len(values) < 5:
            raise PatternError(f"Line {number}: a pattern line needs an "
                               "angle, an origin and an offset")
        lines.append(PatternLine(values[0], (values[1], values[2]),
                                 (values[3], values[4]), tuple(values[5:])))
    close()
    return patterns


def read_pat(path: str) -> list:
    """The patterns in a .pat file on disk. Files written on Windows are
    as often in a code page as in UTF-8, and only names are ever outside
    ASCII, so whatever does not decode is let through as Latin-1."""
    with open(path, "rb") as fh:
        data = fh.read()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    return parse_pat(text)


def write_pat(patterns) -> str:
    """Patterns as the text of a .pat file, the way parse_pat reads them."""
    out = []
    for pattern in patterns:
        head = f"*{pattern.name}"
        if pattern.description:
            head += f", {pattern.description}"
        out.append(head)
        for ln in pattern.lines:
            values = [ln.angle, *ln.origin, *ln.offset, *ln.dashes]
            out.append(", ".join(f"{v:g}" for v in values))
    return "\n".join(out) + "\n"


# --- drawing ----------------------------------------------------------------

def segment_estimate(rings, pattern: HatchPattern, spacing: float) -> int:
    """About how many segments `pattern_segments` will hand back, cheaply,
    so a spacing too fine for the region can be refused before it is
    drawn rather than after."""
    pts = np.vstack([np.asarray(r, float) for r in rings if len(r)])
    span = float(np.ptp(pts, axis=0).max()) if len(pts) else 0.0
    scale = spacing / pattern.row_spacing
    total = 0.0
    for ln in pattern.lines:
        dy = abs(ln.offset[1]) * scale
        rows = span / dy if dy > 1e-12 else 1.0
        run = sum(abs(d) for d in ln.dashes) * scale
        # a dot is drawn as the sides of a small circle
        marks = sum(DOT_SIDES if d == 0 else 1 for d in ln.dashes if d >= 0)
        per_row = (span / run * max(1, marks) if run > 1e-12 else 1.0)
        total += rows * max(per_row, 1.0)
    return int(total)


def pattern_segments(rings, pattern: HatchPattern, angle: float,
                     spacing: float, limit: int | None = None) -> list:
    """The pattern's segments over a region, as [((x0,y0),(x1,y1)), ...].

    `rings` are the outside of the region and its holes, in the
    coordinates the segments come back in, filled even-odd as
    `hatch_region` fills them. The whole pattern is turned by `angle`
    degrees about the region's origin and scaled so its rows lie
    `spacing` apart. `limit` stops it early, for a drawing that would
    rather be incomplete than lock up.
    """
    rings = [np.asarray(r, float) for r in rings if len(r) >= 3]
    if not rings or pattern.solid or spacing <= 0:
        return []
    scale = float(spacing) / pattern.row_spacing
    turn = math.radians(angle)
    rot = np.array([[math.cos(turn), -math.sin(turn)],
                    [math.sin(turn), math.cos(turn)]])
    edges = np.concatenate([np.stack([r, np.roll(r, -1, axis=0)], axis=1)
                            for r in rings])
    out: list = []
    for ln in pattern.lines:
        origin = rot @ (np.asarray(ln.origin) * scale)
        _family(out, edges, ln, (float(origin[0]), float(origin[1])),
                angle, scale, limit)
        if limit is not None and len(out) >= limit:
            return out[:limit]
    return out


def _family(out, edges, ln, origin, angle, scale, limit):
    """One family's segments, appended to `out`."""
    phi = math.radians(ln.angle + angle)
    c, s = math.cos(phi), math.sin(phi)
    to_local = np.array([[c, s], [-s, c]])
    local = (edges - np.asarray(origin)) @ to_local.T          # (E, 2, 2)
    ya, yb = local[:, 0, 1], local[:, 1, 1]
    xa, xb = local[:, 0, 0], local[:, 1, 0]
    dx, dy = ln.offset[0] * scale, ln.offset[1] * scale
    lo, hi = float(min(ya.min(), yb.min())), float(max(ya.max(), yb.max()))
    if abs(dy) > 1e-12:
        step = abs(dy)
        rows = range(math.ceil(lo / step), math.floor(hi / step) + 1)
        shift = dx * (1 if dy > 0 else -1)
    else:
        rows, step, shift = range(0, 1), 0.0, 0.0
    run = [d * scale for d in ln.dashes]
    period = sum(abs(d) for d in run)
    pieces = _dash_pieces(run) if period > 1e-12 else None
    # Edges the family's lines run along. A line lying on one is the
    # boundary itself, which is drawn already; Rhino and AutoCAD leave it
    # out, and drawn twice it would only thicken the outline.
    tol = 1e-9 * max(hi - lo, float(np.ptp(local[:, :, 0])), 1.0)
    level = np.abs(ya - yb) <= tol
    along = (ya[level], np.minimum(xa, xb)[level], np.maximum(xa, xb)[level])
    for k in rows:
        y = k * step
        crosses = (ya > y) != (yb > y)
        if not crosses.any():
            continue
        t = (y - ya[crosses]) / (yb[crosses] - ya[crosses])
        xs = np.sort(xa[crosses] + t * (xb[crosses] - xa[crosses])).tolist()
        start = k * shift
        ox, oy = origin[0] - s * y, origin[1] + c * y
        on_edge = np.abs(along[0] - y) <= tol
        for i in range(0, len(xs) - 1, 2):
            a, b = xs[i], xs[i + 1]
            if on_edge.any():
                mid = (a + b) / 2
                if np.any((along[1][on_edge] <= mid + tol)
                          & (mid - tol <= along[2][on_edge])):
                    continue
            if pieces is None:
                spans = [(a, b)]
            else:
                spans = _dashes_between(a, b, start, period, pieces)
            for p, q in spans:
                out.append(((ox + c * p, oy + s * p),
                            (ox + c * q, oy + s * q)))
            if limit is not None and len(out) >= limit:
                return


def _dash_pieces(run) -> np.ndarray:
    """The inked parts of one period of a dash run, as (start, end) from
    the period's start: dashes as they are and dots where they fall, as
    pieces with no length."""
    pieces = []
    at = 0.0
    for d in run:
        if d >= 0:
            pieces.append((at, at + d))
        at += abs(d)
    return np.asarray(pieces, float).reshape(-1, 2)


def _dashes_between(a, b, start, period, pieces) -> list:
    """The dashes of a run repeating every `period` from `start`, clipped
    to [a, b]; a dot inside it comes back as a piece with no length."""
    first = math.floor((a - start) / period) - 1
    last = math.floor((b - start) / period) + 1
    bases = start + period * np.arange(first, last + 1)
    lo = (bases[:, None] + pieces[None, :, 0]).ravel()
    hi = (bases[:, None] + pieces[None, :, 1]).ravel()
    dots = (hi - lo <= 1e-12) & (lo > a) & (lo < b)
    lo, hi = np.maximum(lo, a), np.minimum(hi, b)
    keep = (hi > lo + 1e-12) | dots
    return list(zip(lo[keep].tolist(), hi[keep].tolist()))


def is_dot(segment) -> bool:
    """Whether a pattern segment is a dot: one with no length."""
    a, b = segment
    return a == b


def dot_ring(centre, radius: float) -> list:
    """A dot as the segments of a small circle round it, in the plane its
    centre is given in (two or three coordinates)."""
    c = np.asarray(centre, float)
    out = []
    for k in range(DOT_SIDES):
        t0 = 2 * math.pi * k / DOT_SIDES
        t1 = 2 * math.pi * (k + 1) / DOT_SIDES
        p = c.copy()
        q = c.copy()
        p[:2] += (radius * math.cos(t0), radius * math.sin(t0))
        q[:2] += (radius * math.cos(t1), radius * math.sin(t1))
        out.append((tuple(p.tolist()), tuple(q.tolist())))
    return out


# --- what the app draws -----------------------------------------------------

def fill_segments(rings, pattern: HatchPattern | None, name: str,
                  angle: float, spacing: float,
                  limit: int | None = None, dots: bool = False):
    """The segments a fill draws over a region, whatever it is called.

    Lines and Cross are drawn as they always were; the app's other
    patterns and those from the library are drawn family by family; a name
    this drawing has no pattern for draws Lines, which is what such a fill
    has always drawn. Solid and None draw no segments at all.

    A dot comes back as the sides of a small circle; with `dots` the
    segments come back with the dots apart, as (segments, [(centre,
    radius)]), for a painter that fills them: a circle a pixel or two
    across drawn as lines is a jumble of pixels, filled it is a dot.
    """
    from .layout import hatch_region
    key = str(name or "").lower()
    if key not in LEGACY and pattern is None:
        pattern = BUILTIN.get(key)
    if key in ("solid", "none") or (pattern is not None and pattern.solid):
        return ([], []) if dots else []
    if pattern is not None and key not in LEGACY:
        out, marks = [], []
        radius = DOT_FRACTION * spacing / 2
        for seg in pattern_segments(rings, pattern, angle, spacing, limit):
            if not is_dot(seg):
                out.append(seg)
            elif dots:
                marks.append((seg[0], radius))
            else:
                out.extend(dot_ring(seg[0], radius))
        return (out, marks) if dots else out
    out = list(hatch_region(rings, angle, spacing))
    if key == "cross":
        out.extend(hatch_region(rings, angle + 90.0, spacing))
    return (out, []) if dots else out


def dot_polygon(centre, radius: float) -> list:
    """A dot as the corners of the small circle to fill, in (x, y)."""
    return [(centre[0] + radius * math.cos(2 * math.pi * k / DOT_SIDES),
             centre[1] + radius * math.sin(2 * math.pi * k / DOT_SIDES))
            for k in range(DOT_SIDES)]


def import_name(pattern: HatchPattern, source: str = "") -> tuple:
    """(name, definition) a pattern from a file is drawn as here.

    One that draws the same as one of the app's own is that one: Rhino's
    Plus is Plus, any solid is Solid. One that only shares a name with one
    of them is kept apart as "BRICK (acad)" after its `source`, so a hatch
    from a file is drawn as that file drew it and a layer set to Brick
    keeps the app's.
    """
    if pattern.solid:
        return "solid", None
    for key in BUILTIN_NAMES:
        if key not in LEGACY and same_pattern(pattern, BUILTIN[key]):
            return key, BUILTIN[key]
    if is_builtin(pattern.name):
        name = f"{pattern.name} ({source or 'file'})"
        return name, HatchPattern(name, pattern.description, pattern.lines)
    return pattern.name, pattern


def merge_into(library: dict, patterns, source: str = "") -> dict:
    """Add patterns to a drawing's library, by name, case aside, and say
    what each is called in the drawing: {name in the file: name here}.

    Each is named as `import_name` says. One already in the library under
    its name is replaced, as loading a newer copy of the same file should.
    """
    named = {}
    for pattern in patterns:
        name, definition = import_name(pattern, source)
        named[pattern.name] = name
        if is_builtin(name):
            continue
        for key in [k for k in library if k.lower() == name.lower()]:
            del library[key]
        library[name] = definition
    return named


def definition_for(library: dict | None, name) -> HatchPattern | None:
    """The families a fill is drawn from: None for Lines, Cross and Solid,
    which draw themselves, and for a name there is no pattern by, which
    draws as Lines. A drawing's own pattern comes before an installed one
    of the same name: the drawing is drawn as it was saved."""
    if is_legacy(name):
        return None
    return resolve(library, name)


def resolve(library: dict | None, name) -> HatchPattern | None:
    """The pattern a name means: one of the app's own, the drawing's own,
    or one installed on this computer, in that order."""
    return lookup(library, name) or lookup(installed(), name)


# --- installed patterns -----------------------------------------------------
#
# Patterns loaded from a .pat file are installed, the way a font is: kept
# beside the settings and offered in every drawing from then on. A drawing
# saves the ones it uses, so it is drawn the same on a computer that never
# installed them.

_INSTALLED: tuple | None = None          # (path, mtime, {name: pattern})


def installed_path() -> str:
    import os
    from ..utils.config import CONFIG_PATH
    settings = os.environ.get("SERP3D_CONFIG", CONFIG_PATH)
    return os.path.join(os.path.dirname(settings), "hatch_patterns.json")


def installed() -> dict:
    """{name: HatchPattern} of every installed pattern; read once and again
    whenever the file changes."""
    import json
    import os
    global _INSTALLED
    path = installed_path()
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}
    if _INSTALLED is not None and _INSTALLED[:2] == (path, mtime):
        return _INSTALLED[2]
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        patterns = {}
        for entry in data.get("patterns", []):
            pattern = HatchPattern.from_dict(entry)
            patterns[pattern.name] = pattern
    except (OSError, ValueError, KeyError, TypeError):
        patterns = {}
    _INSTALLED = (path, mtime, patterns)
    return patterns


def _write_installed(patterns: dict):
    import json
    import os
    global _INSTALLED
    path = installed_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"patterns": [p.to_dict() for p in patterns.values()]},
                  fh, indent=1)
    os.replace(tmp, path)
    _INSTALLED = None


def install(patterns, source: str = "") -> dict:
    """Install patterns, as `merge_into` names them; says what each is
    called: {name in the file: name installed}."""
    library = dict(installed())
    named = merge_into(library, patterns, source)
    _write_installed(library)
    return named


def uninstall(name) -> bool:
    """Take an installed pattern off this computer. Says whether there was
    one by that name."""
    library = dict(installed())
    keys = [k for k in library if k.lower() == str(name).lower()]
    for key in keys:
        del library[key]
    if keys:
        _write_installed(library)
    return bool(keys)


def lookup(library: dict | None, name) -> HatchPattern | None:
    """The pattern a name means in a drawing: one of the app's own, one
    in its library, or None for a name it has no pattern for."""
    key = str(name or "").strip().lower()
    if key in BUILTIN:
        return BUILTIN[key]
    for pattern in (library or {}).values():
        if pattern.key == key:
            return pattern
    return None
