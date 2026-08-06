"""Object snaps: end, mid, center, quad, intersection, perpendicular, near.

Static candidates (end/mid/center/quad) are cached per object; intersections
are cached per scene revision; perpendicular and near are computed against
the cursor each query.
"""

from __future__ import annotations

import numpy as np

from . import geometry, occ

SNAP_TYPES = ("end", "mid", "center", "quad", "int", "appint", "perp",
              "near")

# priority when several candidates fall inside the pick radius
_PRIORITY = {"end": 0, "int": 1, "appint": 2, "quad": 3, "mid": 4,
             "center": 5, "perp": 6, "near": 7}

# How many screen segments near the cursor get paired up. Every pair is
# tried, so the cost is square, and a drawing dense enough to put more than
# this many edges under one pick radius is one where the answer would be a
# guess anyway.
_APPARENT_LIMIT = 160

# Two crossing segments this close along the line of sight are the same
# point in space, which means they really meet: that is `int`'s answer, and
# it is also what every corner of a polyline looks like from here.
_APPARENT_GAP = 1e-6


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


def _world_param(s, da, db, parallel):
    """Where along a segment in space the screen fraction `s` landed.

    Under a parallel projection the two are the same number. A perspective
    one packs the far half of a segment into fewer pixels, so halfway across
    the screen is not halfway along the line, and reading the 3D point off
    `s` would put the snap somewhere the curve does not go.
    """
    if parallel:
        return s
    den = da * s + db * (1.0 - s)
    flat = np.abs(den) < 1e-12
    return np.where(flat, s, s * da / np.where(flat, 1.0, den))


def _misses_the_cursor(mesh, camera, cursor, width, height, pad) -> bool:
    """True if nothing in this mesh can reach the cursor, cheaply.

    Eight corners answered instead of every segment in the object. The
    projection of a box contains the projection of everything inside it, so
    a cursor outside the corners' screen bounds is outside the object. It
    reads the mesh's own cached bounds and never the B-rep, because a
    drawing read from a file holds its shapes unconverted and asking one
    for a bounding box on every mouse move would convert the lot.
    """
    bounds = mesh.bounds() if hasattr(mesh, "bounds") else None
    if bounds is None:
        return False
    lo, hi = np.asarray(bounds[0], float), np.asarray(bounds[1], float)
    corners = np.array([[x, y, z] for x in (lo[0], hi[0])
                        for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
    scr = camera.project(corners, width, height)
    if not (scr[:, 2] > 0).all():
        # part of it is behind the eye, where a corner's pixel means
        # nothing; let the segments speak for themselves
        return False
    return bool(scr[:, 0].min() > cursor[0] + pad
                or scr[:, 0].max() < cursor[0] - pad
                or scr[:, 1].min() > cursor[1] + pad
                or scr[:, 1].max() < cursor[1] - pad)


def _cursor_segments(objects, camera, px, py, width, height, radius_px):
    """Edges of visible objects passing within the pick radius, on screen.

    Solids come too. The edge of a box is not a curve object and it is still
    a line you can see, so a rail passing over one crosses something.
    """
    cursor = np.array([float(px), float(py)])
    r2 = float(radius_px) ** 2
    segs = []
    for obj in objects:
        mesh = getattr(obj, "mesh", None)
        edges = getattr(mesh, "edge_segments", None)
        if edges is None or not len(edges):
            continue
        # eight corners to save projecting the segments is only a saving
        # when there are more than eight of them, and a drawing made of
        # single lines has one each
        if len(edges) > 32 and _misses_the_cursor(mesh, camera, cursor,
                                                  width, height, radius_px):
            continue
        e = np.asarray(edges, float)
        a3, b3 = e[:, 0, :], e[:, 1, :]
        sa = camera.project(a3, width, height)
        sb = camera.project(b3, width, height)
        ab = sb[:, :2] - sa[:, :2]
        ap = cursor[None, :] - sa[:, :2]
        den = np.einsum("ij,ij->i", ab, ab)
        t = np.clip(np.einsum("ij,ij->i", ap, ab)
                    / np.where(den < 1e-12, 1e-12, den), 0.0, 1.0)
        d = cursor[None, :] - (sa[:, :2] + ab * t[:, None])
        keep = ((sa[:, 2] > 0) & (sb[:, 2] > 0)
                & (np.einsum("ij,ij->i", d, d) <= r2))
        for i in np.nonzero(keep)[0]:
            segs.append((a3[i], b3[i], sa[i], sb[i]))
            if len(segs) >= _APPARENT_LIMIT:
                return segs
    return segs


def _apparent_crossings(objects, camera, px, py, width, height,
                        radius_px) -> list[tuple]:
    """Where two edges cross on screen without meeting in space.

    A rafter passing over a wall never touches it, so `int` has nothing at
    the place the two cross in a Top view, and that place is often the one
    being pointed at. It is made by where the camera stands, so unlike a
    real intersection there is nothing to cache: turn the view and every one
    of these moves. It is worked out per query, over the handful of segments
    the cursor is already on top of.
    """
    segs = _cursor_segments(objects, camera, px, py, width, height,
                            radius_px)
    if len(segs) < 2:
        return []
    flat = getattr(camera, "projection", "perspective") == "parallel"
    a3 = np.array([s[0] for s in segs])
    b3 = np.array([s[1] for s in segs])
    sa = np.array([s[2] for s in segs])
    sb = np.array([s[3] for s in segs])

    # every pair at once. A mat of rails over one spot fills the segment
    # budget, and a hundred and sixty of those is thirteen thousand pairs
    # per mouse move, which is a fifth of a second of arithmetic done one
    # pair at a time and under a millisecond done all at once.
    i, j = np.triu_indices(len(segs), k=1)
    p, r = sa[i, :2], sa[j, :2]
    u, v = sb[i, :2] - p, sb[j, :2] - r
    den = u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0]
    # running together on screen: either the same line drawn twice, or so
    # nearly so that where they meet is noise
    live = np.abs(den) >= 1e-6 * (np.hypot(u[:, 0], u[:, 1])
                                  * np.hypot(v[:, 0], v[:, 1]) + 1.0)
    safe = np.where(live, den, 1.0)
    w = r - p
    s1 = (w[:, 0] * v[:, 1] - w[:, 1] * v[:, 0]) / safe
    s2 = (w[:, 0] * u[:, 1] - w[:, 1] * u[:, 0]) / safe
    live &= (s1 >= 0.0) & (s1 <= 1.0) & (s2 >= 0.0) & (s2 <= 1.0)

    da1, db1, da2, db2 = sa[i, 2], sb[i, 2], sa[j, 2], sb[j, 2]
    t1 = _world_param(s1, da1, db1, flat)
    t2 = _world_param(s2, da2, db2, flat)
    d1 = da1 + (db1 - da1) * t1
    d2 = da2 + (db2 - da2) * t2
    # one pixel and one depth is one point in space, so the two agreeing on
    # depth means the curves genuinely touch
    live &= np.abs(d1 - d2) > _APPARENT_GAP

    k = np.nonzero(live)[0]
    if not len(k):
        return []
    # the near one is the one you can see at that pixel; the far one is
    # behind something you are looking at
    first = d1[k] <= d2[k]
    ki, kj = i[k], j[k]
    on_i = a3[ki] + (b3[ki] - a3[ki]) * t1[k][:, None]
    on_j = a3[kj] + (b3[kj] - a3[kj]) * t2[k][:, None]
    return [tuple(q) for q in np.where(first[:, None], on_i, on_j)]


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

    @staticmethod
    def _pending_candidates(chain, picked=None) -> list[tuple[tuple, str]]:
        """Snap candidates on the geometry still being picked.

        `chain` is the run of points the command draws as a connected curve;
        `picked` is simply every point it has taken. Only the chain has
        midpoints worth offering — a box takes two corners in sequence, but
        the line between them is a diagonal and halfway along it is not a
        feature of anything.

        Either way the newest point is left out: it sits under the cursor the
        moment it is placed, so offering it would glue every new leg to zero
        length."""
        def clean(seq):
            return [tuple(float(c) for c in p) for p in (seq or [])]

        run, taken = clean(chain), clean(picked)
        out, seen = [], set()

        def add(p, kind):
            key = (round(p[0], 9), round(p[1], 9), round(p[2], 9), kind)
            if key not in seen:
                seen.add(key)
                out.append((p, kind))

        for p in run[:-1]:
            add(p, "end")
        for p in taken[:-1]:
            add(p, "end")
        for a, b in zip(run, run[1:]):
            add(tuple((x + y) / 2 for x, y in zip(a, b)), "mid")
        return out

    def find(self, camera, px: float, py: float, width: int, height: int,
             radius_px: float = 12.0, base_point=None, pending_points=None,
             picked_points=None):
        """Best snap near the pixel. Returns (point, kind) or None."""
        if not self.enabled:
            return None
        objects = self.scene.visible_objects()
        pts, kinds = [], []

        # what you are drawing is not in the scene yet, but you still want to
        # close it back on its start or land a later pick on an earlier one
        for p, kind in self._pending_candidates(pending_points, picked_points):
            if self.types.get(kind):
                pts.append(p)
                kinds.append(kind)

        for obj in objects:
            for p, kind in self._points(obj):
                if self.types.get(kind):
                    pts.append(p)
                    kinds.append(kind)
        if self.types.get("int"):
            for p in self._intersection_points(objects):
                pts.append(p)
                kinds.append("int")
        if self.types.get("appint"):
            for p in _apparent_crossings(objects, camera, px, py, width,
                                         height, radius_px):
                pts.append(p)
                kinds.append("appint")
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
