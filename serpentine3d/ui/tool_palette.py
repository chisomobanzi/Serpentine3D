"""The left tool strip: one column, always.

A QToolBar with more buttons than its height allows quietly moves the
overflow into an extension chevron, which took Trim through Delete off
the palette on any window shorter than about 1120 px. The strip stays one
column wide and gives each tool a little less height instead — down to a
floor, past which it scrolls rather than dropping anything.

This is a holding answer: how the tools are presented wants a design pass
of its own, and this is not it.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QFrame, QScrollArea, QSizePolicy, QToolButton, QWidget

from .icons import command_icon

MAX_PITCH = 32         # a roomy tool: 30 px of button and 2 of gap
MIN_PITCH = 24         # as tight as it goes before it is hard to hit
GAP = 2
RULE = 6               # the gap a group break leaves behind
MARGIN = 3


def button_pitch(available: int, buttons: int, rules: int) -> int:
    """How much height each tool gets, so they all fit in one column.

    Roomy while there is room, tighter as the window shortens, and never
    below what stays comfortably clickable — past which they no longer
    all fit and the strip scrolls instead.
    """
    if buttons <= 0:
        return MAX_PITCH
    room = available - rules * RULE
    return max(MIN_PITCH, min(MAX_PITCH, room // buttons))


class ToolPalette(QWidget):
    """Tool buttons in a single column, sized to the height they are given."""

    def __init__(self, groups, invoke, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Fixed,
                           QSizePolicy.Policy.Preferred)
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
        self._pitch = MAX_PITCH

    def _button(self, label, command, invoke) -> QToolButton:
        button = QToolButton(self)
        button.setText(label)
        icon = command_icon(command)
        if icon is not None:
            button.setIcon(icon)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setAutoRaise(True)
        button.setToolTip(f"{label}  ({command})")
        button.clicked.connect(lambda _=False, c=command: invoke(c))
        return button

    # ------------------------------------------------------ what it comes to

    def pitch(self) -> int:
        return self._pitch

    def columns(self) -> int:
        """One. The strip does not double up."""
        return 1

    def rules(self) -> list[QFrame]:
        return list(self._rules)

    def _measure(self, available: int) -> tuple[int, int, int]:
        """(pitch, width, height) for that much room, touching nothing."""
        pitch = button_pitch(available, len(self._buttons), len(self._rules))
        height = MARGIN * 2 + len(self._rules) * RULE + (
            len(self._buttons) * pitch - GAP if self._buttons else 0)
        return pitch, pitch - GAP + MARGIN * 2, height

    def _available(self) -> int:
        """The height there is to fill. The scroll area's viewport, whose
        size does not follow ours, so measuring cannot feed back on itself;
        our own only until we are in one."""
        parent = self.parentWidget()
        height = parent.height() if parent is not None else 0
        return (height or self.height()) - MARGIN * 2

    # ----------------------------------------------------------- laying out

    def reflow(self) -> None:
        """Put the tools where the height we have been given says."""
        self._pitch, _, _ = self._measure(self._available())
        size = self._pitch - GAP
        y = MARGIN
        for widget, is_rule in self._items:
            if is_rule:
                widget.setGeometry(MARGIN, y + RULE // 2, size, 1)
                y += RULE
            else:
                widget.setFixedSize(size, size)
                widget.setIconSize(QSize(size - 8, size - 8))
                widget.move(MARGIN, y)
                y += self._pitch

    def resizeEvent(self, event):
        super().resizeEvent(event)
        before = self._pitch
        self.reflow()
        if self._pitch != before:
            self.updateGeometry()

    def sizeHint(self) -> QSize:
        _, width, height = self._measure(self._available())
        return QSize(width, height)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()


class _Strip(QScrollArea):
    """Somewhere for the palette to scroll, no wider than the palette.

    Left alone a scroll area asks for a stock twelve columns by twenty-four
    lines whatever it holds, which as a toolbar widget is 68 px of empty
    strip beside a 29 px column of tools.
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
        # The palette has just sized its tools to the height it was given,
        # so how wide we need to be has changed along with them.
        self.updateGeometry()


def tool_strip(groups, invoke, parent=None) -> QScrollArea:
    """The palette, in something that will scroll it if it has to.

    Only the smallest windows ever ask it to: the palette sizes its tools
    to the height it has first, and the scrollbar turns up only once they
    are as small as they are allowed to get.
    """
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
