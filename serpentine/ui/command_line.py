"""Rhino-style command line: history echo, prompt, input with completion."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout,
    QWidget,
)

from ..commands.base import completions


class CommandInput(QLineEdit):
    tabPressed = Signal()
    upPressed = Signal()
    downPressed = Signal()
    escPressed = Signal()

    def event(self, ev):
        if ev.type() == ev.Type.KeyPress and ev.key() == Qt.Key.Key_Tab:
            self.tabPressed.emit()
            return True
        # with an empty input, cede Ctrl+C/V/A to the app-level shortcuts
        if (ev.type() == ev.Type.ShortcutOverride and not self.text()
                and ev.modifiers() & Qt.KeyboardModifier.ControlModifier
                and ev.key() in (Qt.Key.Key_C, Qt.Key.Key_V, Qt.Key.Key_A)):
            ev.ignore()
            return False
        return super().event(ev)

    def keyPressEvent(self, ev):
        key = ev.key()
        if key == Qt.Key.Key_Up:
            self.upPressed.emit()
        elif key == Qt.Key.Key_Down:
            self.downPressed.emit()
        elif key == Qt.Key.Key_Escape:
            self.escPressed.emit()
        elif (not self.text()
                and ev.modifiers() & Qt.KeyboardModifier.ControlModifier
                and key in (Qt.Key.Key_C, Qt.Key.Key_V, Qt.Key.Key_A,
                            Qt.Key.Key_Z, Qt.Key.Key_Y)):
            ev.ignore()          # bubble to the main window
        else:
            super().keyPressEvent(ev)


class CommandLine(QWidget):
    """Bottom dock: scrolling echo area + prompt + input line."""

    submitted = Signal(str)         # raw text the user entered
    cancelled = Signal()
    optionClicked = Signal(str)     # option chip clicked -> cycle its value

    def __init__(self, parent=None):
        super().__init__(parent)
        self._history: list[str] = []
        self._hist_pos = 0
        self._tab_matches: list[str] = []
        self._tab_index = 0

        mono = QFont("monospace")
        mono.setStyleHint(QFont.StyleHint.TypeWriter)

        self.echo_view = QPlainTextEdit()
        self.echo_view.setReadOnly(True)
        self.echo_view.setMaximumHeight(64)
        self.echo_view.setFont(mono)
        self.echo_view.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.echo_view.setStyleSheet(
            "QPlainTextEdit { background: #1b1c1f; border: none;"
            " color: #85868a; padding: 2px 6px; }")

        self.prompt_label = QLabel("Command")
        self.prompt_label.setObjectName("commandPrompt")

        self.input = CommandInput()
        self.input.setFont(mono)
        self.input.setPlaceholderText(
            "type a command (line, circle, extrude, loft, ...)")
        self.input.returnPressed.connect(self._submit)
        self.input.tabPressed.connect(self._complete)
        self.input.textEdited.connect(self._reset_tab)
        self.input.upPressed.connect(self.history_prev)
        self.input.downPressed.connect(self.history_next)
        self.input.escPressed.connect(self.input.clear)
        self.input.escPressed.connect(self.cancelled.emit)

        self._chip_row = QHBoxLayout()
        self._chip_row.setContentsMargins(0, 0, 0, 0)
        self._chip_row.setSpacing(6)
        self._chips: list[QPushButton] = []

        row = QHBoxLayout()
        row.setContentsMargins(8, 4, 8, 6)
        row.setSpacing(8)
        row.addWidget(self.prompt_label)
        row.addWidget(self.input, 1)
        row.addLayout(self._chip_row)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.echo_view)
        layout.addLayout(row)

    # -- public API --

    def echo(self, msg: str):
        self.echo_view.appendPlainText(msg)
        self.echo_view.moveCursor(QTextCursor.MoveOperation.End)

    def set_prompt(self, text: str):
        self.prompt_label.setText(text)

    def set_options(self, chips: list):
        """Show clickable [Name=Value] chips; click cycles the value."""
        want = [f"{n}={v}" for n, v in chips]
        if want == [c.text() for c in self._chips]:
            return
        for c in self._chips:
            self._chip_row.removeWidget(c)
            c.deleteLater()
        self._chips = []
        for (name, _), label in zip(chips, want):
            chip = QPushButton(label)
            chip.setFlat(True)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            chip.setToolTip(f"Click to change {name} (or type {name}=value)")
            chip.setStyleSheet(
                "QPushButton { color: #d8b44a; background: #26272b;"
                " border: 1px solid #3a3b40; border-radius: 9px;"
                " padding: 1px 10px; }"
                "QPushButton:hover { border-color: #d8b44a; }")
            chip.clicked.connect(
                lambda _=False, n=name: self.optionClicked.emit(n))
            self._chip_row.addWidget(chip)
            self._chips.append(chip)

    def focus(self):
        self.input.setFocus()

    # -- internals --

    def _submit(self):
        text = self.input.text()
        self.input.clear()
        if text.strip():
            self._history.append(text.strip())
        self._hist_pos = len(self._history)
        self.submitted.emit(text)

    def _reset_tab(self):
        self._tab_matches = []

    def _complete(self):
        if not self._tab_matches:
            prefix = self.input.text().strip()
            if not prefix:
                return
            self._tab_matches = completions(prefix)
            self._tab_index = 0
        if self._tab_matches:
            self.input.setText(self._tab_matches[self._tab_index])
            self._tab_index = (self._tab_index + 1) % len(self._tab_matches)

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            return
        super().keyPressEvent(ev)

    def eventFilter(self, obj, ev):
        return super().eventFilter(obj, ev)

    def history_prev(self):
        if self._history and self._hist_pos > 0:
            self._hist_pos -= 1
            self.input.setText(self._history[self._hist_pos])

    def history_next(self):
        if self._hist_pos < len(self._history) - 1:
            self._hist_pos += 1
            self.input.setText(self._history[self._hist_pos])
        else:
            self._hist_pos = len(self._history)
            self.input.clear()
