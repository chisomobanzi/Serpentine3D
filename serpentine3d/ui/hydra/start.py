"""The start page: cards of a new graph and the recent ones."""

from __future__ import annotations

import json
import os

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QLabel, QScrollArea, QVBoxLayout, QWidget,
)

from ...core.hydra import COMPONENTS
from .special import node_size
from .style import ACCENT, BODY, MUTED, NODE_HEIGHT, WIRE, component_icon


def graph_preview(data, width, height):
    """A small picture of a saved graph: its components where they stand,
    with their icons, and the wires between them."""
    pix = QPixmap(width, height)
    pix.fill(QColor("#232427"))
    nodes = [n for n in (data or {}).get("nodes", [])
             if n.get("key") in COMPONENTS]
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if not nodes:
        painter.setPen(MUTED)
        painter.drawText(QRectF(0, 0, width, height),
                         Qt.AlignmentFlag.AlignCenter, "empty")
        painter.end()
        return pix
    boxes = {}
    for n in nodes:
        comp = COMPONENTS[n["key"]]
        params = n.get("params", {})
        _labels, w, h = node_size(comp, params.get("flags"),
                                  params.get("name"), params)
        boxes[n["id"]] = (QRectF(n.get("x", 0.0), n.get("y", 0.0), w, h),
                          comp)
    bounds = QRectF()
    for rect, _comp in boxes.values():
        bounds = bounds.united(rect)
    margin = 14
    scale = min((width - 2 * margin) / max(bounds.width(), 1.0),
                (height - 2 * margin) / max(bounds.height(), 1.0), 1.0)
    painter.translate(width / 2, height / 2)
    painter.scale(scale, scale)
    painter.translate(-bounds.center())
    painter.setPen(QPen(WIRE, 2 / scale))
    for source, _out, target, _in in (data or {}).get("wires", []):
        if source in boxes and target in boxes:
            a = QPointF(boxes[source][0].right(), boxes[source][0].center().y())
            b = QPointF(boxes[target][0].left(), boxes[target][0].center().y())
            bend = max(40.0, abs(b.x() - a.x()) * 0.5)
            path = QPainterPath(a)
            path.cubicTo(a + QPointF(bend, 0), b - QPointF(bend, 0), b)
            painter.drawPath(path)
    for rect, comp in boxes.values():
        painter.setPen(QPen(QColor("#4a4d55"), 1 / scale))
        painter.setBrush(BODY)
        painter.drawRoundedRect(rect, 5, 5)
        icon = component_icon(comp)
        if icon is not None:
            # where the component draws it: after its input names
            labels = node_size(comp)[0]
            side = NODE_HEIGHT - 8
            icon.paint(painter, QRect(int(rect.left() + labels + 6),
                                      int(rect.center().y() - side / 2),
                                      side, side))
    painter.end()
    return pix


class GraphCard(QFrame):
    """One graph on the start page: its picture, name, folder and date.
    A double-click opens it."""

    PREVIEW = (210, 118)

    def __init__(self, title, detail, data, open_it, parent=None,
                 picture=None):
        super().__init__(parent)
        self.setObjectName("hydraCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedWidth(self.PREVIEW[0] + 16)
        self.open_it = open_it
        shown = QLabel()
        shown.setPixmap(picture if picture is not None
                        else graph_preview(data, *self.PREVIEW))
        name = QLabel(title)
        name.setObjectName("cardName")
        about = QLabel(detail)
        about.setObjectName("cardDetail")
        about.setToolTip(detail)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)
        layout.addWidget(shown)
        layout.addWidget(name)
        layout.addWidget(about)
        self.title = title

    def mouseDoubleClickEvent(self, event):
        self.open_it()


class HydraStart(QScrollArea):
    """What Hydra opens on: the graph being worked on to continue, and the
    graphs last saved or opened, as cards. Escape continues."""

    COLUMNS = 3

    _QSS = (
        "HydraStart, #hydraStartPage { background: #1b1c20; }"
        "QLabel#startTitle { color: #85868a; font-family: monospace;"
        " letter-spacing: 1.5px; }"
        "QFrame#hydraCard { background: #232428; border: 1px solid #34353a;"
        " border-radius: 8px; }"
        "QFrame#hydraCard:hover { border-color: %s; }"
        "QLabel#cardName { color: #ececee; font-weight: bold; }"
        "QLabel#cardDetail { color: #85868a; }") % ACCENT.name()

    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet(self._QSS)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.cards: list[GraphCard] = []

    def fill(self, current, recent):
        page = QWidget()
        page.setObjectName("hydraStartPage")
        root = QVBoxLayout(page)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)
        grid = QGridLayout()
        grid.setSpacing(14)
        # a new graph first, then the one being worked on, then the recent
        self.cards = [GraphCard("New Graph", "Start from an empty canvas",
                                None, self.editor.new_graph,
                                picture=_new_picture(*GraphCard.PREVIEW))]
        if current is not None:
            self.cards.append(GraphCard(
                "Continue", "Where you left off", current,
                self.editor.show_canvas))
        for path in recent:
            self.cards.append(GraphCard(
                os.path.splitext(os.path.basename(path))[0],
                _card_detail(path), read_graph(path),
                lambda p=path: self.editor.open_path(p)))
        title = QLabel("RECENT GRAPHS")
        title.setObjectName("startTitle")
        root.addWidget(title)
        for i, card in enumerate(self.cards):
            grid.addWidget(card, i // self.COLUMNS, i % self.COLUMNS)
        grid.setAlignment(Qt.AlignmentFlag.AlignLeft
                          | Qt.AlignmentFlag.AlignTop)
        root.addLayout(grid)
        root.addStretch(1)
        self.setWidget(page)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.editor.show_canvas()
            return
        super().keyPressEvent(event)


def _new_picture(width, height):
    """The New Graph card's picture: a plus on an empty canvas."""
    pix = QPixmap(width, height)
    pix.fill(QColor("#232427"))
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(ACCENT, 3, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap))
    cx, cy, arm = width / 2, height / 2, 18
    painter.drawLine(QPointF(cx - arm, cy), QPointF(cx + arm, cy))
    painter.drawLine(QPointF(cx, cy - arm), QPointF(cx, cy + arm))
    painter.end()
    return pix


def read_graph(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _card_detail(path):
    """The folder a graph is in and when it was last saved."""
    import time
    folder = os.path.basename(os.path.dirname(path)) or path
    when = time.strftime("%d.%m.%Y %H:%M",
                         time.localtime(os.path.getmtime(path)))
    return f"{folder} · {when}"
