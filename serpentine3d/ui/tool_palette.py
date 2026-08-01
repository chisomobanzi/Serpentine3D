"""The left tool strip: one column, full-size tools, scrolled if need be.

A QToolBar with more buttons than its height allows quietly moves the
overflow into an extension chevron, which took Trim through Delete off
the palette on any window shorter than about 1120 px. Eight tools, Delete
among them, gone because the window was not tall enough.

Thirty-two tools at a size worth clicking do not fit in a 900 px window,
and the two ways of pretending otherwise both cost more than they save:
a second column doubles the width of the strip, and smaller icons make
the tools harder to read to buy back a few pixels. So the tools keep
their size, the strip keeps its single column, and what will not fit
scrolls — visibly, and reachable with the wheel.

How the tools are presented wants a design pass of its own; this is not
it.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QFrame, QScrollArea, QSizePolicy, QToolButton, QWidget

from .icons import command_icon

BUTTON = 30            # a square tool button
GAP = 2
PITCH = BUTTON + GAP   # one tool's worth of column
ICON = BUTTON - 8
RULE = 8               # the gap a group break leaves behind
MARGIN = 3


class ToolPalette(QWidget):
    """Every tool button, stacked in one column at one size."""

    def __init__(self, groups, invoke, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._buttons: list[QToolButton] = []
        self._rules: list[QFrame] = []
        self._items: list[tuple[QWidget, bool]] = []   # (widget, is_rule)
        for index, group in enumerate(groups):
            if index:
                rule = QFrame(self)
                rule.setFrameShape(QFrame.Shape.HLine)
                rule.setFrameShadow(QFrame.Shadow.Plain)
                self._rules.append(rule)
                self._items.append((rule, True))
            for label, command in group:
                button = self._button(label, command, invoke)
                self._buttons.append(button)
                self._items.append((button, False))
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
        """One. The strip does not double up."""
        return 1

    def rules(self) -> list[QFrame]:
        return list(self._rules)

    def reflow(self) -> None:
        """Stack the tools, in order, at the size they are."""
        y = MARGIN
        for widget, is_rule in self._items:
            if is_rule:
                widget.setGeometry(MARGIN, y + RULE // 2, BUTTON, 1)
                y += RULE
            else:
                widget.move(MARGIN, y)
                y += PITCH
        self._height = y - GAP + MARGIN

    def sizeHint(self) -> QSize:
        return QSize(BUTTON + MARGIN * 2, self._height)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()


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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # A scrollbar coming or going changes how wide we need to be.
        self.updateGeometry()


def tool_strip(groups, invoke, parent=None) -> QScrollArea:
    """The palette, in something that will scroll it if it has to."""
    area = _Strip(parent)
    area.setObjectName("toolStrip")
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    area.setWidget(ToolPalette(groups, invoke))
    area.setWidgetResizable(True)
    # Expanding, or the toolbar hands the strip its height hint and the
    # tools scroll in a window with room to spare.
    area.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
    return area
