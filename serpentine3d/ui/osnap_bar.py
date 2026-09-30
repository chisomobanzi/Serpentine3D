"""Slim osnap toggle bar shown under the command line (Rhino-style)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QWidget

from ..core.snaps import SNAP_TYPES

_LABELS = {
    "end": "End", "point": "Point", "mid": "Mid", "center": "Cen", "quad": "Quad",
    "int": "Int", "appint": "AppInt", "perp": "Perp", "near": "Near",
}
_TIPS = {
    "end": "Snap to curve endpoints",
    "point": "Snap to point objects and individual point-cloud samples",
    "mid": "Snap to curve midpoints",
    "center": "Snap to circle/arc centers",
    "quad": "Snap to circle quadrant points",
    "int": "Snap to curve-curve intersections",
    "appint": "Snap where two curves cross on screen without meeting",
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
        self._ortho = self._button(
            "Ortho", "Constrain picks to CPlane axes (Shift overrides)")
        self._ortho.setChecked(viewport.ortho)
        self._ortho.toggled.connect(self._ortho_toggled)
        layout.addWidget(self._ortho)
        layout.addStretch(1)
        # A type left set while snaps are off keeps its setting for when
        # they come back on, but must not look on: lit up as usual, the bar
        # with snaps off looked just like the bar with them on.
        self.setStyleSheet(
            'QToolButton[dormant="true"]:checked { background: transparent;'
            ' color: #8a8272; border: 1px dashed #5d5646; }')
        self._show_master(viewport.snaps.enabled)

    def _show_master(self, on: bool):
        """Wake the snap types up, or put them to sleep, with the master."""
        # it says what it is, not only what it would be: a greyed "On" read
        # as one more snap type switched off, not all of them
        self._master.setText("On" if on else "Off")
        for t, btn in self._buttons.items():
            btn.setProperty("dormant", not on)
            btn.setToolTip(_TIPS[t] if on else
                           f"{_TIPS[t]} (object snaps are off: turn On)")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

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
        self._show_master(on)
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

    def _ortho_toggled(self, on: bool):
        self.viewport.ortho = on
        if self.config:
            self.config.set("ortho", on)

    def refresh(self):
        """Sync button states from viewport (after commands toggle them)."""
        self._master.setChecked(self.viewport.snaps.enabled)
        self._show_master(self.viewport.snaps.enabled)
        for t, btn in self._buttons.items():
            btn.setChecked(self.viewport.snaps.types.get(t, False))
        self._grid.setChecked(self.viewport.grid_snap)
        self._ortho.setChecked(self.viewport.ortho)
