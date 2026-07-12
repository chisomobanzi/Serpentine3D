"""Object snap candidates: end, mid, center points of scene geometry."""

from __future__ import annotations

import numpy as np

from . import geometry, occ


def snap_points_for(shape) -> list[tuple[tuple, str]]:
    """[(point, kind)] with kind in end|mid|center."""
    out = []
    seen = set()

    def add(p, kind):
        key = (round(p[0], 6), round(p[1], 6), round(p[2], 6), kind)
        if key not in seen:
            seen.add(key)
            out.append(((p[0], p[1], p[2]), kind))

    for edge in geometry.edges_of(shape):
        try:
            ad = occ.edge_adaptor(edge)
            t0, t1 = ad.FirstParameter(), ad.LastParameter()
            p0, p1 = ad.Value(t0), ad.Value(t1)
            closed = p0.Distance(p1) < 1e-9
            if not closed:
                add((p0.X(), p0.Y(), p0.Z()), "end")
                add((p1.X(), p1.Y(), p1.Z()), "end")
            pm = ad.Value((t0 + t1) / 2)
            add((pm.X(), pm.Y(), pm.Z()), "mid")
            # circles / ellipses expose their center
            from OCP.GeomAbs import GeomAbs_CurveType
            ct = ad.GetType()
            if ct == GeomAbs_CurveType.GeomAbs_Circle:
                c = ad.Circle().Location()
                add((c.X(), c.Y(), c.Z()), "center")
            elif ct == GeomAbs_CurveType.GeomAbs_Ellipse:
                c = ad.Ellipse().Location()
                add((c.X(), c.Y(), c.Z()), "center")
        except Exception:
            continue
    return out


class SnapIndex:
    """Caches snap candidates per object; queries nearest in screen space."""

    def __init__(self, scene):
        self.scene = scene
        self._cache: dict[str, tuple[int, list]] = {}
        self.enabled = True

    def _points(self, obj) -> list:
        entry = self._cache.get(obj.id)
        mesh_key = id(obj.mesh)
        if entry is None or entry[0] != mesh_key:
            entry = (mesh_key, snap_points_for(obj.shape))
            self._cache[obj.id] = entry
        return entry[1]

    def find(self, camera, px: float, py: float, width: int, height: int,
             radius_px: float = 12.0):
        """Nearest snap point to pixel (px,py). Returns (point, kind) or None."""
        if not self.enabled:
            return None
        pts, kinds = [], []
        for obj in self.scene.visible_objects():
            for p, kind in self._points(obj):
                pts.append(p)
                kinds.append(kind)
        if not pts:
            return None
        arr = np.asarray(pts, float)
        scr = camera.project(arr, width, height)
        valid = scr[:, 2] > 0
        if not valid.any():
            return None
        d2 = (scr[:, 0] - px) ** 2 + (scr[:, 1] - py) ** 2
        d2[~valid] = np.inf
        i = int(np.argmin(d2))
        if d2[i] > radius_px ** 2:
            return None
        return (tuple(arr[i]), kinds[i])
