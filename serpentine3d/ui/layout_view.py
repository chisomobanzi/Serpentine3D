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

from ..core import hlr, linetype
from ..utils.math3d import look_at, ortho, perspective
from . import theme

PAPER_COLOR = (0.94, 0.94, 0.92, 1.0)
PAPER_SHADOW = (0.05, 0.05, 0.06, 0.5)
MARGIN_COLOR = (0.55, 0.55, 0.58, 0.8)
BORDER_COLOR = (0.25, 0.28, 0.32, 1.0)
BORDER_ACTIVE = (0.85, 0.64, 0.25, 1.0)
LINE_VISIBLE = (0.10, 0.10, 0.12, 1.0)
LINE_HIDDEN = (0.45, 0.45, 0.5, 1.0)
DIM_COLOR = (0.20, 0.30, 0.55, 1.0)
POINT_MARK_PX = 4.0                     # half a point's cross, on screen
ZOOM_PAD = 1.05                         # air around what a zoom was asked for


def point_marks(points, size: float) -> np.ndarray:
    """A cross for each point, as (M, 2, 3) segments in the points' own units.

    Squared to the page rather than drawn as an x, so it reads as a crosshair
    over the place it marks and not as a mark of its own.
    """
    segs = []
    for p in points:
        x, y, z = float(p[0]), float(p[1]), float(p[2])
        segs.append([[x - size, y, z], [x + size, y, z]])
        segs.append([[x, y - size, z], [x, y + size, z]])
    return np.asarray(segs, np.float32).reshape(-1, 2, 3)


def hlr_visible_segments(by_obj, to_paper, is_picked) -> list:
    """A detail's visible line work as (ink, segments), in the order to draw.

    `by_obj` is what the hidden-line pass carried out: one (object id,
    linetype name, polylines) for each object it drew. Grouping the polylines
    by the ink they take rather than by the object they came from keeps the
    drawing to two uploads however many objects are in it, and the picked ink
    comes last, so where a picked object shares an edge with one that is not,
    what you see is that it is picked.

    A linetype is dashed here rather than by the line renderer, so it dashes
    the same on screen as it does on paper — and a picked object keeps its
    dashes, since going gold says it is picked and not that it is solid.
    """
    from ..core import linetype as _lt

    plain, gold = [], []
    for oid, name, polys in by_obj:
        pattern = _lt.pattern_for(name)
        into = gold if oid is not None and is_picked(oid) else plain
        for poly in polys:
            p = to_paper(poly[:, :2])
            if len(p) < 2:
                continue
            if pattern:
                pairs = _lt.dash_polyline(p, pattern)
                if len(pairs):
                    into.append(np.asarray(pairs, np.float32))
            else:
                into.append(np.stack([p[:-1], p[1:]], axis=1))
    out = []
    for segs, ink in ((plain, LINE_VISIBLE),
                      (gold, (*theme.SELECTION_COLOR, 1.0))):
        if segs:
            out.append((ink, np.concatenate(segs).astype(np.float32)))
    return out


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


def detail_plane(detail):
    """The construction plane a detail looks at.

    Its picks already land on this plane — they are unprojected out of the same
    basis — so drawing on it throws nothing away.
    """
    from ..core.cplane import CPlane
    from ..core.layout import detail_basis
    d, right, _up = detail_basis(detail)
    return CPlane(origin=detail.target, normal=d, xdir=right, name="Detail")


class DetailEye:
    """A detail seen as a camera, so the model can be reached through it.

    Snapping and picking both ask a camera the same two questions — where does
    this model point land on screen, and what does this pixel look along — and
    measure the answers in viewport pixels. Through a detail the projection is
    two steps, the model onto the paper and the paper onto the screen, and it
    has to be the same two steps a pick runs backwards or a snap would not sit
    under the cursor that found it.
    """

    projection = "parallel"          # a detail is an orthographic window

    def __init__(self, layout_view, detail):
        self.lv = layout_view
        self.detail = detail

    def _eye_distance(self) -> float:
        """How far back the viewer stands, as the drawing puts it."""
        det = self.detail
        return (max(det.w, det.h) * det.scale_denom * 4 + 1000) * 0.5

    def project(self, points, width: int, height: int,
                clipped: bool = True) -> np.ndarray:
        """Model points -> (N, 3) of screen x, screen y, depth from the eye.

        `clipped` off asks where a point would appear if the frame did not cut
        it off, which is what the gumball wants: it is drawn over the drawing
        rather than in it, and a handle you cannot reach because the object
        nearly fills the window is no handle.
        """
        from ..core.layout import detail_basis
        det = self.detail
        arr = np.asarray(points, float).reshape(-1, 3)
        d, right, up = detail_basis(det)
        rel = arr - np.asarray(det.target, float)
        u = (rel @ right) / det.scale_denom
        v = (rel @ up) / det.scale_denom
        out = np.empty((len(arr), 3))
        ppm = self.lv.px_per_mm     # the paper transform, one call for all
        out[:, 0] = width / 2 + (det.x + det.w / 2 + u - self.lv.pan[0]) * ppm
        out[:, 1] = height / 2 - (det.y + det.h / 2 + v - self.lv.pan[1]) * ppm
        out[:, 2] = self._eye_distance() - rel @ d
        # A detail clips what it shows to its own rectangle, so a point
        # outside it is not under the cursor however close the paper says it
        # came. Behind the eye is how everything here says "not pickable".
        if clipped:
            outside = (np.abs(u) > det.w / 2) | (np.abs(v) > det.h / 2)
            out[outside, 2] = -1.0
        return out

    def ray_through(self, px: float, py: float, width: int,
                    height: int) -> tuple[np.ndarray, np.ndarray]:
        """Line of sight through a pixel: (origin behind the model, view dir).

        Parallel, so every pixel looks the same way and only the origin moves —
        set back far enough that everything the detail draws is in front of it,
        the way a camera at a distance is.
        """
        from ..core.layout import detail_basis, detail_unproject
        d, _right, _up = detail_basis(self.detail)
        paper = self.lv.screen_to_paper(px, py)
        on_plane = np.asarray(detail_unproject(self.detail, *paper), float)
        return on_plane + d * self._eye_distance(), -d

    def right_up(self) -> tuple[np.ndarray, np.ndarray]:
        from ..core.layout import detail_basis
        _d, right, up = detail_basis(self.detail)
        return right, up

    def to_paper(self, points) -> np.ndarray:
        """Model points as the paper millimetres they are drawn at.

        The first of the two steps `project` takes, on its own: anything drawn
        on a sheet in the model's own coordinates has to be brought out onto
        the paper before the sheet's own transform can put it on screen.
        """
        from ..core.layout import detail_project
        arr = np.asarray(points, np.float32).reshape(-1, 3)
        out = np.zeros_like(arr)
        for i, p in enumerate(arr):
            out[i, :2] = detail_project(self.detail, p)
        return out


class LayoutView:
    def __init__(self, viewport):
        self.vp = viewport
        self.pan = np.array([0.0, 0.0])      # paper mm at viewport centre
        self.px_per_mm = 2.0
        self.entered_detail: str | None = None
        self.ghost_detail = None                 # detail a command is sizing
        self.selected: list = []                 # [(kind, obj)] on this sheet
        self.corners: list = []                  # [(detail, index)] grips
        self.box: tuple | None = None            # live band, screen px
        self._box_add = False
        self._drag: tuple | None = None          # (mode, corners, picks)
        self._press_hit: tuple | None = None
        self._press_corner: tuple | None = None
        self._drag_last: tuple | None = None
        self._drag_moved = False
        self._fitted_for: str | None = None
        self._hlr_cache: dict = {}
        from .paper_gumball import PaperGumball
        # A sheet's own handles. The model window's gumball holds model
        # objects, including the ones seen through a detail; this one holds
        # the paper itself, which is a different thing to take hold of.
        self.gumball = PaperGumball(self)

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

    # -------------------------------------------------------------- zooming

    def zoom_paper(self, x0: float, y0: float, x1: float, y1: float):
        """Frame that rectangle of paper, in millimetres."""
        w, h = self.vp.width(), self.vp.height()
        rw = max(abs(x1 - x0), 1e-3)
        rh = max(abs(y1 - y0), 1e-3)
        self.px_per_mm = float(np.clip(min(w / (rw * ZOOM_PAD),
                                           h / (rh * ZOOM_PAD)), 0.05, 100))
        self.pan = np.array([(x0 + x1) / 2, (y0 + y1) / 2])
        lay = self.layout
        if lay is not None and self.vp.isVisible():
            # Count the sheet as fitted, or the first paint after switching to
            # it would fit it over the top of this and the zoom would never be
            # seen at all.
            #
            # Only once the view is on screen, though. A pane built a moment
            # ago still reports the size it was constructed at, and an extra
            # viewport opened straight onto a sheet zooms before the window
            # has decided how big it is — a fit worked out from that size is
            # wrong by however much the layout is about to change it, and the
            # first paint is the one that knows better.
            self._fitted_for = lay.id
        self.vp.update()

    def sheet_bounds(self) -> tuple | None:
        """The page, and everything on it.

        The page alone is nearly always the same answer. It is not when a
        border has been dragged off the edge, and that is exactly the case
        where a way back to it is wanted — a zoom that cannot show you the
        thing you have lost is no way back.
        """
        lay = self.layout
        if lay is None:
            return None
        from ..core.layout import sheet_item_bounds
        box = [0.0, 0.0, float(lay.paper_w), float(lay.paper_h)]
        for kind, pool in self._pools(lay).items():
            for obj in pool:
                x0, y0, x1, y1 = sheet_item_bounds(kind, obj)
                box = [min(box[0], x0), min(box[1], y0),
                       max(box[2], x1), max(box[3], y1)]
        return tuple(box)

    def zoom_extents(self) -> bool:
        """Show all of whatever is showing: the page, or a detail's model."""
        det = self._entered()
        if det is not None:
            lo, hi = self.vp.scene.bbox()
            self._zoom_detail_box(det, lo, hi)
            return True
        bounds = self.sheet_bounds()
        if bounds is None:
            return False
        self.zoom_paper(*bounds)
        return True

    def zoom_selected(self) -> bool:
        """Frame what is picked. False when nothing is.

        Which selection that means is the question `sheet_view` answers for
        every other command: the sheet's own items on bare paper, the model
        objects inside a detail.
        """
        det = self._entered()
        if det is not None:
            box = self.vp.selected_bbox()
            if box is None:
                return False
            self._zoom_detail_box(det, *box)
            return True
        self._prune()
        if not self.selected:
            return False
        from ..core.layout import sheet_item_bounds
        boxes = [sheet_item_bounds(k, o) for k, o in self.selected]
        self.zoom_paper(min(b[0] for b in boxes), min(b[1] for b in boxes),
                        max(b[2] for b in boxes), max(b[3] for b in boxes))
        return True

    def zoom_window(self, p1, p2) -> bool:
        """Frame the window two picked points span.

        On bare paper they are paper points, because that is the only thing a
        point there can be; inside a detail they are model points, for the
        same reason in reverse.
        """
        det = self._entered()
        if det is not None:
            from ..core.layout import detail_project
            ax, ay = detail_project(det, p1)
            bx, by = detail_project(det, p2)
            self._zoom_detail_rect(det, ax, ay, bx, by)
            return True
        self.zoom_paper(p1[0], p1[1], p2[0], p2[1])
        return True

    def zoom_steps(self, steps: float) -> bool:
        """Zoom about the middle of the view by the wheel's own amount.

        Through `wheel`, so that typing `zoom In` and rolling the wheel are
        one behaviour and not two that have to agree.
        """
        ok = self.wheel(steps, self.vp.width() / 2, self.vp.height() / 2)
        self.vp.update()
        return ok

    def _zoom_detail_rect(self, det, x0: float, y0: float,
                          x1: float, y1: float) -> bool:
        """Aim and scale a detail so that piece of its paper fills the frame.

        Millimetres at the scale the detail is at now, which is what comes
        back from projecting model points through it.
        """
        if det.locked:
            return False
        from ..core.layout import detail_unproject
        # Re-aimed before it is re-scaled: unprojecting reads the scale, so a
        # target worked out at the new one would name a different point.
        det.target = detail_unproject(det, (x0 + x1) / 2, (y0 + y1) / 2)
        grow = max(abs(x1 - x0) / det.w, abs(y1 - y0) / det.h)
        if grow > 1e-9:            # a point has no size to fill a frame with
            det.scale_denom = max(det.scale_denom * grow * ZOOM_PAD, 1e-6)
        self._hlr_cache.pop(det.id, None)
        self.vp.scene.notify("layouts")
        self.vp.update()
        return True

    def _zoom_detail_box(self, det, lo, hi) -> bool:
        """Frame a model bounding box inside a detail.

        All eight corners, since a detail looking at an angle turns the box
        on the page and the near corners are not the wide ones.
        """
        from ..core.layout import detail_project
        pts = [detail_project(det, (x, y, z))
               for x in (lo[0], hi[0]) for y in (lo[1], hi[1])
               for z in (lo[2], hi[2])]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return self._zoom_detail_rect(det, min(xs), min(ys),
                                      max(xs), max(ys))

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
        self._paint_ghost_detail(mvp)

        # after the details: a border or a bubble drawn over a view is meant
        # to be seen, the same way the annotations on top of it are
        self._paint_objects(lay, mvp)

    def _object_ink(self, obj) -> tuple:
        """What colour to draw paper geometry in, picked or not.

        Picked geometry goes gold, the way it does in the model, rather than
        getting a dashed box like the annotations: two lines that overlap share
        a box, and the whole point of picking one is knowing which you have.
        """
        if any(k == "object" and o is obj for k, o in self.selected):
            return (*theme.SELECTION_COLOR, 1.0)
        return (*obj.color, 1.0) if obj.color else LINE_VISIBLE

    def _point_mark_size(self) -> float:
        """Half the width of a point's cross, in paper millimetres.

        Fixed on screen rather than on the paper: a point mark says where
        something is and has no size of its own, so zooming into the page must
        not grow it into a plus sign the size of the drawing.
        """
        return POINT_MARK_PX / max(self.px_per_mm, 1e-6)

    def _paint_objects(self, lay, mvp):
        """Geometry drawn on the paper itself, in millimetres."""
        mark = self._point_mark_size()
        for obj in lay.objects:
            pattern = linetype.pattern_for(obj.linetype)
            segs = []
            for pts in obj.polylines:
                if pattern:
                    segs += [np.stack(pair) for pair
                             in linetype.dash_polyline(pts, pattern)]
                else:
                    segs.append(np.stack([pts[:-1], pts[1:]], axis=1))
            color = self._object_ink(obj)
            if segs:
                # a lineweight is millimetres on the printed sheet, so it scales
                # with the zoom; floored at a pixel, because 0.25mm on a whole
                # page is a quarter of one and a border you cannot see is worse
                # than a border a shade too heavy
                width = max(1.0, obj.lineweight * self.px_per_mm)
                self._draw_segs(mvp, np.concatenate(
                    [s.reshape(-1, 2, 3) for s in segs]), color, width)
            # a point object has no edges, so nothing above draws it: it is a
            # cross of its own, at the weight a mark takes rather than the
            # object's lineweight, which is about ink and this is not ink
            marks = point_marks(obj.points, mark)
            if len(marks):
                self._draw_segs(mvp, marks, color, 1.6)

    def _paint_detail_body(self, detail, paper_mvp):
        """The view inside a detail's rectangle, however it is drawn."""
        mode = detail.display_mode
        if mode in ("wireframe", "shaded", "ghosted"):
            self._paint_detail_3d(detail, mode)
        else:
            self._paint_detail_hlr(detail, paper_mvp)

    def set_ghost_detail(self, detail):
        """The detail a running command is still sizing, or None.

        A detail's hidden lines are cached under its id like any other's, so a
        ghost that never got placed would leave the whole model's linework
        behind it — that goes when the ghost does.
        """
        old = self.ghost_detail
        if old is detail:
            return
        if old is not None:
            lay = self.layout
            if lay is None or not any(d is old for d in lay.details):
                self._hlr_cache.pop(old.id, None)
        self.ghost_detail = detail
        self.vp.update()

    def _paint_ghost_detail(self, paper_mvp):
        """The detail a command is still drawing, so the frame is not a guess.

        Gold and dashed: nothing on the sheet is gold until it is real.
        """
        detail = self.ghost_detail
        if detail is None or detail.w < 1 or detail.h < 1:
            return
        self._paint_detail_body(detail, paper_mvp)
        self._stroke_rect(paper_mvp, detail.x, detail.y, detail.w, detail.h,
                          (*theme.SELECTION_COLOR, 1.0), dashed=True,
                          width=1.6)

    def _paint_detail(self, lay, detail, paper_mvp):
        self._paint_detail_body(detail, paper_mvp)
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
        shapes = [o.shape for o in objs]
        layer_types = vp._layer_linetypes()                 # once, not per object
        lts = [vp._effective_linetype(o, layer_types)
               for o in objs]                               # aligned to shapes
        pws = [vp.scene.print_width_of(o) for o in objs]    # plot pen, aligned

        cut_polys = []
        if shapes and detail.section_offset is not None \
                and not detail.perspective:
            shapes, cut_polys = _section_cut(   # 1:1 with input, keeps order
                shapes, np.asarray(detail.target, float), d, right, up,
                detail.section_offset)

        if not shapes:
            data = {"visible": [], "hidden": [], "cut": cut_polys,
                    "visible_lt": [], "visible_by_obj": [], "visible_groups": []}
            self._hlr_cache[detail.id] = (key, data)
            return data

        # One HLR pass over everything (correct occlusion), visible edges split
        # per shape so each object keeps its own linetype even when hidden by
        # a solid in front of it.
        res = hlr.hlr_project_safe(shapes, origin=detail.target,
                                   view_dir=d, x_dir=right)
        by_shape = res.get("visible_by_shape") or []
        by_obj = []                 # (object id, linetype name, polylines)
        entries = []                # (print width mm, linetype name, polylines)
        if by_shape:
            for i, obj in enumerate(objs):
                name = lts[i] if i < len(lts) else "Continuous"
                polys = hlr.edges_to_polylines(
                    by_shape[i] if i < len(by_shape) else [])
                by_obj.append((obj.id, name, polys))
                entries.append((pws[i] if i < len(pws) else 0.0, name, polys))
        else:                                   # older worker: no split
            # Nothing to say which object any of it came from, so it belongs to
            # no object: it draws, and nothing in it can go gold, and it plots
            # at the device default because no layer owns it.
            polys = hlr.edges_to_polylines(res["visible"] + res["outline"])
            by_obj = [(None, "Continuous", polys)]
            entries = [(0.0, "Continuous", polys)]
        visible = []
        lt_groups: dict = {}
        for _oid, name, polys in by_obj:
            (visible if name == "Continuous"
             else lt_groups.setdefault(name, [])).extend(polys)
        from ..core.layout import merge_line_groups
        data = {"visible": visible,
                "hidden": hlr.edges_to_polylines(res["hidden"]),
                "cut": cut_polys,
                "visible_lt": [(n, p) for n, p in lt_groups.items()],
                "visible_by_obj": by_obj,
                "visible_groups": merge_line_groups(entries)}
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
        # Visible edges, in the inks they take: a hidden-line detail has no
        # faces to tint, so ink is the only way it can show what is picked.
        picked = self.vp.selection.is_selected
        for ink, segs in hlr_visible_segments(data.get("visible_by_obj", []),
                                              to_paper, picked):
            self._draw_segs(paper_mvp, segs, ink, 1.6)
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
        # Last of all, over the ink and under nothing: a handle is a thing to
        # take hold of, so a detail's own linework must not cover it.
        self.gumball.paint(painter)
        self._paint_box(painter)        # last: the band sits over everything

    def _pools(self, lay) -> dict:
        """Where each kind of pickable thing lives on a sheet."""
        from ..core.layout import sheet_pools
        return sheet_pools(lay)

    def _prune(self):
        """Forget anything no longer on the sheet — undo and delete both
        take objects out from under a selection."""
        lay = self.layout
        if lay is None:
            self.selected = []
            self.corners = []
            return
        pools = self._pools(lay)
        self.selected = [(k, o) for k, o in self.selected
                         if o in pools.get(k, ())]
        # A corner is a grip on a lone detail, so it cannot outlive that.
        lone = (self.selected[0][1]
                if len(self.selected) == 1 and self.selected[0][0] == "detail"
                else None)
        self.corners = [(d, i) for d, i in self.corners if d is lone]

    def _paint_selection(self, painter: QPainter):
        lay = self.layout
        self._prune()
        if lay is None or not self.selected:
            return
        gold = QColor(217, 166, 62)
        painter.setPen(QPen(gold, 2, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(0, 0, 0, 0))
        for kind, obj in self.selected:
            if kind == "object":
                continue           # drawn in gold itself, see `_object_ink`
            if kind == "detail":
                x0, y0 = self.paper_to_screen(obj.x, obj.y)
                x1, y1 = self.paper_to_screen(obj.x + obj.w, obj.y + obj.h)
            else:
                from ..core.layout import annotation_bounds
                bx0, by0, bx1, by1 = annotation_bounds(kind, obj)
                x0, y0 = self.paper_to_screen(bx0 - 1, by0 - 1)
                x1, y1 = self.paper_to_screen(bx1 + 1, by1 + 1)
            painter.drawRect(int(min(x0, x1)), int(min(y0, y1)),
                             int(abs(x1 - x0)), int(abs(y0 - y1)))
        # Grips resize, and resizing several rectangles at once from one
        # corner has no meaning, so they only appear on a lone detail.
        if len(self.selected) == 1 and self.selected[0][0] == "detail":
            det = self.selected[0][1]
            picked = {i for d, i in self.corners if d is det}
            painter.setPen(QPen(gold, 1))
            for i, (gx, gy) in enumerate(self._corners(det)):
                sx, sy = self.paper_to_screen(gx, gy)
                # A chosen corner has to read as chosen beside three that are
                # merely available, so it fills dark and grows.
                if i in picked:
                    painter.setBrush(QColor(50, 62, 84))
                    painter.drawRect(int(sx) - 5, int(sy) - 5, 11, 11)
                else:
                    painter.setBrush(gold)
                    painter.drawRect(int(sx) - 4, int(sy) - 4, 8, 8)
            painter.setBrush(QColor(0, 0, 0, 0))

    def _paint_box(self, painter: QPainter):
        """The rubber band: gold for a window that must enclose, slate for a
        crossing that need only touch.

        Model space paints the crossing white, which it can afford against a
        dark viewport. Paper is nearly white, so both inks here are darker
        than the sheet, and a wash inside says which way round it is going.
        """
        if self.box is None:
            return
        x0, y0, x1, y1 = self.box
        crossing = x1 < x0
        colour = QColor(64, 78, 102) if crossing else QColor(176, 132, 40)
        wash = QColor(colour)
        wash.setAlpha(30)
        painter.setPen(QPen(colour, 1, Qt.PenStyle.DashLine))
        painter.setBrush(wash)
        painter.drawRect(int(min(x0, x1)), int(min(y0, y1)),
                         int(abs(x1 - x0)), int(abs(y1 - y0)))
        painter.setBrush(QColor(0, 0, 0, 0))

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

    def step_into_detail(self, sx: float, sy: float):
        """Enter the detail under the cursor, and say which one, or None.

        A command waiting for a point never sees a double-click — the press
        picks a point before the second click arrives — so while one is running
        it is the single click landing on a detail that steps into it. Nothing
        happens for the detail already entered: there the click is a point.
        """
        lay = self.layout
        if lay is None:
            return None
        px, py = self.screen_to_paper(sx, sy)
        detail = lay.detail_at(px, py)
        if detail is None or detail.id == self.entered_detail:
            return None
        self.entered_detail = detail.id
        return detail

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
        from ..core.layout import detail_corners
        return detail_corners(det)

    def _take(self, hit: tuple, add: bool):
        """Make `hit` the selection — or, holding the key, one more of it.

        Pressing on something already picked leaves the rest alone, because
        the press that starts a drag must not first throw the group away.
        """
        if not add:
            if hit not in self.selected:
                self.selected = [hit]
            return
        if hit in self.selected:
            self.selected = [s for s in self.selected if s != hit]
        else:
            self.selected = self.selected + [hit]

    def _take_corner(self, pick: tuple, add: bool):
        """Same hand as `_take`, one level down: a grip of a lone detail."""
        if not add:
            if pick not in self.corners:
                self.corners = [pick]
            return
        if pick in self.corners:
            self.corners = [c for c in self.corners if c != pick]
        else:
            self.corners = self.corners + [pick]

    def press(self, sx: float, sy: float, add: bool = False) -> bool:
        """LMB press while idle: select / start dragging sheet items."""
        lay = self.layout
        if lay is None or self.entered_detail is not None:
            return False
        px, py = self.screen_to_paper(sx, sy)
        tol = max(7.0 / self.px_per_mm, 0.8)
        self._prune()
        if len(self.selected) == 1 and self.selected[0][0] == "detail":
            det = self.selected[0][1]
            for i, (gx, gy) in enumerate(self._corners(det)):
                if abs(px - gx) <= tol and abs(py - gy) <= tol:
                    self._take_corner((det, i), add)
                    if det.locked or (det, i) not in self.corners:
                        return True
                    self._press_corner = None if add else (det, i)
                    self.vp.window_checkpoint("resize detail")
                    self._drag = ("resize", [c for _, c in self.corners],
                                  [("detail", det)])
                    self._drag_last = (px, py)
                    return True
        self.corners = []           # anything but a grip is a coarser pick
        from ..core.layout import annotation_at, paper_object_at
        # In paint order, topmost first: annotations sit over the geometry, the
        # geometry sits over the detail frames it is drawn across.
        hit = annotation_at(lay, px, py, tol=max(tol, 2.0))
        if hit is None:
            obj = paper_object_at(lay, px, py, tol=max(tol, 2.0))
            hit = ("object", obj) if obj is not None else None
        if hit is None:
            det = lay.detail_at(px, py)
            hit = ("detail", det) if det is not None else None
        if hit is not None:
            self._take(hit, add)
            movable = [(k, o) for k, o in self.selected
                       if k != "detail" or not o.locked]
            if movable and hit in self.selected:
                self._press_hit = None if add else hit
                self.vp.window_checkpoint("move sheet item")
                self._drag = ("move", -1, movable)
                self._drag_last = (px, py)
            return True
        # Empty paper: sweep a band out of it.
        if not add:
            self.selected = []
        self.box = (sx, sy, sx, sy)
        self._box_add = add
        return True

    def drag_selected(self, sx: float, sy: float) -> bool:
        if self.box is not None:
            self.box = self.box[:2] + (sx, sy)
            return True
        if self._drag is None:
            return False
        px, py = self.screen_to_paper(sx, sy)
        dx = px - self._drag_last[0]
        dy = py - self._drag_last[1]
        mode, corners, picks = self._drag
        from ..core.layout import move_sheet_item, nudge_detail_corners
        for kind, obj in picks:
            if kind == "detail" and mode != "move":
                nudge_detail_corners(obj, corners, dx, dy)
            else:
                move_sheet_item(kind, obj, dx, dy)
            if kind == "detail":
                self._hlr_cache.pop(obj.id, None)
        self._drag_moved = True
        self._drag_last = (px, py)
        self.vp.scene.notify("layouts")
        return True

    # ------------------------------------------------------------ band pick

    def _box_picks(self) -> list:
        """Everything the band has, in sheet order.

        Left to right is a window and must enclose; right to left is a
        crossing and need only touch. Same hand as model space, so the
        habit carries between the two.
        """
        lay = self.layout
        if lay is None or self.box is None:
            return []
        sx0, sy0, sx1, sy1 = self.box
        crossing = sx1 < sx0
        ax, ay = self.screen_to_paper(sx0, sy0)
        bx, by = self.screen_to_paper(sx1, sy1)
        lo = (min(ax, bx), min(ay, by))
        hi = (max(ax, bx), max(ay, by))
        from ..core.layout import (
            annotation_bounds, paper_object_bounds, paper_object_crosses,
        )
        out = []
        for kind, pool in self._pools(lay).items():
            for obj in pool:
                if kind == "object" and crossing:
                    # Its ink, not its box: a window band can stay with the box
                    # (enclosing the box is enclosing every point in it), but a
                    # crossing band asks what it actually touches.
                    if paper_object_crosses(obj, *lo, *hi):
                        out.append((kind, obj))
                    continue
                if kind == "detail":
                    b = (obj.x, obj.y, obj.x + obj.w, obj.y + obj.h)
                elif kind == "object":
                    b = paper_object_bounds(obj)
                else:
                    b = annotation_bounds(kind, obj)
                if crossing:
                    inside = (b[0] <= hi[0] and b[2] >= lo[0]
                              and b[1] <= hi[1] and b[3] >= lo[1])
                else:
                    inside = (b[0] >= lo[0] and b[2] <= hi[0]
                              and b[1] >= lo[1] and b[3] <= hi[1])
                if inside:
                    out.append((kind, obj))
        return out

    def release_drag(self):
        if self.box is not None:
            sx0, sy0, sx1, sy1 = self.box
            # A press that went nowhere is a click on empty paper, which has
            # already cleared the selection; picking on it would take the
            # whole sheet.
            if abs(sx1 - sx0) > 4 or abs(sy1 - sy0) > 4:
                picks = self._box_picks()
                if self._box_add:
                    self.selected += [p for p in picks
                                      if p not in self.selected]
                else:
                    self.selected = picks
            self.box = None
            self._box_add = False
            return
        if self._drag is None:
            return
        if not self._drag_moved:
            self.vp.window_discard_checkpoint()
            # The press held the whole group together in case it was the
            # start of a drag. It wasn't, so it was a choice: keep the one.
            if self._press_hit is not None:
                self.selected = [self._press_hit]
            if self._press_corner is not None:
                self.corners = [self._press_corner]
        self._drag = None
        self._drag_moved = False
        self._press_hit = None
        self._press_corner = None

    def move_corners(self, dx: float, dy: float) -> int:
        """Shift every picked corner by paper millimetres.

        The same maths the grip drag uses, reached from typed coordinates
        instead of from the mouse. Returns how many corners moved.
        """
        self._prune()
        if not self.corners:
            return 0
        det = self.corners[0][0]
        if det.locked:
            return 0
        from ..core.layout import nudge_detail_corners
        nudge_detail_corners(det, [i for _, i in self.corners], dx, dy)
        self._hlr_cache.pop(det.id, None)
        self.vp.scene.notify("layouts")
        return len(self.corners)

    def move_selected(self, dx: float, dy: float) -> int:
        """Shift every picked sheet item by paper millimetres."""
        self._prune()
        from ..core.layout import move_annotation, move_paper_object
        moved = 0
        for kind, obj in self.selected:
            if kind == "detail":
                if obj.locked:
                    continue
                obj.x += dx
                obj.y += dy
                self._hlr_cache.pop(obj.id, None)
            elif kind == "object":
                move_paper_object(obj, dx, dy)
            else:
                move_annotation(kind, obj, dx, dy)
            moved += 1
        if moved:
            self.vp.scene.notify("layouts")
        return moved

    def copy_selected(self, dx: float, dy: float) -> int:
        """Duplicate every picked sheet item, the copy offset by millimetres.

        It is the copy that moves and the original that is left alone, which
        is what lets a locked frame be copied: the lock is about the frame not
        being disturbed, and it is not. It also leaves the picked items still
        picked, so a second copy is measured from the same place as the first
        instead of walking away from it.
        """
        lay = self.layout
        self._prune()
        if lay is None or not self.selected:
            return 0
        from ..core.layout import (copy_sheet_item, move_annotation,
                                   move_paper_object)
        made = 0
        for kind, obj in list(self.selected):
            dup = copy_sheet_item(lay, kind, obj)
            if dup is None:
                continue
            if kind == "detail":
                dup.x += dx
                dup.y += dy
            elif kind == "object":
                move_paper_object(dup, dx, dy)
            else:
                move_annotation(kind, dup, dx, dy)
            made += 1
        if made:
            self.vp.scene.notify("layouts")
        return made

    def delete_selected(self) -> bool:
        lay = self.layout
        self._prune()
        if lay is None or not self.selected:
            return False
        from ..core.layout import delete_annotation
        self.vp.window_checkpoint("delete sheet items")
        gone = False
        for kind, obj in self.selected:
            if kind == "detail":
                lay.details.remove(obj)
                self._hlr_cache.pop(obj.id, None)
                gone = True
            elif kind == "object":
                lay.objects.remove(obj)
                gone = True
            elif delete_annotation(lay, kind, obj):
                gone = True
        self.selected = []
        if not gone:
            self.vp.window_discard_checkpoint()
            return False
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
