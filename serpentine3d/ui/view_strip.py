"""The strip over Properties: the view, and what is in sight or pickable.

Some buttons are a pair, the way Rhino's are: a left click runs the first
command and a right click its counterpart, so Hide and Show share one
place on the strip instead of taking two.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QHBoxLayout, QToolButton, QVBoxLayout, QWidget

from .icons import command_icon

BUTTON = 32
ICON = 28

# (label, command, right-click label, right-click command)
TOOLS = (
    ("Undo view change", "undoview", None, None),
    ("Redo view change", "redoview", None, None),
    ("Zoom extents", "zoomextents", None, None),
    ("Zoom selected", "zoomselected", None, None),
    ("Hide objects", "hide", "Show hidden objects", "show"),
    ("Isolate objects", "isolate", "Show isolated objects", "unisolate"),
    ("Lock objects", "lock", "Unlock all objects", "unlockall"),
    ("Lock all others", "lockother", "Unlock all objects", "unlockall"),
)

_QSS = (
    "#viewStrip { background: #2e2f34; border-bottom: 1px solid #1b1c1f; }"
    "#viewStrip QToolButton { border: none; border-radius: 3px;"
    " background: transparent; }"
    "#viewStrip QToolButton:hover { background: #3a3b41; }"
    "#viewStrip QToolButton:pressed { background: #45464d; }"
)


class ViewStrip(QWidget):
    """One row of buttons, each running a command through `invoke`."""

    def __init__(self, invoke, parent=None):
        super().__init__(parent)
        self.setObjectName("viewStrip")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(_QSS)
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 1, 4, 1)
        row.setSpacing(1)
        self.buttons: dict[str, QToolButton] = {}
        for label, command, alt_label, alt_command in TOOLS:
            button = self._button(label, command, alt_label, alt_command,
                                  invoke)
            self.buttons[command] = button
            row.addWidget(button)
        row.addStretch(1)

    def _button(self, label, command, alt_label, alt_command, invoke):
        button = QToolButton(self)
        button.setText(label)
        button.setIcon(command_icon(command, ICON))
        button.setIconSize(QSize(ICON, ICON))
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setFixedSize(BUTTON, BUTTON)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tip = f"{label}  ({command})"
        button.clicked.connect(lambda _=False, c=command: invoke(c))
        if alt_command:
            tip += f"\nRight-click: {alt_label}  ({alt_command})"
            button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            button.customContextMenuRequested.connect(
                lambda _pos, c=alt_command: invoke(c))
        button.setToolTip(tip)
        return button


def strip_over(strip: ViewStrip, title: QWidget) -> QWidget:
    """A dock title with the strip on top of it."""
    head = QWidget()
    column = QVBoxLayout(head)
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(0)
    column.addWidget(strip)
    column.addWidget(title)
    return head
