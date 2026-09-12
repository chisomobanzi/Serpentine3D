"""The gumball for the paper itself.

Inside a detail what is picked is a model object, and `Gumball` gives it the
handles the model window gives it, drawn through the detail's eye. On bare
paper what is picked is a detail frame, a note or a dimension, and none of
those are model geometry: there is no shape to transform, only millimetres
across a sheet. So this is a second, much smaller gumball rather than a mode
of the first one, and it shares nothing with it but the look.

It offers two arrows and the one plane pad a sheet has. The pad moves ordinary
sheet items and Shift-drag scales text and paper geometry uniformly in the
paper plane. Paper geometry also gets a Z-axis ring for turning it in the
sheet; a detail frame keeps using its own corner grips for resizing.

Everything here is in paper millimetres, hit-tested in viewport pixels, and
sized so the arrows come out the length they are in the model window.
"""

from __future__ import annotations

import copy

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QPen, QPolygonF

from ..core.layout import (annotation_bounds, copy_sheet_item, move_sheet_item,
                           note_text_height, sheet_item_bounds, sheet_pools)
from .gumball import (
    ARC_R, AXIS_COLORS, CONE1, HOVER_COLOR, PAD0, PAD1, PAD_ALPHA, SHAFT0,
    SIZE_PX, _alt_held,
)

# Paper is two-dimensional, so the axes are named the way the model gumball
# names them and the third never appears: 0 is across the sheet, 1 is up it,
# and the single pad is the one perpendicular to the axis that is not here.
X, Y, PAD_AXIS = 0, 1, 2
_HIT_PX = 7.0                       # how near a cursor has to come to a shaft
_ROT_START_DEG = 20.0               # leave space beside the +X arrow
_ROT_END_DEG = 70.0                 # and beside the +Y arrow


def _qcolor(rgb, alpha: int = 255) -> QColor:
    c = QColor(int(rgb[0] * 255), int(rgb[1] * 255), int(rgb[2] * 255))
    c.setAlpha(alpha)
    return c


def _shift_held(modifiers) -> bool:
    """Shift state, robust to a Qt KeyboardModifiers flag or a plain int."""
    m = getattr(modifiers, "value", modifiers)          # Qt flag -> int
    return bool(int(m) & int(Qt.KeyboardModifier.ShiftModifier.value))


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
        self._copy_undo_selection = None
        self.vp.scene.add_listener(
            self._restore_alt_copy_selection, kinds=("layouts",))

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
        boxes = np.array([
            sheet_item_bounds(k, o, self.vp.scene) for k, o in picks
        ], float)
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

    def _can_rotate(self) -> bool:
        """Whether every selected item has paper-plane geometry to turn."""
        picks = self._picks()
        return bool(picks) and all(kind == "object" for kind, _obj in picks)

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
        if self._can_rotate():
            centre = np.asarray(self.lv.paper_to_screen(*at), float)
            radius = ARC_R * SIZE_PX
            delta = cursor - centre
            angle = float(np.degrees(np.arctan2(-delta[1], delta[0]))) % 360.0
            on_arc = _ROT_START_DEG <= angle <= _ROT_END_DEG
            if on_arc and abs(float(np.linalg.norm(delta)) - radius) < _HIT_PX:
                return ("rot", PAD_AXIS)
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
        rotating = handle == ("rot", PAD_AXIS)
        if handle[0] == "rot" and (not rotating or not self._can_rotate()):
            return False
        self.vp.window_checkpoint("gumball " + handle[0])
        original_selection = list(self.lv.selected)
        copies = []
        if modifiers is not None and _alt_held(modifiers) \
                and handle[0] in ("move", "pad", "rot"):
            lay = self.lv.layout
            if lay is not None:
                for kind, obj in picks:
                    dup = copy_sheet_item(lay, kind, obj)
                    if dup is not None:
                        copies.append((kind, dup))
            if copies:
                picks = copies
                self.lv.selected = list(copies)
                self.vp.layoutSelectionChanged.emit()
                self.vp.scene.notify("layouts")
        scaling_items = (modifiers is not None
                         and _shift_held(modifiers)
                         and handle[0] == "pad"
                         and all(kind in ("note", "object")
                                 for kind, _obj in picks))
        note_originals = []
        object_originals = []
        if scaling_items:
            for kind, obj in picks:
                if kind == "note":
                    note_originals.append((
                        obj,
                        copy.deepcopy(vars(obj)),
                        annotation_bounds("note", obj, self.vp.scene),
                    ))
                else:
                    object_originals.append((obj, obj.shape))
        rotation_originals = ([(obj, obj.shape) for _kind, obj in picks]
                              if rotating else [])
        self.drag = {
            "handle": handle,
            "anchor": at,
            "picks": picks,
            "copies": copies,
            "original_selection": original_selection,
            "start": self.lv.screen_to_paper(px, py),
            "offset": (0.0, 0.0),
            "scale": 1.0,
            "scaling": scaling_items,
            "note_originals": note_originals,
            "object_originals": object_originals,
            "rotation_originals": rotation_originals,
            "angle": 0.0,
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

    def _wanted_scale(self, px: float, py: float) -> float:
        """Uniform paper scale asked for by a Shift-pad drag."""
        d = self.drag
        now = np.asarray(self.lv.screen_to_paper(px, py), float)
        anchor = np.asarray(d["anchor"], float)
        start_radius = float(np.linalg.norm(
            np.asarray(d["start"], float) - anchor))
        if start_radius < 1e-9:
            return 1.0
        return max(float(np.linalg.norm(now - anchor)) / start_radius, 0.01)

    def _wanted_angle(self, px: float, py: float, modifiers=None) -> float:
        """Signed paper-plane angle from the ring press to the cursor."""
        d = self.drag
        anchor = np.asarray(d["anchor"], float)
        start = np.asarray(d["start"], float) - anchor
        now = np.asarray(self.lv.screen_to_paper(px, py), float) - anchor
        if np.linalg.norm(start) < 1e-9 or np.linalg.norm(now) < 1e-9:
            return d["angle"]
        cross = float(start[0] * now[1] - start[1] * now[0])
        dot = float(start @ now)
        angle = float(np.degrees(np.arctan2(cross, dot)))
        if modifiers is not None and _shift_held(modifiers):
            angle = round(angle / 15.0) * 15.0
        return angle

    def _rotate_items_to(self, angle: float):
        """Rotate paper objects from their drag-start shapes."""
        from ..core import geometry
        d = self.drag
        anchor = d["anchor"]
        centre = (float(anchor[0]), float(anchor[1]), 0.0)
        for obj, shape in d["rotation_originals"]:
            obj.shape = geometry.rotate(shape, centre, (0.0, 0.0, 1.0),
                                        angle)
        d["angle"] = float(angle)
        self.vp.scene.notify("layouts")

    def _scale_items_to(self, factor: float):
        """Scale supported sheet items from their drag-start state."""
        d = self.drag
        anchor = np.asarray(d["anchor"], float)
        for note, state, bounds in d["note_originals"]:
            note.__dict__.clear()
            note.__dict__.update(copy.deepcopy(state))
            if abs(factor - 1.0) < 1e-12:
                continue

            x0, y0, x1, y1 = bounds
            old_centre = np.asarray(((x0 + x1) / 2, (y0 + y1) / 2),
                                    float)
            wanted_centre = anchor + (old_centre - anchor) * factor

            # A named annotation style owns the effective height. Scaling is
            # an explicit per-note edit, so preserve its rendered size as the
            # new local height and detach it from that shared style.
            height = note_text_height(note, self.vp.scene)
            note.style = ""
            note.height = height * factor
            bx0, by0, bx1, by1 = annotation_bounds(
                "note", note, self.vp.scene)
            new_centre = np.asarray(((bx0 + bx1) / 2, (by0 + by1) / 2),
                                    float)
            note.x += float(wanted_centre[0] - new_centre[0])
            note.y += float(wanted_centre[1] - new_centre[1])
        if d["object_originals"]:
            from ..core import geometry
            centre = (float(anchor[0]), float(anchor[1]), 0.0)
            factors = (factor, factor, 1.0)
            for obj, shape in d["object_originals"]:
                obj.shape = geometry.scale(
                    shape, centre, factor, factors=factors)
        d["scale"] = factor
        self.vp.scene.notify("layouts")

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
        if self.drag["typed"]:
            return self.drag["last_label"]
        self.drag["armed"] = False
        if self.drag["rotation_originals"]:
            angle = self._wanted_angle(px, py, modifiers)
            self._rotate_items_to(angle)
            label = f"rotate {angle:.1f}\N{DEGREE SIGN}"
        elif self.drag["scaling"]:
            factor = self._wanted_scale(px, py)
            self._scale_items_to(factor)
            label = f"{factor:.3f}x"
        else:
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
        if d["rotation_originals"]:
            moved = abs(d["angle"]) >= 1e-9
        elif d["scaling"]:
            moved = abs(d["scale"] - 1.0) >= 1e-9
        else:
            moved = (abs(d["offset"][0]) >= 1e-9
                     or abs(d["offset"][1]) >= 1e-9)
        if not moved:
            # Nothing went anywhere, so nothing is worth an undo step.
            self._remove_copies(d)
            self.vp.window_discard_checkpoint()
        elif d["copies"]:
            lay = self.lv.layout
            self._copy_undo_selection = {
                "layout": None if lay is None else lay.id,
                "copies": [(kind, obj.id) for kind, obj in d["copies"]],
                "originals": [(kind, obj.id)
                              for kind, obj in d["original_selection"]],
            }
        self.drag = None

    def _restore_alt_copy_selection(self):
        """Keep an Alt-copy selection attached across Undo and Redo.

        Scene restore clones layouts, so even when the selected IDs survive,
        their Python objects do not.  Track both sides of the copy operation
        until the user selects something else, and rebind the selection to
        whichever side exists in the restored layout.
        """
        state = self._copy_undo_selection
        if state is None or self.drag is not None:
            return

        selected = list(self.lv.selected)
        selected_ids = [(kind, obj.id) for kind, obj in selected]
        if selected_ids not in (state["copies"], state["originals"]):
            self._copy_undo_selection = None
            return
        lay = next((item for item in self.vp.scene.layouts
                    if item.id == state["layout"]), None)
        if lay is None:
            self._copy_undo_selection = None
            return
        pools = sheet_pools(lay)

        def resolve(ids):
            items = []
            for kind, oid in ids:
                obj = next((item for item in pools.get(kind, ())
                            if item.id == oid), None)
                if obj is None:
                    return None
                items.append((kind, obj))
            return items

        originals = resolve(state["originals"])
        copies = resolve(state["copies"])
        selected_are_live = (
            originals if selected_ids == state["originals"] else copies)
        selection_is_current = (
            selected_are_live is not None
            and all(old is live for (_kind, old), (_kind2, live)
                    in zip(selected, selected_are_live)))

        if selected_ids == state["copies"]:
            restored = copies if copies is not None else originals
        elif not selection_is_current:
            # Originals selected before a restore means Redo should put the
            # handles back on the copies; without copies, merely rebind the
            # originals cloned by an unrelated restored snapshot.
            restored = copies if copies is not None else originals
        elif copies is not None:
            # Both sides still exist and the user deliberately picked the
            # originals.  Stop tracking so a later layout edit cannot steal
            # that explicit selection back.
            self._copy_undo_selection = None
            return

        if restored is None:
            self._copy_undo_selection = None
            return
        if selection_is_current and restored is selected_are_live:
            return
        self.lv.selected = restored
        self.vp.layoutSelectionChanged.emit()

    def _remove_copies(self, d):
        """Remove copies made provisionally when an Alt drag is abandoned."""
        lay = self.lv.layout
        if lay is None or not d["copies"]:
            return
        pools = sheet_pools(lay)
        for kind, obj in d["copies"]:
            pool = pools.get(kind)
            if pool is not None and obj in pool:
                pool.remove(obj)
            if kind == "detail":
                self.lv._hlr_cache.pop(obj.id, None)
        self.lv.selected = d["original_selection"]
        self.vp.layoutSelectionChanged.emit()
        self.vp.scene.notify("layouts")

    def cancel_drag(self):
        if self.drag is None:
            return
        d = self.drag
        if d["rotation_originals"]:
            self._rotate_items_to(0.0)
        elif d["scaling"]:
            self._scale_items_to(1.0)
        else:
            self._move_to((0.0, 0.0))
        self._remove_copies(d)
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
        return (self.drag is not None
                and self.drag["handle"][0] in ("move", "rot"))

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
        if self.drag["handle"][0] == "rot":
            self._rotate_items_to(value)
        else:
            axis = self.drag["handle"][1]
            self._move_to((value, 0.0) if axis == X else (0.0, value))

    def commit_typed(self) -> bool:
        if self.drag is None or self._parse_typed() is None:
            return False
        self._preview_typed()
        self.end_drag()
        return True

    def readout(self):
        """(text, (screen_x, screen_y)) for the value label, pinned to where
        the drag started so a typed move cannot carry it off screen."""
        d = self.drag
        if d is None:
            return None
        rotating = d["handle"][0] == "rot"
        if d["typed"]:
            text = (f"angle: {d['typed']}\N{DEGREE SIGN}" if rotating
                    else f"distance: {d['typed']}")
        elif d["armed"]:
            text = ("type an angle, Enter" if rotating
                    else "type a distance, Enter")
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
        if self._can_rotate():
            self._paint_rotation_ring(painter, at)
        self._paint_pad(painter, at, s)
        for axis in (X, Y):
            self._paint_arrow(painter, at, s, axis)
        painter.restore()

    def _paint_rotation_ring(self, painter, at):
        centre = QPointF(*self.lv.paper_to_screen(*at))
        radius = ARC_R * SIZE_PX
        painter.setPen(QPen(self._colour("rot", PAD_AXIS), 1.6))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(centre.x() - radius, centre.y() - radius,
                        radius * 2, radius * 2,
                        round(_ROT_START_DEG * 16),
                        round((_ROT_END_DEG - _ROT_START_DEG) * 16))

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
