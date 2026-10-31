"""What the canvas shows: components, their ports and the wires."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import (
    QColor, QFont, QFontMetrics, QPainter, QPainterPath,
    QPainterPathStroker, QPen,
)
from PySide6.QtWidgets import QApplication, QGraphicsItem, QGraphicsPathItem

from ...core import hydra
from ...core.hydra import GEOMETRY_KINDS
from .keys import wiring_mode
from .style import (
    ACCENT, BODY, FLAG_COLOUR, HINT, INPUT_ROW, MARK_FROM, MARK_STEP,
    MUTED, NODE_HEIGHT, NODE_WIDTH, PORT_COLOURS, PORT_RADIUS, PORT_REACH,
    STATUS, TEXT, WIRE, component_icon, mark_room, marks,
)


class PortItem(QGraphicsItem):
    def __init__(self, node_item, port, is_output, row, count):
        super().__init__(node_item)
        self.node_item = node_item
        self.port = port
        self.is_output = is_output
        x = node_item.width if is_output else 0
        self.setPos(x, node_item.height * (row + 1) / (count + 1))
        self.setAcceptHoverEvents(True)
        self._hover = False
        self._mode = None          # set while a dragged wire would dock here
        self.setToolTip(port.name)

    def show_values(self, values, wired):
        """A port's tooltip, kept simple: what it takes, how much it holds
        and where that came from, then the items themselves, so it shows
        how the data comes in."""
        lines = [self.port.what, self._connected(values, wired)]
        if len(values):
            lines.append("")
            lines.extend(hydra.list_tree(values))
        self.setToolTip("\n".join(lines))

    def _connected(self, values, wired):
        """What is connected right now: how much comes by wire, or, with
        no wire, where the value comes from."""
        count = hydra.count_said(values)
        if self.is_output or wired:
            return count
        node = self.node_item.node
        if self.port.name in node.params.get("internal", {}):
            return f"Internalized · {count}"
        if self.port.name in node.params.get("set", {}):
            return f"Set in the model · {count}"
        if len(values):
            return f"Default · {count}"
        if self.port.optional:
            return "Optional · nothing connected"
        return "Nothing connected"

    def flags(self):
        """This port's Graft, Flatten and Reverse, in the order applied."""
        flags = self.node_item.node.params.get("flags", {})
        return hydra.flags_of(
            flags.get(hydra.flag_key(self.port.name, self.is_output)))

    def flag(self):
        """This port's Graft or Flatten, or None."""
        return next((f for f in self.flags() if f != "reverse"), None)

    @property
    def node_id(self):
        return self.node_item.node.id

    def boundingRect(self):
        # room for the + or - badge beside the dot
        r = PORT_REACH + 6
        return QRectF(-r, -r, 2 * r, 2 * r)

    def shape(self):
        # what a click finds: a good deal more than the dot that is drawn
        path = QPainterPath()
        path.addEllipse(QPointF(0, 0), PORT_REACH, PORT_REACH)
        return path

    def set_highlight(self, on, mode=None):
        """Lit as when hovered: where a dragged wire would dock, green when
        it would be added, red when it would be taken away."""
        if (self._hover, self._mode) != (on, mode):
            self._hover, self._mode = on, mode
            self.update()

    def hint(self, modifiers=None):
        """What lighting it up says: None, "add" or "remove"."""
        if self._mode is not None:
            return self._mode
        if modifiers is None:
            scene = self.scene()
            modifiers = (scene.modifiers if scene is not None
                         else QApplication.keyboardModifiers())
        return wiring_mode(modifiers)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        hint = self.hint() if self._hover else None
        colour = HINT[hint]
        if self._hover:
            glow = QColor(colour)
            glow.setAlpha(70)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow)
            painter.drawEllipse(QPointF(0, 0), PORT_RADIUS + 4,
                                PORT_RADIUS + 4)
        painter.setPen(QPen(colour if self._hover else QColor("#1b1c1f"),
                            1.5))
        painter.setBrush(PORT_COLOURS.get(self.port.kind, WIRE))
        painter.drawEllipse(QPointF(0, 0), PORT_RADIUS, PORT_RADIUS)
        if hint is not None:
            self._paint_badge(painter, colour, hint)

    def _paint_badge(self, painter, colour, hint):
        """A small + or - above the port, on the side away from its node."""
        side = 1 if self.is_output else -1
        at = QPointF(side * (PORT_RADIUS + 5), -(PORT_RADIUS + 5))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(colour)
        painter.drawEllipse(at, 5.5, 5.5)
        painter.setPen(QPen(QColor("#1b1c1f"), 1.6))
        painter.drawLine(at - QPointF(3, 0), at + QPointF(3, 0))
        if hint == "add":
            painter.drawLine(at - QPointF(0, 3), at + QPointF(0, 3))

    def hoverEnterEvent(self, event):
        self._hover = True
        self.scene().modifiers = event.modifiers()
        self.update()

    def hoverLeaveEvent(self, event):
        self._hover = False
        self.update()


class WireItem(QGraphicsPathItem):
    def __init__(self, wire=None):
        super().__init__()
        self.wire = wire
        self.mode = None           # a dragged wire's "add" or "remove"
        self.carries = "item"      # item | list | tree, from the last solve
        self.setZValue(-1)
        if wire is not None:
            self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)

    def set_ends(self, a: QPointF, b: QPointF):
        path = QPainterPath(a)
        bend = max(40.0, abs(b.x() - a.x()) * 0.5)
        path.cubicTo(a + QPointF(bend, 0), b - QPointF(bend, 0), b)
        self.setPath(path)

    def paint(self, painter, option, widget=None):
        colour = ACCENT if self.isSelected() else WIRE
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.wire is None:
            pen = QPen(HINT[self.mode] if self.mode is not None else colour,
                       2, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawPath(self.path())
            return
        if self.carries == "item":
            # one item: a single line
            painter.setPen(QPen(colour, 2))
            painter.drawPath(self.path())
            return
        # a list: two lines side by side; a tree: the two lines dashed
        stroker = QPainterPathStroker()
        stroker.setWidth(5)
        stroker.setCapStyle(Qt.PenCapStyle.FlatCap)
        outline = stroker.createStroke(self.path())
        pen = QPen(colour, 1.3)
        if self.carries == "tree":
            pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(outline)

    def shape(self):
        stroker = QPainterPathStroker()
        stroker.setWidth(10)
        return stroker.createStroke(self.path())


def _shown_order(flags):
    """The marks left to right: Graft or Flatten, then Reverse."""
    return [f for f in flags if f != "reverse"] + [
        f for f in flags if f == "reverse"]


def _paint_flag(painter, flag, at):
    """A fork for Graft, one line splitting into three; for Flatten, three
    lines meeting in one, read left to right the way data runs; for Reverse
    two arrows the opposite ways."""
    painter.save()
    painter.setPen(QPen(FLAG_COLOUR, 1.3, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap))
    x, y = at.x(), at.y()
    if flag == "reverse":
        for dy, way in ((-2.5, 1), (2.5, -1)):
            tip = QPointF(x + 3.5 * way, y + dy)
            painter.drawLine(QPointF(x - 3.5 * way, y + dy), tip)
            painter.drawLine(tip, tip + QPointF(-2 * way, -1.8))
            painter.drawLine(tip, tip + QPointF(-2 * way, 1.8))
    else:
        one, many = x - 3.5, x + 3.5
        if flag == "flatten":
            one, many = many, one
        for dy in (-3, 0, 3):
            painter.drawLine(QPointF(one, y), QPointF(many, y + dy))
    painter.restore()


class NodeItem(QGraphicsItem):
    """One line: the component's icon, then its name. Inputs are named down
    the left, beside their ports. A component shown otherwise, such as a
    slider or a panel, has an item of its own in special.py."""

    mid_drag = False      # dragging what is to be one step for Ctrl+Z

    def __init__(self, editor, node):
        super().__init__()
        self.editor = editor
        self.node = node
        self.result = None
        comp = node.component
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsMovable
                      | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
                      | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setPos(node.x, node.y)
        self.setToolTip(comp.description)
        self.setAcceptHoverEvents(True)
        self.labels, self.width, self.height = self.size(
            comp, node.params.get("flags"), node.title, node.params)
        self.out_labels = self.outputs_width(comp, node.params.get("flags"))
        self.inputs = [PortItem(self, p, False, i, len(comp.inputs))
                       for i, p in enumerate(comp.inputs)]
        self.outputs = [PortItem(self, p, True, i, len(comp.outputs))
                        for i, p in enumerate(comp.outputs)]

    @staticmethod
    def labels_width(comp, flags=None):
        """How wide the column of input names is, past their marks."""
        small = QFont()
        small.setPointSizeF(8)
        names = 10 + mark_room(marks(comp, flags, False))
        return (names + max(QFontMetrics(small).horizontalAdvance(p.name)
                            for p in comp.inputs) + 10 if comp.inputs else 0)

    @staticmethod
    def outputs_width(comp, flags=None):
        """How wide the column of output names is, with their marks; none
        for a component with one output, which needs no name."""
        if len(comp.outputs) < 2:
            return 0
        small = QFont()
        small.setPointSizeF(8)
        return (10 + mark_room(marks(comp, flags, True))
                + max(QFontMetrics(small).horizontalAdvance(p.name)
                      for p in comp.outputs) + 10)

    @classmethod
    def size(cls, comp, flags=None, title=None, params=None):
        """Its input names column, width and height: as wide as the names
        in it need, its title, given or its own, and the marks of its
        flagged ports, and no wider."""
        bold = QFont()
        bold.setPointSizeF(9)
        bold.setBold(True)
        labels = cls.labels_width(comp, flags)
        named = QFontMetrics(bold).horizontalAdvance(title or comp.title)
        outs = (cls.outputs_width(comp, flags)
                or mark_room(marks(comp, flags, True)))
        width = max(NODE_WIDTH, labels + NODE_HEIGHT + named + 18 + outs)
        rows = max(len(comp.inputs), len(comp.outputs))
        height = max(NODE_HEIGHT, INPUT_ROW * rows + 8)
        return labels, width, height

    def relayout(self):
        """Sized again, after a port's marks, its name or its size changed
        what it needs."""
        self.prepareGeometryChange()
        self.labels, self.width, self.height = self.size(
            self.node.component, self.node.params.get("flags"),
            self.node.title, self.node.params)
        self.out_labels = self.outputs_width(self.node.component,
                                             self.node.params.get("flags"))
        for ports in (self.inputs, self.outputs):
            for row, port in enumerate(ports):
                port.setY(self.height * (row + 1) / (len(ports) + 1))
        for port in self.outputs:
            port.setX(self.width)
        self.update()
        self.editor.canvas.update_wires(self)

    def names_at(self):
        """Where the input names start: past the marks, the same for all,
        so the names stand in a column."""
        return 10 + mark_room(marks(self.node.component,
                                    self.node.params.get("flags"), False))

    def port_at(self, pos):
        """The port a click at `pos`, in the component, means: an input by
        its name as well as its dot, an output by its marks beside it."""
        for port in self.inputs:
            if (pos.x() < self.labels
                    and abs(pos.y() - port.y()) <= INPUT_ROW / 2):
                return port
        room = self.out_labels or mark_room(
            marks(self.node.component, self.node.params.get("flags"), True))
        reach = INPUT_ROW / 2 if self.out_labels else NODE_HEIGHT / 2
        for port in self.outputs:
            if (pos.x() > self.width - room - 8
                    and abs(pos.y() - port.y()) <= reach):
                return port
        return None

    def boundingRect(self):
        return QRectF(-PORT_RADIUS - 3, 0, self.width + 2 * PORT_RADIUS + 6,
                      self.height)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        status = self.result.status if self.result else "ok"
        selected = self.isSelected()
        body = BODY if status == "ok" else STATUS[status]
        hidden = self.is_hidden()
        outline = QPen(ACCENT if selected else
                       (MUTED if hidden else QColor("#1b1c1f")),
                       1.5 if selected else 1)
        if hidden:
            # hidden in the viewports: dark, dashed and faded, at a glance
            outline.setStyle(Qt.PenStyle.DashLine)
            body = body.darker(165)
        painter.setPen(outline)
        painter.setBrush(body)
        painter.drawRoundedRect(QRectF(0, 0, self.width, self.height), 5, 5)
        if hidden:
            painter.setOpacity(0.45)
        self.paint_inside(painter)

    def paint_inside(self, painter):
        """What it shows inside its box: here its title."""
        self.paint_head(painter)
        left = self.labels + NODE_HEIGHT + 2
        room = self.out_labels or mark_room(
            marks(self.node.component, self.node.params.get("flags"), True))
        painter.drawText(QRectF(left, 0, self.width - left - 8 - room,
                                self.height),
                         Qt.AlignmentFlag.AlignVCenter,
                         self.node.title)

    def paint_head(self, painter):
        """The input names, the icon and the flags' marks, leaving the
        painter set for its title."""
        if self.inputs:
            self._paint_labels(painter)
        if self.out_labels:
            self._paint_output_labels(painter)
        top = int((self.height - NODE_HEIGHT) / 2)
        icon = component_icon(self.node.component)
        if icon is not None:
            icon.paint(painter, QRect(self.labels + 6, top + 4,
                                      NODE_HEIGHT - 8, NODE_HEIGHT - 8))
        font = QFont(painter.font())
        font.setPointSizeF(9)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(TEXT)
        self._paint_flags(painter)

    def can_hide(self):
        """Whether it shows anything in the viewports to hide."""
        return any(p.kind in GEOMETRY_KINDS or p.kind in ("vector", "any")
                   for p in self.node.component.outputs)

    def is_hidden(self):
        return self.can_hide() and not self.node.preview

    def _paint_flags(self, painter):
        """Graft, Flatten and Reverse marked inside the component beside
        their port, as Grasshopper does: before an input's name, beside an
        output. Reverse always stands right of Graft or Flatten."""
        for port in self.inputs:
            for k, flag in enumerate(_shown_order(port.flags())):
                _paint_flag(painter, flag,
                            QPointF(MARK_FROM + k * MARK_STEP, port.y()))
        for port in self.outputs:
            shown = _shown_order(port.flags())
            for k, flag in enumerate(shown):
                _paint_flag(painter, flag, QPointF(
                    self.width - MARK_FROM
                    - (len(shown) - 1 - k) * MARK_STEP, port.y()))

    def _paint_labels(self, painter):
        painter.save()
        font = QFont(painter.font())
        font.setPointSizeF(8)
        painter.setFont(font)
        status = self.result.status if self.result else "ok"
        painter.setPen(MUTED if status == "ok" else TEXT)
        for port in self.inputs:
            left = self.names_at()
            painter.drawText(QRectF(left, port.y() - INPUT_ROW / 2,
                                    self.labels - left, INPUT_ROW),
                             Qt.AlignmentFlag.AlignVCenter, port.port.name)
        painter.setPen(QPen(QColor("#1b1c1f"), 1))
        painter.drawLine(QPointF(self.labels, 5),
                         QPointF(self.labels, self.height - 5))
        painter.restore()

    def _paint_output_labels(self, painter):
        painter.save()
        font = QFont(painter.font())
        font.setPointSizeF(8)
        painter.setFont(font)
        status = self.result.status if self.result else "ok"
        painter.setPen(MUTED if status == "ok" else TEXT)
        left = self.width - self.out_labels
        right = self.width - 10 - mark_room(marks(
            self.node.component, self.node.params.get("flags"), True))
        for port in self.outputs:
            painter.drawText(QRectF(left, port.y() - INPUT_ROW / 2,
                                    right - left, INPUT_ROW),
                             Qt.AlignmentFlag.AlignVCenter
                             | Qt.AlignmentFlag.AlignRight, port.port.name)
        painter.setPen(QPen(QColor("#1b1c1f"), 1))
        painter.drawLine(QPointF(left, 5), QPointF(left, self.height - 5))
        painter.restore()

    def add_menu_entries(self, menu):
        """Its own entries in its right-click menu; none here."""

    def summary(self):
        """How many objects it holds, said in words."""
        comp = self.node.component
        count = (sum(len(v) for v in self.result.outputs.values())
                 if self.result else 0)
        if not comp.picks:
            noun = {"point": "point", "vector": "vector"}.get(
                comp.outputs[0].kind, "object")
            return f"{count} {noun}" + ("" if count == 1 else "s")
        said = f"{count} " + (comp.title.lower() if count == 1
                              else comp.plural)
        if "out" in self.node.params.get("internal", {}):
            said += " (internalized)"
        return said

    def said(self):
        """What its tooltip says it holds."""
        return self.summary()

    def set_result(self, result):
        self.result = result
        tip = f"{self.node.component.description}\n\n{self.said()}"
        if result is not None and result.message:
            tip += "\n" + result.message
        self._tip = tip
        self.setToolTip(tip)
        for port in self.inputs:
            port.show_values(*self.editor.graph.input_values(
                self.node.id, port.port, self.editor.results))
        for port in self.outputs:
            if result is not None:
                port.show_values(result.outputs.get(port.port.name,
                                                    hydra.Tree()), True)
        self.update()

    def hoverMoveEvent(self, event):
        # over an input's name, or an output's marks, the port's own tooltip
        port = self.port_at(event.pos())
        self.setToolTip(port.toolTip() if port is not None
                        else getattr(self, "_tip", ""))
        super().hoverMoveEvent(event)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.node.x, self.node.y = self.pos().x(), self.pos().y()
            self.editor.canvas.update_wires(self)
        return super().itemChange(change, value)

    def port(self, name, output):
        for item in self.outputs if output else self.inputs:
            if item.port.name == name:
                return item
        return None
