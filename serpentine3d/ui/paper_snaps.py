"""Adapt sheet objects to the model's snap engine, in paper millimetres."""
from __future__ import annotations

import numpy as np

from ..core import geometry as g
from ..core.layout import annotation_bounds, sheet_item_linework
from ..core.scene import SceneObject
from ..core.snaps import SnapIndex


class PaperSnaps(SnapIndex):
    projection = "parallel"

    def __init__(self, view):
        self.view = view
        self.revision = 0
        self._objects = {}
        self._features = {}
        super().__init__(self)

    def project(self, points, width, height):
        points = np.asarray(points, float).reshape(-1, 3)
        out = np.ones((len(points), 3))
        out[:, 0] = width / 2 + (points[:, 0] - self.view.pan[0]) * self.view.px_per_mm
        out[:, 1] = height / 2 - (points[:, 1] - self.view.pan[1]) * self.view.px_per_mm
        return out

    def visible_objects(self):
        return [entry[1] for entry in self._objects.values()]

    def _points(self, obj):
        return super()._points(obj) + self._features.get(obj.id, [])

    def sync(self):
        lay = self.view.layout
        previous = self._objects
        current, features = {}, {}

        def include(key, signature, shape_fn, extra=()):
            cached = previous.get(key)
            if cached is not None and cached[0] == signature:
                current[key] = cached
            else:
                shape = shape_fn()
                current[key] = (signature, SceneObject(
                    key, "Paper snap", shape, g.shape_kind(shape), ""))
            features[key] = list(extra)

        def poly(key, points, closed=False, extra=()):
            pts = tuple(tuple(float(c) for c in p[:2]) + (0.,) for p in points)
            pts = tuple(p for i, p in enumerate(pts) if i == 0 or p != pts[i-1])
            if len(pts) > 1 and pts[0] == pts[-1]:
                pts = pts[:-1]
                closed = True
            if not pts:
                return
            include(key, (pts, closed),
                    lambda: g.make_polyline(pts, closed=closed) if len(pts) > 1
                    else g.make_point(pts[0]), extra)

        if lay is not None:
            corners = [(0., 0.), (lay.paper_w, 0.),
                       (lay.paper_w, lay.paper_h), (0., lay.paper_h)]
            for i, a in enumerate(corners):
                # Separate edges let Perp reach each side, not just the side
                # closest to the base point. These are snap proxies only.
                poly(f"__page_edge:{i}", [a, corners[(i + 1) % 4]],
                     extra=[((lay.paper_w/2, lay.paper_h/2, 0.), "center")]
                     if i == 0 else ())
            for obj in lay.objects:
                # Keep the real curves: tessellation vertices are not End snaps.
                include(obj.id, id(obj.shape), lambda obj=obj: obj.shape)
            scene = self.view.vp.scene

            def lines(kind, item, extra=()):
                (points, closed), = sheet_item_linework(kind, item, scene)
                poly(item.id, points, closed, extra)

            for det in lay.details:
                lines("detail", det,
                      extra=[((det.x + det.w/2, det.y + det.h/2, 0.), "center")])
            for note in lay.notes:
                x0, y0, x1, y1 = annotation_bounds("note", note, scene)
                lines("note", note,
                      extra=[((note.x,note.y,0.), "point"),
                             (((x0+x1)/2,(y0+y1)/2,0.), "center")])
            for leader in lay.leaders:
                lines("leader", leader)
            for hatch in lay.hatches:
                for i, (loop, closed) in enumerate(
                        sheet_item_linework("hatch", hatch, scene)):
                    poly(f"{hatch.id}:{i}", loop, closed)
            for dim in lay.dims:
                lines("dim", dim)
            for dim in lay.rdims:
                lines("rdim", dim, extra=[((dim.cx,dim.cy,0.), "center")])
            for dim in lay.adims:
                lines("adim", dim)

        if (previous.keys() != current.keys() or
                any(previous.get(key) is not entry for key, entry in current.items())):
            self.revision += 1
        self._objects, self._features = current, features
        self._cache = {key: value for key, value in self._cache.items() if key in current}

    def pick(self, sx, sy, settings, radius_px):
        if not settings.enabled:
            return None
        self.types = settings.types
        self.sync()
        vp = self.view.vp
        return self.find(self, sx, sy, vp.width(), vp.height(), radius_px,
                         base_point=vp.snap_base, pending_points=vp.pending_points,
                         picked_points=vp.picked_points)
