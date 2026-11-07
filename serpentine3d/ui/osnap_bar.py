"""Slim osnap toggle bar shown under the command line (Rhino-style)."""

from __future__ import annotations

from PySide6.QtCore import QLocale, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractSpinBox, QDoubleSpinBox, QHBoxLayout, QLabel, QToolButton, QWidget,
)

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


class _HeightBox(QDoubleSpinBox):
    """The Project height: a click in selects the number, ready to type
    over, and the cursor never goes into the "Z " in front of it."""

    def __init__(self):
        super().__init__()
        self.lineEdit().cursorPositionChanged.connect(self._keep_off_prefix)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        # after the click has placed its cursor, or it undoes the selection
        QTimer.singleShot(0, self.selectAll)

    def _keep_off_prefix(self, _old: int, new: int):
        edit = self.lineEdit()
        start = len(self.prefix())
        if new < start and not edit.hasSelectedText():
            edit.setCursorPosition(start)


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
        self._project = self._button(
            "Project", "Put every picked point at the height beside it")
        self._project.setChecked(viewport.snaps.project_enabled)
        self._project.toggled.connect(self._project_toggled)
        layout.addWidget(self._project)
        self._project_z = _HeightBox()
        self._project_z.setRange(-1e9, 1e9)
        self._project_z.setDecimals(2)
        self._project_z.setLocale(QLocale.c())       # "0.00", not "0,00"
        self._project_z.setPrefix("Z ")
        self._project_z.setToolTip("Height Project puts picked points at")
        self._project_z.setKeyboardTracking(False)
        self._project_z.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._project_z.setButtonSymbols(
            QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._project_z.setStyleSheet(
            "QDoubleSpinBox { font-size: 11px; padding: 1px 6px;"
            " border: 1px solid #3a3b41; border-radius: 4px;"
            " background: #1e1f22; color: #cfd0d2; }"
            "QDoubleSpinBox:focus { border-color: #d9a441; }"
            # without the origin the hidden arrows still take the width,
            # and the text gets none of it
            "QDoubleSpinBox::up-button, QDoubleSpinBox::down-button"
            " { subcontrol-origin: border; width: 0px; }"
            "QDoubleSpinBox:disabled { color: #5d5e63;"
            " background: transparent; border-color: #2e2f34; }")
        self._project_z.setValue(viewport.snaps.project_z)
        self._project_z.setEnabled(viewport.snaps.project_enabled)
        self._project_z.valueChanged.connect(self._project_z_changed)
        self._fit_project_z()
        layout.addWidget(self._project_z)
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

    def _project_toggled(self, on: bool):
        self.viewport.snaps.project_enabled = on
        self._project_z.setEnabled(on)

    def _fit_project_z(self):
        """As wide as "Z 0.00" needs, not as wide as its range."""
        box = self._project_z
        text = box.prefix() + box.textFromValue(box.value())
        box.setFixedWidth(box.fontMetrics().horizontalAdvance(text) + 18)

    def _project_z_changed(self, z: float):
        self._fit_project_z()
        self.viewport.snaps.project_z = z

    def refresh(self):
        """Sync button states from viewport (after commands toggle them)."""
        self._master.setChecked(self.viewport.snaps.enabled)
        self._show_master(self.viewport.snaps.enabled)
        for t, btn in self._buttons.items():
            btn.setChecked(self.viewport.snaps.types.get(t, False))
        self._grid.setChecked(self.viewport.grid_snap)
        self._ortho.setChecked(self.viewport.ortho)
        self._project.setChecked(self.viewport.snaps.project_enabled)
        self._project_z.setValue(self.viewport.snaps.project_z)
