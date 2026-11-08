"""Delaunay triangulation of points seen from above, for Hydra's Delaunay
Mesh: Bowyer-Watson on numpy, enough for some thousands of points without
pulling in a library for it."""

from __future__ import annotations

import numpy as np


class DelaunayError(ValueError):
    pass


def triangulate(xy) -> np.ndarray:
    """The Delaunay triangles of points in the plane, as rows of three
    indices into `xy`, each turning anticlockwise."""
    xy = np.asarray(xy, float)
    if len(xy) < 3:
        raise DelaunayError("A mesh needs at least three points")
    lo, hi = xy.min(axis=0), xy.max(axis=0)
    size = max(float((hi - lo).max()), 1e-9)
    middle = (lo + hi) / 2
    # a triangle round them all, far enough out to hold every circle
    far = size * 100.0
    corners = middle + np.array([[-far, -far], [far, -far], [0.0, far]])
    points = np.vstack([xy, corners])
    n = len(xy)
    tris = np.array([[n, n + 1, n + 2]], dtype=np.int64)
    centres, radii = _circles(points, tris)
    for i in range(n):
        p = points[i]
        inside = ((centres - p) ** 2).sum(axis=1) < radii * (1 + 1e-12)
        bad = tris[inside]
        tris, centres, radii = tris[~inside], centres[~inside], radii[~inside]
        # the edges of the hole the bad triangles leave: those only one of
        # them has
        edges = np.concatenate([bad[:, [0, 1]], bad[:, [1, 2]],
                                bad[:, [2, 0]]])
        keys = np.sort(edges, axis=1)
        _, first, counts = np.unique(keys, axis=0, return_index=True,
                                     return_counts=True)
        rim = edges[first[counts == 1]]
        new = np.column_stack([rim, np.full(len(rim), i)])
        c, r2 = _circles(points, new)
        ok = np.isfinite(r2)
        tris = np.concatenate([tris, new[ok]])
        centres = np.concatenate([centres, c[ok]])
        radii = np.concatenate([radii, r2[ok]])
    out = tris[(tris < n).all(axis=1)]
    if not len(out):
        raise DelaunayError("The points are all in a line")
    # anticlockwise from above, so the mesh faces up
    a, b, c = (xy[out[:, k]] for k in range(3))
    turn = ((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1])
            - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0]))
    flip = turn < 0
    out[flip] = out[flip][:, [0, 2, 1]]
    out = out[np.abs(turn) > 1e-12 * size * size]
    if not len(out):
        raise DelaunayError("The points are all in a line")
    return out


def _circles(points, tris):
    """Each triangle's circumcircle: its centre and squared radius, the
    radius infinite for three points in a line."""
    a, b, c = (points[tris[:, k]] for k in range(3))
    ax, ay, bx, by = a[:, 0], a[:, 1], b[:, 0], b[:, 1]
    cx, cy = c[:, 0], c[:, 1]
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    flat = np.abs(d) < 1e-18
    d = np.where(flat, 1.0, d)
    a2, b2, c2 = ax * ax + ay * ay, bx * bx + by * by, cx * cx + cy * cy
    ux = (a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / d
    uy = (a2 * (cx - bx) + b2 * (ax - cx) + c2 * (bx - ax)) / d
    centres = np.column_stack([ux, uy])
    radii = ((centres - a) ** 2).sum(axis=1)
    radii[flat] = np.inf
    return centres, radii


def unique_points(points, tolerance=1e-9) -> np.ndarray:
    """Points with any that stand on another, seen from above, left out."""
    pts = np.asarray(points, float)
    keys = np.round(pts[:, :2] / max(tolerance, 1e-15)).astype(np.int64)
    _, first = np.unique(keys, axis=0, return_index=True)
    return pts[np.sort(first)]


def inside_outline(xy, rim) -> np.ndarray:
    """Which points lie inside a closed outline given as its segments, seen
    from above: a ray to the right crosses it an odd number of times."""
    xy = np.asarray(xy, float)
    a, b = rim[:, 0], rim[:, 1]                     # (K, 2) each
    px, py = xy[:, 0][:, None], xy[:, 1][:, None]   # (N, 1)
    ay, by = a[:, 1][None, :], b[:, 1][None, :]
    ax, bx = a[:, 0][None, :], b[:, 0][None, :]
    spans = (ay > py) != (by > py)
    with np.errstate(divide="ignore", invalid="ignore"):
        cross = ax + (py - ay) * (bx - ax) / (by - ay)
    hits = spans & (px < cross)
    return hits.sum(axis=1) % 2 == 1
