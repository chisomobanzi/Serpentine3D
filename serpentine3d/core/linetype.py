"""Linetypes (dash patterns) — Rhino-style, defined in model units.

A pattern is a list of segment lengths in document units; it alternates
dash / gap / dash / gap, starting with a dash. `Continuous` is the empty
pattern (a solid line). Objects default to "ByLayer" and layers to
"Continuous", exactly like Rhino.

Dashing is done on the CPU — `dash_polyline` walks a polyline by arc length
and returns only the drawn segments — so it reuses the normal line renderer
and works identically on screen and in vector export.
"""

from __future__ import annotations

import numpy as np

# name -> [dash, gap, dash, gap, ...] lengths in document units (mm-ish)
LINETYPES: dict[str, list[float]] = {
    "Continuous": [],
    "Dashed": [6.0, 4.0],
    "Dotted": [0.4, 3.0],
    "DashDot": [8.0, 3.0, 0.4, 3.0],
    "Center": [15.0, 4.0, 4.0, 4.0],
    "Hidden": [4.0, 3.0],
    "Border": [8.0, 3.0, 8.0, 3.0, 0.4, 3.0],
    "Phantom": [15.0, 4.0, 4.0, 4.0, 4.0, 4.0],
}


def pattern_for(name: str) -> list[float]:
    return LINETYPES.get(name or "Continuous", [])


def resolve(obj_linetype: str | None, layer_linetype: str) -> str:
    """Effective linetype: an object's own type, or its layer's when the
    object is 'ByLayer' (the default)."""
    if obj_linetype in (None, "", "ByLayer"):
        return layer_linetype or "Continuous"
    return obj_linetype


def dash_polyline(points, pattern, scale: float = 1.0):
    """Split a polyline (list of 3D points) into the drawn dash segments for
    `pattern`. Returns a list of (p0, p1) point pairs. A solid/empty pattern
    passes the polyline through as its raw segments."""
    pts = np.asarray(points, float)
    if len(pts) < 2:
        return []
    pat = [max(float(x), 0.0) * scale for x in (pattern or [])]
    period = sum(pat)
    if period <= 0:
        return [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]

    segs = []
    d = 0.0                                     # global arc length so far
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        seg_len = float(np.linalg.norm(b - a))
        if seg_len <= 1e-12:
            continue
        direction = (b - a) / seg_len
        s = 0.0
        while s < seg_len - 1e-9:
            idx, elem_start, on = _element_at(pat, period, d + s)
            remain = pat[idx] - ((d + s - elem_start) % period)
            step = min(remain, seg_len - s)
            if step <= 1e-9:                    # zero-length element (a dot gap)
                s += 1e-6
                continue
            if on:
                segs.append((a + direction * s, a + direction * (s + step)))
            s += step
        d += seg_len
    return segs


def _element_at(pat, period, dist):
    """(index, element_start_distance, is_dash) for the pattern element the
    running distance `dist` falls in."""
    phase = dist % period
    acc = 0.0
    for i, length in enumerate(pat):
        if phase < acc + length:
            return i, dist - (phase - acc), (i % 2 == 0)
        acc += length
    last = len(pat) - 1
    return last, dist - (phase - (acc - pat[last])), (last % 2 == 0)
