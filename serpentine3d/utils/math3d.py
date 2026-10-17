"""Small numpy 3D-math helpers for the viewport (column-major GL matrices).

Matrices are built and returned in float64. The world-to-eye translation
in look_at is the difference of two coordinates that can both be hundreds
of thousands of units, and a float32 container rounds it to a 3cm grid
out there, which is what used to make far geometry swim. Whoever hands a
matrix to the GPU casts it to float32 at the last moment, after any
anchor has been folded in (see ui.viewport.anchored).
"""

from __future__ import annotations

import math

import numpy as np


# How far from the origin float32 stops being a fine enough grid to hold a
# coordinate on: at 100,000 units it steps 8mm, at a million 6cm. Data past
# this keeps its doubles all the way to the GPU upload, where the viewport
# subtracts an anchor near it and the cast to float32 loses nothing. Inside
# it float32 is good to a fraction of a micron and costs half the memory,
# which on a scanned survey is most of the file.
ANCHOR_NEAR = 4096.0


def display_coords(points) -> np.ndarray:
    """Coordinates for display, in the narrowest precision that holds them.

    An anchor can only recover digits the data still has, so a tessellation
    that casts to float32 on the way out of the kernel has already thrown
    away what the anchor was for: a 5mm detail of a building at survey
    coordinates lands on the same grid point as its neighbour and the two
    faces fight over every pixel. The test is on the coordinates themselves
    rather than on where their middle is: a mesh centred near home can
    still reach a long way out, and the far end is the end that suffers.
    """
    arr = np.asarray(points, np.float64)
    if arr.size and float(np.abs(arr).max()) > ANCHOR_NEAR:
        return np.ascontiguousarray(arr)
    return np.ascontiguousarray(arr, np.float32)


# How many points are rebased at a time. The subtraction needs float64 to
# be worth doing, and a scan does not fit in memory twice.
_CHUNK = 1 << 20


def origin_for(points) -> np.ndarray | None:
    """Where this far-out data should keep its coordinates relative to, or
    None for data near enough home to hold its own.

    The middle of the bounding box rather than the mean, which would lean
    towards whichever end of a scan was sampled hardest.
    """
    if not len(points):
        return None
    lo = np.asarray(points.min(axis=0), np.float64)
    hi = np.asarray(points.max(axis=0), np.float64)
    if max(np.abs(lo).max(), np.abs(hi).max()) <= ANCHOR_NEAR:
        return None
    return (lo + hi) * 0.5


def offsets_from(points, origin) -> np.ndarray:
    """`points` as float32 offsets from `origin`, a chunk at a time.

    float32 holds an offset of a few hundred units to a fraction of a
    micron, so this is what a file or a buffer stores for data whose
    absolute coordinates it could not hold at all.
    """
    out = np.empty((len(points), 3), np.float32)
    for i in range(0, len(points), _CHUNK):
        block = points[i:i + _CHUNK]
        out[i:i + len(block)] = np.asarray(block, np.float64) - origin
    return out


def normalize(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v


def perspective(fov_y_deg: float, aspect: float, near: float,
                far: float) -> np.ndarray:
    f = 1.0 / math.tan(math.radians(fov_y_deg) / 2.0)
    m = np.zeros((4, 4))
    m[0, 0] = f / max(aspect, 1e-6)
    m[1, 1] = f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = (2 * far * near) / (near - far)
    m[3, 2] = -1.0
    return m


def ortho(left: float, right: float, bottom: float, top: float,
          near: float, far: float) -> np.ndarray:
    m = np.eye(4)
    m[0, 0] = 2.0 / (right - left)
    m[1, 1] = 2.0 / (top - bottom)
    m[2, 2] = -2.0 / (far - near)
    m[0, 3] = -(right + left) / (right - left)
    m[1, 3] = -(top + bottom) / (top - bottom)
    m[2, 3] = -(far + near) / (far - near)
    return m


def look_at(eye: np.ndarray, target: np.ndarray, up: np.ndarray) -> np.ndarray:
    f = normalize(target - eye)
    s = normalize(np.cross(f, up))
    u = np.cross(s, f)
    m = np.eye(4)
    m[0, :3] = s
    m[1, :3] = u
    m[2, :3] = -f
    m[0, 3] = -np.dot(s, eye)
    m[1, 3] = -np.dot(u, eye)
    m[2, 3] = np.dot(f, eye)
    return m


def ray_triangle_hits(origin: np.ndarray, direction: np.ndarray,
                      v0: np.ndarray, v1: np.ndarray,
                      v2: np.ndarray) -> np.ndarray:
    """Vectorized Moller-Trumbore. Returns array of t (np.inf where no hit)."""
    eps = 1e-9
    e1 = v1 - v0
    e2 = v2 - v0
    h = np.cross(direction, e2)
    a = np.einsum("ij,ij->i", e1, h)
    t_out = np.full(len(v0), np.inf)
    mask = np.abs(a) > eps
    if not mask.any():
        return t_out
    f = np.zeros_like(a)
    f[mask] = 1.0 / a[mask]
    s = origin - v0
    u = f * np.einsum("ij,ij->i", s, h)
    q = np.cross(s, e1)
    v = f * np.einsum("j,ij->i", direction, q)
    t = f * np.einsum("ij,ij->i", e2, q)
    ok = mask & (u >= -eps) & (v >= -eps) & (u + v <= 1 + eps) & (t > eps)
    t_out[ok] = t[ok]
    return t_out


def ray_line_parameter(origin: np.ndarray, direction: np.ndarray,
                       line_point: np.ndarray,
                       line_dir: np.ndarray) -> float | None:
    """Parameter t on the line (point + t*dir) closest to the ray.

    None when the ray and line are (nearly) parallel."""
    d = normalize(direction)
    u = normalize(line_dir)
    w = origin - line_point
    b = float(np.dot(d, u))
    denom = 1.0 - b * b
    if abs(denom) < 1e-9:
        return None
    d0 = float(np.dot(d, w))
    e = float(np.dot(u, w))
    return (e - b * d0) / denom


def ray_plane_any(origin: np.ndarray, direction: np.ndarray,
                  plane_point: np.ndarray, plane_normal: np.ndarray):
    """Ray-plane intersection allowing hits behind the origin (for
    manipulation planes that may face away)."""
    denom = np.dot(direction, plane_normal)
    if abs(denom) < 1e-9:
        return None
    t = np.dot(plane_point - origin, plane_normal) / denom
    return origin + t * direction


def ray_plane(origin: np.ndarray, direction: np.ndarray,
              plane_point: np.ndarray, plane_normal: np.ndarray):
    denom = np.dot(direction, plane_normal)
    if abs(denom) < 1e-9:
        return None
    t = np.dot(plane_point - origin, plane_normal) / denom
    if t < 0:
        return None
    return origin + t * direction
