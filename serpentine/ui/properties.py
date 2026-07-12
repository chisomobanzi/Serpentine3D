"""Properties panel: shows and edits the selected object."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout, QWidget,
)

from ..core import geometry as g


class PropertiesPanel(QWidget):
    def __init__(self, scene, selection, history, parent=None):
        super().__init__(parent)
        self.scene = scene
        self.selection = selection
        self.history = history
        self._updating = False

        self.header = QLabel("No selection")
        self.header.setStyleSheet("font-weight: bold; padding: 4px;")

        self.name_edit = QLineEdit()
        self.name_edit.editingFinished.connect(self._rename)

        self.layer_combo = QComboBox()
        self.layer_combo.currentIndexChanged.connect(self._change_layer)

        self.kind_label = QLabel("—")
        self.measure_label = QLabel("—")
        self.measure_label.setWordWrap(True)

        form = QFormLayout()
        form.setContentsMargins(8, 4, 8, 8)
        form.setSpacing(6)
        form.addRow("Name", self.name_edit)
        form.addRow("Layer", self.layer_combo)
        form.addRow("Type", self.kind_label)
        form.addRow("Info", self.measure_label)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.header)
        layout.addLayout(form)
        layout.addStretch(1)

        selection.add_listener(self.refresh)
        scene.add_listener(self.refresh)
        self.refresh()

    def _selected(self):
        objs = self.selection.objects()
        return objs[0] if len(objs) == 1 else None

    def refresh(self):
        self._updating = True
        objs = self.selection.objects()
        obj = self._selected()

        self.layer_combo.clear()
        for layer in self.scene.layers.all():
            self.layer_combo.addItem(layer.name, layer.id)

        if obj is None:
            if len(objs) > 1:
                self.header.setText(f"{len(objs)} objects selected")
            else:
                self.header.setText("No selection")
            self.name_edit.setText("")
            self.name_edit.setEnabled(False)
            self.layer_combo.setEnabled(False)
            self.kind_label.setText("—")
            self.measure_label.setText("—")
        else:
            self.header.setText(obj.name)
            self.name_edit.setEnabled(True)
            self.name_edit.setText(obj.name)
            self.layer_combo.setEnabled(True)
            idx = self.layer_combo.findData(obj.layer_id)
            if idx >= 0:
                self.layer_combo.setCurrentIndex(idx)
            self.kind_label.setText(obj.kind.capitalize())
            self.measure_label.setText(self._measures(obj))
        self._updating = False

    def _measures(self, obj) -> str:
        try:
            if obj.kind == "curve":
                return f"Length: {g.curve_length(obj.shape):.3f}"
            if obj.kind == "surface":
                return f"Area: {g.surface_area(obj.shape):.3f}"
            if obj.kind == "solid":
                return (f"Volume: {g.volume(obj.shape):.3f}\n"
                        f"Area: {g.surface_area(obj.shape):.3f}")
        except Exception:
            pass
        return "—"

    def _rename(self):
        obj = self._selected()
        if obj is None or self._updating:
            return
        name = self.name_edit.text().strip()
        if name and name != obj.name:
            self.history.checkpoint("rename")
            self.scene.update(obj.id, name=name)

    def _change_layer(self):
        obj = self._selected()
        if obj is None or self._updating:
            return
        layer_id = self.layer_combo.currentData()
        if layer_id and layer_id != obj.layer_id:
            self.history.checkpoint("change layer")
            self.scene.update(obj.id, layer_id=layer_id)
