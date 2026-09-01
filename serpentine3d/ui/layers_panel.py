"""Layer manager panel."""

from __future__ import annotations

from typing import NamedTuple

from PySide6.QtCore import QItemSelectionModel, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QColorDialog, QComboBox, QHBoxLayout,
    QHeaderView, QMenu, QPushButton, QStyledItemDelegate, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..core import layout as _layout
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


class _Drop(NamedTuple):
    """Where a layer let go of over the tree would land.

    ``parent`` and ``before`` are what the move needs: the branch it joins
    and the layer it goes in front of, with None for the top level and for
    last. ``item`` and ``where`` are what the drawing needs: the row the
    mark goes on, and whether that is a line above it, a line below it, or
    the row itself lit up.
    """

    parent: str | None
    before: str | None
    item: object
    where: str


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

    # the panel's, called with (layer ids, new parent, layer to land before)
    on_drop = None
    # of a row's height, at each end, that means beside the row not inside
    _EDGE = 0.25
    _drop_at = None     # where the drag over the tree would land, if any

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

    def _next_sibling(self, item):
        """The row after this one at its own level, if it has one."""
        parent = item.parent()
        if parent is None:
            i = self.indexOfTopLevelItem(item) + 1
            return self.topLevelItem(i) if i < self.topLevelItemCount() \
                else None
        i = parent.indexOfChild(item) + 1
        return parent.child(i) if i < parent.childCount() else None

    def _drop_spot(self, point) -> _Drop:
        """Where a layer let go of at this point would land.

        A row is read in three bands: the quarter at the top means in
        front of it, the quarter at the bottom means after it, and the
        half between them means inside it. Qt's own answer is two pixels
        at each end of the row, which is a target nobody can hit, and
        between two layers is most of what this panel is dragged for.

        The row under an open branch is that branch's first sublayer, so
        the gap above it belongs to the branch: letting go there puts the
        layer inside, at the top, which is where the line is drawn.
        """
        item = self.itemAt(point)
        if item is None:
            return _Drop(None, None, None, "on")    # bare tree: the top level
        rect = self.visualItemRect(item)
        edge = max(3, round(rect.height() * self._EDGE))
        parent = item.parent()
        parent_id = None if parent is None else _id_of(parent)
        if point.y() - rect.top() < edge:
            return _Drop(parent_id, _id_of(item), item, "above")
        if rect.bottom() - point.y() < edge:
            if item.isExpanded() and item.childCount():
                kid = item.child(0)
                return _Drop(_id_of(item), _id_of(kid), kid, "above")
            after = self._next_sibling(item)
            return _Drop(parent_id, None if after is None else _id_of(after),
                         item, "below")
        return _Drop(_id_of(item), None, item, "on")

    def dragMoveEvent(self, event):
        """Follow the pointer, and mark where the layer would land."""
        super().dragMoveEvent(event)
        self._drop_at = self._drop_spot(event.position().toPoint())
        self.viewport().update()
        # Whatever Qt made of the position: where a layer can go is this
        # tree's own to say, and every point over the list is somewhere,
        # the bare space under the last row included.
        event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self._drop_at = None
        self.viewport().update()
        super().dragLeaveEvent(event)

    def paintEvent(self, event):
        """The tree, and then the mark saying where the layer would land.

        Drawn here rather than by Qt, whose indicator answers to its own
        two-pixel reading of a row and would point somewhere other than
        where the layer is about to go. The line starts where the row it
        marks starts, so its indent says which level the layer lands at,
        which is the only thing that tells a drop beside a branch from a
        drop into it.
        """
        super().paintEvent(event)
        spot = self._drop_at
        if spot is None or spot.item is None:
            return
        rect = self.visualItemRect(spot.item)
        painter = QPainter(self.viewport())
        painter.setPen(QPen(self.palette().highlight().color(), 2))
        right = self.viewport().width() - 1
        if spot.where == "on":
            painter.drawRect(QRect(rect.left(), rect.top() + 1,
                                   right - rect.left() - 1, rect.height() - 2))
        else:
            y = rect.top() + 1 if spot.where == "above" else rect.bottom() - 1
            painter.drawLine(rect.left(), y, right, y)

    def dropEvent(self, event):
        """Where a dragged layer was let go of, handed to the panel.

        Never up to QTreeWidget, which would move the rows itself: these
        rows belong to the scene and are redrawn from it the moment the
        move lands, so a tree that had also moved them would show the move
        twice.
        """
        spot = self._drop_spot(event.position().toPoint())
        self._drop_at = None
        moving = [_id_of(i) for i in self.selectedItems()]
        if not moving and self.currentItem() is not None:
            moving = [_id_of(self.currentItem())]
        if self.on_drop is not None and moving:
            self.on_drop(moving, spot.parent, spot.before)
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
    - a click on a name is a selection gesture and nothing more, so
      ``_item_clicked`` leaves the scene alone and nothing redraws under
      it. Saying which layer to draw on is a double-click, and renaming
      one, which that double-click used to do, is in the row menu.

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
        # not Qt's indicator: the tree draws its own, which agrees
        # with where the drop is actually going to put the layer
        self.tree.setDropIndicatorShown(False)
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
        self.tree.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._row_menu)
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
        btn_out = QPushButton("↰")
        btn_out.setStyleSheet(btn_style)
        btn_out.setToolTip("Move the selected layer out of its parent")
        # A lambda, not the method: a clicked signal hands its checked
        # state to any slot that will take an argument, and this one takes
        # the layers to move.
        btn_out.clicked.connect(lambda: self._move_out())
        btn_up = QPushButton("↑")
        btn_up.setStyleSheet(btn_style)
        btn_up.setToolTip("Move the selected layer up the list")
        btn_up.clicked.connect(lambda: self._move_in_list(-1))
        btn_down = QPushButton("↓")
        btn_down.setStyleSheet(btn_style)
        btn_down.setToolTip("Move the selected layer down the list")
        btn_down.clicked.connect(lambda: self._move_in_list(1))
        btn_del = QPushButton("−")
        btn_del.setStyleSheet(btn_style)
        btn_del.setToolTip("Delete selected layer")
        btn_del.clicked.connect(self._delete_layer)

        btns = QHBoxLayout()
        btns.setContentsMargins(4, 2, 4, 4)
        btns.addWidget(btn_add)
        btns.addWidget(btn_sub)
        # Three jobs in this row, so three groups: two buttons that make a
        # layer, one that moves one, one that throws one away. Without the
        # gaps they read as four ways to make a layer, and the one that
        # only moves the picked layer comes as a surprise.
        btns.addSpacing(10)
        btns.addWidget(btn_out)
        btns.addWidget(btn_up)
        btns.addWidget(btn_down)
        btns.addSpacing(10)
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

    def width_short_by(self) -> int:
        """How many pixels the panel is short of showing every column.

        The four narrow columns take the width their own content needs
        and the name takes whatever is left, so the panel width the
        window hands over decides whether the name fits. 280px is this
        machine's font's number: measured against a wider sans-serif the
        same five columns want more, there is nothing left for the name,
        and the layer everything is drawn on reads "Defa...". The window
        asks after it has set that width, and gives back the difference.
        """
        tree = self.tree
        return max(0, tree.sizeHintForColumn(_NAME_COL)
                   - tree.columnWidth(_NAME_COL))

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
        if column == _COLOR_COL:
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
        """A double-click: on the name it chooses the layer, else it edits."""
        if column == _NAME_COL:
            self.scene.layers.current_id = self._layer_id(item)
            self.scene.notify()
            return
        if column not in (_TYPE_COL, _PRINT_COL):
            return
        # making a cell editable is one of the panel's own writes; Type and
        # Print already show the layer's value, their delegates seed the
        # drop-down from it
        self._updating = True
        try:
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        finally:
            self._updating = False
        self.tree.editItem(item, column)

    def _rename(self, layer_id):
        """Open a layer's name for typing, from the row menu.

        The row shows more than the name - the count of what is on the
        layer, and the dot on the active one - so the cell is written back
        to the bare name first, or the user would be editing the label.
        """
        item = self._all_rows().get(layer_id)
        if item is None:
            return
        self._updating = True
        try:
            item.setText(_NAME_COL, self.scene.layers.get(layer_id).name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        finally:
            self._updating = False
        self.tree.editItem(item, _NAME_COL)

    def _pick_row(self, layer_id):
        """Put the picked row on a layer that has just been made.

        The tree is redrawn from the scene, which puts back whatever was
        picked before, so a new layer would otherwise arrive with the row
        above it still picked: the next press of the button would work
        from that one, and a name typed straight away would rename it.
        """
        item = self._all_rows().get(layer_id)
        if item is None:
            return
        self.tree.setCurrentItem(item)
        self.tree.clearSelection()
        item.setSelected(True)

    def _new_layer(self):
        """A new layer beside the picked one, at the level it is on.

        Beside, not at the bottom of the list: the `↳` button next to
        this one makes a layer inside the picked one, so this one making
        its sibling is the pair of them, and either way the new layer
        turns up on the row the user is already looking at. A sublayer
        picked here gets a sublayer of the same parent, not a top-level
        layer at the end of the panel. Nothing picked means the end of
        the top level, since there is no row to be beside.
        """
        item = self.tree.currentItem()
        beside = None if item is None else self._layer_id(item)
        layers = self.scene.layers
        parent_id = None if beside is None else layers.get(beside).parent
        self.history.checkpoint("new layer")
        layer = layers.create(parent=parent_id)
        if beside is not None:
            # In front of whatever was under it, or nothing if it was the
            # last of its parent's layers. The new layer is already one
            # of them, at the end, so it is left out of the count.
            kin = [la.id for la in layers.children(parent_id)
                   if la.id != layer.id]
            after = kin.index(beside) + 1
            layers.place(layer.id, parent_id,
                         kin[after] if after < len(kin) else None)
        layers.current_id = layer.id
        self.scene.notify()
        self._pick_row(layer.id)

    def _new_sublayer(self):
        """A new layer under the picked one, the way Rhino's panel does it.

        Nothing picked means there is nowhere to put it; the + beside this
        button is the one that makes a layer of its own.
        """
        item = self.tree.currentItem()
        if item is None:
            return
        self._new_sublayer_under(self._layer_id(item))

    def _new_sublayer_under(self, parent_id):
        """A new layer inside the named one."""
        item = self._all_rows().get(parent_id)
        self.history.checkpoint("new sublayer")
        layer = self.scene.layers.create(parent=parent_id)
        self.scene.layers.current_id = layer.id
        # Open the branch on the row itself, not in `_collapsed`, which
        # the redraw is about to work out again from the tree: a new layer
        # made inside a closed branch is a new layer nobody can see.
        if item is not None:
            item.setExpanded(True)
        self.scene.notify()
        self._pick_row(layer.id)

    def _row_menu(self, pos):
        """The menu a right-click on a row opens.

        The panel spells out every other move a layer can make, and left
        the way back out of a branch to a drag onto the blank space under
        the last row, which nobody guesses and which is not there at all
        once the layers fill the panel.
        """
        item = self.tree.itemAt(pos)
        if item is None:
            return
        layer_id = self._layer_id(item)
        if layer_id not in self._selected_layer_ids():
            self.tree.setCurrentItem(item)
        self._menu_for(layer_id).exec(self.tree.viewport().mapToGlobal(pos))

    def _menu_for(self, layer_id) -> QMenu:
        """The menu for the row under the pointer.

        It acts on the whole selection when that row is one of the picked
        ones, and on that row alone otherwise: right-clicking one of five
        picked layers to move only that one is never what was meant.
        """
        layers = self.scene.layers
        picked = self._selected_layer_ids()
        ids = sorted(picked) if layer_id in picked else [layer_id]
        parents = {layers.get(i).parent for i in ids}
        menu = QMenu(self)
        # The double-click that used to open a rename now says which layer
        # to draw on, so this is the way in to a layer's name.
        menu.addAction("Rename", lambda: self._rename(layer_id))
        menu.addAction("New sublayer",
                       lambda: self._new_sublayer_under(layer_id))
        menu.addSeparator()
        self._add_hatch_menu(menu, ids)
        menu.addSeparator()
        # Name the branch when they all sit in the same one, so the entry
        # says where the layer ends up and not merely that it moves.
        if len(parents) == 1 and None not in parents:
            (parent,) = parents
            text = f"Move out of {layers.get(parent).name}"
        else:
            text = "Move out one level"
        out = menu.addAction(text, lambda: self._move_out(ids))
        out.setEnabled(bool(parents - {None}))
        # Only worth offering where it is a different move: for a layer
        # one level down, out of its branch is the top level already.
        deep = [i for i in ids if layers.get(i).parent
                and layers.get(layers.get(i).parent).parent]
        if deep:
            menu.addAction("Move to the top level",
                           lambda: self._move_out(ids, to_top=True))
        return menu

    def _add_hatch_menu(self, menu, ids):
        """The fill a hatch drawn on these layers starts out with.

        A layer is a material and a material has a fill, so this is where
        Concrete is told it crosses. It lives in the menu rather than in a
        column of its own because the tree's five columns already fill the
        panel exactly, and a sixth would come out of the layer name.

        The tick says what the picked layers are set to now, and says
        nothing at all when they disagree: two materials picked together
        are not one material.
        """
        layers = self.scene.layers
        have = {layers.get(i).hatch for i in ids}
        # Built with the menu as its parent, not by addMenu's own name:
        # a submenu Qt owns lives as long as the menu it hangs off, and
        # one Python owns is collected while the menu is still open.
        sub = QMenu("Hatch", menu)
        menu.addMenu(sub)
        for pattern in ("", *_layout.HATCH_PATTERNS):
            action = sub.addAction(pattern.capitalize() if pattern else "None")
            action.setCheckable(True)
            action.setChecked(have == {pattern})
            action.triggered.connect(
                lambda _checked=False, p=pattern: self._set_hatch(ids, p))

    def _set_hatch(self, ids, pattern):
        self.history.checkpoint("layer hatch")
        for layer_id in ids:
            self.scene.layers.set_hatch(layer_id, pattern)
        self.scene.notify()

    def _move_in_list(self, step):
        """Move every picked layer one place up (-1) or down (1).

        A layer whose neighbour that way is picked too stays where it is,
        so a run of picked layers travels as a block, keeps its own order,
        and stops together when the one in front runs out of room.
        """
        layers = self.scene.layers
        picked = self._selected_layer_ids()
        if not picked:
            return
        # Nearest the end they are heading for goes first, or the picked
        # layers take each other's places on the way.
        ids = [la.id for la in layers.all() if la.id in picked]
        if step > 0:
            ids.reverse()
        self.history.checkpoint("move layer")
        moved = False
        for layer_id in ids:
            siblings = [la.id for la in
                        layers.children(layers.get(layer_id).parent)]
            i = siblings.index(layer_id) + step
            if not 0 <= i < len(siblings) or siblings[i] in picked:
                continue
            moved = (layers.move_up(layer_id) if step < 0
                     else layers.move_down(layer_id)) or moved
        if not moved:
            self.history.discard_checkpoint()
            return
        self.scene.notify()

    def _move_out(self, layer_ids=None, to_top=False):
        """Take layers out of the branch they sit in.

        Out is one level: a layer that leaves Walls::Exterior lands in
        Walls, beside the parent it came out of, which is what a user
        dragging it up the tree by hand would do. `to_top` is the deep
        case, where climbing out a level at a time is a chore.

        A layer inside another one that is moving is left alone, for the
        same reason a drag leaves it alone: it is already going where its
        parent goes.
        """
        layers = self.scene.layers
        if layer_ids is None:
            layer_ids = self._selected_layer_ids()
        moving = [i for i in layer_ids if layers.get(i).parent]
        inside = {d.id for i in moving for d in layers.descendants(i)}
        moving = [i for i in moving if i not in inside]
        if not moving:
            return
        # Where each one lands, worked out before anything moves: read
        # afterwards, a layer whose parent has itself just come out would
        # be measured against a tree that no longer holds it.
        targets = {i: (None if to_top else layers.get(layers.get(i).parent)
                       .parent) for i in moving}
        self.history.checkpoint("move layer out")
        moved = False
        for layer_id, parent in targets.items():
            try:
                layers.set_parent(layer_id, parent)
                moved = True
            except ValueError:
                pass
        if not moved:
            self.history.discard_checkpoint()
        self.scene.notify()

    def _move_layers(self, layer_ids, parent_id, before_id=None):
        """Put dragged layers where they were let go of.

        A layer inside one of the others is left alone: it is already going
        where its parent goes, and moving it too would take it out of the
        branch the user is dragging. What is left goes down in the order
        the list had it in, each in front of the same layer, so a group
        picked up together keeps its own order on landing.
        """
        layers = self.scene.layers
        moving = [i for i in layer_ids if i != parent_id]
        inside = {d.id for i in moving for d in layers.descendants(i)}
        moving = [i for i in moving if i not in inside]
        if not moving:
            return
        listed = [la.id for la in layers.all()]
        moving.sort(key=listed.index)
        # Qt is still inside the drop, so the redraw has to wait a turn:
        # the same guard the edited-item handler uses, for the same reason.
        self._in_item_change = True
        try:
            self.history.checkpoint("move layer")
            moved = False
            for layer_id in moving:
                try:
                    moved = layers.place(layer_id, parent_id,
                                         before_id) or moved
                except ValueError:
                    # into its own branch: that branch would have no top
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
