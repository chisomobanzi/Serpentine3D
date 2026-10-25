"""Caps on model clipping planes: the face a plane leaves where it cuts a
solid, filled and hatched the way the solid's section is (#40).

A clipping plane used to leave a solid hollow. The shader drops whatever
is past the plane, and what had been inside the solid showed as the backs
of its own faces. A cap closes it, the way a section drawing closes a cut.

It is worked out on the GPU each frame, so it follows a plane being
dragged. For each live plane, and each look of cap: count on the stencil
how many solids each pixel of the plane lies inside, with only that plane
cutting, a solid's back faces adding one and its front faces taking one
away; then lay a sheet over the plane where the count is not zero, cut by
the other planes. Counting rather than flipping a bit keeps two touching
solids of one material from cancelling where they overlap.

Round each cap goes its cut line (#82), in the width and colour the
solid's section says. The stencil knows where a cap is but not where it
ends, so the line is worked out on the CPU instead: where the plane meets
the solid's triangles, kept until the plane or the solid changes.

The pure parts are here: which planes and which objects, the hatch's basis
on the plane, the look of a cap and its line, and how far apart its lines
fall. The viewport does the drawing with the programs below.
"""

from __future__ import annotations

import math
from typing import NamedTuple

import numpy as np

MAX_PLANES = 4                # what the shader clips with, and so caps

# How a cap fills, as the cap shader reads it. FAMILIES is a pattern from
# a .pat file (#92), drawn family by family from `CapStyle.families`.
PLAIN, LINES, CROSS, SOLID, FAMILIES = 0, 1, 2, 3, 4
_PATTERN_CODES = {"none": PLAIN, "lines": LINES, "cross": CROSS,
                  "solid": SOLID}
# What the shader has room for: the families of every pattern acad.pat
# ships but a few, and the dashes of any of their lines. A pattern with
# more is drawn with the first of them.
MAX_FAMILIES = 16
MAX_DASHES = 8

CUT_SHADE = 0.55              # a cap is a darker shade of its object...
POCHE_SHADE = 0.30            # ...and darker still poched in ink
INK_ON_SCREEN = (0.07, 0.07, 0.08)   # ink, as hatch lines on screen
LINE_ALPHA = 0.9
# A hatch spaced 2.5 mm on paper falls about 7.5 px apart on screen, so a
# layer's tighter or looser hatch keeps its character in the model too.
CAP_PX_PER_MM = 3.0


class CapPlane(NamedTuple):
    origin: tuple
    normal: tuple             # pointing at the half the plane takes away
    u: np.ndarray             # the hatch's x on the plane: level if it can be
    v: np.ndarray
    equation: np.ndarray      # the clip vec4 the shader dots with


class CapStyle(NamedTuple):
    pattern: int              # PLAIN, LINES, CROSS or SOLID
    fill: tuple               # (r, g, b) of the cap under any lines
    line: tuple               # (r, g, b, a); a == 0 draws no lines
    angle: float              # radians from the plane's u
    spacing_mm: float         # the layer's spacing on paper
    # FAMILIES only: per family (cos, sin, ox, oy, dx, dy, dashes), in
    # rows of the pattern, turned by the fill's angle
    families: tuple = ()


def plane_axes(normal) -> tuple:
    """Two unit axes in the plane, (u, v), right-handed seen from the cut
    side (u x v is the normal), with u level wherever the plane allows:
    on a wall's cut, u runs along the floor the way a section is read."""
    n = np.asarray(normal, float)
    n = n / np.linalg.norm(n)
    u = np.cross((0.0, 0.0, 1.0), n)
    if np.linalg.norm(u) < 1e-6:              # a level plane: x is x
        u = np.array([1.0, 0.0, 0.0]) - n * n[0]
    u = u / np.linalg.norm(u)
    return u, np.cross(n, u)


def cap_planes(frames) -> list:
    """The planes that cap: the live ones, in the order and number the
    viewport clips with, so plane i caps where clip i cuts."""
    from .viewport import clip_equation
    planes = []
    for origin, normal, on in frames:
        if not on:
            continue
        u, v = plane_axes(normal)
        planes.append(CapPlane(tuple(origin), tuple(normal), u, v,
                               clip_equation(origin, normal)))
        if len(planes) == MAX_PLANES:
            break
    return planes


def straddling(lows, highs, origin, normal) -> np.ndarray:
    """Which of many boxes a plane passes through, all at once: (N, 3)
    lows and highs in, a boolean per box out. Every frame asks this of
    every solid in view, so it is one sum over arrays rather than eight
    corners an object. A box's corners lie within its half-extent, read
    along the normal, of the distance to its middle; the plane passes
    through when that span has the plane strictly inside it. One that only
    touches a face cuts nothing away and caps nothing."""
    lows = np.asarray(lows, float).reshape(-1, 3)
    highs = np.asarray(highs, float).reshape(-1, 3)
    n = np.asarray(normal, float)
    middle = (lows + highs) / 2.0
    reach = np.abs(n) @ ((highs - lows) / 2.0).T
    across = (middle - np.asarray(origin, float)) @ n
    slack = 1e-9 * np.maximum(np.abs(across) + reach, 1e-9)
    return (across - reach < -slack) & (across + reach > slack)


def straddles(bounds, origin, normal) -> bool:
    """Whether a plane passes through one box, (low, high)."""
    low, high = bounds
    return bool(straddling([low], [high], origin, normal)[0])


def cap_style(fill, display_rgb) -> CapStyle:
    """How a cap through an object looks, from its section fill (pattern,
    angle, spacing, colour or None for ink) and the colour it shows in.

    On screen a cut has to read against the model's own faces, not against
    paper: the cap is a darker shade of the object, lines go over it in
    their colour, solid floods it in its colour or a darker poché, and
    None leaves it plain. None leaves a cut empty on paper, but in the
    model the solid still has to look solid.

    A background of its own (#91) takes the place of the shade under the
    lines, so a cut can read in the colour its drawing
    gives it rather than in whatever colour the object happens to be."""
    definition = getattr(fill, "definition", None)
    pattern = _PATTERN_CODES.get(fill.pattern, LINES)
    if definition is not None and fill.pattern.lower() not in _PATTERN_CODES:
        pattern = SOLID if definition.solid else FAMILIES
    shade = tuple(float(c) * CUT_SHADE for c in display_rgb[:3])
    if pattern == SOLID:
        flood = (tuple(float(c) for c in fill.color[:3]) if fill.color
                 else tuple(float(c) * POCHE_SHADE for c in display_rgb[:3]))
        return CapStyle(SOLID, flood, (0.0, 0.0, 0.0, 0.0), 0.0,
                        fill.spacing)
    if pattern == PLAIN:
        return CapStyle(PLAIN, shade, (0.0, 0.0, 0.0, 0.0), 0.0, fill.spacing)
    ink = (tuple(float(c) for c in fill.color[:3]) if fill.color
           else INK_ON_SCREEN)
    background = getattr(fill, "background", None)
    if background:
        shade = tuple(float(c) for c in background[:3])
    families = (pattern_families(definition, fill.angle)
                if pattern == FAMILIES else ())
    return CapStyle(pattern, shade, (*ink, LINE_ALPHA),
                    math.radians(fill.angle), fill.spacing, families)


def pattern_families(definition, angle: float) -> tuple:
    """A pattern's families as the cap shader takes them: each line's
    direction, origin and step in rows of the pattern, so one row is the
    hatch's spacing, the whole turned `angle` degrees."""
    row = definition.row_spacing
    t = math.radians(angle)
    c, s = math.cos(t), math.sin(t)
    out = []
    for ln in definition.lines[:MAX_FAMILIES]:
        phi = math.radians(ln.angle + angle)
        ox, oy = ln.origin[0] / row, ln.origin[1] / row
        out.append((math.cos(phi), math.sin(phi),
                    c * ox - s * oy, s * ox + c * oy,
                    ln.offset[0] / row, ln.offset[1] / row,
                    tuple(d / row for d in ln.dashes[:MAX_DASHES])))
    return tuple(out)


def family_uniforms(families) -> tuple:
    """(uFamA, uFamB, uDash) for the cap shader, as float32 arrays padded
    to the room it has: per family (cos, sin, ox, oy) and (dx, dy, run,
    dash count), then every family's dashes, MAX_DASHES apiece."""
    a = np.zeros((MAX_FAMILIES, 4), np.float32)
    b = np.zeros((MAX_FAMILIES, 4), np.float32)
    dash = np.zeros(MAX_FAMILIES * MAX_DASHES, np.float32)
    for i, (c, s, ox, oy, dx, dy, dashes) in enumerate(families):
        a[i] = (c, s, ox, oy)
        b[i] = (dx, dy, sum(abs(d) for d in dashes), len(dashes))
        dash[i * MAX_DASHES:i * MAX_DASHES + len(dashes)] = dashes
    return a, b, dash


def cut_line_style(fill, px_per_mm: float | None = None):
    """The line round a cap, as ((r, g, b, a), pixels), or None for a
    section with no cut line. Its width on the paper is drawn the way a
    layer's print width is on screen; ink is the ink its hatch draws in.

    On a sheet, where there is a millimetre to measure by (`px_per_mm`
    pixels to it), the line is its width on the paper, as a hidden-line
    detail draws it and as it prints (#94). Never under a pixel either way.
    """
    from ..core.layers import screen_width_for
    if fill.cut_line_width <= 0:
        return None
    rgb = (tuple(float(c) for c in fill.cut_line_color[:3])
           if fill.cut_line_color else INK_ON_SCREEN)
    width = (screen_width_for(fill.cut_line_width) if px_per_mm is None
             else max(1.0, round(fill.cut_line_width * px_per_mm, 2)))
    return (*rgb, 1.0), width


def plane_cut_segments(vertices, triangles, origin, normal) -> np.ndarray:
    """Where a plane meets a mesh's triangles, as (K, 2, 3) segments.

    Every triangle with corners both sides of the plane is crossed along
    two of its edges, and the two crossings are a segment of the cut. A
    corner lying on the plane counts as behind it, so each triangle has
    two crossings or none; one that only touches the plane at a corner
    has nothing to give and is left out, rather than drawn as a speck.
    """
    v = np.asarray(vertices, float).reshape(-1, 3)
    t = np.asarray(triangles).reshape(-1, 3)
    if not len(t) or not len(v):
        return np.zeros((0, 2, 3))
    d = (v - np.asarray(origin, float)) @ np.asarray(normal, float)
    ahead = d > 0
    # A dragged plane asks this of the whole mesh every frame, and almost
    # none of it is crossed: find the few that are before any arithmetic.
    first = ahead[t[:, 0]]
    t = t[(first != ahead[t[:, 1]]) | (first != ahead[t[:, 2]])]
    if not len(t):
        return np.zeros((0, 2, 3))
    sides = ahead[t]
    count = sides.sum(axis=1)
    # the corner on its own side of the plane, and the two across from it
    lone = np.where(count == 1, np.argmax(sides, axis=1),
                    np.argmin(sides, axis=1))
    rows = np.arange(len(t))
    a = t[rows, lone]
    b = t[rows, (lone + 1) % 3]
    c = t[rows, (lone + 2) % 3]

    def crossing(i, j):
        s = d[i] / (d[i] - d[j])
        return v[i] + s[:, None] * (v[j] - v[i])

    segs = np.stack([crossing(a, b), crossing(a, c)], axis=1)
    length = np.linalg.norm(segs[:, 1] - segs[:, 0], axis=1)
    return segs[length > 1e-12]


class CutLines:
    """Each solid's cut line under each plane, worked out once and kept
    while neither moves: a plane standing still in a scene that is being
    orbited asks the same question every frame. What a frame did not ask
    for is let go at its end, so a deleted solid or a plane dragged on is
    not held on to."""

    def __init__(self):
        self._kept: dict = {}
        self._used: dict = {}

    def segments(self, oid, mesh, plane: CapPlane) -> np.ndarray:
        key = (oid, tuple(plane.origin), tuple(plane.normal))
        hit = self._used.get(key) or self._kept.get(key)
        if hit is None or hit[0] is not mesh:
            # Cut in the mesh's own coordinates and move the answer out:
            # the plane is a point and a direction, the mesh is millions
            # of triangles, so the plane is the one that travels. A
            # dragged plane asks this of every solid it touches.
            here = np.asarray(plane.origin, float) - mesh.origin
            cut = plane_cut_segments(mesh.local, mesh.triangles,
                                     here, plane.normal)
            hit = (mesh, mesh.to_world(cut))
        self._used[key] = hit
        return hit[1]

    def end_frame(self):
        self._kept, self._used = self._used, {}


def group_by_style(items) -> list:
    """[(style, [ids])] for (id, style) pairs, in the order styles first
    come up: one stencil pass for every cap that looks the same."""
    groups: dict = {}
    for oid, style in items:
        groups.setdefault(style, []).append(oid)
    return list(groups.items())


def pixels_per_unit(mvp, point, direction, width_px, height_px) -> float:
    """How many pixels one model unit along `direction` takes up on screen
    at `point`. Zero where it cannot be read, behind the eye."""
    m = np.asarray(mvp, float)
    a = m @ np.array([*point, 1.0], float)
    b = m @ np.array([*(np.asarray(point, float)
                        + np.asarray(direction, float)), 1.0], float)
    if a[3] <= 1e-12 or b[3] <= 1e-12:
        return 0.0
    da = a[:2] / a[3]
    db = b[:2] / b[3]
    dx = (db[0] - da[0]) * width_px / 2.0
    dy = (db[1] - da[1]) * height_px / 2.0
    return float(math.hypot(dx, dy))


def hatch_period(spacing_mm: float, px_per_unit: float):
    """The distance between a cap's hatch lines, in model units: about
    CAP_PX_PER_MM pixels for each paper millimetre of the hatch's spacing,
    rounded to a power of two. The lines are fixed to the plane, so they
    keep still while the view turns, and a period that only ever doubles
    or halves keeps them from crawling while it zooms."""
    if px_per_unit <= 0 or spacing_mm <= 0:
        return None
    units = spacing_mm * CAP_PX_PER_MM / px_per_unit
    return float(2.0 ** round(math.log2(units)))


def cap_quad(extent: float) -> np.ndarray:
    """The sheet laid over a plane, as two triangles in (u, v, 0) about its
    origin, `extent` out each way; the stencil keeps only what is cut."""
    e = float(extent)
    return np.array([(-e, -e), (e, -e), (e, e), (-e, -e), (e, e), (-e, e)],
                    np.float32)


# The stencil pass: positions only, cut by one plane, nothing written to
# colour or depth. Its own program, so nothing the mesh shader grows later
# (a discard, say) can quietly stop it counting.
COUNT_VERT = """
#version 330 core
layout(location=0) in vec3 pos;
uniform mat4 uMVP;
uniform vec4 uClips[4];
uniform int uClipCount;
out float gl_ClipDistance[4];
void main() {
    gl_Position = uMVP * vec4(pos, 1.0);
    for (int i = 0; i < uClipCount; ++i)
        gl_ClipDistance[i] = dot(uClips[i], vec4(pos, 1.0));
}
"""

COUNT_FRAG = """
#version 330 core
out vec4 frag;
void main() { frag = vec4(0.0); }
"""

# The cap: a sheet on the plane, positions given as (u, v) about the
# plane's origin and placed by uOrigin, uU and uV, so a model far from the
# world's origin is still drawn in small float32 numbers.
CAP_VERT = """
#version 330 core
layout(location=0) in vec2 uv;
uniform mat4 uMVP;
uniform vec3 uU;
uniform vec3 uV;
uniform vec4 uClips[4];
uniform int uClipCount;
out vec2 vUV;
out float gl_ClipDistance[4];
void main() {
    vec3 pos = uU * uv.x + uV * uv.y;
    gl_Position = uMVP * vec4(pos, 1.0);
    for (int i = 0; i < uClipCount; ++i)
        gl_ClipDistance[i] = dot(uClips[i], vec4(pos, 1.0));
    vUV = uv;
}
"""

CAP_FRAG = """
#version 330 core
in vec2 vUV;
uniform vec3 uFill;
uniform vec4 uLine;
uniform int uPattern;
uniform float uPeriod;
uniform float uAngle;
uniform int uFamilyCount;
uniform vec4 uFamA[16];      // cos, sin, origin x, origin y
uniform vec4 uFamB[16];      // step along, step across, run, dash count
uniform float uDash[128];    // 8 a family
out vec4 frag;
float lines(float t) {
    float d = abs(fract(t / uPeriod + 0.5) - 0.5) * uPeriod;
    float w = max(fwidth(t), 1e-6);
    return 1.0 - smoothstep(0.25 * w, w, d);    // a hairline, smoothed
}
// One family of a .pat pattern, in rows of the pattern: the nearest of
// its lines, then whether that point of the line is inked.
float family(int i, vec2 p) {
    vec4 a = uFamA[i];
    vec4 b = uFamB[i];
    vec2 q = p - a.zw;
    float along = dot(q, a.xy);
    float across = dot(q, vec2(-a.y, a.x));
    float row = abs(b.y) > 1e-6 ? floor(across / b.y + 0.5) : 0.0;
    float off = across - row * b.y;
    float w = max(fwidth(across), 1e-6);
    float m = 1.0 - smoothstep(0.25 * w, w, abs(off));
    int n = int(b.w + 0.5);
    if (n > 0 && b.z > 1e-6) {
        float x = mod(along - row * b.x, b.z);
        float wa = max(fwidth(along), 1e-6);
        float at = 0.0;
        float ink = 0.0;
        for (int k = 0; k < 8; ++k) {
            if (k >= n) break;
            float d = uDash[i * 8 + k];
            if (d > 0.0 && x >= at && x <= at + d) ink = 1.0;
            if (d == 0.0 && (abs(x - at) < wa || abs(x - at - b.z) < wa))
                ink = 1.0;
            at += abs(d);
        }
        m *= ink;
    }
    return m;
}
void main() {
    vec3 col = uFill;
    if (uPattern == 1 || uPattern == 2) {
        float m = lines(dot(vUV, vec2(-sin(uAngle), cos(uAngle))));
        if (uPattern == 2)
            m = max(m, lines(dot(vUV, vec2(cos(uAngle), sin(uAngle)))));
        col = mix(col, uLine.rgb, m * uLine.a);
    } else if (uPattern == 4) {
        vec2 p = vUV / uPeriod;
        float m = 0.0;
        for (int i = 0; i < 16; ++i) {
            if (i >= uFamilyCount) break;
            m = max(m, family(i, p));
        }
        col = mix(col, uLine.rgb, m * uLine.a);
    }
    frag = vec4(col, 1.0);
}
"""
