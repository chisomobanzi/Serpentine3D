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
        # float64: a plane out at survey coordinates would otherwise have
        # its origin rounded to float32's 3cm grid at birth, before the
        # viewport's own float64 fold could do anything about it.
        m = np.eye(4)
        m[:3, 0] = self.xdir
        m[:3, 1] = self.ydir
        m[:3, 2] = self.normal
        m[:3, 3] = self.origin
        return m

    def is_world_xy(self) -> bool:
        return (np.allclose(self.origin, 0) and
                np.allclose(self.normal, (0, 0, 1)) and
                np.allclose(self.xdir, (1, 0, 0)))


def face_outline(vertices, triangles) -> np.ndarray:
    """The (K, 2, 3) boundary of a patch: the edges only one triangle has."""
    ends = np.sort(triangles[:, [[0, 1], [1, 2], [2, 0]]].reshape(-1, 2),
                   axis=1)
    edges, counts = np.unique(ends, axis=0, return_counts=True)
    return vertices[edges[counts == 1]]


def on_face(vertices, triangles, toward, like: CPlane):
    """(plane, outline) for a flat patch of triangles; None if it is not flat.

    The normal comes out on the `toward` side, so a height drawn up from the
    face leaves it on the side you are looking at. The axes are taken from
    `like` so the plane reads the way the one you were on did: up stays up on
    a wall, and a roof keeps its X. Then they are squared to the face's
    longest straight edge, because a rectangle drawn on a turned box should
    lie along that box and not along the world.
    """
    a, b, c = (vertices[triangles[:, i]] for i in range(3))
    areas = np.cross(b - a, c - a)
    sizes = np.linalg.norm(areas, axis=1)
    keep = sizes > 1e-12
    total = areas[keep].sum(axis=0)
    length = np.linalg.norm(total)
    if length < 1e-12:
        return None
    normal = total / length
    if (areas[keep] / sizes[keep, None] @ normal).min() < 1.0 - 1e-4:
        return None
    centre = (sizes[keep, None] * (a + b + c)[keep]).sum(axis=0)
    origin = centre / (3.0 * sizes[keep].sum())
    if np.dot(normal, toward) < 0:
        normal = -normal

    if abs(np.dot(normal, like.normal)) > 0.9:
        want = like.xdir - np.dot(like.xdir, normal) * normal
    else:
        up = like.normal - np.dot(like.normal, normal) * normal
        want = np.cross(up, normal)
    want = want / np.linalg.norm(want)

    outline = face_outline(vertices, triangles)
    spans = outline[:, 1] - outline[:, 0]
    lengths = np.linalg.norm(spans, axis=1)
    longest = int(np.argmax(lengths))
    # A curve's outline is all short chords, and the longest of them is a
    # direction nobody chose: only a side of the shape is worth squaring to.
    if lengths[longest] > lengths.sum() / 8.0:
        along = spans[longest] / lengths[longest]
        across = np.cross(normal, along)
        want = max((along, -along, across, -across),
                   key=lambda axis: float(np.dot(axis, want)))
    return CPlane(origin, normal, want, name="Face"), outline


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
