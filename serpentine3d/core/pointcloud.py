"""Native point-cloud objects: a scan as points, without OCCT.

A PointCloudShape stands in for a TopoDS_Shape in the scene the way a
MeshShape does. A scanner hands over millions of points and no surfaces,
and asking the kernel to hold them as vertices would be both slow and
wrong: nothing is being modelled with them yet. They are shown, selected,
measured against, saved and reloaded. Everything else (snapping to them,
cropping, meshing) comes later.

The arrays are exactly the ones the .serp v3 container carries
(protocol/SERP-SESSION-RECORD.md): xyz float32, rgb uint8, conf float32,
level uint8. Keeping them in their file types means a save writes the
bytes it read, not a copy in another precision.
"""

from __future__ import annotations

import numpy as np

# The coarse-to-fine levels a scan comes in: 0 is the 10 cm pass, 2 the
# 1 cm one. A reader on weak hardware draws every point with level <= L.
MAX_LEVEL = 2


class PointCloudShape:
    """Immutable point cloud. Transform methods return new instances."""

    __slots__ = ("xyz", "rgb", "conf", "level", "provenance")

    def __init__(self, xyz, rgb=None, conf=None, level=None,
                 provenance: dict | None = None):
        self.xyz = np.ascontiguousarray(xyz, np.float32).reshape(-1, 3)
        n = len(self.xyz)
        self.rgb = None if rgb is None else \
            np.ascontiguousarray(rgb, np.uint8).reshape(-1, 3)
        self.conf = None if conf is None else \
            np.ascontiguousarray(conf, np.float32).reshape(-1)
        self.level = None if level is None else \
            np.ascontiguousarray(level, np.uint8).reshape(-1)
        for name, arr in (("rgb", self.rgb), ("conf", self.conf),
                          ("level", self.level)):
            if arr is not None and len(arr) != n:
                raise ValueError(f"{name} has {len(arr)} rows for {n} points")
        # Where the scan came from (session, stream, backbone, ...): kept
        # so a file saved back carries what it was opened with.
        self.provenance = dict(provenance) if provenance else None

    # -- interrogation --

    @property
    def count(self) -> int:
        return len(self.xyz)

    def IsNull(self) -> bool:          # TopoDS protocol compatibility
        return len(self.xyz) == 0

    def bbox(self):
        if not len(self.xyz):
            return ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        mn = self.xyz.min(axis=0)
        mx = self.xyz.max(axis=0)
        return (tuple(float(v) for v in mn), tuple(float(v) for v in mx))

    def centroid(self):
        if not len(self.xyz):
            return (0.0, 0.0, 0.0)
        # float64 for the sum: a million float32 points added up in
        # float32 drift by metres
        return tuple(float(v) for v in self.xyz.astype(np.float64).mean(axis=0))

    def level_counts(self) -> tuple | None:
        """How many points sit at each level 0..MAX_LEVEL, or None."""
        if self.level is None:
            return None
        counts = np.bincount(self.level, minlength=MAX_LEVEL + 1)
        return tuple(int(c) for c in counts[:MAX_LEVEL + 1])

    # -- transforms --

    def transformed(self, matrix) -> "PointCloudShape":
        """Apply a 4x4 (or 3x3) transform, returning a new cloud."""
        m = np.asarray(matrix, np.float64)
        pts = self.xyz.astype(np.float64)
        if m.shape == (3, 3):
            pts = pts @ m.T
        else:
            pts = pts @ m[:3, :3].T + m[:3, 3]
        return PointCloudShape(pts, self.rgb, self.conf, self.level,
                               self.provenance)

    def translated(self, offset) -> "PointCloudShape":
        pts = self.xyz.astype(np.float64) + np.asarray(offset, np.float64)
        return PointCloudShape(pts, self.rgb, self.conf, self.level,
                               self.provenance)

    def copy(self) -> "PointCloudShape":
        return PointCloudShape(
            self.xyz.copy(),
            None if self.rgb is None else self.rgb.copy(),
            None if self.conf is None else self.conf.copy(),
            None if self.level is None else self.level.copy(),
            self.provenance)

    # -- subsets --

    def _take(self, mask_or_index) -> "PointCloudShape":
        sel = mask_or_index
        return PointCloudShape(
            self.xyz[sel],
            None if self.rgb is None else self.rgb[sel],
            None if self.conf is None else self.conf[sel],
            None if self.level is None else self.level[sel],
            self.provenance)

    def subset(self, max_level: int) -> "PointCloudShape":
        """The points with level <= max_level; the whole cloud when it
        carries no levels."""
        if self.level is None:
            return self
        return self._take(self.level <= int(max_level))

    def subsampled(self, fraction: float) -> "PointCloudShape":
        """Every point with probability `fraction`, evenly along the array
        rather than by chance, so the same call gives the same answer."""
        f = float(fraction)
        if not (0.0 < f <= 1.0):
            raise ValueError("Fraction must be between 0 and 1")
        n = len(self.xyz)
        keep = max(1, int(round(n * f))) if n else 0
        if keep >= n:
            return self.copy()
        idx = np.linspace(0, n - 1, keep).round().astype(np.int64)
        return self._take(idx)


def cloud_to_display(cloud: PointCloudShape):
    """DisplayMesh for the viewport: the points as vertices, no faces.

    The points are ordered coarse-to-fine when the cloud carries levels,
    so that "every point with level <= L" is the first N of the buffer
    and a budgeted draw is one shorter draw call, not a second upload.
    `cloud_levels` holds those cumulative counts.
    """
    from .tessellate import DisplayMesh
    dm = DisplayMesh()
    xyz, rgb = cloud.xyz, cloud.rgb
    levels = None
    if cloud.level is not None and len(cloud.level):
        order = np.argsort(cloud.level, kind="stable")
        xyz = xyz[order]
        rgb = None if rgb is None else rgb[order]
        counts = np.bincount(cloud.level, minlength=MAX_LEVEL + 1)
        levels = tuple(int(c) for c in np.cumsum(counts[:MAX_LEVEL + 1]))
    dm.vertices = xyz
    dm.cloud_colors = rgb
    dm.cloud_levels = levels
    dm.is_cloud = True
    return dm
