"""The Sheets list: a drawing set's sheets in their groups, beside Layers.

Layouts were a strip of tabs along the bottom of the window, which is fine
for three and lost at thirty (#38). This lists them the way a set is bound,
sheets in groups that can sit inside each other, in the order they print
in, which is also the tab strip's order: moving a row here moves its tab.

A click picks (Properties shows what is picked), a double-click opens a
sheet, and the sheet on screen carries the gold dot the current layer
carries in Layers. Rows are dragged to reorder and to regroup; whatever the
drag leaves in the tree is read back as the new binding.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QHBoxLayout, QMenu, QPushButton, QStyle,
    QStyledItemDelegate, QStyleOptionViewItem, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from ..core.layout import (PAPER_SIZES, Layout, SheetGroup, sheet_label,
                           sheet_tree)
from ..utils.units import format_paper_size
from . import theme

_KIND_ROLE = Qt.ItemDataRole.UserRole          # "sheet" or "group"
_ID_ROLE = Qt.ItemDataRole.UserRole + 1
_OPEN_ROLE = Qt.ItemDataRole.UserRole + 2      # the sheet on screen
_MARK_W = 18                                   # the dot's column


class _RowDelegate(QStyledItemDelegate):
    """A sheet row: a dot, gold on the sheet on screen and an empty ring
    on the rest, so the names line up; a group row: its name, a weight
    heavier. Rows are the panels' shared height.

    Editing a row edits the name alone, not the label with the number in
    front, and the edit goes to the panel rather than into the row: the
    row is rebuilt from the scene, and a row's text is not a name.
    """

    def __init__(self, panel):
        super().__init__(panel.tree)
        self._panel = panel

    def setEditorData(self, editor, index):
        editor.setText(self._panel.name_of(index.data(_KIND_ROLE),
                                           index.data(_ID_ROLE)))

    def setModelData(self, editor, model, index):
        self._panel.rename(index.data(_KIND_ROLE), index.data(_ID_ROLE),
                           editor.text())

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(theme.LIST_ROW_HEIGHT)
        return size

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        style = opt.widget.style() if opt.widget is not None \
            else QApplication.style()
        if index.data(_KIND_ROLE) == "group":
            opt.font.setWeight(QFont.Weight.DemiBold)
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt,
                              painter, opt.widget)
            return
        back = QStyleOptionViewItem(opt)
        back.text = ""
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, back,
                          painter, opt.widget)
        rect = option.rect
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        centre = QPointF(rect.x() + _MARK_W / 2, rect.center().y() + 0.5)
        if index.data(_OPEN_ROLE):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.ACCENT))
            painter.drawEllipse(centre, 3.5, 3.5)
        else:
            painter.setPen(QPen(QColor("#55565e"), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(centre, 3.0, 3.0)
        painter.restore()
        front = QStyleOptionViewItem(opt)
        front.rect = rect.adjusted(_MARK_W - 3, 0, 0, 0)
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, front,
                          painter, opt.widget)


class _SheetTree(QTreeWidget):
    """The tree, dragging rows within itself, a faint rule under each row.
    A drop is read back by the panel once Qt has finished moving rows."""

    def __init__(self, on_drop):
        super().__init__()
        self._on_drop = on_drop

    def dropEvent(self, event):
        super().dropEvent(event)
        QTimer.singleShot(0, self._on_drop)

    def drawRow(self, painter, option, index):
        super().drawRow(painter, option, index)
        painter.save()
        painter.setPen(QColor(0, 0, 0, 41))
        y = option.rect.bottom()
        painter.drawLine(0, y, self.viewport().width(), y)
        painter.restore()


class SheetsPanel(QWidget):
    """A drawing set's sheets in their groups. `make_sheet()` makes a sheet
    and hands it back (the window's, which also opens it); `delete_sheet`
    deletes one and says whether it did (the window's asks first when
    there is drawing on it). Both default to doing it here, quietly."""

    pickedChanged = Signal()
    openRequested = Signal(str)            # a sheet's layout id
    printRequested = Signal(list)          # layout ids to offer to print

    def __init__(self, scene, history, make_sheet=None, delete_sheet=None):
        super().__init__()
        self.scene = scene
        self.history = history
        self._make_sheet = make_sheet
        self._delete_sheet = delete_sheet
        self._open_id = None
        self._updating = False

        self.tree = _SheetTree(self.sync_from_tree)
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(1)
        self.tree.setIndentation(12)
        self.tree.setUniformRowHeights(True)
        self.tree.setStyleSheet("QTreeWidget { border: none; }")
        self.tree.setItemDelegate(_RowDelegate(self))
        self.tree.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setDragEnabled(True)
        self.tree.setAcceptDrops(True)
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.tree.setEditTriggers(
            QAbstractItemView.EditTrigger.EditKeyPressed)
        self.tree.itemSelectionChanged.connect(self._picks_changed)
        self.tree.itemDoubleClicked.connect(self._double_clicked)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._row_menu)

        style = ("QPushButton { padding: 2px; font-weight: bold; "
                 "min-width: 26px; max-width: 26px; }")
        buttons = QHBoxLayout()
        buttons.setContentsMargins(4, 4, 4, 4)
        buttons.setSpacing(4)
        for text, tip, slot in (
                ("+", "New sheet, in the picked group", self.new_sheet),
                ("▤", "New group, inside the picked one", self.new_group),
                ("↑", "Move the picked rows up",
                 lambda: self.move_picked(-1)),
                ("↓", "Move the picked rows down",
                 lambda: self.move_picked(1)),
                ("−", "Delete the picked sheets or groups (a group's "
                      "sheets stay)", self.delete_picked)):
            button = QPushButton(text)
            button.setStyleSheet(style)
            button.setToolTip(tip)
            button.clicked.connect(lambda _c=False, f=slot: f())
            buttons.addWidget(button)
            if text == "▤":
                buttons.addSpacing(8)
        buttons.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.tree, 1)
        layout.addLayout(buttons)

        scene.add_listener(self._scene_changed)
        self.rebuild()

    # ------------------------------------------------------------- showing

    def _scene_changed(self, kind="all"):
        if kind in ("all", "layouts"):
            self.rebuild()

    def rebuild(self):
        """Fill the tree from the scene, keeping what was open and picked."""
        if self._updating:
            return
        expanded = {self._key(it) for it in self._all_items()
                    if it.isExpanded()}
        first = not self.tree.topLevelItemCount()
        picked = {self._key(it) for it in self.tree.selectedItems()}
        self._updating = True
        self.tree.blockSignals(True)
        try:
            self.tree.clear()
            for node in sheet_tree(self.scene.layouts,
                                   self.scene.sheet_groups):
                self.tree.addTopLevelItem(self._row(node))
            for item in self._all_items():
                key = self._key(item)
                if item.childCount():
                    item.setExpanded(first or key in expanded)
                item.setSelected(key in picked)
        finally:
            self.tree.blockSignals(False)
            self._updating = False

    def _row(self, node):
        kind, thing, children = node
        item = QTreeWidgetItem([thing.name if kind == "group"
                                else sheet_label(thing)])
        item.setData(0, _KIND_ROLE, kind)
        item.setData(0, _ID_ROLE, thing.id)
        flags = (Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                 | Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsEditable)
        if kind == "group":
            flags |= Qt.ItemFlag.ItemIsDropEnabled
            item.setToolTip(0, f"Group: {thing.name}")
        else:
            item.setData(0, _OPEN_ROLE, thing.id == self._open_id)
            w, h = thing.paper_w, thing.paper_h
            size = _paper_name(w, h, self.scene.units)
            item.setToolTip(0, f"{sheet_label(thing)}: {size}; "
                               "double-click to open")
        item.setFlags(flags)
        for child in children:
            item.addChild(self._row(child))
        return item

    def set_open(self, space_id):
        """Mark the sheet on screen ("model" or an id)."""
        self._open_id = space_id
        for item in self._all_items():
            if item.data(0, _KIND_ROLE) == "sheet":
                item.setData(0, _OPEN_ROLE,
                             item.data(0, _ID_ROLE) == space_id)

    def is_open_row(self, item) -> bool:
        return bool(item.data(0, _OPEN_ROLE))

    # -------------------------------------------------------------- picking

    def _picks_changed(self):
        if not self._updating:
            self.pickedChanged.emit()

    def picked_sheet_ids(self) -> list:
        """The picked sheets, in the set's order."""
        ids = {it.data(0, _ID_ROLE) for it in self.tree.selectedItems()
               if it.data(0, _KIND_ROLE) == "sheet"}
        return [lay.id for lay in self.scene.layouts if lay.id in ids]

    def picked_group_ids(self) -> list:
        return [it.data(0, _ID_ROLE) for it in self.tree.selectedItems()
                if it.data(0, _KIND_ROLE) == "group"]

    def clear_picked(self):
        self.tree.clearSelection()

    def pick(self, layout_ids):
        """Pick these sheets, and nothing else."""
        self.tree.blockSignals(True)
        try:
            for item in self._all_items():
                item.setSelected(item.data(0, _KIND_ROLE) == "sheet"
                                 and item.data(0, _ID_ROLE) in layout_ids)
        finally:
            self.tree.blockSignals(False)
        self.pickedChanged.emit()

    def _double_clicked(self, item, _column=0):
        if item.data(0, _KIND_ROLE) == "sheet":
            self.openRequested.emit(item.data(0, _ID_ROLE))

    # -------------------------------------------------------------- editing

    def _target_group(self):
        """The group a new row goes in: the picked one, or the picked
        sheet's own."""
        for item in self.tree.selectedItems():
            if item.data(0, _KIND_ROLE) == "group":
                return item.data(0, _ID_ROLE)
            parent = item.parent()
            if parent is not None:
                return parent.data(0, _ID_ROLE)
        return None

    def new_sheet(self):
        group = self._target_group()
        self.history.checkpoint("new sheet")
        if self._make_sheet is not None:
            lay = self._make_sheet()
        else:
            w, h = PAPER_SIZES["A3"]
            lay = Layout(name=f"Sheet {len(self.scene.layouts) + 1}",
                         paper_w=float(w), paper_h=float(h))
            self.scene.layouts.append(lay)
        lay.group = group
        self.scene.notify("layouts")
        return lay

    def new_group(self):
        parent = self._target_group()
        taken = {g.name for g in self.scene.sheet_groups}
        n = len(self.scene.sheet_groups) + 1
        while f"Group {n}" in taken:
            n += 1
        self.history.checkpoint("new sheet group")
        group = SheetGroup(name=f"Group {n}", parent=parent)
        self.scene.sheet_groups.append(group)
        self.scene.notify("layouts")
        return group

    def _thing(self, kind, key):
        if kind == "sheet":
            return self.scene.get_layout(key)
        return next((g for g in self.scene.sheet_groups if g.id == key),
                    None)

    def name_of(self, kind, key) -> str:
        thing = self._thing(kind, key)
        return thing.name if thing is not None else ""

    def rename(self, kind, key, text: str):
        """Rename a sheet or a group; a sheet keeps its number."""
        text = (text or "").strip()
        thing = self._thing(kind, key)
        if thing is None or not text or text == thing.name:
            self.rebuild()
            return
        self.history.checkpoint("rename sheet" if kind == "sheet"
                                else "rename sheet group")
        thing.name = text
        self.scene.notify("layouts")

    def rename_row(self, item, text: str):
        self.rename(item.data(0, _KIND_ROLE), item.data(0, _ID_ROLE), text)

    def edit_row(self, item):
        """Open a row's name for typing (the delegate gives it the name)."""
        self.tree.editItem(item, 0)

    def move_picked(self, step: int):
        """Move the picked rows one place up (-1) or down (1) among the
        rows beside them, and read the tree back."""
        items = self.tree.selectedItems()
        if not items:
            return
        if step > 0:
            items = list(reversed(items))
        self._updating = True
        try:
            for item in items:
                parent = item.parent()
                holder = parent if parent is not None else None
                count = (holder.childCount() if holder is not None
                         else self.tree.topLevelItemCount())
                index = (holder.indexOfChild(item) if holder is not None
                         else self.tree.indexOfTopLevelItem(item))
                to = index + step
                if not 0 <= to < count:
                    continue
                if holder is not None:
                    holder.takeChild(index)
                    holder.insertChild(to, item)
                else:
                    self.tree.takeTopLevelItem(index)
                    self.tree.insertTopLevelItem(to, item)
                item.setSelected(True)
        finally:
            self._updating = False
        self.sync_from_tree()

    def delete_picked(self):
        """Delete the picked rows. A group goes and its sheets and groups
        move up to where it was; a sheet goes the way the window deletes
        one, which asks first when there is drawing on it."""
        groups = self.picked_group_ids()
        sheets = self.picked_sheet_ids()
        if groups:
            self.history.checkpoint("delete sheet group")
            by_id = {g.id: g for g in self.scene.sheet_groups}
            for gid in groups:
                gone = by_id.get(gid)
                if gone is None:
                    continue
                for lay in self.scene.layouts:
                    if lay.group == gid:
                        lay.group = gone.parent
                for g in self.scene.sheet_groups:
                    if g.parent == gid:
                        g.parent = gone.parent
                self.scene.sheet_groups.remove(gone)
            self.scene.notify("layouts")
        for lid in sheets:
            lay = self.scene.get_layout(lid)
            if lay is None:
                continue
            if self._delete_sheet is not None:
                self._delete_sheet(lay)
            else:
                self.history.checkpoint("delete sheet")
                self.scene.layouts.remove(lay)
                self.scene.notify("layouts")

    def sync_from_tree(self):
        """Read the tree back into the set: every sheet's group and place,
        every group's parent and place. One undo step, if anything moved."""
        order, groups_seen, parents, homes = [], [], {}, {}

        def walk(item, parent_gid):
            kind, key = item.data(0, _KIND_ROLE), item.data(0, _ID_ROLE)
            if kind == "group":
                groups_seen.append(key)
                parents[key] = parent_gid
                for i in range(item.childCount()):
                    walk(item.child(i), key)
            else:
                order.append(key)
                homes[key] = parent_gid

        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i), None)
        by_layout = {lay.id: lay for lay in self.scene.layouts}
        by_group = {g.id: g for g in self.scene.sheet_groups}
        new_layouts = ([by_layout[k] for k in order if k in by_layout]
                       + [lay for lay in self.scene.layouts
                          if lay.id not in homes])
        new_groups = ([by_group[k] for k in groups_seen if k in by_group]
                      + [g for g in self.scene.sheet_groups
                         if g.id not in parents])
        moved = (
            [lay.id for lay in new_layouts]
            != [lay.id for lay in self.scene.layouts]
            or [g.id for g in new_groups]
            != [g.id for g in self.scene.sheet_groups]
            or any(by_layout[k].group != gid for k, gid in homes.items()
                   if k in by_layout)
            or any(by_group[k].parent != gid for k, gid in parents.items()
                   if k in by_group))
        if not moved:
            self.rebuild()
            return
        self.history.checkpoint("move sheets")
        for k, gid in homes.items():
            if k in by_layout:
                by_layout[k].group = gid
        for k, gid in parents.items():
            if k in by_group:
                by_group[k].parent = gid
        self.scene.layouts[:] = new_layouts
        self.scene.sheet_groups[:] = new_groups
        self.scene.notify("layouts")

    # ----------------------------------------------------------------- menu

    def _row_menu(self, pos):
        item = self.tree.itemAt(pos)
        menu = QMenu(self)
        if item is not None and not item.isSelected():
            self.tree.clearSelection()
            item.setSelected(True)
        if item is not None and item.data(0, _KIND_ROLE) == "sheet":
            sid = item.data(0, _ID_ROLE)
            menu.addAction("Open", lambda: self.openRequested.emit(sid))
        if item is not None:
            menu.addAction("Rename", lambda: self.edit_row(item))
        menu.addAction("New sheet", self.new_sheet)
        menu.addAction("New group", self.new_group)
        sheets = self.picked_sheet_ids()
        if sheets:
            menu.addSeparator()
            menu.addAction("Print…",
                           lambda: self.printRequested.emit(sheets))
        if item is not None:
            menu.addSeparator()
            menu.addAction("Delete", self.delete_picked)
        self._menu = menu                 # held, or Qt takes it away
        menu.popup(self.tree.viewport().mapToGlobal(pos))

    # -------------------------------------------------------------- helpers

    def _all_items(self):
        out = []
        stack = [self.tree.topLevelItem(i)
                 for i in range(self.tree.topLevelItemCount())]
        while stack:
            item = stack.pop(0)
            out.append(item)
            stack[0:0] = [item.child(i) for i in range(item.childCount())]
        return out

    @staticmethod
    def _key(item):
        return (item.data(0, _KIND_ROLE), item.data(0, _ID_ROLE))


def _paper_name(w: float, h: float, units: str) -> str:
    """A3 landscape, or the size when it is not a standard, in the units
    the sheet is read in."""
    for name, (pw, ph) in PAPER_SIZES.items():
        if (abs(w - pw) < 0.5 and abs(h - ph) < 0.5):
            return f"{name} landscape"
        if (abs(w - ph) < 0.5 and abs(h - pw) < 0.5):
            return f"{name} portrait"
    return format_paper_size(w, h, units)
