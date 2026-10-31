"""A group's background on the canvas: drawn round its components and
following them as they move. A click on the background chooses the group,
a drag moves all of it, and Delete ends the grouping."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QGraphicsItem

from .style import ACCENT, TEXT

PADDING = 14                # round its components, in scene units
NAME_HEIGHT = 20            # the strip over it its name is written in
NAME_GAP = 6                # between that strip and the background


class GroupItem(QGraphicsItem):
    def __init__(self, canvas, group_id):
        super().__init__()
        self.canvas = canvas
        self.group_id = group_id
        self.chosen = False
        self._rect = QRectF()
        self._drag = None          # (press point, {NodeItem: start})
        self.setZValue(-2)         # behind its components and their wires
        self.setToolTip("A group: drag it to move all of it, right-click "
                        "to name it, Delete to end the grouping")
        self.refit()

    def members(self):
        ids = self.canvas.editor.graph.groups.get(self.group_id, [])
        return [self.canvas.node_items[nid] for nid in ids
                if nid in self.canvas.node_items]

    def refit(self):
        """Round its components again, after one moved or changed size."""
        rect = QRectF()
        for item in self.members():
            box = QRectF(item.pos().x(), item.pos().y(), item.width,
                         item.height)
            rect = box if rect.isNull() else rect.united(box)
        self.prepareGeometryChange()
        self._rect = rect.adjusted(-PADDING, -PADDING, PADDING, PADDING)
        self.update()

    def name(self):
        return self.canvas.editor.graph.group_names.get(self.group_id, "")

    @staticmethod
    def name_font():
        font = QFont()
        font.setPointSizeF(10)
        font.setBold(True)
        return font

    def _name_rect(self):
        # over its middle, as wide as the name needs
        width = QFontMetrics(self.name_font()).horizontalAdvance(
            self.name()) + 8
        return QRectF(self._rect.center().x() - width / 2,
                      self._rect.top() - NAME_GAP - NAME_HEIGHT, width,
                      NAME_HEIGHT)

    def boundingRect(self):
        rect = self._rect
        if self.name():
            rect = rect.united(self._name_rect())
        return rect.adjusted(-1, -1, 1, 1)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(ACCENT, 1.5) if self.chosen
                       else QPen(QColor(255, 255, 255, 30), 1))
        painter.setBrush(QColor(20, 21, 23, 215 if self.chosen else 200))
        painter.drawRoundedRect(self._rect, 8, 8)
        if self.name():
            painter.setFont(self.name_font())
            painter.setPen(ACCENT if self.chosen else TEXT)
            painter.drawText(self._name_rect(),
                             Qt.AlignmentFlag.AlignCenter, self.name())

    def set_chosen(self, chosen):
        self.chosen = chosen
        self.update()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        self.canvas.choose_group(self)
        self._drag = (event.scenePos(),
                      {item: item.pos() for item in self.members()})
        event.accept()

    def mouseMoveEvent(self, event):
        if self._drag is None:
            return
        at, starts = self._drag
        for item, start in starts.items():
            item.setPos(start + event.scenePos() - at)

    def mouseReleaseEvent(self, event):
        if self._drag is None:
            return
        self._drag = None
        self.canvas.editor.record()
