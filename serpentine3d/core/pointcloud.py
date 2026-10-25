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

float32 holds a millimetre near the origin and a quarter of a metre at a
UTM northing, so a georeferenced scan stored in absolute coordinates does
not come back as a scan: its points snap onto the grid's planes and read
as a set of lines. So the points are kept as offsets from `origin`, a
float64 point near the cloud picked when it is built. The offsets are the
float32 the container wants and are good to a micron whatever the cloud's
coordinates are; `xyz` adds the origin back for anything that wants the
world's own numbers. A cloud near the origin has an origin of zero and is
byte for byte what it always was.
"""

from __future__ import annotations

import numpy as np

from ..utils.math3d import ANCHOR_NEAR, offsets_from, origin_for

# The coarse-to-fine levels a scan comes in: 0 is the 10 cm pass, 2 the
# 1 cm one. A reader on weak hardware draws every point with level <= L.
MAX_LEVEL = 2


class PointCloudShape:
    """Immutable point cloud. Transform methods return new instances."""

    __slots__ = ("local", "origin", "rgb", "conf", "level", "provenance")

    def __init__(self, xyz, rgb=None, conf=None, level=None,
                 provenance: dict | None = None, origin=None):
        """`xyz` is in world coordinates, unless `origin` is given: then
        it holds offsets from that point, which is how a file hands back
        what it stored without going through the world's numbers."""
        if origin is None:
            pts = np.asarray(xyz).reshape(-1, 3)
            found = origin_for(pts)
            if found is None:
                self.local = np.ascontiguousarray(pts, np.float32)
                self.origin = np.zeros(3)
            else:
                self.local = offsets_from(pts, found)
                self.origin = found
        else:
            self.local = np.ascontiguousarray(xyz, np.float32).reshape(-1, 3)
            self.origin = np.asarray(origin, np.float64).reshape(3)
        n = len(self.local)
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
    def xyz(self) -> np.ndarray:
        """The points in world coordinates.

        The offsets themselves for a cloud near the origin, where they are
        already the world's numbers; for one standing far out, the origin
        added back in float64, which is a copy. Anything asking per frame
        or per mouse move narrows the cloud first and calls `to_world` on
        what is left of it (see core/snaps.py).
        """
        return self.to_world(self.local)

    def to_world(self, local) -> np.ndarray:
        """Offsets from this cloud's origin, as world coordinates."""
        if not self.far:
            return np.asarray(local)
        return np.asarray(local, np.float64) + self.origin

    @property
    def far(self) -> bool:
        """Whether this cloud keeps its points relative to an origin."""
        return bool(np.any(self.origin))

    @property
    def count(self) -> int:
        return len(self.local)

    def IsNull(self) -> bool:          # TopoDS protocol compatibility
        return len(self.local) == 0

    def bbox(self):
        if not len(self.local):
            return ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        mn = np.asarray(self.local.min(axis=0), np.float64) + self.origin
        mx = np.asarray(self.local.max(axis=0), np.float64) + self.origin
        return (tuple(float(v) for v in mn), tuple(float(v) for v in mx))

    def centroid(self):
        if not len(self.local):
            return (0.0, 0.0, 0.0)
        # float64 for the sum: a million float32 points added up in
        # float32 drift by metres
        mean = self.local.astype(np.float64).mean(axis=0) + self.origin
        return tuple(float(v) for v in mean)

    def level_counts(self) -> tuple | None:
        """How many points sit at each level 0..MAX_LEVEL, or None."""
        if self.level is None:
            return None
        counts = np.bincount(self.level, minlength=MAX_LEVEL + 1)
        return tuple(int(c) for c in counts[:MAX_LEVEL + 1])

    # -- transforms --

    def _rebuilt(self, local, origin) -> "PointCloudShape":
        """A cloud of these offsets about this origin.

        An origin that has come home is folded back into the points, so a
        scan moved to the world's origin is stored the way one modelled
        there would be, and nothing carries an origin it has no use for.
        """
        origin = np.asarray(origin, np.float64).reshape(3)
        if np.abs(origin).max() <= ANCHOR_NEAR:
            return PointCloudShape(
                np.asarray(local, np.float64) + origin,
                self.rgb, self.conf, self.level, self.provenance)
        return PointCloudShape(local, self.rgb, self.conf, self.level,
                               self.provenance, origin=origin)

    def transformed(self, matrix) -> "PointCloudShape":
        """Apply a 4x4 (or 3x3) transform, returning a new cloud.

        The origin goes through the transform and the offsets only through
        its rotation, so a scan at survey coordinates is turned about its
        own middle rather than about a point a million units away.
        """
        m = np.asarray(matrix, np.float64)
        rot = m if m.shape == (3, 3) else m[:3, :3]
        shift = np.zeros(3) if m.shape == (3, 3) else m[:3, 3]
        return self._rebuilt(self.local.astype(np.float64) @ rot.T,
                             self.origin @ rot.T + shift)

    def translated(self, offset) -> "PointCloudShape":
        return self._rebuilt(self.local,
                             self.origin + np.asarray(offset, np.float64))

    def copy(self) -> "PointCloudShape":
        return PointCloudShape(
            self.local.copy(),
            None if self.rgb is None else self.rgb.copy(),
            None if self.conf is None else self.conf.copy(),
            None if self.level is None else self.level.copy(),
            self.provenance, origin=self.origin.copy())

    # -- subsets --

    def _take(self, mask_or_index) -> "PointCloudShape":
        sel = mask_or_index
        return PointCloudShape(
            self.local[sel],
            None if self.rgb is None else self.rgb[sel],
            None if self.conf is None else self.conf[sel],
            None if self.level is None else self.level[sel],
            self.provenance, origin=self.origin)

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
        n = len(self.local)
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
    local, rgb = cloud.local, cloud.rgb
    levels = None
    if cloud.level is not None and len(cloud.level):
        order = np.argsort(cloud.level, kind="stable")
        local = local[order]
        rgb = None if rgb is None else rgb[order]
        counts = np.bincount(cloud.level, minlength=MAX_LEVEL + 1)
        levels = tuple(int(c) for c in np.cumsum(counts[:MAX_LEVEL + 1]))
    # The display works in world coordinates like every other mesh: the
    # viewport takes its own anchor off these and uploads small numbers.
    dm.vertices = cloud.to_world(local)
    dm.cloud_colors = rgb
    dm.cloud_levels = levels
    dm.is_cloud = True
    return dm
