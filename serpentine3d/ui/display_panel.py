"""What the pane you are in draws: its mode, and what it draws on top.

Rhino puts this beside Properties and people coming from it look there
first. GitHub #5 asked for it by name, wanting isocurves off in a rendered
view; before this the only way to reach a display mode at all was the
viewport's own title, and isocurves could not be reached at all.

The panel holds no state. It reads the active viewport on every refresh
and writes straight back to it, so four panes with four different settings
stay four panes rather than one panel's idea of them.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QVBoxLayout, QWidget,
)

#: Mode id to the label people read, in the order the View menu lists them.
_MODES = [
    ("wireframe", "Wireframe"),
    ("shaded", "Shaded"),
    ("ghosted", "Ghosted"),
    ("rendered", "Rendered"),
    ("technical", "Technical"),
    ("zebra", "Zebra"),
    ("curvature", "Curvature"),
    ("draft", "Draft angle"),
]


class DisplayPanel(QWidget):
    """Display settings for whichever viewport is active."""

    def __init__(self, viewport_source, parent=None):
        super().__init__(parent)
        self._source = viewport_source
        self._loading = False           # refresh must not look like a click

        self.mode_box = QComboBox()
        for mode_id, label in _MODES:
            self.mode_box.addItem(label, mode_id)
        self.mode_box.currentIndexChanged.connect(self._mode_picked)

        self.iso_box = QCheckBox("Surface isocurves")
        self.iso_box.setToolTip(
            "The wires across a surface. Off in Rendered by default.")
        self.iso_box.toggled.connect(
            lambda on: self._write(lambda vp: vp.set_isocurves(on)))

        self.edge_box = QCheckBox("Surface edges")
        self.edge_box.setToolTip(
            "The outlines of faces. Curves and text are not affected.")
        self.edge_box.toggled.connect(
            lambda on: self._write(lambda vp: vp.set_edges(on)))

        form = QFormLayout()
        form.setContentsMargins(8, 8, 8, 4)
        form.addRow("Mode", self.mode_box)

        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.addLayout(form)
        box.addWidget(self.iso_box)
        box.addWidget(self.edge_box)
        box.addStretch(1)

        self.refresh()

    # -- reading the pane --

    def viewport(self):
        return self._source()

    def refresh(self):
        """Point the controls at the active viewport. Called when the active
        pane changes and when one of them changes mode by another route."""
        vp = self.viewport()
        if vp is None:
            return
        self._loading = True
        try:
            i = self.mode_box.findData(vp.display_mode)
            if i >= 0:
                self.mode_box.setCurrentIndex(i)
            self.iso_box.setChecked(vp.shows_isocurves())
            self.edge_box.setChecked(vp.shows_edges())
        finally:
            self._loading = False

    # -- and writing back to it --

    def _write(self, fn):
        vp = self.viewport()
        if vp is not None and not self._loading:
            fn(vp)

    def _mode_picked(self, _index):
        mode = self.mode_box.currentData()
        self._write(lambda vp: vp.set_display_mode(mode))

    # -- what the tests and the window talk to --

    def mode(self) -> str:
        return self.mode_box.currentData()

    def set_mode(self, mode: str):
        i = self.mode_box.findData(mode)
        if i >= 0:
            self.mode_box.setCurrentIndex(i)

    def isocurves_checked(self) -> bool:
        return self.iso_box.isChecked()

    def set_isocurves_checked(self, on: bool):
        self.iso_box.setChecked(bool(on))

    def edges_checked(self) -> bool:
        return self.edge_box.isChecked()

    def set_edges_checked(self, on: bool):
        self.edge_box.setChecked(bool(on))
