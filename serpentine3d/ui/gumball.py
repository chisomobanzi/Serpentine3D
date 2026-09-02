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


def _turned(p, anchor, axis, degrees):
    """`p` turned about the line through `anchor` along `axis`."""
    k = np.asarray(axis, float)
    k = k / (np.linalg.norm(k) or 1.0)
    v = np.asarray(p, float) - anchor
    a = math.radians(degrees)
    return (anchor + v * math.cos(a) + np.cross(k, v) * math.sin(a)
            + k * float(np.dot(k, v)) * (1.0 - math.cos(a)))


def _alt_held(modifiers) -> bool:
    """Alt state, robust to a Qt KeyboardModifiers flag or a plain int."""
    m = getattr(modifiers, "value", modifiers)          # Qt flag -> int
    return bool(int(m) & int(Qt.KeyboardModifier.AltModifier.value))


def _ctrl_held(modifiers) -> bool:
    """Ctrl state, read the same way, for the arrow that extrudes."""
    m = getattr(modifiers, "value", modifiers)          # Qt flag -> int
    return bool(int(m) & int(Qt.KeyboardModifier.ControlModifier.value))


# The filled box on the shaft grows the thing; scale is the hollow box on the
# far side of the pivot, on a dashed leader that mirrors the shaft. Each axis
# then reads as one handle with an end of its own either way, and two boxes
# that look different and sit at opposite ends are never mistaken for each
# other, so neither asks you to hold a key down while you drag.
# DASH0 and SCALE_POS are distances back along -axis: see _leader.
EXT_POS = 0.6
DASH0, SCALE_POS = 0.18, 1.66
ARC_R = 0.82
PAD0, PAD1 = 0.28, 0.5

# handle ids: ("move",axis) ("pad",axis) ("rot",axis) ("scale",axis)
#             ("ext",axis) — the filled box, where there is something to grow
_ONE_DOF = ("move", "rot", "scale", "ext")   # take a single typed value


class Gumball:
    def __init__(self, viewport):
        self.vp = viewport
        self.enabled = True
        if viewport.config is not None:
            self.enabled = bool(viewport.config.get("gumball", default=True))
        self.hover = None
        self.drag = None          # dict with handle, originals, refs
        self._geom_cache = None
        self._sweep_key = None    # what _sweep_sources was last asked about
        self._sweep_cache: list = []
        self._sweep_axes: dict = {}

    # ----------------------------------------------------------- state

    def active(self) -> bool:
        vp = self.vp
        # A sheet on its own has nothing for a gumball to hold — paper geometry
        # is dragged by its own ink — but inside a detail what is picked is a
        # model object, so it gets the handles the model window gives it.
        on_model = vp.space == "model" or vp._detail_eye() is not None
        if not (self.enabled and on_model and not vp.point_mode):
            return False
        if self.drag is not None:            # a drag stays live to its end
            return True
        return (bool(vp.selection.ids)
                or self._cv_target() is not None
                or self._pushpull_target() is not None
                or self._multiface_target() is not None
                or self._fillet_target() is not None)

    def _cv_target(self):
        """({obj_id: [index]}, mean position) for the held control points.

        Only points a pane is showing count. PointsOff leaves the selection
        as it found it, and a handle standing on a point nobody can see is
        not something anybody is still holding.
        """
        subs = getattr(self.vp.selection, "subobjects", None)
        if not subs:
            return None
        held: dict = {}
        at = []
        for oid, kind, idx in subs:
            if kind != "cv" or oid not in self.vp.cv_enabled:
                continue
            obj = self.vp.scene.get(oid)
            pts = None if obj is None else self.vp._cv_points(obj)
            if pts is None or not (0 <= idx < len(pts)):
                continue
            held.setdefault(oid, []).append(int(idx))
            at.append(np.asarray(pts[idx], float))
        if not at:
            return None
        return held, np.mean(at, axis=0)

    def _pushpull_target(self):
        """For a single selected planar face, return
        (obj_id, face_index, centroid, (t1, t2, normal)); else None.

        This is what turns the gumball into a face handle: an axis-aligned
        arrow that moves the face in/out and rebuilds the solid. A planar
        face pushes/pulls along its normal (geometry.push_pull); a curved
        face offsets along its outward direction (geometry.offset_face), so
        e.g. a cylinder's wall grows/shrinks its radius. Returns
        (oid, face_index, centroid, (t1, t2, axis), planar)."""
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
            face = flist[fidx]
            try:
                axis = np.asarray(g.face_normal(face), float)   # planar
                centroid = np.asarray(g.centroid(face), float)
                planar = True
            except g.GeometryError:          # curved -> offset along outward
                pt, nrm = g.face_point_normal(face)   # sampled on the surface
                centroid = np.asarray(pt, float)
                axis = np.asarray(nrm, float)
                planar = False
        except g.GeometryError:
            return None
        length = float(np.linalg.norm(axis))
        if length < 1e-9:
            return None
        axis = axis / length
        ref = (np.array([1.0, 0.0, 0.0]) if abs(axis[0]) < 0.9
               else np.array([0.0, 1.0, 0.0]))
        t1 = np.cross(axis, ref)
        t1 = t1 / (np.linalg.norm(t1) or 1.0)
        t2 = np.cross(axis, t1)
        return oid, fidx, centroid, (t1, t2, axis), planar

    def _face_axis(self, face):
        """(centroid/sample-point, outward unit normal) for a face, planar
        or curved; None if it has no usable normal."""
        try:
            nrm = np.asarray(g.face_normal(face), float)     # planar
            c = np.asarray(g.centroid(face), float)
        except g.GeometryError:
            pt, nrm = g.face_point_normal(face)              # curved
            c, nrm = np.asarray(pt, float), np.asarray(nrm, float)
        length = float(np.linalg.norm(nrm))
        if length < 1e-9:
            return None
        return c, nrm / length

    def _multiface_target(self):
        """For 2+ selected faces on one solid, return
        (obj_id, [face_index...], anchor, (t1, t2, axis)); else None.

        All the faces offset by the same distance along their own normals
        (geometry.offset_faces) — inflate/deflate a shape, grow a slab from
        both sides, etc. The handle sits at the faces' mean point along the
        summed outward normal (first face's normal if they cancel)."""
        subs = getattr(self.vp.selection, "subobjects", None)
        if not subs:
            return None
        faces = [(oid, idx) for (oid, kind, idx) in subs if kind == "face"]
        if len(faces) < 2:
            return None
        oid = faces[0][0]
        idxs = [idx for (o, idx) in faces if o == oid]
        if len(idxs) < 2:                    # need 2+ on the same solid
            return None
        obj = self.vp.scene.get(oid)
        if obj is None:
            return None
        try:
            flist = g.faces_of(obj.shape)
            if any(not (0 <= i < len(flist)) for i in idxs):
                return None
            axes = [self._face_axis(flist[i]) for i in idxs]
        except g.GeometryError:
            return None
        if any(a is None for a in axes):
            return None
        pts = [c for c, _ in axes]
        normals = [n for _, n in axes]
        anchor = np.mean(pts, axis=0)
        axis = np.sum(normals, axis=0)
        if np.linalg.norm(axis) < 1e-6:      # opposing faces cancel
            axis = normals[0]
        axis = axis / (np.linalg.norm(axis) or 1.0)
        ref = (np.array([1.0, 0.0, 0.0]) if abs(axis[0]) < 0.9
               else np.array([0.0, 1.0, 0.0]))
        t1 = np.cross(axis, ref)
        t1 = t1 / (np.linalg.norm(t1) or 1.0)
        t2 = np.cross(axis, t1)
        return oid, idxs, anchor, (t1, t2, axis)

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

    def _sweep_sources(self) -> list:
        """Everything held that a filled box could sweep, or an empty list.

        Held edges grow a surface each and leave the object they came off
        alone. A curve keeps itself and hands you a new surface, so the
        curve you were drawing with is still there to go on using. A
        surface is consumed by the solid it becomes: a spare copy of it
        buried in the solid's own face is clutter you cannot see to pick.
        Anything else — a solid, a mesh, a held control point — has
        nothing here to grow.

        The answer is kept from one call to the next, because it reads
        geometry and is asked once a frame and again on every mouse move.
        The selection and the scene revision together say when it can
        have changed.
        """
        sel = self.vp.selection
        subs = list(getattr(sel, "subobjects", []))
        key = (getattr(self.vp.scene, "revision", 0), tuple(sel.ids),
               tuple(subs))
        if self._sweep_key == key:
            return self._sweep_cache
        sources: list = []
        kinds = {k for (_o, k, _i) in subs}
        edges = [(oid, idx) for (oid, kind, idx) in subs if kind == "edge"]
        if "cv" in kinds:
            pass                             # the gumball is on the points
        elif edges:
            for oid, idx in edges:
                obj = self.vp.scene.get(oid)
                if obj is None:
                    continue
                try:
                    elist = g.edges_of(obj.shape)
                except g.GeometryError:
                    continue
                if 0 <= idx < len(elist):
                    sources.append({"src": elist[idx], "cap": False,
                                    "into": None, "layer": obj.layer_id})
        else:
            for obj in sel.objects():
                if obj.kind == "curve":
                    # cap so that a closed curve gives the box you were
                    # after and not the four walls of it; extrude ignores
                    # it when the curve is open.
                    sources.append({"src": obj.shape, "cap": True,
                                    "into": None, "layer": obj.layer_id})
                elif obj.kind == "surface":
                    sources.append({"src": obj.shape, "cap": False,
                                    "into": obj.id, "layer": obj.layer_id})
        self._sweep_key, self._sweep_cache = key, sources
        self._sweep_axes = {}
        return sources

    def _extrude_target(self, handle, modifiers, direction=None):
        """What a translate arrow with Ctrl held would grow, or None.

        A line pulled sideways is a plane, and the gumball is already
        standing on the line with an arrow pointing the way; without this
        the only road from a line to a surface is to leave the gumball,
        type extrude and pick the line again. Ctrl is the whole
        difference.

        With a direction, only what that direction would actually add to
        is given back, so a Ctrl-drag along a line's own length falls
        through to moving it rather than leaving a flattened surface lying
        on top of it.
        """
        if handle[0] != "ext" and not (handle[0] == "move"
                                       and _ctrl_held(modifiers)):
            return None
        sources = self._sweep_sources()
        if direction is not None:
            sources = [s for s in sources
                       if not g.sweep_adds_nothing(s["src"], direction)]
        return sources or None

    def _can_extrude(self, direction=None) -> bool:
        """Is there anything here a filled box could grow?

        Asked per axis, given a direction: a flat surface swept within its
        own plane, or a straight line swept along its own length, comes
        back as what it already was, so no box is drawn on that axis and
        the arrow that moves it is all that is there.
        """
        sources = self._sweep_sources()
        if not sources or direction is None:
            return bool(sources)
        k = tuple(round(float(v), 6) for v in direction)
        hit = self._sweep_axes.get(k)
        if hit is None:
            try:
                hit = any(not g.sweep_adds_nothing(s["src"], k)
                          for s in sources)
            except g.GeometryError:
                # This runs inside paint, once per axis. A shape the
                # geometry cannot measure is not worth a pane that stops
                # drawing for the rest of the session: draw the handle and
                # let the extrude itself say what is wrong with it.
                hit = True
            self._sweep_axes[k] = hit
        return hit

    def _face_mode(self) -> bool:
        """Is the gumball acting as a face push/pull or offset handle now?"""
        if self.drag is not None:
            return bool(self.drag.get("pp") or self.drag.get("multiface"))
        return (self._pushpull_target() is not None
                or self._multiface_target() is not None)

    def _fillet_mode(self) -> bool:
        """Is the gumball acting as an edge fillet handle right now?"""
        if self.drag is not None:
            return bool(self.drag.get("fillet"))
        return (self._pushpull_target() is None
                and self._fillet_target() is not None)

    def anchor_and_axes(self):
        if self.drag is None:
            cv = self._cv_target()
            if cv is not None:               # a held control point comes first
                cp = self._plane()
                return cv[1], (np.asarray(cp.xdir), np.asarray(cp.ydir),
                               np.asarray(cp.normal))
            pp = self._pushpull_target()
            if pp is not None:               # face push/pull takes priority
                _, _, centroid, basis, _ = pp
                return centroid, basis
            mf = self._multiface_target()
            if mf is not None:               # then multi-face offset
                _, _, anchor, basis = mf
                return anchor, basis
            ft = self._fillet_target()
            if ft is not None:               # then edge fillet
                _, _, anchor, basis = ft
                return anchor, basis
        objs = self.vp.selection.objects()
        if not objs:
            return None
        # Once per frame while you orbit, and again on every mouse move for
        # the hover test — so it asks each object for bounds it has already
        # been asked for. SceneObject.bbox remembers them; the union is one
        # array operation because a per-object numpy loop over a whole
        # drawing costs more than the measuring used to.
        boxes = np.array([o.bbox() for o in objs], float)
        anchor = (boxes[:, 0].min(axis=0) + boxes[:, 1].max(axis=0)) / 2
        cp = self._plane()
        return anchor, (np.asarray(cp.xdir), np.asarray(cp.ydir),
                        np.asarray(cp.normal))

    def _plane(self):
        """The plane the axes lie in.

        Inside a detail it is the plane the detail looks at, so two arrows lie
        along the view and the third runs away from you — which is the way the
        drawing is being read. The construction plane the model window is set
        to would put all three of them at an angle to a front view.
        """
        eye = self.vp._detail_eye()
        if eye is None:
            return self.vp.cplane
        from .layout_view import detail_plane
        return detail_plane(eye.detail)

    def _project(self, pts):
        """Where gumball geometry lands on screen, frame or no frame.

        The handles are drawn over the drawing rather than in it, so a detail's
        edge does not cut them off the way it cuts off the model they hold: an
        object that nearly fills its window would otherwise have handles nobody
        can reach.
        """
        vp = self.vp
        return vp._eye().project(np.asarray(pts, float), vp.width(),
                                 vp.height(), clipped=False)

    def _view_dir(self, anchor):
        """Which way the eye looks where the gumball is."""
        vp = self.vp
        scr = self._project([anchor])[0]
        _origin, direction = vp._eye().ray_through(
            float(scr[0]), float(scr[1]), vp.width(), vp.height())
        return np.asarray(direction, float)

    def _usable(self, kind, axis, axes, vdir) -> bool:
        """Whether a handle can be dragged from where it is being looked at.

        An arrow pointing straight away from you, and a circle or pad seen
        exactly edge-on, are a ray parallel to the line or the plane it would
        be dragged along: that has no answer, or every answer, so the drag is
        refused. A handle that would be refused is better not drawn and not
        hit at all — in a detail, which looks squarely down one axis, they
        would otherwise lie right on top of the handles that do work.
        """
        if vdir is None:
            return True
        along = abs(float(np.dot(np.asarray(axes[axis], float), vdir)))
        if kind in ("move", "scale", "ext"):
            return along < 1.0 - 1e-6       # the line is not the line of sight
        return along > 1e-6                 # the plane faces you at all

    def _draw_anchor(self):
        """Where the gumball is drawn this frame. During a move/pad drag
        it tracks the geometry (frozen anchor + applied offset); rotate
        and scale keep the anchor as the fixed pivot. An extrude stays put
        too: the curve it is growing from has not gone anywhere.
        """
        if self.drag is None:
            state = self.anchor_and_axes()
            return None if state is None else (state[0], state[1])
        d = self.drag
        anchor = np.asarray(d["anchor"], float)
        if d["handle"][0] in ("move", "pad") and not d.get("extrude"):
            anchor = anchor + d["offset"]
        return anchor, d["axes"]

    def _size_world(self, anchor) -> float:
        """World length that projects to SIZE_PX pixels at the anchor."""
        right, _ = self.vp._eye().right_up()
        scr = self._project(np.stack([anchor, anchor + right]))
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
        vdir = self._view_dir(anchor)
        GL.glDisable(GL.GL_DEPTH_TEST)

        def color_for(handle, base):
            if self.hover == handle or (
                    self.drag and self.drag["handle"] == handle):
                return HOVER_COLOR
            return base

        # rotation circles
        for i in range(3):
            if not self._usable("rot", i, axes, vdir):
                continue
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
            if not self._usable("pad", i, axes, vdir):
                continue
            u, v = axes[(i + 1) % 3], axes[(i + 2) % 3]
            c0 = anchor + (u + v) * PAD0 * s
            c1 = anchor + u * PAD1 * s + v * PAD0 * s
            c2 = anchor + (u + v) * PAD1 * s
            c3 = anchor + u * PAD0 * s + v * PAD1 * s
            tris = np.asarray([c0, c1, c2, c0, c2, c3], np.float32)
            self._tris(mvp, tris, (*color_for(("pad", i), AXIS_COLORS[i]),
                                   PAD_ALPHA))

        # shafts + cones + the two boxes
        for i in range(3):
            if not self._usable("move", i, axes, vdir):
                continue
            axis = axes[i]
            color = color_for(("move", i), AXIS_COLORS[i])
            a0 = anchor + axis * SHAFT0 * s
            a1 = anchor + axis * SHAFT1 * s
            self._lines(mvp, np.asarray([a0, a1], np.float32),
                        (*color, 1.0), 2.4)
            self._cone(mvp, anchor, axis, axes[(i + 1) % 3],
                       axes[(i + 2) % 3], s, (*color, 1.0))
            kc = color_for(("scale", i), AXIS_COLORS[i])
            self._leader(mvp, anchor, axis, s, (*kc, 0.85))
            self._knob(mvp, anchor - axis * SCALE_POS * s, s,
                       (*kc, 1.0), fill=False)
            if self._can_extrude(axis):
                self._knob(mvp, anchor + axis * EXT_POS * s, s,
                           (*color_for(("ext", i), AXIS_COLORS[i]), 1.0))
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
        # The edge gets the same filled box as everything else, so it is not
        # the one case left needing the keyboard: the arrow rounds the edge
        # off, the box pulls a surface out of it.
        ext = (HOVER_COLOR if self.hover == ("ext", 2) else PP_COLOR)
        self._knob(mvp, anchor + n * EXT_POS * s, s, (*ext, 1.0))
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

    def _knob(self, mvp, center, s, color, fill: bool = True):
        """A box facing you: filled to grow the thing, hollow to scale it."""
        cam = self.vp._eye()
        right, up = cam.right_up()
        r = 0.06 * s
        c0 = center - right * r - up * r
        c1 = center + right * r - up * r
        c2 = center + right * r + up * r
        c3 = center - right * r + up * r
        if fill:
            self._tris(mvp, np.asarray([c0, c1, c2, c0, c2, c3], np.float32),
                       color)
            return
        self._lines(mvp, np.asarray([c0, c1, c1, c2, c2, c3, c3, c0],
                                    np.float32), color, 1.8)

    def _leader(self, mvp, anchor, axis, s, color):
        """The dashed run back from the pivot to the scale box.

        It leaves the anchor where the shaft does and goes the other way, so
        the hollow box is not a stray mark floating behind the gumball: the
        dashes say which axis it belongs to and that it is the other end of
        the same handle the arrow is one end of.
        """
        n, run = 6, SCALE_POS - DASH0 - 0.06
        pts = []
        for k in range(n):
            t0 = DASH0 + run * (k / n)
            t1 = t0 + run * 0.55 / n
            pts.extend([anchor - axis * t0 * s, anchor - axis * t1 * s])
        self._lines(mvp, np.asarray(pts, np.float32), color, 1.4)

    def _paper(self, pts):
        """The points to upload: as they are, or where they appear on a sheet.

        The handles are built in the model, like everything a detail shows, so
        on a sheet they come back out through the window that is showing them
        rather than landing on the paper at the model's own numbers. Both
        uploads go through here, so nothing drawn can miss it.
        """
        eye = self.vp._detail_eye()
        return pts if eye is None else eye.to_paper(pts)

    def _lines(self, mvp, pts, color, width):
        from .viewport import rebased
        vp = self.vp
        # On paper the anchor is None and rebased is a plain cast; in the
        # model it is the frame anchor already folded into `mvp`, so far
        # handles hold as still as the geometry they stand on.
        pts = self._paper(pts)
        vp._preview.update(rebased(pts.reshape(-1, 3), vp._frame_anchor))
        vp._set_line_uniforms(mvp, color)
        vp._line_width(width)
        GL.glBindVertexArray(vp._preview.vao)
        GL.glDrawArrays(GL.GL_LINES, 0, len(pts.reshape(-1, 3)))

    def _tris(self, mvp, pts, color):
        from .viewport import rebased
        vp = self.vp
        pts = self._paper(pts)
        vp._preview.update(rebased(pts, vp._frame_anchor))
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
        scr = self._project([anchor])[0]
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
        vdir = self._view_dir(anchor)     # what is not worth testing for

        def scr(p):
            out = self._project([p])[0]
            return out[:2] if out[2] > 0 else None

        cursor = np.array([px, py])

        if self._face_mode():                 # only the push/pull arrow
            n = axes[2]
            a = scr(anchor - n * CONE1 * s)
            b = scr(anchor + n * CONE1 * s)
            if a is not None and b is not None and _seg_dist(cursor, a, b) < 8:
                return ("move", 2)
            return None

        if self._fillet_mode():               # radius arrow, and the box on it
            n = axes[2]
            p = scr(anchor + n * EXT_POS * s)
            if p is not None and np.linalg.norm(p - cursor) < 6.5:
                return ("ext", 2)
            a = scr(anchor)
            b = scr(anchor + n * CONE1 * s)
            if a is not None and b is not None and _seg_dist(cursor, a, b) < 8:
                return ("move", 2)
            return None

        # the boxes (smallest targets first, and the filled one sits on the
        # shaft, so it has to be asked about before the arrow it lies along)
        for kind, along in (("ext", EXT_POS), ("scale", -SCALE_POS)):
            for i in range(3):
                if not self._usable(kind, i, axes, vdir):
                    continue
                if kind == "ext" and not self._can_extrude(axes[i]):
                    continue
                p = scr(anchor + axes[i] * along * s)
                if p is not None and np.linalg.norm(p - cursor) < 6.5:
                    return (kind, i)
        # pads
        for i in range(3):
            if not self._usable("pad", i, axes, vdir):
                continue
            u, v = axes[(i + 1) % 3], axes[(i + 2) % 3]
            corners = [anchor + (u * a + v * b) * s
                       for a, b in ((PAD0, PAD0), (PAD1, PAD0),
                                    (PAD1, PAD1), (PAD0, PAD1))]
            pts = [scr(c) for c in corners]
            if all(p is not None for p in pts) and _in_poly(cursor, pts):
                return ("pad", i)
        # arrows (shaft + cone)
        for i in range(3):
            if not self._usable("move", i, axes, vdir):
                continue
            a = scr(anchor + axes[i] * SHAFT0 * s)
            b = scr(anchor + axes[i] * CONE1 * s)
            if a is None or b is None:
                continue
            if _seg_dist(cursor, a, b) < 7:
                return ("move", i)
        # rotation circles
        for i in range(3):
            if not self._usable("rot", i, axes, vdir):
                continue
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
        cv = self._cv_target()
        pp = None if cv is not None else self._pushpull_target()
        mf = (None if (cv is not None or pp is not None)
              else self._multiface_target())
        ex = (None if (cv is not None or pp is not None or mf is not None)
              else self._extrude_target(handle, modifiers,
                                       axes[handle[1]]))
        ft = (None if (cv is not None or pp is not None or mf is not None
                       or ex is not None) else self._fillet_target())
        if handle[0] == "ext" and ex is None:
            # Nothing here grows. Doing nothing beats quietly moving the
            # thing you were trying to grow.
            return False
        if cv is not None:                    # held control points
            originals = {}
            for oid in cv[0]:
                obj = vp.scene.get(oid)
                if obj is not None:
                    originals[oid] = obj.shape
            if not originals:
                return False
            self.vp.window_checkpoint("gumball " + handle[0])
        elif pp is not None:                  # face push/pull mode
            if handle != ("move", 2):
                return False
            obj = vp.scene.get(pp[0])
            if obj is None:
                return False
            originals = {pp[0]: obj.shape}
            self.vp.window_checkpoint("push/pull")
        elif mf is not None:                  # multi-face offset mode
            if handle != ("move", 2):
                return False
            obj = vp.scene.get(mf[0])
            if obj is None:
                return False
            originals = {mf[0]: obj.shape}
            self.vp.window_checkpoint("push faces")
        elif ex is not None:                  # Ctrl: grow it, do not move it
            # Nothing is built here. A drag that never leaves the anchor has
            # grown nothing, and a surface of no height is not something the
            # drawing should be asked to hold even for a frame.
            originals = {s["into"]: vp.scene.get(s["into"]).shape
                         for s in ex if s["into"] is not None}
            self.vp.window_checkpoint("gumball extrude")
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
        origin, direction = vp._eye().ray_through(px, py, vp.width(),
                                                  vp.height())
        kind, i = handle
        ref = None
        if kind in ("move", "scale", "ext"):
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
            "cvs": dict(cv[0]) if cv is not None else None,
            "pp": (pp[0], pp[1]) if pp is not None else None,
            "pp_planar": bool(pp[4]) if pp is not None else True,
            "multiface": (mf[0], list(mf[1])) if mf is not None else None,
            "fillet": (ft[0], list(ft[1])) if ft is not None else None,
            "chamfer": ft is not None and _alt_held(modifiers),
            "extrude": ex, "made": {},
            "ref": ref, "last_label": "", "offset": np.zeros(3),
            "typed": "", "armed": False, "moved": False,
        }
        vp.selection.rebuilding = self.rebuilding_id()
        return True

    def drag_to(self, px, py, modifiers) -> str:
        d = self.drag
        if d is None or d["typed"]:      # numeric entry overrides the mouse
            return d["last_label"] if d else ""
        vp = self.vp
        anchor, axes = d["anchor"], d["axes"]
        kind, i = d["handle"]
        origin, direction = vp._eye().ray_through(px, py, vp.width(),
                                                  vp.height())
        uniform = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        d["moved"] = True
        if d.get("fillet"):                  # hold Alt to chamfer instead
            d["chamfer"] = _alt_held(modifiers)
        if kind == "pad":
            hit = ray_plane_any(origin, direction, anchor, axes[i])
            if hit is None:
                return d["last_label"]
            delta = hit - d["ref"]
            d["offset"] = np.asarray(delta, float)
            self._move_by(delta)
            d["last_label"] = ("move "
                               + vp.scene.format_length(float(
                                   np.linalg.norm(delta))))
            return d["last_label"]
        if kind in ("move", "ext"):
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
        if kind in ("move", "ext"):
            if d.get("extrude"):              # the box, or Ctrl and an arrow
                self._extrude_by(axes[i], float(value))
                d["offset"] = np.asarray(axes[i] * value, float)
                label = "extrude " + vp.scene.format_length(float(value))
            elif d.get("pp"):                 # face push/pull or offset
                oid, fidx = d["pp"]
                orig = d["originals"].get(oid)
                planar = d.get("pp_planar", True)
                if orig is not None and vp.scene.get(oid) is not None:
                    try:
                        new = (g.push_pull(orig, fidx, value) if planar
                               else g.offset_face(orig, fidx, value))
                        vp.scene.replace_shape(oid, new)
                    except g.GeometryError:
                        pass
                d["offset"] = np.asarray(axes[i] * value, float)
                verb = "push/pull" if planar else "offset"
                label = verb + " " + vp.scene.format_length(float(value))
            elif d.get("multiface"):          # offset every selected face
                oid, idxs = d["multiface"]
                orig = d["originals"].get(oid)
                if orig is not None and vp.scene.get(oid) is not None:
                    if abs(value) > 1e-4:
                        try:
                            vp.scene.replace_shape(
                                oid, g.offset_faces(orig,
                                                    {k: value for k in idxs}))
                        except g.GeometryError:
                            pass          # too big — keep last good
                    else:
                        vp.scene.replace_shape(oid, orig)   # 0 → original
                d["offset"] = np.asarray(axes[i] * value, float)
                label = (f"push {len(idxs)} faces "
                         + vp.scene.format_length(float(value)))
            elif d.get("fillet"):             # edge fillet/chamfer, radius=value
                oid, idxs = d["fillet"]
                orig = d["originals"].get(oid)
                radius = float(value)
                chamfer = bool(d.get("chamfer"))
                if orig is not None and vp.scene.get(oid) is not None:
                    if radius > 1e-4:
                        try:
                            edges = [g.edges_of(orig)[k] for k in idxs]
                            vp.scene.replace_shape(
                                oid, g.fillet_edges(orig, radius, edges=edges,
                                                    chamfer=chamfer))
                        except (g.GeometryError, IndexError):
                            pass          # too big — keep last good
                    else:
                        vp.scene.replace_shape(oid, orig)   # 0 → no fillet
                d["offset"] = np.asarray(axes[i] * max(radius, 0.0), float)
                verb = "chamfer" if chamfer else "fillet"
                label = verb + " " + vp.scene.format_length(float(radius))
            else:
                delta = axes[i] * value
                d["offset"] = np.asarray(delta, float)
                self._move_by(delta)
                label = "move " + vp.scene.format_length(float(value))
        elif kind == "rot":
            self._turn_by(anchor, axes[i], value)
            label = f"rotate {value:.1f}°"
        elif kind == "scale":
            if abs(value) < 1e-4:
                return d["last_label"]
            if uniform:
                self._scale_by(anchor, None, value)
                label = f"scale {value:.3f} (uniform)"
            else:
                self._scale_by(anchor, axes[i], value)
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

    # What is being held is either whole objects or some of one object's
    # control points, and every handle has to do the same thing to both. A
    # shape transform says nothing about where a single pole should end up,
    # so each of these says it once, in the two ways it has to be said.

    def _move_by(self, delta):
        if self.drag.get("cvs"):
            self._apply_cvs(lambda p: p + delta)
        else:
            self._apply(lambda s: g.translate(s, tuple(delta)))

    def _turn_by(self, anchor, axis, degrees):
        if self.drag.get("cvs"):
            self._apply_cvs(lambda p: _turned(p, anchor, axis, degrees))
        else:
            self._apply(lambda s: g.rotate(s, tuple(anchor), tuple(axis),
                                           degrees))

    def _scale_by(self, anchor, axis, value):
        """About `anchor`, along `axis`, or every way if `axis` is None."""
        cvs = self.drag.get("cvs")
        if axis is None:
            if cvs:
                self._apply_cvs(lambda p: anchor + (p - anchor) * value)
            else:
                self._apply(lambda s: g.scale(s, tuple(anchor), value))
        elif cvs:
            self._apply_cvs(
                lambda p: p + axis * float(np.dot(p - anchor, axis))
                * (value - 1.0))
        else:
            self._apply(lambda s: g.scale_along_axis(
                s, tuple(anchor), tuple(axis), value))

    def _apply_cvs(self, at):
        """Put each held control point where `at` says it goes.

        Measured from the shape the drag began with every time, so what the
        curve looks like depends on the drag so far and not on how many mouse
        moves it took to get here: run the point out and back and the curve is
        the one you started with.
        """
        d = self.drag
        vp = self.vp
        for obj_id, idxs in d["cvs"].items():
            original = d["originals"].get(obj_id)
            obj = vp.scene.get(obj_id)
            if original is None or obj is None:
                continue
            surface = obj.kind == "surface"
            try:
                was = (g.surface_control_points(original)[0] if surface
                       else g.get_control_points(original))
                shape = original
                for i in idxs:
                    to = tuple(float(v) for v in at(np.asarray(was[i], float)))
                    shape = (g.move_surface_control_point(shape, i, to)
                             if surface
                             else g.move_control_point(shape, i, to))
                vp.scene.replace_shape(obj_id, shape)
            except (g.GeometryError, IndexError):
                pass

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

    def _extrude_by(self, axis, value):
        """Rebuild what the drag is growing, at the distance it stands at now.

        Back at nothing is back at nothing: whatever the drag made goes, so
        that pulling out and changing your mind leaves the drawing as it was
        rather than with a duplicate of the line lying on the line. That is
        also what makes a drag that ends at zero cost nothing to undo.
        """
        d, vp = self.drag, self.vp
        for k, s in enumerate(d["extrude"]):
            oid = d["made"].get(k, s["into"])
            if abs(value) < 1e-9:
                if s["into"] is None and oid is not None:
                    vp.scene.remove(oid)
                    d["made"].pop(k, None)
                elif s["into"] is not None:
                    vp.scene.replace_shape(oid, s["src"])
                continue
            try:
                grown = self._grown(s, axis, value)
            except g.GeometryError:
                continue                     # too far — keep the last good one
            if oid is None:
                d["made"][k] = vp.scene.add(grown, layer_id=s["layer"]).id
            elif vp.scene.get(oid) is not None:
                vp.scene.replace_shape(oid, grown)

    def _grown(self, source, axis, value):
        """One source at this distance, capped if it is a curve that closes.

        A closed curve that does not lie flat has no face to cap with, and it
        is still worth the open extrusion rather than nothing at all.
        """
        try:
            return g.extrude(source["src"], tuple(axis), value,
                             cap=source["cap"])
        except g.GeometryError:
            if not source["cap"]:
                raise
            return g.extrude(source["src"], tuple(axis), value, cap=False)

    def rebuilding_id(self):
        """The object a live drag is rebuilding, or None.

        A fillet, push/pull or multi-face drag calls replace_shape on
        every mouse move, so the picked edge or face indices refer to
        the shape the drag started from, not to whatever is on screen
        this frame. The viewport quiets that object's sub-object
        highlight until the drag settles; end_drag then drops or
        re-points the picks (_clear_filleted_edges, _resync_face).
        """
        d = self.drag
        if not d:
            return None
        for key in ("fillet", "pp", "multiface"):
            v = d.get(key)
            if v:
                return v[0]
        return None

    def end_drag(self):
        d = self.drag
        if d is not None and float(np.linalg.norm(d["offset"])) > 1e-9:
            if d.get("pp") and d.get("pp_planar", True):
                self._resync_face(d)         # curved offsets keep their index
            elif d.get("fillet"):
                self._clear_filleted_edges(d)
            elif d.get("made"):
                # You are holding what you just grew, not the line you grew it
                # from: the next thing anyone does is to the new surface.
                made = [i for i in d["made"].values()
                        if self.vp.scene.get(i) is not None]
                if made:
                    self.vp.selection.set(made)
        self.vp.selection.rebuilding = None
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
        for obj_id in (d.get("made") or {}).values():
            vp.scene.remove(obj_id)          # nothing grew, so nothing stays
        for obj_id, original in d["originals"].items():
            if vp.scene.get(obj_id) is not None:
                vp.scene.replace_shape(obj_id, original)
        self.vp.window_discard_checkpoint()
        self.vp.selection.rebuilding = None
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
