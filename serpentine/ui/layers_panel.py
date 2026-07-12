"""Layer manager panel."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog, QHBoxLayout, QPushButton, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)


class LayersPanel(QWidget):
    changed = Signal()

    def __init__(self, scene, history, parent=None):
        super().__init__(parent)
        self.scene = scene
        self.history = history
        self._rebuilding = False

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Layer", "", ""])
        self.tree.setRootIsDecorated(False)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().resizeSection(0, 130)
        self.tree.header().resizeSection(1, 32)
        self.tree.header().resizeSection(2, 32)
        self.tree.itemChanged.connect(self._item_changed)
        self.tree.itemClicked.connect(self._item_clicked)
        self.tree.itemDoubleClicked.connect(self._edit_item)

        btn_add = QPushButton("+")
        btn_add.setFixedWidth(28)
        btn_add.setToolTip("New layer")
        btn_add.clicked.connect(self._new_layer)
        btn_del = QPushButton("−")
        btn_del.setFixedWidth(28)
        btn_del.setToolTip("Delete selected layer")
        btn_del.clicked.connect(self._delete_layer)

        btns = QHBoxLayout()
        btns.setContentsMargins(4, 2, 4, 4)
        btns.addWidget(btn_add)
        btns.addWidget(btn_del)
        btns.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self.tree, 1)
        layout.addLayout(btns)

        scene.add_listener(self.rebuild)
        self.rebuild()

    def rebuild(self):
        self._rebuilding = True
        self.tree.clear()
        current = self.scene.layers.current_id
        counts = {}
        for obj in self.scene.all():
            counts[obj.layer_id] = counts.get(obj.layer_id, 0) + 1
        for layer in self.scene.layers.all():
            n = counts.get(layer.id, 0)
            label = f"{layer.name}" + (f"  ({n})" if n else "")
            if layer.id == current:
                label = "● " + label
            item = QTreeWidgetItem([label, "", ""])
            item.setData(0, Qt.ItemDataRole.UserRole, layer.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                1, Qt.CheckState.Checked if layer.visible
                else Qt.CheckState.Unchecked)
            item.setToolTip(1, "Visible")
            color = QColor.fromRgbF(*layer.color)
            item.setBackground(2, color)
            item.setToolTip(2, "Double-click name to rename; click swatch "
                               "to change colour")
            self.tree.addTopLevelItem(item)
        self._rebuilding = False

    # -- interactions --

    def _layer_id(self, item) -> str:
        return item.data(0, Qt.ItemDataRole.UserRole)

    def _item_clicked(self, item, column):
        layer_id = self._layer_id(item)
        if column == 0:
            self.scene.layers.current_id = layer_id
            self.scene.notify()
        elif column == 2:
            layer = self.scene.layers.get(layer_id)
            color = QColorDialog.getColor(
                QColor.fromRgbF(*layer.color), self, "Layer colour")
            if color.isValid():
                self.history.checkpoint("layer colour")
                self.scene.layers.set_color(
                    layer_id, (color.redF(), color.greenF(), color.blueF()))
                self.scene.notify()

    def _item_changed(self, item, column):
        if self._rebuilding:
            return
        if column == 1:
            layer_id = self._layer_id(item)
            visible = item.checkState(1) == Qt.CheckState.Checked
            self.scene.layers.set_visible(layer_id, visible)
            self.scene.notify()
        elif column == 0:
            # rename via inline edit
            layer_id = self._layer_id(item)
            text = item.text(0).lstrip("● ").split("  (")[0].strip()
            if text:
                self.history.checkpoint("rename layer")
                self.scene.layers.rename(layer_id, text)
            self.scene.notify()

    def _edit_item(self, item, column):
        if column == 0:
            layer = self.scene.layers.get(self._layer_id(item))
            item.setText(0, layer.name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            self.tree.editItem(item, 0)

    def _new_layer(self):
        self.history.checkpoint("new layer")
        layer = self.scene.layers.create()
        self.scene.layers.current_id = layer.id
        self.scene.notify()

    def _delete_layer(self):
        item = self.tree.currentItem()
        if item is None:
            return
        layer_id = self._layer_id(item)
        try:
            self.history.checkpoint("delete layer")
            # objects on the deleted layer move to default
            for obj in self.scene.all():
                if obj.layer_id == layer_id:
                    self.scene.update(obj.id, layer_id="default")
            self.scene.layers.remove(layer_id)
        except ValueError:
            self.history.discard_checkpoint()
        self.scene.notify()
