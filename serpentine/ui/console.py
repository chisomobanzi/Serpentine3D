"""Dockable Python console with the live document in scope."""

from __future__ import annotations

import code
import contextlib
import io
import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QLineEdit, QPlainTextEdit, QVBoxLayout, QWidget,
)

BANNER = (
    "Serpentine Python console.\n"
    "  scene      the live scene        geo    geometry builders\n"
    "  api        programmatic api      window the main window\n"
    "e.g.  api.create_curve([[0,0,0],[10,5,0],[20,0,0]])\n"
)


class ConsoleInput(QLineEdit):
    historyUp = Signal()
    historyDown = Signal()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Up:
            self.historyUp.emit()
        elif ev.key() == Qt.Key.Key_Down:
            self.historyDown.emit()
        else:
            super().keyPressEvent(ev)


class PythonConsole(QWidget):
    def __init__(self, window, parent=None):
        super().__init__(parent)
        from ..api import SerpApi
        from ..core import geometry as geo
        namespace = {
            "window": window,
            "scene": window.scene,
            "selection": window.selection,
            "geo": geo,
            "api": SerpApi(window),
        }
        self.interp = code.InteractiveConsole(namespace)
        self._history: list[str] = []
        self._pos = 0
        self._buffer: list[str] = []

        mono = QFont("monospace")
        mono.setStyleHint(QFont.StyleHint.TypeWriter)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setFont(mono)
        self.output.setStyleSheet(
            "QPlainTextEdit { background: #1b1c1f; color: #b9bcc2; }")
        self.output.setPlainText(BANNER)
        self.input = ConsoleInput()
        self.input.setFont(mono)
        self.input.setPlaceholderText(">>>")
        self.input.returnPressed.connect(self._run)
        self.input.historyUp.connect(self._prev)
        self.input.historyDown.connect(self._next)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self.output, 1)
        layout.addWidget(self.input)

    def _write(self, text: str):
        self.output.moveCursor(QTextCursor.MoveOperation.End)
        self.output.insertPlainText(text)
        self.output.moveCursor(QTextCursor.MoveOperation.End)

    def _run(self):
        line = self.input.text()
        self.input.clear()
        if line.strip():
            self._history.append(line)
        self._pos = len(self._history)
        prompt = "... " if self._buffer else ">>> "
        self._write(f"{prompt}{line}\n")
        self._buffer.append(line)
        source = "\n".join(self._buffer)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(out):
            try:
                more = self.interp.runsource(source)
            except SystemExit:
                more = False
        if not more:
            self._buffer = []
        text = out.getvalue()
        if text:
            self._write(text)

    def _prev(self):
        if self._history and self._pos > 0:
            self._pos -= 1
            self.input.setText(self._history[self._pos])

    def _next(self):
        if self._pos < len(self._history) - 1:
            self._pos += 1
            self.input.setText(self._history[self._pos])
        else:
            self._pos = len(self._history)
            self.input.clear()
