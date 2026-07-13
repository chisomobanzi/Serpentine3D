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

        from PySide6.QtWidgets import QHBoxLayout, QPushButton
        self.color_btn = QPushButton()
        self.color_btn.setFixedSize(40, 22)
        self.color_btn.setToolTip("Object colour override")
        self.color_btn.clicked.connect(self._pick_color)
        self.color_reset = QPushButton("By layer")
        self.color_reset.setToolTip("Remove the override, use layer colour")
        self.color_reset.clicked.connect(self._reset_color)
        color_row = QHBoxLayout()
        color_row.setContentsMargins(0, 0, 0, 0)
        color_row.addWidget(self.color_btn)
        color_row.addWidget(self.color_reset)
        color_row.addStretch(1)
        self.color_widget = QWidget()
        self.color_widget.setLayout(color_row)

        self.kind_label = QLabel("—")
        self.measure_label = QLabel("—")
        self.measure_label.setWordWrap(True)

        form = QFormLayout()
        form.setContentsMargins(8, 4, 8, 8)
        form.setSpacing(6)
        form.addRow("Name", self.name_edit)
        form.addRow("Layer", self.layer_combo)
        form.addRow("Colour", self.color_widget)
        form.addRow("Type", self.kind_label)
        form.addRow("Info", self.measure_label)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.header)
        layout.addLayout(form)
        layout.addStretch(1)

        selection.add_listener(self.refresh)
        scene.add_listener(self.refresh, kinds=("objects", "layers"))
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
            self.color_widget.setEnabled(False)
            self.color_btn.setStyleSheet("")
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
            self.color_widget.setEnabled(True)
            color = self.scene.color_of(obj)
            self.color_btn.setStyleSheet(
                "QPushButton { background: rgb(%d,%d,%d); border: 1px solid"
                " #55565e; }" % tuple(int(c * 255) for c in color))
            self.color_reset.setEnabled(obj.color is not None)
        self._updating = False

    def _pick_color(self):
        obj = self._selected()
        if obj is None:
            return
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QColorDialog
        current = QColor.fromRgbF(*self.scene.color_of(obj))
        color = QColorDialog.getColor(current, self, "Object colour")
        if color.isValid():
            self.history.checkpoint("object colour")
            self.scene.update(obj.id, color=(color.redF(), color.greenF(),
                                             color.blueF()))

    def _reset_color(self):
        obj = self._selected()
        if obj is not None and obj.color is not None:
            self.history.checkpoint("object colour")
            self.scene.update(obj.id, color=None)

    def _measures(self, obj) -> str:
        fmt = self.scene.format_length
        u = self.scene.units
        try:
            if obj.kind == "curve":
                return f"Length: {fmt(g.curve_length(obj.shape))}"
            if obj.kind == "surface":
                return f"Area: {g.surface_area(obj.shape):.3f} {u}²"
            if obj.kind == "solid":
                return (f"Volume: {g.volume(obj.shape):.3f} {u}³\n"
                        f"Area: {g.surface_area(obj.shape):.3f} {u}²")
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
