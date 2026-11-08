"""The node bar: a tab per category, and a component clicked there
waiting on the cursor."""

from __future__ import annotations

from PySide6.QtCore import QMimeData, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor, QCursor, QDrag, QFont, QFontMetrics, QPainter, QPainterPath,
    QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QScrollArea, QSizePolicy, QTabBar,
    QTabWidget, QToolButton, QVBoxLayout, QWidget,
)

from ...core.hydra import CATEGORIES, COMPONENTS
from .style import (
    ACCENT, BODY, COMPONENT_MIME, PORT_COLOURS, TEXT, WIRE, component_icon,
)


def placing_cursor(comp):
    """The cursor a component waits on: a small node, its icon, title and
    ports, with a plus at its corner, its middle where it will go."""
    bold = QFont()
    bold.setPointSizeF(8)
    bold.setBold(True)
    metrics = QFontMetrics(bold)
    title = metrics.elidedText(comp.title, Qt.TextElideMode.ElideRight, 110)
    ports = max(len(comp.inputs), len(comp.outputs), 1)
    body = QRectF(6, 4, 37 + metrics.horizontalAdvance(title),
                  max(26, ports * 9 + 8))
    pix = QPixmap(int(body.right()) + 9, int(body.bottom()) + 9)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#1b1c1f"), 1))
    painter.setBrush(BODY)
    painter.drawRoundedRect(body, 4, 4)
    icon = component_icon(comp)
    if icon is not None:
        icon.paint(painter, QRect(int(body.left()) + 5,
                                  int(body.center().y()) - 9, 18, 18))
    painter.setFont(bold)
    painter.setPen(TEXT)
    painter.drawText(body.adjusted(27, 0, 0, 0),
                     Qt.AlignmentFlag.AlignVCenter, title)
    painter.setPen(QPen(QColor("#1b1c1f"), 1))
    for x, side in ((body.left(), comp.inputs), (body.right(), comp.outputs)):
        for i, port in enumerate(side):
            y = body.top() + body.height() * (i + 1) / (len(side) + 1)
            painter.setBrush(PORT_COLOURS.get(port.kind, WIRE))
            painter.drawEllipse(QPointF(x, y), 3, 3)
    corner = body.bottomRight()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(ACCENT)
    painter.drawEllipse(corner, 6.5, 6.5)
    painter.setPen(QPen(QColor("#1b1c1f"), 2, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap))
    painter.drawLine(corner - QPointF(3, 0), corner + QPointF(3, 0))
    painter.drawLine(corner - QPointF(0, 3), corner + QPointF(0, 3))
    painter.end()
    middle = body.center()
    return QCursor(pix, int(middle.x()), int(middle.y()))


class NodeButton(QToolButton):
    """A component in the node bar: clicked, it goes in the middle of the
    canvas; dragged, it goes where it is let go."""

    def __init__(self, editor, comp):
        super().__init__()
        self.editor = editor
        self.key = comp.key
        self.setText(comp.title)
        icon = component_icon(comp)
        if icon is not None:
            self.setIcon(icon)
        self.setIconSize(QSize(18, 18))
        self.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setToolTip(comp.description)
        self.clicked.connect(lambda: editor.start_placing(self.key))
        self._pressed = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = event.position()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (self._pressed is not None
                and (event.position() - self._pressed).manhattanLength()
                >= QApplication.startDragDistance()):
            self._pressed = None
            self.setDown(False)
            drag = QDrag(self)
            data = QMimeData()
            data.setData(COMPONENT_MIME, self.key.encode())
            drag.setMimeData(data)
            drag.setPixmap(self.icon().pixmap(24, 24))
            drag.exec(Qt.DropAction.CopyAction)
            return
        super().mouseMoveEvent(event)


class NodeRow(QScrollArea):
    """One tab's components side by side; too many to fit, the wheel
    scrolls them sideways."""

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        for policy in (self.setHorizontalScrollBarPolicy,
                       self.setVerticalScrollBarPolicy):
            policy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def wheelEvent(self, event):
        bar = self.horizontalScrollBar()
        bar.setValue(bar.value() - event.angleDelta().y())


class CardTabs(QTabBar):
    """Tabs drawn as file cards, by their fills alone: the chosen one in
    the colour of the panel it opens onto, its top corners rounded and its
    foot flaring out into the panel; the others darker, lower, behind."""

    ROUND = 5                  # the top corners
    FLARE = 5                  # where the chosen tab's foot meets the edge

    def __init__(self, panel):
        super().__init__()
        self.panel = QColor(panel)
        self.setMouseTracking(True)
        self._hovered = -1

    def mouseMoveEvent(self, event):
        hovered = self.tabAt(event.position().toPoint())
        if hovered != self._hovered:
            self._hovered = hovered
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._hovered = -1
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        chosen = self.currentIndex()
        for i in range(self.count()):
            if i != chosen:
                self._paint_tab(painter, i, False)
        if chosen >= 0:
            self._paint_tab(painter, chosen, True)
        painter.end()

    def _paint_tab(self, painter, i, chosen):
        rect = QRectF(self.tabRect(i))
        if not chosen:
            rect.adjust(2, 0, -2, 0)        # a little air between them
        foot = self.height()                # where the panel begins
        left, right = rect.left(), rect.right() + 1
        top = rect.top() + (0 if chosen else 3)
        r, f = self.ROUND, self.FLARE
        outline = QPainterPath()
        if chosen:
            # a flare out into the edge on each side, but where the tab
            # stands at the panel's own corner, a straight drop into it
            if left - f >= 0:
                outline.moveTo(left - f, foot)
                outline.quadTo(left, foot, left, foot - f)
            else:
                outline.moveTo(left, foot)
            outline.lineTo(left, top + r)
        else:
            outline.moveTo(left, foot)
            outline.lineTo(left, top + r)
        outline.quadTo(left, top, left + r, top)
        outline.lineTo(right - r, top)
        outline.quadTo(right, top, right, top + r)
        if chosen:
            outline.lineTo(right, foot - f)
            outline.quadTo(right, foot, right + f, foot)
        else:
            outline.lineTo(right, foot)
        body = QPainterPath(outline)
        body.lineTo(body.currentPosition().x(), self.height())
        body.lineTo(outline.elementAt(0).x, self.height())
        body.closeSubpath()
        hovered = i == self._hovered
        fill = (self.panel if chosen
                else QColor("#2c2e33") if hovered else QColor("#26282c"))
        painter.fillPath(body, fill)
        painter.setPen(QColor("#e4e5e7") if chosen or hovered
                       else QColor("#9a9b9e"))
        text = QRectF(rect.left(), top, rect.width(), foot - top)
        painter.drawText(text, Qt.AlignmentFlag.AlignCenter, self.tabText(i))


class NodeBar(QWidget):
    """The components a tab at a time, a tab for each category, as in
    Grasshopper: file-card tabs above, the chosen one joined to the panel
    of its components below, as tabs are in any program. The tab last
    chosen is the one it opens on."""

    _PANEL = "#2f3136"         # the chosen tab and the panel it opens onto
    _QSS = (
        # no outlines anywhere: the shapes are told apart by their fills,
        # which stay sharp however the screen is scaled
        "NodeBar { background: #1f2023; }"
        "QTabWidget::pane { background: %(panel)s; border: none;"
        " border-radius: 6px; border-top-left-radius: 0; top: 0px; }"
        # the tabs draw themselves; this only gives them their size
        "QTabBar::tab { padding: 6px 18px; margin-right: 8px;"
        " border: none; background: transparent; }"
        # the pages show the pane's colour through, as one with the tab
        "QTabWidget QStackedWidget, #nodeBarRow, NodeRow"
        " { background: transparent; }"
        # each component a button of its own, in the colours of a node
        "QToolButton { color: #e4e5e7; background: #3a3d44;"
        " border: 1px solid #1b1c1f; border-radius: 4px; padding: 5px 12px; }"
        "QToolButton:hover { background: #454850; border-color: #d9a441; }"
        "QToolButton:pressed { background: #26282c; }"
    ) % {"panel": _PANEL}

    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setStyleSheet(self._QSS)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)
        self.tabs = QTabWidget()
        self.tabs.setTabBar(CardTabs(self._PANEL))
        self.tabs.setDocumentMode(False)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabBar().setDrawBase(False)
        self.buttons: dict[str, NodeButton] = {}
        self.groups: dict[str, list[str]] = {}
        for category in CATEGORIES:
            self.tabs.addTab(self._page(category), category)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 10)
        root.addWidget(self.tabs)
        self.tabs.currentChanged.connect(self._chosen)
        shown = editor.window.cfg.get("hydra_tab", default=CATEGORIES[0])
        self.tabs.setCurrentIndex(
            CATEGORIES.index(shown) if shown in CATEGORIES else 0)
        self.setFixedHeight(self.sizeHint().height())

    def _page(self, category):
        row = QWidget()
        row.setObjectName("nodeBarRow")
        buttons = QHBoxLayout(row)
        buttons.setContentsMargins(12, 10, 12, 10)
        buttons.setSpacing(6)
        self.groups[category] = []
        for comp in COMPONENTS.values():
            if comp.category == category:
                button = NodeButton(self.editor, comp)
                buttons.addWidget(button)
                self.buttons[comp.key] = button
                self.groups[category].append(comp.key)
        buttons.addStretch(1)
        page = NodeRow()
        page.setWidget(row)
        page.setFixedHeight(row.sizeHint().height())
        return page

    def category(self) -> str:
        """The tab being shown."""
        return CATEGORIES[self.tabs.currentIndex()]

    def show_category(self, category):
        self.tabs.setCurrentIndex(CATEGORIES.index(category))

    def _chosen(self, index):
        self.editor.window.cfg.set("hydra_tab", CATEGORIES[index])
