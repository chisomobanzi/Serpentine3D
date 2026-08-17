"""Layer manager panel."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog, QHBoxLayout, QPushButton, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from ..core import linetype as _lt

# tree columns: name, visible check, colour swatch, linetype, print width
_TYPE_COL = 3
_PRINT_COL = 4


def _parse_print_width(text: str):
    """Millimetres from a print-width cell, or None if it makes no sense.

    Empty or "Default" is the device default, 0. A negative reads as the
    default too, since we have no no-plot pen. Anything unparseable returns
    None so the caller can leave the width where it was.
    """
    t = (text or "").strip()
    if t == "" or t.lower() == "default":
        return 0.0
    try:
        return max(0.0, float(t))
    except ValueError:
        return None


class LayersPanel(QWidget):
    changed = Signal()

    def __init__(self, scene, history, parent=None):
        super().__init__(parent)
        self.scene = scene
        self.history = history
        self._rebuilding = False

        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["Layer", "", "", "Type", "Print"])
        self.tree.setRootIsDecorated(False)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().resizeSection(0, 130)
        self.tree.header().resizeSection(1, 32)
        self.tree.header().resizeSection(2, 32)
        self.tree.header().resizeSection(_TYPE_COL, 78)
        self.tree.header().resizeSection(_PRINT_COL, 54)
        self.tree.itemChanged.connect(self._item_changed)
        self.tree.itemClicked.connect(self._item_clicked)
        self.tree.itemDoubleClicked.connect(self._edit_item)

        btn_style = ("QPushButton { padding: 2px; font-weight: bold; "
                     "min-width: 26px; max-width: 26px; }")
        btn_add = QPushButton("+")
        btn_add.setStyleSheet(btn_style)
        btn_add.setToolTip("New layer")
        btn_add.clicked.connect(self._new_layer)
        btn_del = QPushButton("−")
        btn_del.setStyleSheet(btn_style)
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

        scene.add_listener(self.rebuild, kinds=("objects", "layers"))
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
            print_text = ("Default" if layer.print_width == 0
                          else f"{layer.print_width:g}")
            item = QTreeWidgetItem([label, "", "", layer.linetype, print_text])
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
            item.setToolTip(_TYPE_COL, "Click to cycle the layer's linetype")
            item.setToolTip(_PRINT_COL, "Plotted pen width in mm; "
                                        "double-click to edit, blank for default")
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
        elif column == _TYPE_COL:
            layer = self.scene.layers.get(layer_id)
            names = list(_lt.LINETYPES)
            i = names.index(layer.linetype) if layer.linetype in names else -1
            self.history.checkpoint("layer linetype")
            self.scene.layers.set_linetype(layer_id, names[(i + 1) % len(names)])
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
        elif column == _PRINT_COL:
            layer_id = self._layer_id(item)
            width = _parse_print_width(item.text(_PRINT_COL))
            if width is not None:
                self.history.checkpoint("layer print width")
                self.scene.layers.set_print_width(layer_id, width)
            # notify redraws the cell from the layer, so a rejected value
            # snaps back to what the layer still says
            self.scene.notify()

    def _edit_item(self, item, column):
        if column == 0:
            layer = self.scene.layers.get(self._layer_id(item))
            item.setText(0, layer.name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            self.tree.editItem(item, 0)
        elif column == _PRINT_COL:
            layer = self.scene.layers.get(self._layer_id(item))
            item.setText(_PRINT_COL,
                         "" if layer.print_width == 0 else f"{layer.print_width:g}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            self.tree.editItem(item, _PRINT_COL)

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
