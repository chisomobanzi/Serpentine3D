"""Searchable command reference dialog (F1)."""

from __future__ import annotations

import html

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QLineEdit, QTextBrowser, QVBoxLayout,
)

from ..commands.help_cmd import command_reference


class HelpBrowser(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Serpentine3D — command reference")
        self.resize(560, 640)
        self.setWindowFlag(Qt.WindowType.Tool)

        self.search = QLineEdit()
        self.search.setPlaceholderText("filter commands…")
        self.search.textChanged.connect(self._render)

        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(False)

        layout = QVBoxLayout(self)
        layout.addWidget(self.search)
        layout.addWidget(self.view, 1)
        self._render("")
        self.search.setFocus()

    def _render(self, needle: str):
        needle = needle.lower().strip()
        parts = ["<style>h3{color:#d8b44a;margin:10px 0 2px}"
                 "td{padding:1px 10px 1px 0;vertical-align:top}"
                 ".n{color:#7fb4e6;font-family:monospace;white-space:nowrap}"
                 ".a{color:#85868a;font-size:90%}</style>"]
        for section, cmds in command_reference().items():
            rows = []
            for name, aliases, doc in cmds:
                hay = f"{name} {' '.join(aliases)} {doc}".lower()
                if needle and needle not in hay:
                    continue
                alias = (f" <span class='a'>({html.escape(', '.join(aliases))}"
                         ")</span>" if aliases else "")
                rows.append(f"<tr><td class='n'>{html.escape(name)}{alias}"
                            f"</td><td>{html.escape(doc)}</td></tr>")
            if rows:
                parts.append(f"<h3>{html.escape(section)}</h3>"
                             f"<table>{''.join(rows)}</table>")
        if len(parts) == 1:
            parts.append("<p>No commands match.</p>")
        self.view.setHtml("".join(parts))

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(ev)
