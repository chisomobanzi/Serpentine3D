"""The left tool strip: resizable columns, full-size tools, scrolled if need be.

A QToolBar with more buttons than its height allows quietly moves the
overflow into an extension chevron, which took Trim through Delete off
the palette on any window shorter than about 1120 px. Eight tools, Delete
among them, gone because the window was not tall enough.

So the tools keep their size, what will not fit scrolls — visibly, and
reachable with the wheel — and dragging the strip's right edge snaps it
to 1, 2, or more columns of tools, flowing left-to-right within each group.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QFrame, QScrollArea, QSizePolicy, QToolButton, QWidget

from .icons import command_icon

BUTTON = 30            # a square tool button
GAP = 2
PITCH = BUTTON + GAP   # one tool's worth of column
ICON = BUTTON - 8
RULE = 8               # the gap a group break leaves behind
MARGIN = 3
GRIP = 5               # width of the right-edge resize handle
MAX_COLUMNS = 6


def columns_for_width(width: int, max_columns: int = MAX_COLUMNS) -> int:
    """Snap a dragged pixel width to a column count in [1, max_columns]."""
    cols = round((width - MARGIN * 2 + GAP) / PITCH)
    return max(1, min(cols, max(1, max_columns)))


class ToolPalette(QWidget):
    """Every tool button, flowing left-to-right within each group."""

    columnsChanged = Signal(int)

    def __init__(self, groups, invoke, parent=None, *, columns: int = 1):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._max_columns = max((len(g) for g in groups), default=1)
        self._columns = max(1, min(int(columns), self._max_columns))
        # An empty column's worth, so that the size hint is answerable from
        # the moment the widget exists: reflow only works out the real
        # height once every button has been parented on, and a hint asked
        # for before then came back as an AttributeError from inside a Qt
        # override, which surfaces as a bare SystemError somewhere else.
        self._width = self._columns * PITCH - GAP + MARGIN * 2
        self._height = MARGIN * 2
        self._buttons: list[QToolButton] = []
        self._rules: list[QFrame] = []
        self._groups: list[list[QToolButton]] = []
        for index, group in enumerate(groups):
            if index:
                rule = QFrame(self)
                rule.setFrameShape(QFrame.Shape.HLine)
                rule.setFrameShadow(QFrame.Shadow.Plain)
                self._rules.append(rule)
            group_buttons: list[QToolButton] = []
            for label, command in group:
                button = self._button(label, command, invoke)
                self._buttons.append(button)
                group_buttons.append(button)
            self._groups.append(group_buttons)
        self.reflow()

    def _button(self, label, command, invoke) -> QToolButton:
        button = QToolButton(self)
        button.setText(label)
        icon = command_icon(command)
        if icon is not None:
            button.setIcon(icon)
            button.setIconSize(QSize(ICON, ICON))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setFixedSize(BUTTON, BUTTON)
        button.setAutoRaise(True)
        button.setToolTip(f"{label}  ({command})")
        button.clicked.connect(lambda _=False, c=command: invoke(c))
        return button

    def columns(self) -> int:
        return self._columns

    def set_columns(self, columns: int) -> None:
        target = max(1, min(int(columns), self._max_columns))
        if target == self._columns:
            return
        self._columns = target
        self.reflow()
        self.resize(self.sizeHint())
        self.updateGeometry()
        self.columnsChanged.emit(self._columns)

    def rules(self) -> list[QFrame]:
        return list(self._rules)

    def reflow(self) -> None:
        """Lay out the tools left-to-right within each group."""
        cols = self._columns
        span = cols * PITCH - GAP
        self._width = span + MARGIN * 2
        y = MARGIN
        for index, group_buttons in enumerate(self._groups):
            if index:
                rule = self._rules[index - 1]
                rule.setGeometry(MARGIN, y + RULE // 2, span, 1)
                y += RULE
            for i, button in enumerate(group_buttons):
                col = i % cols
                row = i // cols
                button.move(MARGIN + col * PITCH, y + row * PITCH)
            if group_buttons:
                rows = (len(group_buttons) - 1) // cols + 1
                y += rows * PITCH
        self._height = (y - GAP + MARGIN) if self._buttons else (MARGIN * 2)

    def sizeHint(self) -> QSize:
        return QSize(self._width, self._height)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()


class _ResizeGrip(QWidget):
    """Right-edge drag handle that snaps the tool strip by column count."""

    def __init__(self, host: QWidget, strip: _Strip):
        super().__init__(host)
        self._host = host
        self._strip = strip
        self._dragging = False
        self._hovered = False
        self.setObjectName("toolPaletteGrip")
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self.setMouseTracking(True)
        self.setToolTip("Drag to resize toolbar columns")
        host.installEventFilter(self)
        self._reposition()
        self.show()
        self.raise_()

    def _reposition(self) -> None:
        w = self._host.width()
        h = self._host.height()
        self.setGeometry(max(0, w - GRIP), 0, GRIP, max(0, h))
        self.raise_()

    def eventFilter(self, obj, event):
        if obj is self._host and event.type() in (
                QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.LayoutRequest):
            self._reposition()
        return False

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            local_x = self._strip.mapFromGlobal(
                event.globalPosition().toPoint()).x()
            palette = self._strip.widget()
            if isinstance(palette, ToolPalette):
                palette.set_columns(
                    columns_for_width(local_x, palette._max_columns))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        if self._dragging or self._hovered:
            painter = QPainter(self)
            painter.fillRect(self.width() - 2, 0, 2, self.height(),
                             QColor("#8a6a2f"))


class _Strip(QScrollArea):
    """Somewhere for the palette to scroll, no wider than the palette.

    Left alone a scroll area asks for a stock twelve columns by twenty-four
    lines whatever it holds, which as a toolbar widget is 68 px of empty
    strip beside a column of tools half that wide, and 432 px of height in
    a bar more than twice as tall.
    """

    def sizeHint(self) -> QSize:
        hint = self.widget().sizeHint()
        bar = self.verticalScrollBar()
        width = hint.width() + (bar.sizeHint().width()
                                if bar.isVisible() else 0)
        return QSize(width, hint.height())

    def minimumSizeHint(self) -> QSize:
        return QSize(self.sizeHint().width(), 0)

    def _sync_layouts(self) -> None:
        self.updateGeometry()
        w = self.parentWidget()
        while w is not None:
            if w.layout() is not None:
                w.layout().invalidate()
                w.layout().activate()
            w.updateGeometry()
            w = w.parentWidget()

    def _on_columns_changed(self, _columns: int) -> None:
        self._sync_layouts()
        # Scrollbar visibility may toggle on the next layout pass; re-sync once.
        QTimer.singleShot(0, self._sync_layouts)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # A scrollbar coming or going changes how wide we need to be.
        self.updateGeometry()


def tool_strip(groups, invoke, parent=None, *, columns: int = 1) -> QScrollArea:
    """The palette, in something that will scroll it if it has to."""
    area = _Strip(parent)
    area.setObjectName("toolStrip")
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    palette = ToolPalette(groups, invoke, columns=columns)
    area.setWidget(palette)
    area.setWidgetResizable(True)
    # Expanding, or the toolbar hands the strip its height hint and the
    # tools scroll in a window with room to spare.
    area.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
    palette.columnsChanged.connect(area._on_columns_changed)
    host = parent if parent is not None else area
    area._grip = _ResizeGrip(host, area)
    return area
