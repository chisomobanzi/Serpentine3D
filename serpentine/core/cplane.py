"""Construction plane: the plane you draw on.

Picking rays intersect it, the grid is drawn on it, and drawing commands
use its normal/basis instead of assuming world XY.
"""

from __future__ import annotations

import numpy as np


class CPlane:
    def __init__(self, origin=(0, 0, 0), normal=(0, 0, 1), xdir=(1, 0, 0),
                 name: str = "World Top"):
        self.name = name
        self.origin = np.asarray(origin, float)
        n = np.asarray(normal, float)
        self.normal = n / np.linalg.norm(n)
        x = np.asarray(xdir, float)
        x = x - np.dot(x, self.normal) * self.normal
        if np.linalg.norm(x) < 1e-9:
            # pick any direction perpendicular to the normal
            ref = np.array([1.0, 0, 0])
            if abs(np.dot(ref, self.normal)) > 0.9:
                ref = np.array([0, 1.0, 0])
            x = ref - np.dot(ref, self.normal) * self.normal
        self.xdir = x / np.linalg.norm(x)
        self.ydir = np.cross(self.normal, self.xdir)

    # -- coordinate mapping --

    def to_world(self, u: float, v: float, w: float = 0.0) -> tuple:
        p = (self.origin + u * self.xdir + v * self.ydir + w * self.normal)
        return (float(p[0]), float(p[1]), float(p[2]))

    def from_world(self, pt) -> tuple:
        d = np.asarray(pt, float) - self.origin
        return (float(np.dot(d, self.xdir)), float(np.dot(d, self.ydir)),
                float(np.dot(d, self.normal)))

    def snap_to_grid(self, pt, step: float) -> tuple:
        u, v, w = self.from_world(pt)
        return self.to_world(round(u / step) * step,
                             round(v / step) * step, w)

    def basis_matrix(self) -> np.ndarray:
        """4x4 model matrix mapping plane-local coords to world."""
        m = np.eye(4, dtype=np.float32)
        m[:3, 0] = self.xdir
        m[:3, 1] = self.ydir
        m[:3, 2] = self.normal
        m[:3, 3] = self.origin
        return m

    def is_world_xy(self) -> bool:
        return (np.allclose(self.origin, 0) and
                np.allclose(self.normal, (0, 0, 1)) and
                np.allclose(self.xdir, (1, 0, 0)))


PRESETS = {
    "world": lambda: CPlane(),
    "top": lambda: CPlane(),
    "front": lambda: CPlane(normal=(0, -1, 0), xdir=(1, 0, 0),
                            name="World Front"),
    "back": lambda: CPlane(normal=(0, 1, 0), xdir=(-1, 0, 0),
                           name="World Back"),
    "right": lambda: CPlane(normal=(1, 0, 0), xdir=(0, 1, 0),
                            name="World Right"),
    "left": lambda: CPlane(normal=(-1, 0, 0), xdir=(0, -1, 0),
                           name="World Left"),
}


def from_three_points(origin, x_point, y_point) -> CPlane:
    o = np.asarray(origin, float)
    x = np.asarray(x_point, float) - o
    if np.linalg.norm(x) < 1e-9:
        raise ValueError("X-axis point coincides with the origin")
    y_hint = np.asarray(y_point, float) - o
    n = np.cross(x, y_hint)
    if np.linalg.norm(n) < 1e-9:
        raise ValueError("The three points are collinear")
    return CPlane(origin=o, normal=n, xdir=x, name="Custom")
