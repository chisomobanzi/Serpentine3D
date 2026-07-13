"""Slim osnap toggle bar shown under the command line (Rhino-style)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QWidget

from ..core.snaps import SNAP_TYPES

_LABELS = {
    "end": "End", "mid": "Mid", "center": "Cen", "quad": "Quad",
    "int": "Int", "perp": "Perp", "near": "Near",
}
_TIPS = {
    "end": "Snap to curve endpoints",
    "mid": "Snap to curve midpoints",
    "center": "Snap to circle/arc centers",
    "quad": "Snap to circle quadrant points",
    "int": "Snap to curve-curve intersections",
    "perp": "Snap perpendicular from the previous point",
    "near": "Snap to the nearest point on a curve",
}


class OsnapBar(QWidget):
    def __init__(self, viewport, config, parent=None):
        super().__init__(parent)
        self.viewport = viewport
        self.config = config
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 1, 8, 3)
        layout.setSpacing(2)

        title = QLabel("Osnap:")
        title.setStyleSheet("color: #85868a; font-size: 11px;")
        layout.addWidget(title)

        self._master = self._button("On", "Master object-snap toggle")
        self._master.setChecked(viewport.snaps.enabled)
        self._master.toggled.connect(self._master_toggled)
        layout.addWidget(self._master)

        self._buttons = {}
        for t in SNAP_TYPES:
            btn = self._button(_LABELS[t], _TIPS[t])
            btn.setChecked(viewport.snaps.types.get(t, False))
            btn.toggled.connect(
                lambda on, kind=t: self._type_toggled(kind, on))
            layout.addWidget(btn)
            self._buttons[t] = btn

        layout.addSpacing(12)
        self._grid = self._button("Grid", "Snap picked points to the grid")
        self._grid.setChecked(viewport.grid_snap)
        self._grid.toggled.connect(self._grid_toggled)
        layout.addWidget(self._grid)
        layout.addStretch(1)

    def _button(self, text: str, tip: str) -> QToolButton:
        btn = QToolButton()
        btn.setText(text)
        btn.setToolTip(tip)
        btn.setCheckable(True)
        btn.setStyleSheet(
            "QToolButton { font-size: 11px; padding: 1px 7px; }")
        return btn

    def _master_toggled(self, on: bool):
        self.viewport.snaps.enabled = on
        if self.config:
            self.config.set("osnaps", "enabled", on)

    def _type_toggled(self, kind: str, on: bool):
        self.viewport.snaps.types[kind] = on
        if self.config:
            self.config.set("osnaps", kind, on)

    def _grid_toggled(self, on: bool):
        self.viewport.grid_snap = on
        if self.config:
            self.config.set("grid_snap", on)

    def refresh(self):
        """Sync button states from viewport (after commands toggle them)."""
        self._master.setChecked(self.viewport.snaps.enabled)
        for t, btn in self._buttons.items():
            btn.setChecked(self.viewport.snaps.types.get(t, False))
        self._grid.setChecked(self.viewport.grid_snap)
