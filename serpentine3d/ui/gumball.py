"""Gumball: on-object move/rotate/scale manipulator.

Handles (aligned to the construction plane, anchored at the selection
centre, constant screen size):
  - axis arrows        -> move along axis
  - plane pads         -> move in plane
  - circles            -> rotate about axis (Shift snaps to 15 degrees)
  - square knobs       -> scale along axis (Shift scales uniformly)

Precision: drag a handle for feel, or click it and type an exact value
(distance / angle / factor) then Enter — the value previews live while
you type. Grid snap rounds move drags to the grid step. Alt-drag any
move handle drags a copy. Escape cancels.
"""

from __future__ import annotations

import math

import numpy as np
from OpenGL import GL
from PySide6.QtCore import Qt

from ..core import geometry as g
from ..utils.math3d import ray_line_parameter, ray_plane_any

AXIS_COLORS = ((0.86, 0.33, 0.31), (0.42, 0.72, 0.35), (0.35, 0.55, 0.92))
HOVER_COLOR = (1.0, 0.85, 0.3)
PP_COLOR = (0.85, 0.71, 0.29)    # push/pull arrow on a face (brand gold)
FILLET_COLOR = (0.44, 0.74, 0.86)   # fillet radius handle on edges (teal)
PAD_ALPHA = 0.35
SIZE_PX = 78.0            # on-screen gumball radius
SHAFT0, SHAFT1 = 0.18, 1.0
CONE1 = 1.22
SCALE_POS = 0.6
ARC_R = 0.82
PAD0, PAD1 = 0.28, 0.5

# handle ids: ("move",axis) ("pad",axis) ("rot",axis) ("scale",axis)
_ONE_DOF = ("move", "rot", "scale")     # take a single typed value


class Gumball:
    def __init__(self, viewport):
        self.vp = viewport
        self.enabled = True
        if viewport.config is not None:
            self.enabled = bool(viewport.config.get("gumball", default=True))
        self.hover = None
        self.drag = None          # dict with handle, originals, refs
        self._geom_cache = None

    # ----------------------------------------------------------- state

    def active(self) -> bool:
        vp = self.vp
        if not (self.enabled and vp.space == "model" and not vp.point_mode):
            return False
        if self.drag is not None:            # a drag stays live to its end
            return True
        return (bool(vp.selection.ids)
                or self._pushpull_target() is not None
                or self._fillet_target() is not None)

    def _pushpull_target(self):
        """For a single selected planar face, return
        (obj_id, face_index, centroid, (t1, t2, normal)); else None.

        This is what turns the gumball into a face push/pull handle: a
        normal-aligned arrow that moves the face in/out and rebuilds the
        solid (via geometry.push_pull). Non-planar faces have no single
        normal, so they get no handle."""
        subs = getattr(self.vp.selection, "subobjects", None)
        if not subs:
            return None
        faces = [(oid, idx) for (oid, kind, idx) in subs if kind == "face"]
        if len(faces) != 1:                  # v1: one face at a time
            return None
        oid, fidx = faces[0]
        obj = self.vp.scene.get(oid)
        if obj is None:
            return None
        try:
            flist = g.faces_of(obj.shape)
            if not (0 <= fidx < len(flist)):
                return None
            normal = np.asarray(g.face_normal(flist[fidx]), float)
            centroid = np.asarray(g.centroid(flist[fidx]), float)
        except g.GeometryError:
            return None                      # non-planar: no push/pull
        length = float(np.linalg.norm(normal))
        if length < 1e-9:
            return None
        normal = normal / length
        ref = (np.array([1.0, 0.0, 0.0]) if abs(normal[0]) < 0.9
               else np.array([0.0, 1.0, 0.0]))
        t1 = np.cross(normal, ref)
        t1 = t1 / (np.linalg.norm(t1) or 1.0)
        t2 = np.cross(normal, t1)
        return oid, fidx, centroid, (t1, t2, normal)

    def _fillet_target(self):
        """For one or more selected edges on a single solid, return
        (obj_id, [edge_index...], anchor, (t1, t2, outward)); else None.

        Turns the gumball into an interactive fillet: a single outward
        handle at the edges' midpoint that sets the radius and rebuilds the
        solid live (via geometry.fillet_edges). Any number of edges fillet
        together at one radius."""
        subs = getattr(self.vp.selection, "subobjects", None)
        if not subs:
            return None
        edges = [(oid, idx) for (oid, kind, idx) in subs if kind == "edge"]
        if not edges:
            return None
        oid = edges[0][0]
        idxs = [idx for (o, idx) in edges if o == oid]   # one solid at a time
        obj = self.vp.scene.get(oid)
        if obj is None:
            return None
        try:
            elist = g.edges_of(obj.shape)
            if any(not (0 <= i < len(elist)) for i in idxs):
                return None
            mids = [np.asarray(g.centroid(elist[i]), float) for i in idxs]
            solid_c = np.asarray(g.centroid(obj.shape), float)
        except g.GeometryError:
            return None
        anchor = np.mean(mids, axis=0)
        out = anchor - solid_c
        length = float(np.linalg.norm(out))
        out = out / length if length > 1e-9 else np.array([0.0, 0.0, 1.0])
        ref = (np.array([1.0, 0.0, 0.0]) if abs(out[0]) < 0.9
               else np.array([0.0, 1.0, 0.0]))
        t1 = np.cross(out, ref)
        t1 = t1 / (np.linalg.norm(t1) or 1.0)
        t2 = np.cross(out, t1)
        return oid, idxs, anchor, (t1, t2, out)

    def _face_mode(self) -> bool:
        """Is the gumball acting as a face push/pull handle right now?"""
        if self.drag is not None:
            return bool(self.drag.get("pp"))
        return self._pushpull_target() is not None

    def _fillet_mode(self) -> bool:
        """Is the gumball acting as an edge fillet handle right now?"""
        if self.drag is not None:
            return bool(self.drag.get("fillet"))
        return (self._pushpull_target() is None
                and self._fillet_target() is not None)

    def anchor_and_axes(self):
        if self.drag is None:
            pp = self._pushpull_target()
            if pp is not None:               # face push/pull takes priority
                _, _, centroid, basis = pp
                return centroid, basis
            ft = self._fillet_target()
            if ft is not None:               # then edge fillet
                _, _, anchor, basis = ft
                return anchor, basis
        objs = self.vp.selection.objects()
        if not objs:
            return None
        mins = np.full(3, np.inf)
        maxs = np.full(3, -np.inf)
        for o in objs:
            mn, mx = g.bbox(o.shape)
            mins = np.minimum(mins, mn)
            maxs = np.maximum(maxs, mx)
        anchor = (mins + maxs) / 2
        cp = self.vp.cplane
        return anchor, (np.asarray(cp.xdir), np.asarray(cp.ydir),
                        np.asarray(cp.normal))

    def _draw_anchor(self):
        """Where the gumball is drawn this frame. During a move/pad drag
        it tracks the geometry (frozen anchor + applied offset); rotate
        and scale keep the anchor as the fixed pivot.
        """
        if self.drag is None:
            state = self.anchor_and_axes()
            return None if state is None else (state[0], state[1])
        d = self.drag
        anchor = np.asarray(d["anchor"], float)
        if d["handle"][0] in ("move", "pad"):
            anchor = anchor + d["offset"]
        return anchor, d["axes"]

    def _size_world(self, anchor) -> float:
        """World length that projects to SIZE_PX pixels at the anchor."""
        cam = self.vp.camera
        w, h = self.vp.width(), self.vp.height()
        right, _ = cam.right_up()
        probe = np.stack([anchor, anchor + right])
        scr = cam.project(probe, w, h)
        px = float(np.hypot(scr[1, 0] - scr[0, 0], scr[1, 1] - scr[0, 1]))
        if px < 1e-6:
            return 1.0
        return SIZE_PX / px

    # -------------------------------------------------------- painting

    def paint(self, mvp):
        if not self.active():
            return
        if self._face_mode():
            self._paint_pushpull(mvp)
            return
        if self._fillet_mode():
            self._paint_fillet(mvp)
            return
        state = self._draw_anchor()
        if state is None:
            return
        anchor, axes = state
        s = self._size_world(anchor)
        GL.glDisable(GL.GL_DEPTH_TEST)

        def color_for(handle, base):
            if self.hover == handle or (
                    self.drag and self.drag["handle"] == handle):
                return HOVER_COLOR
            return base

        # rotation circles
        for i in range(3):
            u, v = axes[(i + 1) % 3], axes[(i + 2) % 3]
            pts = []
            for k in range(49):
                a = k / 48 * 2 * math.pi
                pts.append(anchor + ARC_R * s
                           * (u * math.cos(a) + v * math.sin(a)))
            arr = np.asarray(pts, np.float32)
            segs = np.stack([arr[:-1], arr[1:]], axis=1).reshape(-1, 3)
            self._lines(mvp, segs, (*color_for(("rot", i), AXIS_COLORS[i]),
                                    0.85), 1.6)

        # plane pads
        for i in range(3):
            u, v = axes[(i + 1) % 3], axes[(i + 2) % 3]
            c0 = anchor + (u + v) * PAD0 * s
            c1 = anchor + u * PAD1 * s + v * PAD0 * s
            c2 = anchor + (u + v) * PAD1 * s
            c3 = anchor + u * PAD0 * s + v * PAD1 * s
            tris = np.asarray([c0, c1, c2, c0, c2, c3], np.float32)
            self._tris(mvp, tris, (*color_for(("pad", i), AXIS_COLORS[i]),
                                   PAD_ALPHA))

        # shafts + cones + scale knobs
        for i in range(3):
            axis = axes[i]
            color = color_for(("move", i), AXIS_COLORS[i])
            a0 = anchor + axis * SHAFT0 * s
            a1 = anchor + axis * SHAFT1 * s
            self._lines(mvp, np.asarray([a0, a1], np.float32),
                        (*color, 1.0), 2.4)
            self._cone(mvp, anchor, axis, axes[(i + 1) % 3],
                       axes[(i + 2) % 3], s, (*color, 1.0))
            kc = color_for(("scale", i), AXIS_COLORS[i])
            self._knob(mvp, anchor + axis * SCALE_POS * s, s,
                       (*kc, 1.0))
        GL.glEnable(GL.GL_DEPTH_TEST)
        self.vp._line_width(1.0)

    def _paint_pushpull(self, mvp):
        """A single double-headed arrow along the face normal (in = carve,
        out = extrude), plus a faint square marking the face plane."""
        state = self._draw_anchor()
        if state is None:
            return
        anchor, axes = state
        s = self._size_world(anchor)
        u, v, n = axes[0], axes[1], axes[2]
        GL.glDisable(GL.GL_DEPTH_TEST)
        hot = (self.hover == ("move", 2)
               or (self.drag is not None
                   and self.drag["handle"] == ("move", 2)))
        col = HOVER_COLOR if hot else PP_COLOR
        self._lines(mvp, np.asarray(
            [anchor - n * SHAFT1 * s, anchor + n * SHAFT1 * s], np.float32),
            (*col, 1.0), 2.6)
        self._cone(mvp, anchor, n, u, v, s, (*col, 1.0))
        self._cone(mvp, anchor, -n, u, v, s, (*col, 1.0))
        r = PAD0 * s                          # face-plane marker
        c0, c1 = anchor + (u + v) * r, anchor + (u - v) * r
        c2, c3 = anchor - (u + v) * r, anchor - (u - v) * r
        self._lines(mvp, np.asarray([c0, c1, c1, c2, c2, c3, c3, c0],
                                    np.float32), (*col, 0.5), 1.4)
        GL.glEnable(GL.GL_DEPTH_TEST)
        self.vp._line_width(1.0)

    def _paint_fillet(self, mvp):
        """A single outward arrow at the selected edges' midpoint whose length
        sets the fillet radius, plus a small quarter-round arc as a hint."""
        state = self._draw_anchor()
        if state is None:
            return
        anchor, axes = state
        s = self._size_world(anchor)
        u, v, n = axes[0], axes[1], axes[2]
        GL.glDisable(GL.GL_DEPTH_TEST)
        hot = (self.hover == ("move", 2)
               or (self.drag is not None
                   and self.drag["handle"] == ("move", 2)))
        col = HOVER_COLOR if hot else FILLET_COLOR
        self._lines(mvp, np.asarray(
            [anchor + n * SHAFT0 * s, anchor + n * SHAFT1 * s], np.float32),
            (*col, 1.0), 2.6)
        self._cone(mvp, anchor, n, u, v, s, (*col, 1.0))
        # quarter-round arc (fillet motif) in the n-u plane at the anchor
        r = 0.42 * s
        pts = []
        for k in range(13):
            a = k / 12 * (math.pi / 2)
            pts.append(anchor + r * (n * math.cos(a) + u * math.sin(a)))
        arr = np.asarray(pts, np.float32)
        segs = np.stack([arr[:-1], arr[1:]], axis=1).reshape(-1, 3)
        self._lines(mvp, segs, (*col, 0.7), 1.6)
        GL.glEnable(GL.GL_DEPTH_TEST)
        self.vp._line_width(1.0)

    def _cone(self, mvp, anchor, axis, u, v, s, color):
        tip = anchor + axis * CONE1 * s
        base = anchor + axis * SHAFT1 * s
        r = 0.055 * s
        tris = []
        n = 10
        for k in range(n):
            a0 = k / n * 2 * math.pi
            a1 = (k + 1) / n * 2 * math.pi
            p0 = base + r * (u * math.cos(a0) + v * math.sin(a0))
            p1 = base + r * (u * math.cos(a1) + v * math.sin(a1))
            tris.extend([tip, p0, p1])
        self._tris(mvp, np.asarray(tris, np.float32), color)

    def _knob(self, mvp, center, s, color):
        cam = self.vp.camera
        right, up = cam.right_up()
        r = 0.06 * s
        c0 = center - right * r - up * r
        c1 = center + right * r - up * r
        c2 = center + right * r + up * r
        c3 = center - right * r + up * r
        self._tris(mvp, np.asarray([c0, c1, c2, c0, c2, c3], np.float32),
                   color)

    def _lines(self, mvp, pts, color, width):
        vp = self.vp
        vp._preview.update(pts.reshape(-1, 3).astype(np.float32))
        vp._set_line_uniforms(mvp, color)
        vp._line_width(width)
        GL.glBindVertexArray(vp._preview.vao)
        GL.glDrawArrays(GL.GL_LINES, 0, len(pts.reshape(-1, 3)))

    def _tris(self, mvp, pts, color):
        vp = self.vp
        vp._preview.update(pts.astype(np.float32))
        vp._set_line_uniforms(mvp, color)
        GL.glBindVertexArray(vp._preview.vao)
        GL.glDrawArrays(GL.GL_TRIANGLES, 0, len(pts))

    def readout(self):
        """(text, (screen_x, screen_y)) for the value readout, pinned to
        where the drag STARTED — a typed move sends the geometry (and its
        live anchor) off screen, so the readout stays put. None if there
        is nothing to show."""
        d = self.drag
        if d is None:
            return None
        anchor = np.asarray(d["anchor"], float)
        scr = self.vp.camera.project(np.asarray([anchor], float),
                                     self.vp.width(), self.vp.height())[0]
        if scr[2] <= 0:
            return None
        kind = d["handle"][0]
        if d["typed"]:
            unit = {"move": "", "rot": "°", "scale": "×"}.get(kind, "")
            prompt = {"move": "distance", "rot": "angle",
                      "scale": "factor"}.get(kind, "")
            text = f"{prompt}: {d['typed']}{unit}"
        elif d.get("armed"):
            prompt = {"move": "distance", "rot": "angle",
                      "scale": "factor"}.get(kind, "")
            text = f"type a {prompt}, Enter"
        else:
            text = d.get("last_label", "")
        if not text:
            return None
        return text, (int(scr[0]) + 18, int(scr[1]) - 14)

    # ------------------------------------------------------- hit testing

    def hit_test(self, px, py):
        if not self.active():
            return None
        state = self.anchor_and_axes()
        if state is None:
            return None
        anchor, axes = state
        s = self._size_world(anchor)
        cam = self.vp.camera
        w, h = self.vp.width(), self.vp.height()

        def scr(p):
            out = cam.project(np.asarray([p], float), w, h)[0]
            return out[:2] if out[2] > 0 else None

        cursor = np.array([px, py])

        if self._face_mode():                 # only the push/pull arrow
            n = axes[2]
            a = scr(anchor - n * CONE1 * s)
            b = scr(anchor + n * CONE1 * s)
            if a is not None and b is not None and _seg_dist(cursor, a, b) < 8:
                return ("move", 2)
            return None

        if self._fillet_mode():               # only the outward radius arrow
            n = axes[2]
            a = scr(anchor)
            b = scr(anchor + n * CONE1 * s)
            if a is not None and b is not None and _seg_dist(cursor, a, b) < 8:
                return ("move", 2)
            return None

        # scale knobs (smallest targets first)
        for i in range(3):
            p = scr(anchor + axes[i] * SCALE_POS * s)
            if p is not None and np.linalg.norm(p - cursor) < 6.5:
                return ("scale", i)
        # pads
        for i in range(3):
            u, v = axes[(i + 1) % 3], axes[(i + 2) % 3]
            corners = [anchor + (u * a + v * b) * s
                       for a, b in ((PAD0, PAD0), (PAD1, PAD0),
                                    (PAD1, PAD1), (PAD0, PAD1))]
            pts = [scr(c) for c in corners]
            if all(p is not None for p in pts) and _in_poly(cursor, pts):
                return ("pad", i)
        # arrows (shaft + cone)
        for i in range(3):
            a = scr(anchor + axes[i] * SHAFT0 * s)
            b = scr(anchor + axes[i] * CONE1 * s)
            if a is None or b is None:
                continue
            if _seg_dist(cursor, a, b) < 7:
                return ("move", i)
        # rotation circles
        for i in range(3):
            u, v = axes[(i + 1) % 3], axes[(i + 2) % 3]
            best = np.inf
            for k in range(36):
                ang = k / 36 * 2 * math.pi
                p = scr(anchor + ARC_R * s
                        * (u * math.cos(ang) + v * math.sin(ang)))
                if p is not None:
                    best = min(best, float(np.linalg.norm(p - cursor)))
            if best < 7:
                return ("rot", i)
        return None

    def update_hover(self, px, py) -> bool:
        new = self.hit_test(px, py)
        if new != self.hover:
            self.hover = new
            return True
        return False

    # ----------------------------------------------------------- dragging

    def begin_drag(self, handle, px, py, modifiers) -> bool:
        state = self.anchor_and_axes()
        if state is None:
            return False
        anchor, axes = state
        vp = self.vp
        pp = self._pushpull_target()
        ft = None if pp is not None else self._fillet_target()
        if pp is not None:                    # face push/pull mode
            if handle != ("move", 2):
                return False
            obj = vp.scene.get(pp[0])
            if obj is None:
                return False
            originals = {pp[0]: obj.shape}
            self.vp.window_checkpoint("push/pull")
        elif ft is not None:                  # edge fillet mode
            if handle != ("move", 2):
                return False
            obj = vp.scene.get(ft[0])
            if obj is None:
                return False
            originals = {ft[0]: obj.shape}
            self.vp.window_checkpoint("fillet")
        else:
            objs = vp.selection.objects()
            if not objs:
                return False
            copy_mode = bool(modifiers & Qt.KeyboardModifier.AltModifier) and \
                handle[0] in ("move", "pad")
            self.vp.window_checkpoint("gumball " + handle[0])
            if copy_mode:
                new_objs = []
                for o in objs:
                    new_objs.append(vp.scene.add(g.copy_shape(o.shape),
                                                 layer_id=o.layer_id))
                vp.selection.set([o.id for o in new_objs])
                objs = new_objs
            originals = {o.id: o.shape for o in objs}
        origin, direction = vp.camera.ray_through(px, py, vp.width(),
                                                  vp.height())
        kind, i = handle
        ref = None
        if kind == "move" or kind == "scale":
            t = ray_line_parameter(origin, direction, anchor, axes[i])
            if t is None:
                return False
            ref = t
        elif kind == "pad":
            hit = ray_plane_any(origin, direction, anchor, axes[i])
            if hit is None:
                return False
            ref = hit
        elif kind == "rot":
            hit = ray_plane_any(origin, direction, anchor, axes[i])
            if hit is None:
                return False
            vec = hit - anchor
            if np.linalg.norm(vec) < 1e-9:
                return False
            ref = vec / np.linalg.norm(vec)
        self.drag = {
            "handle": handle, "anchor": anchor, "axes": axes,
            "originals": originals,
            "pp": (pp[0], pp[1]) if pp is not None else None,
            "fillet": (ft[0], list(ft[1])) if ft is not None else None,
            "ref": ref, "last_label": "", "offset": np.zeros(3),
            "typed": "", "armed": False, "moved": False,
        }
        return True

    def drag_to(self, px, py, modifiers) -> str:
        d = self.drag
        if d is None or d["typed"]:      # numeric entry overrides the mouse
            return d["last_label"] if d else ""
        vp = self.vp
        anchor, axes = d["anchor"], d["axes"]
        kind, i = d["handle"]
        origin, direction = vp.camera.ray_through(px, py, vp.width(),
                                                  vp.height())
        uniform = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        d["moved"] = True
        if kind == "pad":
            hit = ray_plane_any(origin, direction, anchor, axes[i])
            if hit is None:
                return d["last_label"]
            delta = hit - d["ref"]
            d["offset"] = np.asarray(delta, float)
            self._apply(lambda s: g.translate(s, tuple(delta)))
            d["last_label"] = ("move "
                               + vp.scene.format_length(float(
                                   np.linalg.norm(delta))))
            return d["last_label"]
        if kind == "move":
            t = ray_line_parameter(origin, direction, anchor, axes[i])
            if t is None:
                return d["last_label"]
            value = t - d["ref"]
            if vp.grid_snap and vp.grid_snap_step > 0:
                value = round(value / vp.grid_snap_step) * vp.grid_snap_step
        elif kind == "rot":
            hit = ray_plane_any(origin, direction, anchor, axes[i])
            if hit is None:
                return d["last_label"]
            vec = hit - anchor
            n = np.linalg.norm(vec)
            if n < 1e-9:
                return d["last_label"]
            vec = vec / n
            cosv = float(np.clip(np.dot(d["ref"], vec), -1, 1))
            sign = float(np.dot(np.cross(d["ref"], vec), axes[i]))
            value = math.degrees(math.acos(cosv)) * (1 if sign >= 0 else -1)
            if uniform:
                value = round(value / 15.0) * 15.0
        elif kind == "scale":
            t = ray_line_parameter(origin, direction, anchor, axes[i])
            if t is None or abs(d["ref"]) < 1e-9:
                return d["last_label"]
            value = t / d["ref"]
        else:
            return d["last_label"]
        return self.apply_scalar(value, uniform=uniform)

    def apply_scalar(self, value: float, uniform: bool = False) -> str:
        """Apply the move/rotate/scale transform for a single value and
        return its label. Shared by mouse drag and typed entry."""
        d = self.drag
        if d is None:
            return ""
        vp = self.vp
        kind, i = d["handle"]
        anchor, axes = d["anchor"], d["axes"]
        if kind == "move":
            if d.get("pp"):                   # face push/pull, not translate
                oid, fidx = d["pp"]
                orig = d["originals"].get(oid)
                if orig is not None and vp.scene.get(oid) is not None:
                    try:
                        vp.scene.replace_shape(
                            oid, g.push_pull(orig, fidx, value))
                    except g.GeometryError:
                        pass
                d["offset"] = np.asarray(axes[i] * value, float)
                label = "push/pull " + vp.scene.format_length(float(value))
            elif d.get("fillet"):             # edge fillet, radius = value
                oid, idxs = d["fillet"]
                orig = d["originals"].get(oid)
                radius = float(value)
                if orig is not None and vp.scene.get(oid) is not None:
                    if radius > 1e-4:
                        try:
                            edges = [g.edges_of(orig)[k] for k in idxs]
                            vp.scene.replace_shape(
                                oid, g.fillet_edges(orig, radius, edges=edges))
                        except (g.GeometryError, IndexError):
                            pass          # radius too big — keep last good
                    else:
                        vp.scene.replace_shape(oid, orig)   # 0 → no fillet
                d["offset"] = np.asarray(axes[i] * max(radius, 0.0), float)
                label = "fillet " + vp.scene.format_length(float(radius))
            else:
                delta = axes[i] * value
                d["offset"] = np.asarray(delta, float)
                self._apply(lambda s: g.translate(s, tuple(delta)))
                label = "move " + vp.scene.format_length(float(value))
        elif kind == "rot":
            self._apply(lambda s: g.rotate(s, tuple(anchor),
                                           tuple(axes[i]), value))
            label = f"rotate {value:.1f}°"
        elif kind == "scale":
            if abs(value) < 1e-4:
                return d["last_label"]
            if uniform:
                self._apply(lambda s: g.scale(s, tuple(anchor), value))
                label = f"scale {value:.3f} (uniform)"
            else:
                self._apply(lambda s: g.scale_along_axis(
                    s, tuple(anchor), tuple(axes[i]), value))
                label = f"scale {value:.3f}"
        else:
            return d["last_label"]
        d["last_label"] = label
        return label

    # -------------------------------------------------------- numeric entry

    def accepts_typing(self) -> bool:
        return self.drag is not None and self.drag["handle"][0] in _ONE_DOF

    def type_char(self, ch: str) -> bool:
        """Feed a keystroke ('0'..'9', '.', '-', 'back') to numeric entry.
        Returns True if consumed."""
        d = self.drag
        if d is None or d["handle"][0] not in _ONE_DOF:
            return False
        if ch == "back":
            d["typed"] = d["typed"][:-1]
        elif ch in "0123456789.-":
            d["typed"] += ch
        else:
            return False
        self._preview_typed()
        return True

    def _parse_typed(self):
        s = self.drag["typed"]
        if s in ("", "-", ".", "-.", "+"):
            return None
        try:
            return float(s)
        except ValueError:
            return None

    def _preview_typed(self):
        val = self._parse_typed()
        if val is None:
            self._apply(lambda s: s)          # revert to originals
            self.drag["offset"] = np.zeros(3)
            self.drag["last_label"] = ""
        else:
            self.apply_scalar(val)

    def commit_typed(self) -> bool:
        d = self.drag
        if d is None:
            return False
        val = self._parse_typed()
        if val is None:
            return False
        self.apply_scalar(val)
        self.end_drag()
        return True

    def arm(self):
        """Keep an un-dragged handle click alive so a value can be typed."""
        if self.drag is not None and self.drag["handle"][0] in _ONE_DOF:
            self.drag["armed"] = True

    def _apply(self, fn):
        d = self.drag
        vp = self.vp
        for obj_id, original in d["originals"].items():
            if vp.scene.get(obj_id) is None:
                continue
            try:
                vp.scene.replace_shape(obj_id, fn(original))
            except g.GeometryError:
                pass

    def end_drag(self):
        d = self.drag
        if d is not None and float(np.linalg.norm(d["offset"])) > 1e-9:
            if d.get("pp"):
                self._resync_face(d)
            elif d.get("fillet"):
                self._clear_filleted_edges(d)
        self.drag = None

    def _clear_filleted_edges(self, d):
        """A committed fillet consumes the picked edges (their indices now
        point at unrelated edges of the rebuilt solid), so drop them from the
        sub-object selection rather than leave the handle on stale edges."""
        oid, idxs = d["fillet"]
        sel = self.vp.selection
        for i in idxs:
            if (oid, "edge", i) in sel.subobjects:
                sel.toggle_subobject(oid, "edge", i)

    def _resync_face(self, d):
        """push_pull rebuilds the solid, so the picked face index goes stale.
        Re-point the sub-object selection at the moved face on the new solid
        (nearest same-facing planar face to where it ended up) so repeated
        pulls keep working."""
        oid, old = d["pp"]
        obj = self.vp.scene.get(oid)
        if obj is None:
            return
        normal = np.asarray(d["axes"][2], float)
        target = np.asarray(d["anchor"], float) + np.asarray(d["offset"], float)
        try:
            faces = g.faces_of(obj.shape)
        except g.GeometryError:
            return
        best_i, best_score = None, np.inf
        for i, f in enumerate(faces):
            try:
                fn = np.asarray(g.face_normal(f), float)
                c = np.asarray(g.centroid(f), float)
            except g.GeometryError:
                continue
            fn = fn / (np.linalg.norm(fn) or 1.0)
            if np.dot(fn, normal) < 0.9:        # same orientation only
                continue
            score = float(np.linalg.norm(c - target))
            if score < best_score:
                best_score, best_i = score, i
        if best_i is None or best_i == old:
            return
        sel = self.vp.selection
        if (oid, "face", old) in sel.subobjects:
            sel.toggle_subobject(oid, "face", old)
        if (oid, "face", best_i) not in sel.subobjects:
            sel.toggle_subobject(oid, "face", best_i)

    def cancel_drag(self):
        d = self.drag
        if d is None:
            return
        vp = self.vp
        for obj_id, original in d["originals"].items():
            if vp.scene.get(obj_id) is not None:
                vp.scene.replace_shape(obj_id, original)
        self.vp.window_discard_checkpoint()
        self.drag = None


def _seg_dist(p, a, b) -> float:
    ab = b - a
    denom = float(np.dot(ab, ab))
    if denom < 1e-12:
        return float(np.linalg.norm(p - a))
    t = float(np.clip(np.dot(p - a, ab) / denom, 0, 1))
    return float(np.linalg.norm(p - (a + ab * t)))


def _in_poly(p, poly) -> bool:
    inside = False
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        if ((a[1] > p[1]) != (b[1] > p[1])):
            x = a[0] + (p[1] - a[1]) / (b[1] - a[1]) * (b[0] - a[0])
            if p[0] < x:
                inside = not inside
    return inside
