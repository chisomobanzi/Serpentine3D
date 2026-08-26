"""Layer manager panel."""

from __future__ import annotations

from PySide6.QtCore import QItemSelectionModel, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QColorDialog, QComboBox, QHBoxLayout,
    QPushButton, QStyledItemDelegate, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from ..core import linetype as _lt

# tree columns: name, visible check, colour swatch, linetype, print width
_NAME_COL = 0
_VISIBLE_COL = 1
_COLOR_COL = 2
_TYPE_COL = 3
_PRINT_COL = 4

# the ISO pen widths a plotter is set up with, offered in the Print cell
_STANDARD_PEN_WIDTHS = ("0.13", "0.18", "0.25", "0.35", "0.5", "0.7", "1.0")


class _ChoiceDelegate(QStyledItemDelegate):
    """Edits a cell with a drop-down of the known choices.

    The Type cell used to advance on every click, which hid the options and
    made a mis-click cost a lap round the list; a drop-down shows them all
    and commits one. An editable one also takes a typed value, for a pen
    width that is not on the list.
    """

    def __init__(self, choices, editable, parent=None):
        super().__init__(parent)
        self._choices = list(choices)
        self._editable = editable

    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        combo.addItems(self._choices)
        combo.setEditable(self._editable)
        return combo

    def setEditorData(self, editor, index):
        editor.setCurrentText(index.data() or "")

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)


class _LayerTree(QTreeWidget):
    """The layers tree, with a visibility click that leaves the selection be.

    In extended selection Qt lets a press on an already selected row through
    untouched, then on release re-selects only that row. The release is also
    what toggles a check box, so one click on a box in a selected group
    switched the group off and then shrank the selection to the clicked row;
    the next click on the same box only brought that one back. Rhino never
    changes the selection from the on/off bulb, so a release in the visible
    column runs with selection switched off: the box still toggles, the rows
    stay picked.
    """

    def mouseReleaseEvent(self, event):
        index = self.indexAt(event.position().toPoint())
        if index.isValid() and index.column() == _VISIBLE_COL:
            mode = self.selectionMode()
            self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
            try:
                super().mouseReleaseEvent(event)
            finally:
                self.setSelectionMode(mode)
            return
        super().mouseReleaseEvent(event)


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
    """The layers list: name, visibility, colour, linetype and print width.

    The panel redraws its whole tree from the scene on every notify, and a
    click or an edit in the tree ends in a notify, so the redraw runs in the
    middle of Qt's own handling of that click or edit. Each guard below
    covers one consequence of that:

    - the redraw writes to items, which Qt reports as changes just like a
      user's edit: ``_updating`` mutes the change handler meanwhile;
    - the redraw would delete the item Qt is still inside: ``_in_item_change``
      makes ``rebuild()`` wait for the next turn;
    - the redraw drops the selection and the current row: ``rebuild()``
      remembers both by layer id and puts them back;
    - a shift- or ctrl-click on a name is a selection gesture, so
      ``_item_clicked`` leaves the scene alone and nothing redraws under it.

    A click on a visibility box has a trouble of its own, in ``_LayerTree``.
    """

    changed = Signal()

    def __init__(self, scene, history, parent=None):
        super().__init__(parent)
        self.scene = scene
        self.history = history
        # the guards the class docstring describes
        self._updating = False        # the panel is writing to the tree itself
        self._in_item_change = False  # Qt is still inside an edited item

        self.tree = _LayerTree()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["Layer", "", "", "Type", "Print"])
        self.tree.setRootIsDecorated(False)
        # several layers can be picked at once, so one click on a visibility
        # box can switch a whole group of them together
        self.tree.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().resizeSection(_NAME_COL, 130)
        self.tree.header().resizeSection(_VISIBLE_COL, 32)
        self.tree.header().resizeSection(_COLOR_COL, 32)
        self.tree.header().resizeSection(_TYPE_COL, 78)
        self.tree.header().resizeSection(_PRINT_COL, 54)
        self.tree.setItemDelegateForColumn(_TYPE_COL, _ChoiceDelegate(
            _lt.LINETYPES, editable=False, parent=self.tree))
        self.tree.setItemDelegateForColumn(_PRINT_COL, _ChoiceDelegate(
            ("Default", *_STANDARD_PEN_WIDTHS), editable=True, parent=self.tree))
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
        if self._in_item_change:
            # Qt is still inside the item; redraw on the next turn instead
            QTimer.singleShot(0, self.rebuild)
            return
        self._updating = True
        picked = self._remember_picked()
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
            item.setData(_NAME_COL, Qt.ItemDataRole.UserRole, layer.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                _VISIBLE_COL, Qt.CheckState.Checked if layer.visible
                else Qt.CheckState.Unchecked)
            item.setToolTip(_VISIBLE_COL, "Visible")
            color = QColor.fromRgbF(*layer.color)
            item.setBackground(_COLOR_COL, color)
            item.setToolTip(_COLOR_COL, "Double-click name to rename; click "
                                        "swatch to change colour")
            item.setToolTip(_TYPE_COL, "Double-click to choose the layer's "
                                       "linetype")
            item.setToolTip(_PRINT_COL, "Plotted pen width in mm; double-click "
                                        "to pick or type one, Default for the "
                                        "device pen")
            self.tree.addTopLevelItem(item)
        self._restore_picked(picked)
        self._updating = False

    def _remember_picked(self):
        """The selected layers and the current row, by layer id.

        Clearing the tree drops both; a redraw puts them back so a group the
        user picked stays picked and a shift-click still ranges from the row
        they clicked last.
        """
        current = self.tree.currentItem()
        return (self._selected_layer_ids(),
                None if current is None else self._layer_id(current))

    def _restore_picked(self, picked):
        selected, current = picked
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            layer_id = self._layer_id(item)
            if layer_id in selected:
                item.setSelected(True)
            if layer_id == current:
                # NoUpdate: make it current without touching the selection
                self.tree.setCurrentItem(
                    item, _NAME_COL, QItemSelectionModel.SelectionFlag.NoUpdate)

    # -- interactions --

    def _layer_id(self, item) -> str:
        return item.data(_NAME_COL, Qt.ItemDataRole.UserRole)

    def _selected_layer_ids(self) -> set[str]:
        return {self._layer_id(item) for item in self.tree.selectedItems()}

    def _item_clicked(self, item, column):
        layer_id = self._layer_id(item)
        if column == _NAME_COL:
            # a modifier-click is a selection gesture, not a change of layer
            if QApplication.keyboardModifiers() != Qt.KeyboardModifier.NoModifier:
                return
            self.scene.layers.current_id = layer_id
            self.scene.notify()
        elif column == _COLOR_COL:
            layer = self.scene.layers.get(layer_id)
            color = QColorDialog.getColor(
                QColor.fromRgbF(*layer.color), self, "Layer colour")
            if color.isValid():
                self.history.checkpoint("layer colour")
                self.scene.layers.set_color(
                    layer_id, (color.redF(), color.greenF(), color.blueF()))
                self.scene.notify()

    def _item_changed(self, item, column):
        if self._updating:
            return
        # Qt reads the item again after this signal (a real click on a check
        # box segfaulted once it was gone), so rebuild() must wait a turn
        self._in_item_change = True
        try:
            self._apply_edit(item, column)
        finally:
            self._in_item_change = False

    def _apply_edit(self, item, column):
        """Write what the user put in a cell back to its layer."""
        layer_id = self._layer_id(item)
        if column == _VISIBLE_COL:
            visible = item.checkState(_VISIBLE_COL) == Qt.CheckState.Checked
            # a box in the selection switches the whole selection; a box
            # outside it switches only its own layer
            selected = self._selected_layer_ids()
            targets = selected if layer_id in selected else {layer_id}
            self.history.checkpoint("layer visibility")
            with self.scene.batched():
                for target in targets:
                    self.scene.layers.set_visible(target, visible)
                self.scene.notify()
        elif column == _NAME_COL:
            # rename via inline edit
            text = item.text(_NAME_COL).lstrip("● ").split("  (")[0].strip()
            if text:
                self.history.checkpoint("rename layer")
                self.scene.layers.rename(layer_id, text)
            self.scene.notify()
        elif column == _TYPE_COL:
            name = item.text(_TYPE_COL)
            if name in _lt.LINETYPES:
                self.history.checkpoint("layer linetype")
                self.scene.layers.set_linetype(layer_id, name)
            self.scene.notify()
        elif column == _PRINT_COL:
            width = _parse_print_width(item.text(_PRINT_COL))
            if width is not None:
                self.history.checkpoint("layer print width")
                self.scene.layers.set_print_width(layer_id, width)
            # notify redraws the cell from the layer, so a rejected value
            # snaps back to what the layer still says
            self.scene.notify()

    def _edit_item(self, item, column):
        if column not in (_NAME_COL, _TYPE_COL, _PRINT_COL):
            return
        # making a cell editable is one of the panel's own writes; Type and
        # Print already show the layer's value, their delegates seed the
        # drop-down from it
        self._updating = True
        try:
            if column == _NAME_COL:
                layer = self.scene.layers.get(self._layer_id(item))
                item.setText(_NAME_COL, layer.name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        finally:
            self._updating = False
        self.tree.editItem(item, column)

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
