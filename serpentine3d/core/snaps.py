"""Object snaps: end, mid, center, quad, intersection, perpendicular, near.

Static candidates (end/mid/center/quad) are cached per object; intersections
are cached per scene revision; perpendicular and near are computed against
the cursor each query.
"""

from __future__ import annotations

import numpy as np

from . import geometry, occ

SNAP_TYPES = ("end", "mid", "center", "quad", "int", "perp", "near")

# priority when several candidates fall inside the pick radius
_PRIORITY = {"end": 0, "int": 1, "quad": 2, "mid": 3, "center": 4,
             "perp": 5, "near": 6}


def _static_snap_points(shape) -> list[tuple[tuple, str]]:
    """end / mid / center / quad candidates for one shape."""
    out = []
    seen = set()

    def add(x, y, z, kind):
        key = (round(x, 6), round(y, 6), round(z, 6), kind)
        if key not in seen:
            seen.add(key)
            out.append(((x, y, z), kind))

    if shape.ShapeType() == occ.VERTEX:
        x, y, z = geometry.point_coords(shape)
        add(x, y, z, "end")
        return out

    from OCP.GeomAbs import GeomAbs_CurveType
    for edge in geometry.edges_of(shape):
        try:
            ad = occ.edge_adaptor(edge)
            t0, t1 = ad.FirstParameter(), ad.LastParameter()
            p0, p1 = ad.Value(t0), ad.Value(t1)
            closed = p0.Distance(p1) < 1e-9
            if not closed:
                add(p0.X(), p0.Y(), p0.Z(), "end")
                add(p1.X(), p1.Y(), p1.Z(), "end")
            pm = ad.Value((t0 + t1) / 2)
            add(pm.X(), pm.Y(), pm.Z(), "mid")

            ct = ad.GetType()
            circ = None
            if ct == GeomAbs_CurveType.GeomAbs_Circle:
                circ = ad.Circle()
            elif ct == GeomAbs_CurveType.GeomAbs_Ellipse:
                el = ad.Ellipse()
                c = el.Location()
                add(c.X(), c.Y(), c.Z(), "center")
            if circ is not None:
                c = circ.Location()
                add(c.X(), c.Y(), c.Z(), "center")
                if closed:
                    # quadrant points relative to the world axes projected
                    # onto the circle plane
                    n = np.array([circ.Axis().Direction().X(),
                                  circ.Axis().Direction().Y(),
                                  circ.Axis().Direction().Z()])
                    center = np.array([c.X(), c.Y(), c.Z()])
                    r = circ.Radius()
                    ref = np.array([1.0, 0.0, 0.0])
                    qx = ref - np.dot(ref, n) * n
                    if np.linalg.norm(qx) < 1e-9:
                        ref = np.array([0.0, 1.0, 0.0])
                        qx = ref - np.dot(ref, n) * n
                    qx /= np.linalg.norm(qx)
                    qy = np.cross(n, qx)
                    for d in (qx, -qx, qy, -qy):
                        q = center + r * d
                        add(q[0], q[1], q[2], "quad")
        except Exception:
            continue
    return out


def _intersections(objects) -> list[tuple]:
    """Pairwise curve-curve intersection points (bbox-filtered)."""
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    curves = [(o, geometry.bbox(o.shape)) for o in objects
              if o.kind == "curve"]
    pts = []
    checked = 0
    for i in range(len(curves)):
        for j in range(i + 1, len(curves)):
            if checked > 400:
                return pts
            (oa, (amn, amx)), (ob, (bmn, bmx)) = curves[i], curves[j]
            if any(amn[k] > bmx[k] + 1e-6 or bmn[k] > amx[k] + 1e-6
                   for k in range(3)):
                continue
            checked += 1
            try:
                dist = BRepExtrema_DistShapeShape(oa.shape, ob.shape)
                if not dist.IsDone() or dist.Value() > 1e-6:
                    continue
                for s in range(1, dist.NbSolution() + 1):
                    p = dist.PointOnShape1(s)
                    pts.append((p.X(), p.Y(), p.Z()))
            except Exception:
                continue
    return pts


class SnapIndex:
    def __init__(self, scene, config=None):
        self.scene = scene
        self._cache: dict[str, tuple[int, list]] = {}
        self._int_cache: tuple[int, list] | None = None
        self.enabled = True
        self.types = {t: t in ("end", "mid", "center", "quad", "int")
                      for t in SNAP_TYPES}
        if config is not None:
            osnaps = config.get("osnaps", default={}) or {}
            self.enabled = bool(osnaps.get("enabled", True))
            for t in SNAP_TYPES:
                if t in osnaps:
                    self.types[t] = bool(osnaps[t])

    # -- caches --

    def _points(self, obj) -> list:
        entry = self._cache.get(obj.id)
        mesh_key = id(obj.mesh)
        if entry is None or entry[0] != mesh_key:
            entry = (mesh_key, _static_snap_points(obj.shape))
            self._cache[obj.id] = entry
        return entry[1]

    def _intersection_points(self, objects) -> list:
        rev = self.scene.revision
        if self._int_cache is None or self._int_cache[0] != rev:
            self._int_cache = (rev, _intersections(objects))
        return self._int_cache[1]

    # -- query --

    def find(self, camera, px: float, py: float, width: int, height: int,
             radius_px: float = 12.0, base_point=None):
        """Best snap near the pixel. Returns (point, kind) or None."""
        if not self.enabled:
            return None
        objects = self.scene.visible_objects()
        pts, kinds = [], []

        for obj in objects:
            for p, kind in self._points(obj):
                if self.types.get(kind):
                    pts.append(p)
                    kinds.append(kind)
        if self.types.get("int"):
            for p in self._intersection_points(objects):
                pts.append(p)
                kinds.append("int")
        if self.types.get("perp") and base_point is not None:
            for p in self._perp_feet(objects, base_point):
                pts.append(p)
                kinds.append("perp")

        best = None
        best_score = None
        if pts:
            arr = np.asarray(pts, float)
            scr = camera.project(arr, width, height)
            d2 = (scr[:, 0] - px) ** 2 + (scr[:, 1] - py) ** 2
            d2[scr[:, 2] <= 0] = np.inf
            in_range = d2 < radius_px ** 2
            for i in np.nonzero(in_range)[0]:
                score = (_PRIORITY[kinds[i]], d2[i])
                if best_score is None or score < best_score:
                    best_score = score
                    best = (tuple(arr[i]), kinds[i])

        if best is None and self.types.get("near"):
            near = self._near(objects, camera, px, py, width, height,
                              radius_px)
            if near is not None:
                best = (near, "near")
        return best

    def _perp_feet(self, objects, base_point) -> list:
        """Feet of perpendiculars from base_point onto visible curves."""
        from OCP.BRepExtrema import BRepExtrema_DistShapeShape
        from .occ import BRepBuilderAPI_MakeVertex, gp_Pnt
        v = BRepBuilderAPI_MakeVertex(
            gp_Pnt(*[float(c) for c in base_point])).Vertex()
        feet = []
        for obj in objects:
            if obj.kind != "curve":
                continue
            try:
                dist = BRepExtrema_DistShapeShape(v, obj.shape)
                if dist.IsDone():
                    for s in range(1, min(dist.NbSolution(), 4) + 1):
                        p = dist.PointOnShape2(s)
                        feet.append((p.X(), p.Y(), p.Z()))
            except Exception:
                continue
        return feet

    def _near(self, objects, camera, px, py, width, height, radius_px):
        """Closest point on any curve's tessellation, in screen space."""
        best = None
        best_d2 = radius_px ** 2
        cursor = np.array([px, py])
        for obj in objects:
            mesh = obj.mesh
            if not len(mesh.edge_segments):
                continue
            seg = mesh.edge_segments
            a3, b3 = seg[:, 0, :].astype(float), seg[:, 1, :].astype(float)
            sa = camera.project(a3, width, height)
            sb = camera.project(b3, width, height)
            valid = (sa[:, 2] > 0) & (sb[:, 2] > 0)
            if not valid.any():
                continue
            ab = sb[:, :2] - sa[:, :2]
            ap = cursor[None, :] - sa[:, :2]
            denom = np.einsum("ij,ij->i", ab, ab)
            denom[denom < 1e-12] = 1e-12
            t = np.clip(np.einsum("ij,ij->i", ap, ab) / denom, 0, 1)
            closest = sa[:, :2] + ab * t[:, None]
            d = cursor[None, :] - closest
            d2 = np.einsum("ij,ij->i", d, d)
            d2[~valid] = np.inf
            i = int(np.argmin(d2))
            if d2[i] < best_d2:
                best_d2 = d2[i]
                world = a3[i] + (b3[i] - a3[i]) * t[i]
                best = tuple(world)
        return best


# kept for backward compatibility with existing tests
def snap_points_for(shape) -> list[tuple[tuple, str]]:
    return [(p, k) for p, k in _static_snap_points(shape)
            if k in ("end", "mid", "center")]
