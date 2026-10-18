"""The popup a command's FormReq is shown as (#45).

A command asks for several answers at once and says nothing about how
they are put on screen; this is the window that puts them there. The
fields are ordinary requests, so there are only three kinds to draw: a
choice, a number and a line of text. A field that does not apply to the
answers given so far is drawn greyed rather than hidden, so the popup
keeps its shape as you change your mind about the pattern.

Cancelling the popup cancels the command, as closing a file picker does.
"""

from __future__ import annotations

import math
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFormLayout, QLabel, QLineEdit,
                               QVBoxLayout)

from ..commands.base import NumberReq, OptionReq
from .dialogs import untether


class _NumberBox(QDoubleSpinBox):
    """A spin box that counts as finely as the number needs without
    showing the zeros that implies.

    A hatch over a 4mm detail opens on a spacing of 0.0002, so the box
    has to count to seven places; a spacing of 0.5 would then read as
    0.5000, which is four invitations to wonder what they are for. One
    digit after the point always stays, so a whole number still looks
    like something you can type a fraction into.
    """

    def textFromValue(self, value: float) -> str:
        text = super().textFromValue(value)
        point = str(self.locale().decimalPoint())
        if point and point in text:
            text = text.rstrip("0")
            if text.endswith(point):
                text += "0"
        return text


def _decimals_for(default, minimum) -> int:
    """How finely a spin box has to count to hold this number.

    Three significant figures of whatever it opens on, and never fewer
    than two decimals or more than eight.
    """
    size = abs(float(default or 0.0)) or abs(float(minimum or 0.0))
    if size <= 0:
        return 2
    return int(max(2, min(8, 3 - math.floor(math.log10(size)))))


class FormDialog(QDialog):
    """One command's form, with a widget per field."""

    def __init__(self, form, parent=None):
        super().__init__(parent)
        self.setWindowTitle(form.title or form.prompt or "Options")
        # No icon beside the title: a few options asked about what is
        # already on screen are not a second program to be told apart
        # from the first. An empty icon is not enough on Windows, which
        # falls back to the window class's own; a tool window has no icon
        # to fall back to, and its slimmer title bar suits a popup this
        # small anyway. Linux keeps the plain window `untether` wants,
        # which is what gets it out of GNOME's attached-dialog grip.
        self.setWindowIcon(QIcon())
        if sys.platform.startswith("win"):
            self.setWindowFlag(Qt.WindowType.Tool, True)
        untether(self, over=parent)
        self.form = form
        self._widgets: dict = {}
        outer = QVBoxLayout(self)
        if form.prompt and form.prompt != form.title:
            outer.addWidget(QLabel(form.prompt))
        rows = QFormLayout()
        outer.addLayout(rows)
        for field in form.fields:
            widget = self._widget_for(field.req)
            if widget is None:
                continue
            self._widgets[field.name] = widget
            rows.addRow(field.req.prompt, widget)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self._refresh_enabled()

    # -- the widgets ------------------------------------------------------

    def _widget_for(self, req):
        if isinstance(req, OptionReq):
            box = QComboBox()
            box.addItems(list(req.options))
            if req.default in req.options:
                box.setCurrentText(req.default)
            box.currentTextChanged.connect(self._refresh_enabled)
            return box
        if isinstance(req, NumberReq):
            spin = _NumberBox()
            # Enough decimals for the number it opens on: a hatch over a
            # 4mm detail starts at a spacing of 0.0002, and a box with two
            # decimals would round that to nothing and refuse to hatch.
            spin.setDecimals(_decimals_for(req.default, req.minimum))
            spin.setRange(req.minimum if req.minimum is not None else -1e9,
                          1e9)
            spin.setValue(float(req.default or 0.0))
            spin.setSingleStep(max(abs(float(req.default or 1.0)) / 10.0,
                                   float(req.minimum or 0.0) or 1e-6))
            return spin
        edit = QLineEdit(str(getattr(req, "default", "") or ""))
        return edit

    def _value(self, name):
        widget = self._widgets[name]
        if isinstance(widget, QComboBox):
            return widget.currentText()
        if isinstance(widget, QDoubleSpinBox):
            return float(widget.value())
        return widget.text()

    def _refresh_enabled(self, *_args):
        """Grey the fields that do not apply to the answers as they stand."""
        answers = {}
        for field in self.form.fields:
            if field.name not in self._widgets:
                continue
            applies = field.when is None or bool(field.when(answers))
            self._widgets[field.name].setEnabled(applies)
            answers[field.name] = self._value(field.name)

    def values(self) -> dict:
        """What the popup was left showing, by field name."""
        return {name: self._value(name) for name in self._widgets}
