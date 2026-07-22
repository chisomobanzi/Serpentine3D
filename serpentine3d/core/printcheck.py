"""3D-print readiness analysis on a tessellated mesh.

Reports the things a slicer cares about before you print: is the mesh
watertight (closed) and manifold, are there degenerate facets, how much of
the surface faces downward steeply enough to need supports, the thinnest
wall, and the overall print size. Pure geometry — no Qt, unit-testable.
"""

from __future__ import annotations

import math

import numpy as np

from .tessellate import tessellate


def analyze(shape, *, deflection: float | None = None,
            overhang_deg: float = 45.0, wall_threshold: float = 1.0) -> dict:
    """Tessellate `shape` (or accept a MeshShape) and return a report dict.

    For a B-rep solid, watertight/manifold come from the *topology* — a solid
    is a closed volume by construction, so we don't let harmless tessellation
    artifacts (degenerate facets at fillet poles, etc.) raise false alarms.
    Only an imported MeshShape is judged by its raw triangle connectivity.
    """
    from . import geometry as g
    mesh = tessellate(shape, deflection)
    r = analyze_mesh(mesh.vertices, mesh.triangles,
                     overhang_deg=overhang_deg, wall_threshold=wall_threshold)
    kind = g.shape_kind(shape)
    if kind == "mesh":
        r["brep_valid"] = None
        return r                                 # trust the mesh connectivity

    closed = kind == "solid"                     # a solid is a closed shell
    valid = bool(g.is_valid(shape))
    r["watertight"] = closed
    r["manifold"] = closed
    if closed:
        r["open_edges"] = 0
        r["nonmanifold_edges"] = 0
    r["degenerate"] = 0                          # tessellation-only artifact
    r["brep_valid"] = valid
    r["ok"] = bool(closed and valid)
    return r


def analyze_mesh(vertices, triangles, *, overhang_deg: float = 45.0,
                 wall_threshold: float = 1.0) -> dict:
    v = np.asarray(vertices, np.float64)
    t = np.asarray(triangles, np.int64)
    v, t = _weld(v, t)                       # share per-face duplicate verts

    open_edges, nonmanifold = _edge_health(t)
    degenerate = _degenerate(v, t)
    overhang = _overhang_fraction(v, t, overhang_deg)
    min_wall = _min_wall(v, t)
    size = ((v.max(axis=0) - v.min(axis=0)).tolist()
            if len(v) else [0.0, 0.0, 0.0])

    ok = (open_edges == 0 and nonmanifold == 0 and degenerate == 0)
    return {
        "vertices": int(len(v)),
        "triangles": int(len(t)),
        "watertight": open_edges == 0,
        "open_edges": int(open_edges),
        "manifold": nonmanifold == 0,
        "nonmanifold_edges": int(nonmanifold),
        "degenerate": int(degenerate),
        "overhang_fraction": float(overhang),
        "overhang_deg": float(overhang_deg),
        "min_wall": min_wall,
        "wall_threshold": float(wall_threshold),
        "thin": min_wall is not None and min_wall < wall_threshold,
        "size": size,
        "ok": bool(ok),
    }


# --------------------------------------------------------------------- helpers

def _weld(v, t):
    if not len(v):
        return v, t
    key = np.round(v, 5)
    uniq, inv = np.unique(key, axis=0, return_inverse=True)
    return uniq, inv[t]


def _edge_health(t):
    """A closed manifold surface shares every undirected edge by exactly two
    triangles: count-1 edges are holes, count>2 edges are non-manifold."""
    if not len(t):
        return 0, 0
    e = np.sort(np.vstack([t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]]), axis=1)
    _, counts = np.unique(e, axis=0, return_counts=True)
    return int((counts == 1).sum()), int((counts > 2).sum())


def _degenerate(v, t):
    if not len(t):
        return 0
    n = np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]])
    return int((np.linalg.norm(n, axis=1) < 1e-12).sum())


def _overhang_fraction(v, t, deg):
    """Fraction of surface area whose outward normal faces downward more
    steeply than `deg` from vertical (Z-up build) — i.e. would want supports.
    A face `deg` from vertical has n_z = -sin(deg); steeper is more negative.
    Faces resting on the build plate (the model's lowest slab) are excluded —
    they sit on the bed, not in mid-air, so they need no support."""
    if not len(t):
        return 0.0
    n = np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]])
    ln = np.linalg.norm(n, axis=1)
    area = 0.5 * ln
    total = area.sum()
    if total <= 0:
        return 0.0
    nz = np.divide(n[:, 2], ln, out=np.zeros(len(n)), where=ln > 0)
    cz = v[t, 2].mean(axis=1)                        # per-triangle centroid z
    zmin, zmax = v[:, 2].min(), v[:, 2].max()
    on_bed = cz <= zmin + 1e-3 * max(zmax - zmin, 1e-9)
    mask = (nz < -math.sin(math.radians(deg))) & ~on_bed
    return float(area[mask].sum() / total)


def _min_wall(v, t):
    """Thinnest wall, by casting a ray from each face inward along -normal and
    taking the nearest opposite face. Sampled to at most 600 faces. Returns
    None when nothing is hit (e.g. an open surface)."""
    if len(t) < 4:
        return None
    a, b, c = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
    fn = np.cross(b - a, c - a)
    ln = np.linalg.norm(fn, axis=1, keepdims=True)
    n = np.divide(fn, ln, out=np.zeros_like(fn), where=ln > 0)
    cen = (a + b + c) / 3.0
    diag = float(np.linalg.norm(v.max(axis=0) - v.min(axis=0)))
    eps = max(1e-6, 1e-5 * diag)

    m = len(t)
    idx = (np.arange(m) if m <= 600
           else np.unique(np.linspace(0, m - 1, 600).astype(int)))
    best = math.inf
    for i in idx:
        d = _ray_faces(cen[i] - n[i] * eps, -n[i], a, b, c, eps)
        if d < best:
            best = d
    return None if math.isinf(best) else float(best + eps)


def _ray_faces(orig, direction, a, b, c, eps):
    """Nearest positive ray/triangle hit distance (Möller–Trumbore), or inf."""
    e1, e2 = b - a, c - a
    p = np.cross(direction, e2)
    det = (e1 * p).sum(axis=1)
    ok = np.abs(det) > 1e-12
    inv = np.divide(1.0, det, out=np.zeros_like(det), where=ok)
    tv = orig - a
    u = (tv * p).sum(axis=1) * inv
    q = np.cross(tv, e1)
    w = (direction * q).sum(axis=1) * inv
    dist = (e2 * q).sum(axis=1) * inv
    hit = ok & (u >= -1e-6) & (w >= -1e-6) & (u + w <= 1 + 1e-6) & (dist > eps)
    if not hit.any():
        return math.inf
    return float(dist[hit].min())
