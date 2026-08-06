"""The gumball for the paper itself.

Inside a detail what is picked is a model object, and `Gumball` gives it the
handles the model window gives it, drawn through the detail's eye. On bare
paper what is picked is a detail frame, a note or a dimension, and none of
those are model geometry: there is no shape to transform, only millimetres
across a sheet. So this is a second, much smaller gumball rather than a mode
of the first one, and it shares nothing with it but the look.

It offers two arrows and the one plane pad a sheet has. Nothing turns and
nothing scales, because nothing on a sheet has an angle or a size that a
handle could honestly change — a detail frame is an upright rectangle with
corner grips of its own for that. Handles that would lie about what they do
are better not drawn.

Everything here is in paper millimetres, hit-tested in viewport pixels, and
sized so the arrows come out the length they are in the model window.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QPen, QPolygonF

from ..core.layout import move_sheet_item, sheet_item_bounds
from .gumball import (
    AXIS_COLORS, CONE1, HOVER_COLOR, PAD0, PAD1, PAD_ALPHA, SHAFT0, SIZE_PX,
)

# Paper is two-dimensional, so the axes are named the way the model gumball
# names them and the third never appears: 0 is across the sheet, 1 is up it,
# and the single pad is the one perpendicular to the axis that is not here.
X, Y, PAD_AXIS = 0, 1, 2
_HIT_PX = 7.0                       # how near a cursor has to come to a shaft


def _qcolor(rgb, alpha: int = 255) -> QColor:
    c = QColor(int(rgb[0] * 255), int(rgb[1] * 255), int(rgb[2] * 255))
    c.setAlpha(alpha)
    return c


class PaperGumball:
    """Handles on what is picked on a sheet.

    Duck-typed against `Gumball` for the handful of things the viewport asks
    of whichever one is live — `drag`, `hover`, `hit_test`, `begin_drag`,
    `drag_to`, `end_drag`, `cancel_drag`, `arm`, `accepts_typing`,
    `type_char`, `commit_typed`, `readout` — so a press, a hover and a
    keystroke can be routed by one accessor instead of three branches.
    """

    def __init__(self, layout_view):
        self.lv = layout_view
        self.hover = None
        self.drag = None            # dict: handle, start, offset, typed, ...

    # ----------------------------------------------------------------- state

    @property
    def vp(self):
        return self.lv.vp

    def active(self) -> bool:
        lv = self.lv
        vp = self.vp
        if vp.space == "model" or lv.entered_detail is not None:
            return False            # in a detail the model's gumball has it
        if vp.point_mode or not vp.gumball.enabled:
            return False
        if self.drag is not None:   # a drag stays live to its end
            return True
        return bool(self._picks())

    def _picks(self) -> list:
        """What of the selection a handle could actually move.

        A locked detail is the one thing on a sheet that is picked but does
        not travel, and a gumball standing on nothing but locked details would
        be a set of arrows that do nothing when you pull them.
        """
        self.lv._prune()
        return [(k, o) for k, o in self.lv.selected
                if k != "detail" or not o.locked]

    def anchor(self):
        """The middle of everything picked, in paper millimetres."""
        picks = self._picks()
        if not picks:
            return None
        boxes = np.array([sheet_item_bounds(k, o) for k, o in picks], float)
        return ((boxes[:, 0].min() + boxes[:, 2].max()) / 2,
                (boxes[:, 1].min() + boxes[:, 3].max()) / 2)

    def _size_mm(self) -> float:
        """Paper length that comes out SIZE_PX pixels long at this zoom."""
        return SIZE_PX / max(self.lv.px_per_mm, 1e-9)

    def _draw_anchor(self):
        """Where it is drawn this frame: during a move it travels with what it
        is moving, so the arrows stay under the cursor that took them."""
        if self.drag is None:
            return self.anchor()
        at = self.drag["anchor"]
        dx, dy = self.drag["offset"]
        return (at[0] + dx, at[1] + dy)

    # ----------------------------------------------------------- hit testing

    def _axis_end(self, at, axis: int, reach: float):
        s = self._size_mm() * reach
        return (at[0] + (s if axis == X else 0.0),
                at[1] + (s if axis == Y else 0.0))

    def hit_test(self, px: float, py: float):
        if not self.active():
            return None
        at = self._draw_anchor()
        if at is None:
            return None
        s = self._size_mm()
        cursor = np.array([px, py], float)
        # The pad first: it is the smaller target and it sits in the corner
        # both arrows set out from.
        quad = [self.lv.paper_to_screen(at[0] + a * s, at[1] + b * s)
                for a, b in ((PAD0, PAD0), (PAD1, PAD0),
                             (PAD1, PAD1), (PAD0, PAD1))]
        if _in_poly(cursor, quad):
            return ("pad", PAD_AXIS)
        for axis in (X, Y):
            a = np.array(self.lv.paper_to_screen(
                *self._axis_end(at, axis, SHAFT0)), float)
            b = np.array(self.lv.paper_to_screen(
                *self._axis_end(at, axis, CONE1)), float)
            if _seg_dist(cursor, a, b) < _HIT_PX:
                return ("move", axis)
        return None

    def update_hover(self, px: float, py: float) -> bool:
        new = self.hit_test(px, py)
        if new != self.hover:
            self.hover = new
            return True
        return False

    # -------------------------------------------------------------- dragging

    def begin_drag(self, handle, px: float, py: float,
                   modifiers=None) -> bool:
        at = self.anchor()
        picks = self._picks()
        if at is None or not picks:
            return False
        self.vp.window_checkpoint("gumball " + handle[0])
        self.drag = {
            "handle": handle,
            "anchor": at,
            "picks": picks,
            "start": self.lv.screen_to_paper(px, py),
            "offset": (0.0, 0.0),
            "typed": "",
            "armed": False,
            "last_label": "",
        }
        return True

    def _wanted(self, px: float, py: float) -> tuple:
        """Where the drag asks the selection to be, relative to its start."""
        d = self.drag
        now = self.lv.screen_to_paper(px, py)
        dx = now[0] - d["start"][0]
        dy = now[1] - d["start"][1]
        axis = d["handle"][1]
        if d["handle"][0] == "move":
            return (dx, 0.0) if axis == X else (0.0, dy)
        return (dx, dy)

    def _move_to(self, offset: tuple):
        """Put the selection at `offset` from where the drag found it.

        Measured from the start rather than the last mouse position, so a
        drag that passes over a spot twice leaves things where that spot says
        and a typed value replaces the drag instead of adding to it.
        """
        d = self.drag
        dx = offset[0] - d["offset"][0]
        dy = offset[1] - d["offset"][1]
        for kind, obj in d["picks"]:
            move_sheet_item(kind, obj, dx, dy)
            if kind == "detail":
                self.lv._hlr_cache.pop(obj.id, None)
        d["offset"] = (offset[0], offset[1])
        self.vp.scene.notify("layouts")

    def drag_to(self, px: float, py: float, modifiers=None) -> str:
        if self.drag is None:
            return ""
        self.drag["typed"] = ""
        self.drag["armed"] = False
        self._move_to(self._wanted(px, py))
        dx, dy = self.drag["offset"]
        if self.drag["handle"][0] == "move":
            label = f"{dx if self.drag['handle'][1] == X else dy:.2f} mm"
        else:
            label = f"{dx:.2f}, {dy:.2f} mm"
        self.drag["last_label"] = label
        return label

    def end_drag(self):
        d = self.drag
        if d is None:
            return
        if abs(d["offset"][0]) < 1e-9 and abs(d["offset"][1]) < 1e-9:
            # Nothing went anywhere, so nothing is worth an undo step.
            self.vp.window_discard_checkpoint()
        self.drag = None

    def cancel_drag(self):
        if self.drag is None:
            return
        self._move_to((0.0, 0.0))
        self.vp.window_discard_checkpoint()
        self.drag = None
        self.vp.scene.notify("layouts")

    # --------------------------------------------------------- typing a value

    def arm(self):
        """Keep a drag live after a click that never moved, so a distance can
        be typed into the handle that was taken."""
        if self.drag is not None and self.accepts_typing():
            self.drag["armed"] = True

    def accepts_typing(self) -> bool:
        """One number can say how far along one axis. It cannot say how far
        in two directions at once, so the pad takes nothing."""
        return self.drag is not None and self.drag["handle"][0] == "move"

    def type_char(self, ch: str) -> bool:
        d = self.drag
        if d is None or not self.accepts_typing():
            return False
        d["typed"] = d["typed"][:-1] if ch == "back" else d["typed"] + ch
        d["armed"] = True
        self._preview_typed()
        return True

    def _parse_typed(self):
        try:
            return float(self.drag["typed"])
        except (TypeError, ValueError):
            return None

    def _preview_typed(self):
        value = self._parse_typed()
        if value is None:
            return
        axis = self.drag["handle"][1]
        self._move_to((value, 0.0) if axis == X else (0.0, value))

    def commit_typed(self) -> bool:
        if self.drag is None or self._parse_typed() is None:
            return False
        self._preview_typed()
        self.drag = None
        return True

    def readout(self):
        """(text, (screen_x, screen_y)) for the value label, pinned to where
        the drag started so a typed move cannot carry it off screen."""
        d = self.drag
        if d is None:
            return None
        if d["typed"]:
            text = f"distance: {d['typed']}"
        elif d["armed"]:
            text = "type a distance, Enter"
        else:
            text = d["last_label"]
        if not text:
            return None
        sx, sy = self.lv.paper_to_screen(*d["anchor"])
        return text, (int(sx) + 18, int(sy) - 14)

    # -------------------------------------------------------------- painting

    def paint(self, painter):
        """Drawn with QPainter over the sheet, not into it.

        Everything else on a sheet is ink on paper and is drawn in the GL
        pass; a handle is a thing to take hold of, so it goes on last and
        reaches over a detail's own linework rather than under it.
        """
        if not self.active():
            return
        at = self._draw_anchor()
        if at is None:
            return
        s = self._size_mm()
        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing)
        self._paint_pad(painter, at, s)
        for axis in (X, Y):
            self._paint_arrow(painter, at, s, axis)
        painter.restore()

    def _colour(self, kind: str, axis: int, alpha: int = 255) -> QColor:
        if self.hover == (kind, axis):
            return _qcolor(HOVER_COLOR, alpha)
        return _qcolor(AXIS_COLORS[axis], alpha)

    def _paint_pad(self, painter, at, s):
        quad = QPolygonF([
            QPointF(*self.lv.paper_to_screen(at[0] + a * s, at[1] + b * s))
            for a, b in ((PAD0, PAD0), (PAD1, PAD0),
                         (PAD1, PAD1), (PAD0, PAD1))])
        colour = self._colour("pad", PAD_AXIS)
        painter.setPen(QPen(colour, 1.2))
        painter.setBrush(QBrush(_qcolor(
            HOVER_COLOR if self.hover == ("pad", PAD_AXIS)
            else AXIS_COLORS[PAD_AXIS], int(PAD_ALPHA * 255))))
        painter.drawPolygon(quad)
        painter.setBrush(Qt.BrushStyle.NoBrush)

    def _paint_arrow(self, painter, at, s, axis: int):
        colour = self._colour("move", axis)
        a = np.array(self.lv.paper_to_screen(
            *self._axis_end(at, axis, SHAFT0)), float)
        b = np.array(self.lv.paper_to_screen(
            *self._axis_end(at, axis, CONE1)), float)
        painter.setPen(QPen(colour, 2.0))
        painter.drawLine(QPointF(*a), QPointF(*b))
        # The head, as a triangle: 10 pixels back from the tip and 4 across,
        # which is what the model gumball's cone comes out as on screen.
        d = b - a
        n = float(np.hypot(*d)) or 1.0
        d = d / n
        side = np.array([-d[1], d[0]])
        painter.setPen(QPen(colour, 1.0))
        painter.setBrush(QBrush(colour))
        painter.drawPolygon(QPolygonF([
            QPointF(*b), QPointF(*(b - d * 10 + side * 4)),
            QPointF(*(b - d * 10 - side * 4))]))
        painter.setBrush(Qt.BrushStyle.NoBrush)


def _seg_dist(p, a, b) -> float:
    """Pixels from `p` to the segment a-b."""
    ab = b - a
    denom = float(ab @ ab)
    if denom < 1e-12:
        return float(np.linalg.norm(p - a))
    t = float(np.clip((p - a) @ ab / denom, 0.0, 1.0))
    return float(np.linalg.norm(p - (a + ab * t)))


def _in_poly(p, poly) -> bool:
    """Even-odd test, the same one the model gumball's pads use."""
    inside = False
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        if (y0 > p[1]) != (y1 > p[1]):
            xx = x0 + (p[1] - y0) * (x1 - x0) / ((y1 - y0) or 1e-12)
            if p[0] < xx:
                inside = not inside
    return inside
