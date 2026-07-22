"""Paper-space rendering and interaction, hosted by the Viewport.

Paper coordinates are millimetres, origin at the sheet's bottom-left.
The layout "camera" is a pan (mm) + zoom (pixels per mm).
"""

from __future__ import annotations

import math

import numpy as np
from OpenGL import GL
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen

from ..core import hlr
from ..utils.math3d import look_at, ortho, perspective

PAPER_COLOR = (0.94, 0.94, 0.92, 1.0)
PAPER_SHADOW = (0.05, 0.05, 0.06, 0.5)
MARGIN_COLOR = (0.55, 0.55, 0.58, 0.8)
BORDER_COLOR = (0.25, 0.28, 0.32, 1.0)
BORDER_ACTIVE = (0.85, 0.64, 0.25, 1.0)
LINE_VISIBLE = (0.10, 0.10, 0.12, 1.0)
LINE_HIDDEN = (0.45, 0.45, 0.5, 1.0)
DIM_COLOR = (0.20, 0.30, 0.55, 1.0)


def detail_direction(detail) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(view_dir_towards_viewer, right, up) for a detail camera."""
    ce = math.cos(detail.elevation)
    d = np.array([ce * math.cos(detail.azimuth),
                  ce * math.sin(detail.azimuth),
                  math.sin(detail.elevation)])
    z_up = np.array([0.0, 0.0, 1.0])
    cross = np.cross(-d, z_up)
    if np.linalg.norm(cross) < 1e-6:
        right = np.array([-math.sin(detail.azimuth),
                          math.cos(detail.azimuth), 0.0])
    else:
        right = cross / np.linalg.norm(cross)
    up = np.cross(right, -d)
    return d, right, up


class LayoutView:
    def __init__(self, viewport):
        self.vp = viewport
        self.pan = np.array([0.0, 0.0])      # paper mm at viewport centre
        self.px_per_mm = 2.0
        self.entered_detail: str | None = None
        self.selected: tuple | None = None       # (kind, obj) on this sheet
        self._drag: tuple | None = None          # (mode, kind, obj, corner)
        self._drag_last: tuple | None = None
        self._drag_moved = False
        self._fitted_for: str | None = None
        self._hlr_cache: dict = {}

    # ------------------------------------------------------------ transforms

    @property
    def layout(self):
        for lay in self.vp.scene.layouts:
            if lay.id == self.vp.space:
                return lay
        return None

    def fit(self):
        lay = self.layout
        if lay is None:
            return
        w, h = self.vp.width(), self.vp.height()
        self.px_per_mm = min(w / (lay.paper_w * 1.15),
                             h / (lay.paper_h * 1.15))
        self.pan = np.array([lay.paper_w / 2, lay.paper_h / 2])

    def paper_to_screen(self, x: float, y: float) -> tuple[float, float]:
        w, h = self.vp.width(), self.vp.height()
        sx = w / 2 + (x - self.pan[0]) * self.px_per_mm
        sy = h / 2 - (y - self.pan[1]) * self.px_per_mm
        return sx, sy

    def screen_to_paper(self, sx: float, sy: float) -> tuple[float, float]:
        w, h = self.vp.width(), self.vp.height()
        x = (sx - w / 2) / self.px_per_mm + self.pan[0]
        y = -(sy - h / 2) / self.px_per_mm + self.pan[1]
        return x, y

    def _paper_mvp(self) -> np.ndarray:
        """Ortho MVP mapping paper mm -> clip space."""
        w, h = self.vp.width(), self.vp.height()
        half_w = w / 2 / self.px_per_mm
        half_h = h / 2 / self.px_per_mm
        return ortho(self.pan[0] - half_w, self.pan[0] + half_w,
                     self.pan[1] - half_h, self.pan[1] + half_h,
                     -10, 10)

    # ------------------------------------------------------------- painting

    def paint(self):
        lay = self.layout
        if lay is None:
            return
        if self._fitted_for != lay.id:
            self.fit()
            self._fitted_for = lay.id
        vp = self.vp
        mvp = self._paper_mvp()

        # paper sheet + shadow
        self._fill_rect(mvp, 3, -3, lay.paper_w, lay.paper_h, PAPER_SHADOW)
        self._fill_rect(mvp, 0, 0, lay.paper_w, lay.paper_h, PAPER_COLOR)
        m = lay.margin
        self._stroke_rect(mvp, m, m, lay.paper_w - 2 * m,
                          lay.paper_h - 2 * m, MARGIN_COLOR, dashed=True)

        for detail in lay.details:
            self._paint_detail(lay, detail, mvp)

    def _paint_detail(self, lay, detail, paper_mvp):
        vp = self.vp
        mode = detail.display_mode
        if mode in ("wireframe", "shaded", "ghosted"):
            self._paint_detail_3d(detail, mode)
        else:
            self._paint_detail_hlr(detail, paper_mvp)
        entered = detail.id == self.entered_detail
        if detail.show_border or entered:
            color = BORDER_ACTIVE if entered else BORDER_COLOR
            self._stroke_rect(paper_mvp, detail.x, detail.y, detail.w,
                              detail.h, color, width=2.2 if entered else 1.2)

    def detail_matrices(self, detail, px_w: float,
                        px_h: float) -> tuple[np.ndarray, np.ndarray]:
        d, right, up = detail_direction(detail)
        target = np.asarray(detail.target, float)
        if detail.perspective:
            eye = target + d * detail.perspective_distance
            proj = perspective(45.0, px_w / max(px_h, 1),
                               detail.perspective_distance * 0.001,
                               detail.perspective_distance * 100 + 1000)
        else:
            span = max(detail.w, detail.h) * detail.scale_denom * 4 + 1000
            eye = target + d * span * 0.5
            half_w = detail.w / 2 * detail.scale_denom
            half_h = detail.h / 2 * detail.scale_denom
            proj = ortho(-half_w, half_w, -half_h, half_h, 0.01, span * 2)
        view = look_at(eye, target, up)
        return proj, view

    def _paint_detail_3d(self, detail, mode):
        vp = self.vp
        ratio = vp.devicePixelRatioF()
        x0, y0 = self.paper_to_screen(detail.x, detail.y)
        x1, y1 = self.paper_to_screen(detail.x + detail.w,
                                      detail.y + detail.h)
        px = int(min(x0, x1) * ratio)
        py = int((vp.height() - max(y0, y1)) * ratio)
        pw = max(int(abs(x1 - x0) * ratio), 1)
        ph = max(int(abs(y0 - y1) * ratio), 1)
        GL.glEnable(GL.GL_SCISSOR_TEST)
        GL.glScissor(px, py, pw, ph)
        GL.glViewport(px, py, pw, ph)
        GL.glClearColor(0.98, 0.98, 0.97, 1.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)
        proj, view = self.detail_matrices(detail, pw, ph)
        mvp = (proj @ view).astype(np.float32)
        vp._draw_objects(mvp, view, mode_override=mode,
                         light_background=True)
        GL.glDisable(GL.GL_SCISSOR_TEST)
        GL.glViewport(0, 0, int(vp.width() * ratio),
                      int(vp.height() * ratio))

    def _detail_hlr(self, detail) -> dict:
        vp = self.vp
        key = (vp.scene.revision, round(detail.azimuth, 6),
               round(detail.elevation, 6), tuple(detail.target),
               detail.perspective, detail.section_offset)
        cached = self._hlr_cache.get(detail.id)
        if cached is not None and cached[0] == key:
            return cached[1]
        d, right, up = detail_direction(detail)
        from ..core.mesh import MeshShape
        objs = [o for o in vp.scene.visible_objects()
                if not isinstance(o.shape, MeshShape)]
        # Group by effective linetype so non-Continuous objects can export as
        # dashed linework. An all-Continuous scene stays a single HLR pass.
        groups: dict = {}
        for o in objs:
            groups.setdefault(vp._effective_linetype(o), []).append(o.shape)

        def run(shapes):
            cut = []
            if shapes and detail.section_offset is not None \
                    and not detail.perspective:
                shapes, cut = _section_cut(
                    shapes, np.asarray(detail.target, float), d, right, up,
                    detail.section_offset)
            if not shapes:
                return [], [], cut
            res = hlr.hlr_project_safe(shapes, origin=detail.target,
                                       view_dir=d, x_dir=right)
            return (hlr.edges_to_polylines(res["visible"] + res["outline"]),
                    hlr.edges_to_polylines(res["hidden"]), cut)

        vis, hidden, cut_polys = run(groups.pop("Continuous", []))
        visible_lt = []
        for name, shapes in groups.items():
            gv, gh, _ = run(shapes)
            if gv:
                visible_lt.append((name, gv))
            hidden = hidden + gh
        data = {"visible": vis, "hidden": hidden, "cut": cut_polys,
                "visible_lt": visible_lt}
        self._hlr_cache[detail.id] = (key, data)
        return data

    def _paint_detail_hlr(self, detail, paper_mvp):
        data = self._detail_hlr(detail)
        cx = detail.x + detail.w / 2
        cy = detail.y + detail.h / 2
        s = 1.0 / detail.scale_denom

        # clip to the detail rectangle
        vp = self.vp
        ratio = vp.devicePixelRatioF()
        x0, y0 = self.paper_to_screen(detail.x, detail.y)
        x1, y1 = self.paper_to_screen(detail.x + detail.w,
                                      detail.y + detail.h)
        GL.glEnable(GL.GL_SCISSOR_TEST)
        GL.glScissor(int(min(x0, x1) * ratio),
                     int((vp.height() - max(y0, y1)) * ratio),
                     max(int(abs(x1 - x0) * ratio), 1),
                     max(int(abs(y0 - y1) * ratio), 1))
        self._fill_rect(paper_mvp, detail.x, detail.y, detail.w, detail.h,
                        (0.985, 0.985, 0.975, 1.0))

        def to_paper(poly2d):
            out = np.zeros((len(poly2d), 3), np.float32)
            out[:, 0] = cx + poly2d[:, 0] * s
            out[:, 1] = cy + poly2d[:, 1] * s
            return out

        # hidden lines first so coincident visible edges draw over them
        if detail.display_mode == "hidden":
            segs_h = []
            for poly in data["hidden"]:
                p = to_paper(poly[:, :2])
                segs_h.append(hlr.dash_segments(p, dash=1.6, gap=1.0))
            segs_h = [s for s in segs_h if len(s)]
            if segs_h:
                allh = np.concatenate(segs_h)
                self._draw_segs(paper_mvp, allh, LINE_HIDDEN, 1.0)
        segs_v = []
        for poly in data["visible"]:
            p = to_paper(poly[:, :2])
            segs_v.append(np.stack([p[:-1], p[1:]], axis=1))
        if segs_v:
            self._draw_segs(paper_mvp, np.concatenate(segs_v),
                            LINE_VISIBLE, 1.6)
        # non-Continuous linetypes: same ink, dashed per their pattern
        from ..core import linetype as _lt
        for name, polys in data.get("visible_lt", []):
            pattern = _lt.pattern_for(name)
            dsegs = []
            for poly in polys:
                p = to_paper(poly[:, :2])
                pairs = (_lt.dash_polyline(p, pattern) if pattern
                         else list(zip(p[:-1], p[1:])))
                dsegs.extend([a, b] for a, b in pairs)
            if dsegs:
                self._draw_segs(paper_mvp, np.asarray(dsegs, np.float32),
                                LINE_VISIBLE, 1.6)
        # section-cut faces: heavy outline + 45-degree hatching
        cut = data.get("cut") or []
        if cut:
            from ..core.layout import hatch_lines
            hatch_segs = []
            outline_segs = []
            for poly in cut:
                paper = [(cx + px * s, cy + py * s) for px, py in poly]
                arr = np.asarray([(p[0], p[1], 0.0) for p in paper],
                                 np.float32)
                outline_segs.append(np.stack([arr[:-1], arr[1:]], axis=1))
                for a, b in hatch_lines(paper, 45.0, 2.5):
                    hatch_segs.append(np.asarray(
                        [[a[0], a[1], 0], [b[0], b[1], 0]], np.float32))
            if hatch_segs:
                self._draw_segs(paper_mvp, np.stack(hatch_segs),
                                (0.25, 0.27, 0.32, 1.0), 1.0)
            if outline_segs:
                self._draw_segs(paper_mvp, np.concatenate(outline_segs),
                                (0.05, 0.05, 0.07, 1.0), 2.2)
        GL.glDisable(GL.GL_SCISSOR_TEST)

    # ------------------------------------------------------- QPainter texts

    def paint_overlay(self, painter: QPainter):
        """Text drawn with QPainter after the GL pass."""
        lay = self.layout
        if lay is None:
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # detail scale labels
        for detail in lay.details:
            if not detail.show_label:
                continue
            sx, sy = self.paper_to_screen(detail.x + 1.5, detail.y + 1.5)
            painter.setPen(QPen(QColor(90, 95, 105)))
            painter.setFont(QFont("sans", max(int(2.6 * self.px_per_mm), 7)))
            label = detail.scale_text()
            if detail.locked:
                label += "  [locked]"
            painter.drawText(int(sx), int(sy) - 2, label)
        self._paint_selection(painter)
        from . import annot_paint
        scene = self.vp.scene
        idx = 1
        for i, l in enumerate(scene.layouts):
            if l.id == lay.id:
                idx = i + 1
        annot_paint.draw_all(
            painter,
            lambda x, y: self.paper_to_screen(x, y),
            self.px_per_mm, lay, scene,
            sheet_index=idx, sheet_count=max(len(scene.layouts), 1))

    def _paint_selection(self, painter: QPainter):
        lay = self.layout
        if lay is None or self.selected is None:
            return
        kind, obj = self.selected
        pools = {"note": lay.notes, "dim": lay.dims, "rdim": lay.rdims,
                 "adim": lay.adims, "leader": lay.leaders,
                 "hatch": lay.hatches, "detail": lay.details}
        if obj not in pools.get(kind, ()):
            self.selected = None                # stale after undo/delete
            return
        gold = QColor(217, 166, 62)
        painter.setPen(QPen(gold, 2, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(0, 0, 0, 0))
        if kind == "detail":
            x0, y0 = self.paper_to_screen(obj.x, obj.y)
            x1, y1 = self.paper_to_screen(obj.x + obj.w, obj.y + obj.h)
            painter.drawRect(int(min(x0, x1)), int(min(y0, y1)),
                             int(abs(x1 - x0)), int(abs(y0 - y1)))
            painter.setBrush(gold)
            for gx, gy in self._corners(obj):
                sx, sy = self.paper_to_screen(gx, gy)
                painter.drawRect(int(sx) - 4, int(sy) - 4, 8, 8)
            painter.setBrush(QColor(0, 0, 0, 0))
        else:
            from ..core.layout import annotation_bounds
            x0, y0, x1, y1 = annotation_bounds(kind, obj)
            sx0, sy0 = self.paper_to_screen(x0 - 1, y0 - 1)
            sx1, sy1 = self.paper_to_screen(x1 + 1, y1 + 1)
            painter.drawRect(int(min(sx0, sx1)), int(min(sy0, sy1)),
                             int(abs(sx1 - sx0)), int(abs(sy0 - sy1)))

    # ------------------------------------------------------------ GL helpers

    def _fill_rect(self, mvp, x, y, w, h, color):
        vp = self.vp
        GL.glDisable(GL.GL_DEPTH_TEST)
        verts = np.array([
            [x, y, 0], [x + w, y, 0], [x, y + h, 0],
            [x + w, y, 0], [x + w, y + h, 0], [x, y + h, 0],
        ], np.float32)
        vp._preview.update(verts)
        GL.glUseProgram(vp._line_prog)
        GL.glUniformMatrix4fv(
            GL.glGetUniformLocation(vp._line_prog, "uMVP"), 1, GL.GL_TRUE,
            mvp.astype(np.float32))
        GL.glUniform4f(GL.glGetUniformLocation(vp._line_prog, "uColor"),
                       *color)
        GL.glBindVertexArray(vp._preview.vao)
        GL.glDrawArrays(GL.GL_TRIANGLES, 0, 6)
        GL.glEnable(GL.GL_DEPTH_TEST)

    def _stroke_rect(self, mvp, x, y, w, h, color, dashed=False,
                     width=1.2):
        corners = np.array([[x, y, 0], [x + w, y, 0], [x + w, y + h, 0],
                            [x, y + h, 0]], np.float32)
        segs = []
        for i in range(4):
            a, b = corners[i], corners[(i + 1) % 4]
            if dashed:
                seg = hlr.dash_segments(np.stack([a, b]), dash=3, gap=2)
                if len(seg):
                    segs.append(seg)
            else:
                segs.append(np.stack([a, b])[None, :, :])
        if segs:
            self._draw_segs(mvp, np.concatenate(segs), color, width)

    def _draw_segs(self, mvp, segs, color, width):
        vp = self.vp
        GL.glDisable(GL.GL_DEPTH_TEST)
        pts = segs.reshape(-1, 3).astype(np.float32)
        vp._preview.update(pts)
        vp._set_line_uniforms(mvp.astype(np.float32), color)
        vp._line_width(width)
        GL.glBindVertexArray(vp._preview.vao)
        GL.glDrawArrays(GL.GL_LINES, 0, len(pts))
        GL.glEnable(GL.GL_DEPTH_TEST)

    # ------------------------------------------------------------ interaction

    def wheel(self, steps: float, sx: float, sy: float) -> bool:
        detail = self._entered()
        if detail is not None:
            if not detail.locked:
                detail.scale_denom = max(
                    detail.scale_denom * (0.9 ** steps), 1e-6)
                self.vp.scene.notify("layouts")
            return True
        # zoom the paper around the cursor
        before = self.screen_to_paper(sx, sy)
        self.px_per_mm = float(np.clip(self.px_per_mm * (1.1 ** steps),
                                       0.05, 100))
        after = self.screen_to_paper(sx, sy)
        self.pan += np.array(before) - np.array(after)
        return True

    def drag(self, dx: float, dy: float, orbit: bool) -> bool:
        detail = self._entered()
        if detail is not None:
            if detail.locked:
                return True
            if orbit and detail.perspective:
                detail.azimuth -= dx * 0.008
                detail.elevation = float(np.clip(
                    detail.elevation + dy * 0.008,
                    -math.radians(89.9), math.radians(89.9)))
            else:
                d, right, up = detail_direction(detail)
                mm_per_px = 1.0 / self.px_per_mm
                shift = ((-dx * right + dy * up) * mm_per_px
                         * detail.scale_denom)
                detail.target = [float(c) for c in
                                 (np.asarray(detail.target) + shift)]
            self._hlr_cache.pop(detail.id, None)
            self.vp.scene.notify("layouts")
            return True
        self.pan -= np.array([dx, -dy]) / self.px_per_mm
        return True

    def double_click(self, sx: float, sy: float) -> bool:
        lay = self.layout
        if lay is None:
            return False
        px, py = self.screen_to_paper(sx, sy)
        detail = lay.detail_at(px, py)
        self.entered_detail = detail.id if detail else None
        return True

    def click_outside_exits(self, sx: float, sy: float) -> bool:
        """Returns True if the click exited an entered detail."""
        detail = self._entered()
        if detail is None:
            return False
        px, py = self.screen_to_paper(sx, sy)
        if not detail.contains(px, py):
            self.entered_detail = None
            return True
        return False

    def _entered(self):
        lay = self.layout
        if lay is None or self.entered_detail is None:
            return None
        for d in lay.details:
            if d.id == self.entered_detail:
                return d
        self.entered_detail = None
        return None

    # ----------------------------------------- annotation & frame editing

    @staticmethod
    def _corners(det):
        return ((det.x, det.y), (det.x + det.w, det.y),
                (det.x + det.w, det.y + det.h), (det.x, det.y + det.h))

    def press(self, sx: float, sy: float) -> bool:
        """LMB press while idle: select / start dragging sheet items."""
        lay = self.layout
        if lay is None or self.entered_detail is not None:
            return False
        px, py = self.screen_to_paper(sx, sy)
        tol = max(7.0 / self.px_per_mm, 0.8)
        if self.selected and self.selected[0] == "detail":
            det = self.selected[1]
            for i, (gx, gy) in enumerate(self._corners(det)):
                if abs(px - gx) <= tol and abs(py - gy) <= tol:
                    if det.locked:
                        return True
                    self.vp.window_checkpoint("resize detail")
                    self._drag = ("resize", "detail", det, i)
                    self._drag_last = (px, py)
                    return True
        from ..core.layout import annotation_at
        hit = annotation_at(lay, px, py, tol=max(tol, 2.0))
        if hit is not None:
            self.selected = hit
            self.vp.window_checkpoint("move annotation")
            self._drag = ("move",) + hit + (-1,)
            self._drag_last = (px, py)
            return True
        det = lay.detail_at(px, py)
        if det is not None:
            self.selected = ("detail", det)
            if not det.locked:
                self.vp.window_checkpoint("move detail")
                self._drag = ("move", "detail", det, -1)
                self._drag_last = (px, py)
            return True
        if self.selected is not None:
            self.selected = None
            return True
        return False

    def drag_selected(self, sx: float, sy: float) -> bool:
        if self._drag is None:
            return False
        px, py = self.screen_to_paper(sx, sy)
        dx = px - self._drag_last[0]
        dy = py - self._drag_last[1]
        mode, kind, obj, corner = self._drag
        if kind == "detail":
            if mode == "move":
                obj.x += dx
                obj.y += dy
            else:
                x0, y0 = obj.x, obj.y
                x1, y1 = obj.x + obj.w, obj.y + obj.h
                if corner in (0, 3):
                    x0 += dx
                else:
                    x1 += dx
                if corner in (0, 1):
                    y0 += dy
                else:
                    y1 += dy
                obj.x, obj.w = min(x0, x1), max(abs(x1 - x0), 5.0)
                obj.y, obj.h = min(y0, y1), max(abs(y1 - y0), 5.0)
            self._hlr_cache.pop(obj.id, None)
        else:
            from ..core.layout import move_annotation
            move_annotation(kind, obj, dx, dy)
        self._drag_moved = True
        self._drag_last = (px, py)
        self.vp.scene.notify("layouts")
        return True

    def release_drag(self):
        if self._drag is None:
            return
        if not self._drag_moved:
            self.vp.window_discard_checkpoint()
        self._drag = None
        self._drag_moved = False

    def delete_selected(self) -> bool:
        lay = self.layout
        if lay is None or self.selected is None:
            return False
        kind, obj = self.selected
        if kind == "detail":
            if obj not in lay.details:
                self.selected = None
                return False
            self.vp.window_checkpoint("delete detail")
            lay.details.remove(obj)
            self._hlr_cache.pop(obj.id, None)
        else:
            from ..core.layout import delete_annotation
            self.vp.window_checkpoint("delete annotation")
            if not delete_annotation(lay, kind, obj):
                self.vp.window_discard_checkpoint()
                self.selected = None
                return False
        self.selected = None
        self.vp.scene.notify("layouts")
        return True


def _section_cut(shapes, target, d, right, up, offset):
    """Cut shapes with a half-space in front of the section plane.

    Returns (cut_shapes, cut_polygons_2d) — polygons are the section
    outlines in the detail's projector frame (model units)."""
    from ..core import geometry as g
    from ..core.occ import gp_Pln

    plane_pt = target + d * float(offset)
    # extent large enough to swallow the whole scene
    import numpy as np
    diag = 0.0
    for s in shapes:
        mn, mx = g.bbox(s)
        diag = max(diag, float(np.linalg.norm(np.subtract(mx, mn))),
                   float(np.linalg.norm(np.subtract(mx, plane_pt))),
                   float(np.linalg.norm(np.subtract(mn, plane_pt))))
    L = diag * 2 + 10
    corners = [plane_pt + right * sx * L + up * sy * L
               for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    quad = g.make_polyline([tuple(c) for c in corners], closed=True)
    cutter = g.extrude(g.planar_face(quad), tuple(d), L, cap=False)

    out_shapes = []
    cut_polys = []
    for s in shapes:
        kind = g.shape_kind(s)
        try:
            if kind == "solid":
                out_shapes.append(g.boolean_difference(s, cutter))
            else:
                out_shapes.append(s)
                continue
        except g.GeometryError:
            out_shapes.append(s)
            continue
        # section outline for hatching
        try:
            from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
            plane = gp_Pln(g._pnt(tuple(plane_pt)), g._dir(tuple(d)))
            sec = BRepAlgoAPI_Section(s, plane)
            sec.Build()
            if sec.IsDone():
                for wire in g._curve_pieces(g.edges_of(sec.Shape()), []):
                    pts = g.sample_curve(wire, 96)
                    poly = [((p[0] - plane_pt[0]) * right[0]
                             + (p[1] - plane_pt[1]) * right[1]
                             + (p[2] - plane_pt[2]) * right[2],
                             (p[0] - plane_pt[0]) * up[0]
                             + (p[1] - plane_pt[1]) * up[1]
                             + (p[2] - plane_pt[2]) * up[2])
                            for p in pts]
                    if len(poly) >= 3:
                        cut_polys.append(poly)
        except Exception:
            pass
    return out_shapes, cut_polys
