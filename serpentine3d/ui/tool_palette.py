"""The left tool strip, which flows into more columns rather than losing
tools off the bottom.

A QToolBar with more buttons than its height allows quietly moves the
overflow into an extension chevron. With thirty-two tools that meant
everything from Trim onwards — Delete included — disappearing on any
window shorter than about 1120 px. Widening the strip by one button costs
far less than eight tools costs.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QFrame, QSizePolicy, QToolButton, QWidget

from .icons import command_icon

BUTTON = 30            # a square tool button
GAP = 2
STEP = BUTTON + GAP    # one tool's worth of column
RULE = 9               # the gap a group break leaves behind
MARGIN = 3


def flow_columns(heights: list[int], available: int) -> list[tuple[int, int]]:
    """Where each item sits: (column, y), running down then across.

    Items stack top to bottom until the next one would hang below
    `available`, which starts a fresh column. An item taller than the whole
    column still gets placed — overhanging is better than vanishing.
    """
    places = []
    column = y = 0
    for height in heights:
        if y and y + height > available:
            column += 1
            y = 0
        places.append((column, y))
        y += height
    return places


class ToolPalette(QWidget):
    """Tool buttons in as many columns as the height it is given needs."""

    def __init__(self, groups, invoke, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Fixed,
                           QSizePolicy.Policy.Expanding)
        self._items = []          # (widget, height) in palette order
        self._rules = []
        self._columns = 1
        for gi, group in enumerate(groups):
            if gi:
                rule = QFrame(self)
                rule.setFrameShape(QFrame.Shape.HLine)
                rule.setFrameShadow(QFrame.Shadow.Plain)
                self._rules.append(rule)
                self._items.append((rule, RULE))
            for label, command in group:
                self._items.append((self._button(label, command, invoke),
                                    STEP))

    def _button(self, label, command, invoke):
        button = QToolButton(self)
        button.setText(label)
        icon = command_icon(command)
        if icon is not None:
            button.setIcon(icon)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setAutoRaise(True)
        button.setFixedSize(BUTTON, BUTTON)
        button.setToolTip(f"{label}  ({command})")
        button.clicked.connect(lambda _=False, c=command: invoke(c))
        return button

    # -- what the tests and the toolbar ask about --

    def columns(self) -> int:
        return self._columns

    def margin(self) -> int:
        return MARGIN

    def rules(self) -> list[QFrame]:
        return list(self._rules)

    # -- laying out --

    def reflow(self):
        """Lay the tools out for the height there is, and say what size that
        came to. Returns (width, height)."""
        places, self._columns, size = self._measure(self._available())
        for (widget, _), (column, y) in zip(self._items, places):
            if widget in self._rules:
                # A rule at the top of a column underlines nothing.
                widget.setVisible(y > 0)
                widget.setGeometry(MARGIN + column * STEP, MARGIN + y + 4,
                                   BUTTON, 1)
            else:
                widget.setGeometry(MARGIN + column * STEP, MARGIN + y,
                                   BUTTON, BUTTON)
        return size

    def _measure(self, available: int):
        """Where everything would go in a column this tall, how many columns
        that takes, and the (width, height) it all comes to."""
        places = flow_columns([h for _, h in self._items],
                              max(available, STEP))
        columns = places[-1][0] + 1 if places else 1
        used = max((y + h for (_, h), (_, y) in zip(self._items, places)),
                   default=0)
        return places, columns, (columns * STEP - GAP + MARGIN * 2,
                                 used + MARGIN * 2)

    def _available(self) -> int:
        """The height there is to fill: our own, once the toolbar has given
        us one. Before that there is nothing to go on, and guessing small
        would flow the palette into a column per tool, so assume they all
        fit and let the first resize say otherwise."""
        if self.height() <= STEP:
            return sum(h for _, h in self._items)
        return self.height() - MARGIN * 2

    def resizeEvent(self, event):
        super().resizeEvent(event)
        before = self._columns
        self.reflow()
        if self._columns != before:
            self.updateGeometry()

    def sizeHint(self) -> QSize:
        _, _, (width, height) = self._measure(self._available())
        return QSize(width, height)

    def minimumSizeHint(self) -> QSize:
        return QSize(STEP - GAP + MARGIN * 2, STEP + MARGIN * 2)
