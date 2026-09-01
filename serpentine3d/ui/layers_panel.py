"""Layer manager panel."""

from __future__ import annotations

from PySide6.QtCore import QItemSelectionModel, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QColorDialog, QComboBox, QHBoxLayout,
    QHeaderView, QPushButton, QStyledItemDelegate, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..core import linetype as _lt
from . import theme

# tree columns: name, visible check, colour swatch, linetype, print width
_NAME_COL = 0
_VISIBLE_COL = 1
_COLOR_COL = 2
_TYPE_COL = 3
_PRINT_COL = 4

# the ISO pen widths a plotter is set up with, offered in the Print cell
_STANDARD_PEN_WIDTHS = ("0.13", "0.18", "0.25", "0.35", "0.5", "0.7", "1.0")

def _column_width(tree, column, *choices) -> int:
    """How wide a column has to be for the longest choice it can hold.

    Measured, not guessed: a hand-picked pixel width fits the font it was
    picked against and clips the same word under a theme that asks for a
    bigger one. Only the view knows what a cell costs beyond its text
    (margins, the focus frame, the padding the stylesheet adds), and it can
    only say so for the rows it has, so ask it about those and then add
    however much wider the longest choice would be.
    """
    fm = tree.fontMetrics()
    shown = max((fm.horizontalAdvance(tree.topLevelItem(i).text(column))
                 for i in range(tree.topLevelItemCount())), default=0)
    longest = max(fm.horizontalAdvance(c) for c in choices)
    return tree.sizeHintForColumn(column) + max(0, longest - shown)


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

    def updateEditorGeometry(self, editor, option, index):
        """Open the drop-down at the width its own list needs.

        A column is sized for the text it shows, which leaves nothing for
        the frame and arrow a combo box adds, so an editor held to its cell
        opens with its own choices cut off: "Continuous" as "Contin".
        Let it overhang the cells to its right instead, and slide it back
        inside the view rather than let it run off the edge.
        """
        rect = QRect(option.rect)
        rect.setWidth(max(rect.width(), editor.sizeHint().width()))
        view = editor.parentWidget()
        if view is not None:
            rect.setWidth(min(rect.width(), view.width()))
            if rect.right() > view.rect().right():
                rect.moveRight(view.rect().right())
            if rect.left() < view.rect().left():
                rect.moveLeft(view.rect().left())
        editor.setGeometry(rect)


def _id_of(item) -> str:
    """The layer a row stands for."""
    return item.data(_NAME_COL, Qt.ItemDataRole.UserRole)


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

    on_drop = None      # the panel's, called with (layer ids, new parent)

    def size_columns(self):
        """Give every column the width its own content asks for, except the
        name, which takes whatever the panel has left.

        A fresh window gives this panel a fixed 280px column, and the four
        narrow columns each have a width their content needs. The name is
        the only one that does not, so the name is the one that gives: with
        it stretched, every other column stays on screen at any panel
        width, instead of Print sitting off the edge behind a scrollbar.
        """
        header = self.header()
        header.setMinimumSectionSize(24)
        header.setSectionResizeMode(_NAME_COL, QHeaderView.ResizeMode.Stretch)
        header.resizeSection(_VISIBLE_COL, 28)
        # 24, not 28: a filled swatch needs no more, and the four pixels go
        # to the name column, which is the one an indented sublayer eats.
        header.resizeSection(_COLOR_COL, 24)
        header.resizeSection(
            _TYPE_COL, _column_width(self, _TYPE_COL, *_lt.LINETYPES))
        header.resizeSection(_PRINT_COL, _column_width(
            self, _PRINT_COL, "Default", *_STANDARD_PEN_WIDTHS))

    def dropEvent(self, event):
        """Where a dragged layer was let go of, handed to the panel.

        Never up to QTreeWidget, which would move the rows itself: these
        rows belong to the scene and are redrawn from it the moment the
        move lands, so a tree that had also moved them would show the move
        twice. Letting go over nothing means the top level.
        """
        item = self.itemAt(event.position().toPoint())
        target = None if item is None else _id_of(item)
        moving = [_id_of(i) for i in self.selectedItems()]
        if not moving and self.currentItem() is not None:
            moving = [_id_of(self.currentItem())]
        if self.on_drop is not None and moving:
            self.on_drop(moving, target)
        event.accept()

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
        # branches the user has closed, so a redraw does not open them again
        self._collapsed = set()

        self.tree = _LayerTree()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["Layer", "", "", "Type", "Print"])
        # a sublayer is drawn under its parent, so the branch needs its
        # expander back
        self.tree.setRootIsDecorated(True)
        # Tighter than Qt's 20px a level. The dock is 280px wide and four
        # of the five columns are sized from their own content, so the name
        # column is what an indent is taken out of: at the default indent a
        # root layer read "Def..." and a grandchild's name had no room left
        # at all. At 12 a fresh window's Default still reads in full. Deep
        # names still run out of room, so every row carries its full path as
        # a tooltip and the name column takes all of any width the user
        # gives the dock.
        self.tree.setIndentation(12)
        self.tree.setDragEnabled(True)
        self.tree.setAcceptDrops(True)
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.tree.setDropIndicatorShown(True)
        self.tree.on_drop = self._move_layers
        # several layers can be picked at once, so one click on a visibility
        # box can switch a whole group of them together
        self.tree.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.header().setStretchLastSection(False)
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
        btn_sub = QPushButton("↳")
        btn_sub.setStyleSheet(btn_style)
        btn_sub.setToolTip("New sublayer of the selected layer")
        btn_sub.clicked.connect(self._new_sublayer)
        btn_del = QPushButton("−")
        btn_del.setStyleSheet(btn_style)
        btn_del.setToolTip("Delete selected layer")
        btn_del.clicked.connect(self._delete_layer)

        btns = QHBoxLayout()
        btns.setContentsMargins(4, 2, 4, 4)
        btns.addWidget(btn_add)
        btns.addWidget(btn_sub)
        btns.addWidget(btn_del)
        btns.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self.tree, 1)
        layout.addLayout(btns)

        scene.add_listener(self.rebuild, kinds=("objects", "layers"))
        self.rebuild()
        self.tree.size_columns()

    def rebuild(self):
        if self._in_item_change:
            # Qt is still inside the item; redraw on the next turn instead
            QTimer.singleShot(0, self.rebuild)
            return
        self._updating = True
        picked = self._remember_picked()
        self.tree.clear()
        counts = {}
        for obj in self.scene.all():
            counts[obj.layer_id] = counts.get(obj.layer_id, 0) + 1
        layers = self.scene.layers
        known = {la.id for la in layers.all()}
        for layer in layers.all():
            # A parent that is not there is not a parent: a file written by
            # something else can say so, and the layer has to appear
            # somewhere rather than nowhere.
            if layer.parent is None or layer.parent not in known:
                self._add_row(layer, None, counts)
        self._restore_picked(picked)
        self._updating = False

    def _add_row(self, layer, parent_item, counts):
        """One layer's row, and every row of the branch under it."""
        n = counts.get(layer.id, 0)
        label = f"{layer.name}" + (f"  ({n})" if n else "")
        if layer.id == self.scene.layers.current_id:
            label = "● " + label
        print_text = ("Default" if layer.print_width == 0
                      else f"{layer.print_width:g}")
        item = QTreeWidgetItem([label, "", "", layer.linetype, print_text])
        item.setData(_NAME_COL, Qt.ItemDataRole.UserRole, layer.id)
        item.setToolTip(_NAME_COL, self.scene.layers.full_path(layer.id))
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        # The layer's own switch, which is what the user set. Whether it is
        # on screen is another question, and the answer is the grey below.
        item.setCheckState(
            _VISIBLE_COL, Qt.CheckState.Checked if layer.visible
            else Qt.CheckState.Unchecked)
        item.setToolTip(_VISIBLE_COL, "Visible")
        if not self.scene.layers.is_visible(layer.id):
            item.setForeground(_NAME_COL, QColor(theme.TEXT_MUTED))
        color = QColor.fromRgbF(*layer.color)
        item.setBackground(_COLOR_COL, color)
        item.setToolTip(_COLOR_COL, "Double-click name to rename; click "
                                    "swatch to change colour")
        item.setToolTip(_TYPE_COL, "Double-click to choose the layer's "
                                   "linetype")
        item.setToolTip(_PRINT_COL, "Plotted pen width in mm; double-click "
                                    "to pick or type one, Default for the "
                                    "device pen")
        if parent_item is None:
            self.tree.addTopLevelItem(item)
        else:
            parent_item.addChild(item)
        for child in self.scene.layers.children(layer.id):
            self._add_row(child, item, counts)
        return item

    def _all_rows(self) -> dict:
        """Every row in the tree by layer id, however deep it sits."""
        out = {}
        stack = [self.tree.topLevelItem(i)
                 for i in range(self.tree.topLevelItemCount())]
        while stack:
            item = stack.pop()
            out[self._layer_id(item)] = item
            stack.extend(item.child(i) for i in range(item.childCount()))
        return out

    def _remember_picked(self):
        """The selected layers and the current row, by layer id.

        Clearing the tree drops both; a redraw puts them back so a group the
        user picked stays picked and a shift-click still ranges from the row
        they clicked last.
        """
        current = self.tree.currentItem()
        # A branch is open unless the user closed it, so a layer that
        # arrives inside one is on screen without being hunted for.
        self._collapsed = {
            layer_id for layer_id, item in self._all_rows().items()
            if item.childCount() and not item.isExpanded()}
        return (self._selected_layer_ids(),
                None if current is None else self._layer_id(current))

    def _restore_picked(self, picked):
        selected, current = picked
        for layer_id, item in self._all_rows().items():
            item.setExpanded(layer_id not in self._collapsed)
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

    def _new_sublayer(self):
        """A new layer under the picked one, the way Rhino's panel does it.

        Nothing picked means there is nowhere to put it; the + beside this
        button is the one that makes a layer of its own.
        """
        item = self.tree.currentItem()
        if item is None:
            return
        parent_id = self._layer_id(item)
        self.history.checkpoint("new sublayer")
        layer = self.scene.layers.create(parent=parent_id)
        self.scene.layers.current_id = layer.id
        # Open the branch on the row itself, not in `_collapsed`, which
        # the redraw is about to work out again from the tree: a new layer
        # made inside a closed branch is a new layer nobody can see.
        item.setExpanded(True)
        self.scene.notify()

    def _move_layers(self, layer_ids, parent_id):
        """Put dragged layers under another one, or back at the top level.

        A layer inside one of the others is left alone: it is already going
        where its parent goes, and moving it too would take it out of the
        branch the user is dragging.
        """
        layers = self.scene.layers
        moving = [i for i in layer_ids if i != parent_id]
        inside = {d.id for i in moving for d in layers.descendants(i)}
        moving = [i for i in moving if i not in inside]
        if not moving:
            return
        # Qt is still inside the drop, so the redraw has to wait a turn:
        # the same guard the edited-item handler uses, for the same reason.
        self._in_item_change = True
        try:
            self.history.checkpoint("move layer")
            moved = False
            for layer_id in moving:
                try:
                    layers.set_parent(layer_id, parent_id)
                    moved = True
                except ValueError:
                    # onto its own child: that branch would have no top
                    pass
            if moved:
                self.scene.notify()
            else:
                self.history.discard_checkpoint()
        finally:
            self._in_item_change = False

    def _delete_layer(self):
        item = self.tree.currentItem()
        if item is None:
            return
        layer_id = self._layer_id(item)
        try:
            self.history.checkpoint("delete layer")
            # takes the layers under it, and moves their objects to default
            self.scene.remove_layer(layer_id)
        except ValueError:
            self.history.discard_checkpoint()
        self.scene.notify()
