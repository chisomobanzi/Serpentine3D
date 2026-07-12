"""Small numpy 3D-math helpers for the viewport (column-major GL matrices)."""

from __future__ import annotations

import math

import numpy as np


def normalize(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v


def perspective(fov_y_deg: float, aspect: float, near: float,
                far: float) -> np.ndarray:
    f = 1.0 / math.tan(math.radians(fov_y_deg) / 2.0)
    m = np.zeros((4, 4), np.float32)
    m[0, 0] = f / max(aspect, 1e-6)
    m[1, 1] = f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = (2 * far * near) / (near - far)
    m[3, 2] = -1.0
    return m


def ortho(left: float, right: float, bottom: float, top: float,
          near: float, far: float) -> np.ndarray:
    m = np.eye(4, dtype=np.float32)
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
    m = np.eye(4, dtype=np.float32)
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


def ray_plane(origin: np.ndarray, direction: np.ndarray,
              plane_point: np.ndarray, plane_normal: np.ndarray):
    denom = np.dot(direction, plane_normal)
    if abs(denom) < 1e-9:
        return None
    t = np.dot(plane_point - origin, plane_normal) / denom
    if t < 0:
        return None
    return origin + t * direction
