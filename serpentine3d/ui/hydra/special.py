"""Components shown otherwise than as a line with their title: the Number
Slider with its rail, the Boolean Toggle with its value, the Panel with its
text and the Geometry Pipeline with what it takes. Another one is a
NodeItem subclass, added to ITEMS under its component's key."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QActionGroup, QColor, QFont, QFontMetrics, QPen

from ...core import hydra
from .items import NodeItem
from .style import (
    ACCENT, MUTED, NODE_HEIGHT, NODE_WIDTH, PANEL_HEAD, PANEL_HEIGHT,
    PANEL_WIDTH, SLIDER_WIDTH, TEXT, VALUE_GAP, VALUE_WIDTH,
    component_icon, mark_room, marks,
)


PANEL_GRIP = 14              # the corner of a panel that drags its size
PANEL_SMALLEST = (120, 60)   # how small a panel can be dragged


class ValueItem(NodeItem):
    """A slider or a toggle: it shows its value, not its title, but a name
    given to it stands before the value."""

    width_alone = None      # as wide as the title needs, when None

    @staticmethod
    def name_room(title):
        bold = QFont()
        bold.setPointSizeF(9)
        bold.setBold(True)
        return QFontMetrics(bold).horizontalAdvance(title) + 12

    @classmethod
    def size(cls, comp, flags=None, title=None, params=None):
        labels, width, height = super().size(comp, flags, title)
        if title and title != comp.title:
            return labels, ((cls.width_alone or NODE_WIDTH)
                            + cls.name_room(title)), NODE_HEIGHT
        return labels, cls.width_alone or width, height

    def _given_name_room(self):
        """What a name given to it takes before its value."""
        if "name" not in self.node.params:
            return 0
        return self.name_room(self.node.title)

    def _paint_given_name(self, painter):
        room = self._given_name_room()
        if room:
            painter.setPen(TEXT)
            painter.drawText(QRectF(NODE_HEIGHT + 2, 0, room, self.height),
                             Qt.AlignmentFlag.AlignVCenter, self.node.title)
        return room


class SliderItem(ValueItem):
    """A rail with a knob to drag, and the value written beside it."""

    width_alone = SLIDER_WIDTH

    def __init__(self, editor, node):
        super().__init__(editor, node)
        self.mid_drag = False

    def paint_inside(self, painter):
        self.paint_head(painter)
        self._paint_given_name(painter)
        p = self.node.params
        x0, x1 = self._rail()
        y = NODE_HEIGHT / 2
        span = p["max"] - p["min"]
        knob = x0 + (x1 - x0) * ((p["value"] - p["min"]) / span
                                 if span > 0 else 0.0)
        painter.setPen(QPen(QColor("#1b1c1f"), 4, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(x0, y), QPointF(x1, y))
        painter.setPen(QPen(ACCENT, 4, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(x0, y), QPointF(knob, y))
        painter.setPen(QPen(QColor("#1b1c1f"), 1))
        painter.setBrush(TEXT)
        painter.drawEllipse(QPointF(knob, y), 6, 6)
        painter.setPen(TEXT)
        font = QFont(painter.font())
        font.setPointSizeF(10.5)
        painter.setFont(font)
        painter.drawText(self.value_rect(),
                         Qt.AlignmentFlag.AlignVCenter
                         | Qt.AlignmentFlag.AlignRight, self.value_text())

    def _rail(self):
        """Where the rail runs, left to right, along the middle."""
        return (NODE_HEIGHT + 6 + self._given_name_room(),
                self.width - VALUE_WIDTH - VALUE_GAP - 12)

    def value_rect(self):
        """Where the value is written, clear of the output on the right."""
        return QRectF(self.width - VALUE_WIDTH - VALUE_GAP, 0, VALUE_WIDTH,
                      NODE_HEIGHT)

    def value_text(self):
        p = self.node.params
        return hydra.format_number(p["value"], p["decimals"])

    def said(self):
        return self.value_text()

    def slide_to(self, x):
        p = self.node.params
        x0, x1 = self._rail()
        t = min(max((x - x0) / (x1 - x0), 0.0), 1.0)
        hydra.set_slider(p, p["min"] + (p["max"] - p["min"]) * t)
        self.set_result(self.result)
        self.editor.changed()

    def _on_rail(self, pos):
        x0, x1 = self._rail()
        return x0 - 8 <= pos.x() <= x1 + 8

    def mouseDoubleClickEvent(self, event):
        self.editor.type_value(self)

    def mousePressEvent(self, event):
        if (event.button() == Qt.MouseButton.LeftButton
                and self._on_rail(event.pos())):
            self.mid_drag = True
            self.slide_to(event.pos().x())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.mid_drag:
            self.slide_to(event.pos().x())
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.mid_drag:
            self.mid_drag = False
            self.editor.record()
            return
        super().mouseReleaseEvent(event)

    def add_menu_entries(self, menu):
        editor = self.editor
        menu.addAction("Change Range...", lambda: editor.change_range(self))
        places = menu.addMenu("Decimal Places")
        group = QActionGroup(places)
        for n in range(hydra.MAX_DECIMALS + 1):
            action = places.addAction(str(n))
            action.setCheckable(True)
            action.setChecked(n == self.node.params["decimals"])
            group.addAction(action)
            action.triggered.connect(
                lambda checked=False, n=n: editor.set_decimals(self, n))
        menu.addSeparator()


class ToggleItem(ValueItem):
    """True or False, True lit up; a double-click switches it."""

    def paint_inside(self, painter):
        self.paint_head(painter)
        room = self._paint_given_name(painter)
        on = bool(self.node.params.get("value"))
        painter.setPen(ACCENT if on else MUTED)
        left = NODE_HEIGHT + 2 + room
        painter.drawText(QRectF(left, 0, self.width - left - 12, self.height),
                         Qt.AlignmentFlag.AlignVCenter,
                         "True" if on else "False")

    def summary(self):
        return "True" if self.node.params.get("value") else "False"

    def mouseDoubleClickEvent(self, event):
        self.editor.flip(self.node.id)

    def add_menu_entries(self, menu):
        menu.addAction("Switch", lambda: self.editor.flip(self.node.id))
        menu.addSeparator()


class PanelItem(NodeItem):
    """A box of text under a title strip: what comes in, or what was typed
    into it with a double-click. Its corner, bottom right, drags it to
    another size."""

    def __init__(self, editor, node):
        super().__init__(editor, node)
        self._resize_from = None

    @classmethod
    def size(cls, comp, flags=None, title=None, params=None):
        width, height = (params or {}).get("size",
                                           (PANEL_WIDTH, PANEL_HEIGHT))
        # wider by the room its marks take, so the text keeps its room
        return 0, (width + mark_room(marks(comp, flags, False))
                   + mark_room(marks(comp, flags, True))), height

    def _on_grip(self, pos):
        return (pos.x() > self.width - PANEL_GRIP
                and pos.y() > self.height - PANEL_GRIP)

    def _paint_grip(self, painter):
        painter.save()
        painter.setPen(QPen(MUTED, 1))
        right, bottom = self.width - 3, self.height - 3
        for k in (4, 8):
            painter.drawLine(QPointF(right - k, bottom),
                             QPointF(right, bottom - k))
        painter.restore()

    def hoverMoveEvent(self, event):
        if self._on_grip(event.pos()):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        else:
            self.unsetCursor()
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event):
        self.unsetCursor()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        if (event.button() == Qt.MouseButton.LeftButton
                and self._on_grip(event.pos())):
            width, height = self.node.params.get(
                "size", (PANEL_WIDTH, PANEL_HEIGHT))
            # where the corner was grabbed, and the size it had then
            self._resize_from = (event.pos(), width, height)
            self.mid_drag = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resize_from is None:
            super().mouseMoveEvent(event)
            return
        start, width, height = self._resize_from
        moved = event.pos() - start
        self.node.params["size"] = [
            round(max(PANEL_SMALLEST[0], width + moved.x())),
            round(max(PANEL_SMALLEST[1], height + moved.y()))]
        self.relayout()

    def mouseReleaseEvent(self, event):
        if self._resize_from is None:
            super().mouseReleaseEvent(event)
            return
        self._resize_from = None
        self.mid_drag = False
        self.editor.changed()

    def panel_area(self):
        """Where its text goes, under its title strip, clear of the marks
        of its ports' flags."""
        flags = self.node.params.get("flags")
        comp = self.node.component
        left = 6 + mark_room(marks(comp, flags, False))
        right = 6 + mark_room(marks(comp, flags, True))
        return QRectF(left, PANEL_HEAD, self.width - left - right,
                      self.height - PANEL_HEAD - 6)

    def panel_lines(self):
        """What it shows: what comes in, listed as tooltips list it, or the
        text typed into it; a word on what to do when empty."""
        port = self.inputs[0].port
        tree, wired = self.editor.graph.input_values(
            self.node.id, port, self.editor.results)
        if wired:
            return hydra.list_tree(tree, most=40) or ["empty"], True
        text = self.node.params.get("text", "")
        if not text.strip():
            return ["Double-click to type"], False
        return text.splitlines(), True

    def paint_inside(self, painter):
        icon = component_icon(self.node.component)
        if icon is not None:
            icon.paint(painter, QRect(6, 3, PANEL_HEAD - 6, PANEL_HEAD - 6))
        font = QFont(painter.font())
        font.setPointSizeF(9)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(TEXT)
        painter.drawText(QRectF(PANEL_HEAD + 2, 0, self.width, PANEL_HEAD),
                         Qt.AlignmentFlag.AlignVCenter, self.node.title)
        area = self.panel_area()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#25272b"))
        painter.drawRoundedRect(area, 3, 3)
        lines, filled = self.panel_lines()
        font.setBold(False)
        font.setPointSizeF(8.5)
        painter.setFont(font)
        painter.setPen(TEXT if filled else MUTED)
        painter.save()
        painter.setClipRect(area)
        painter.drawText(area.adjusted(6, 4, -6, -4),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                         "\n".join(lines))
        painter.restore()
        self._paint_flags(painter)
        self._paint_grip(painter)

    def mouseDoubleClickEvent(self, event):
        if self._on_grip(event.pos()):
            # back to the size every panel starts at
            self.node.params.pop("size", None)
            self.relayout()
            self.editor.changed()
            return
        self.editor.type_panel(self)


class PipelineItem(NodeItem):
    """Says what it takes as well as how much it found."""

    def summary(self):
        count = (sum(len(v) for v in self.result.outputs.values())
                 if self.result else 0)
        return f"{count} object" + ("" if count == 1 else "s") + (
            " · " + pipe_said(self.node.params))

    def add_menu_entries(self, menu):
        self.editor.pipe_menus(menu, self.node)
        menu.addSeparator()


def pipe_said(params) -> str:
    """A Geometry Pipeline's filter in words."""
    names = {"point": "points", "curve": "curves", "brep": "breps",
             "mesh": "meshes"}
    types = [names[t] for t in params.get("types", [])]
    layer = params.get("layer") or "all layers"
    return f"{', '.join(types) or 'no types'} on {layer}"


ITEMS = {"slider": SliderItem, "toggle": ToggleItem, "panel": PanelItem,
         "pipeline": PipelineItem}


def item_for(editor, node):
    """The canvas item a component is shown with."""
    return ITEMS.get(node.key, NodeItem)(editor, node)


def node_size(comp, flags=None, title=None, params=None):
    """A component's input names column, width and height, as its item
    sizes itself."""
    return ITEMS.get(comp.key, NodeItem).size(comp, flags, title, params)
