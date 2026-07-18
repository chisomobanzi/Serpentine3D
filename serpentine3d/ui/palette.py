"""Fuzzy command palette (Ctrl+Shift+P): type a few letters, run a command."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout,
)

from ..commands.base import all_commands


def fuzzy_score(query: str, text: str) -> int | None:
    """Subsequence match score (higher = better); None if no match."""
    q = query.lower()
    t = text.lower()
    if not q:
        return 0
    score, ti, streak = 0, 0, 0
    for ch in q:
        i = t.find(ch, ti)
        if i < 0:
            return None
        if i == ti:                      # consecutive
            streak += 1
            score += 3 + streak
        else:
            streak = 0
            score += 1
        if i == 0 or t[i - 1] in " _-":  # word start
            score += 4
        ti = i + 1
    score -= len(t) // 8                 # mild bias toward short names
    return score


class CommandPalette(QDialog):
    """Floating fuzzy finder over every registered command."""

    def __init__(self, parent, run_fn):
        super().__init__(parent)
        self._run = run_fn
        self.setWindowFlags(Qt.WindowType.Popup)
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Type a command…")
        self.input.textChanged.connect(self._refilter)
        self.input.installEventFilter(self)
        layout.addWidget(self.input)
        self.listing = QListWidget()
        self.listing.setMaximumHeight(320)
        self.listing.itemActivated.connect(self._activate)
        layout.addWidget(self.listing)

        self._entries = []
        for cd in sorted(all_commands(), key=lambda c: c.name):
            doc = (cd.fn.__doc__ or "").strip().splitlines()
            summary = doc[0].rstrip(".") if doc else ""
            haystack = " ".join([cd.name, *cd.aliases, summary])
            self._entries.append((cd.name, summary, haystack))
        self._refilter("")

    def _refilter(self, text: str):
        self.listing.clear()
        scored = []
        for name, summary, haystack in self._entries:
            s = fuzzy_score(text, haystack)
            if s is not None:
                scored.append((-s, name, summary))
        scored.sort()
        for _, name, summary in scored[:60]:
            label = f"{name}   —   {summary}" if summary else name
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.listing.addItem(item)
        if self.listing.count():
            self.listing.setCurrentRow(0)

    def _activate(self, item: QListWidgetItem):
        name = item.data(Qt.ItemDataRole.UserRole)
        self.accept()
        self._run(name)

    def eventFilter(self, obj, ev):
        if obj is self.input and ev.type() == ev.Type.KeyPress:
            key = ev.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                row = self.listing.currentRow()
                step = 1 if key == Qt.Key.Key_Down else -1
                nrow = max(0, min(self.listing.count() - 1, row + step))
                self.listing.setCurrentRow(nrow)
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                item = self.listing.currentItem()
                if item is not None:
                    self._activate(item)
                return True
        return super().eventFilter(obj, ev)

    @staticmethod
    def popup(parent, run_fn):
        dlg = CommandPalette(parent, run_fn)
        # centred over the parent window, near the top (Sublime-style)
        geo = parent.geometry()
        dlg.move(geo.x() + (geo.width() - dlg.minimumWidth()) // 2,
                 geo.y() + 80)
        dlg.input.setFocus()
        dlg.exec()
