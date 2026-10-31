"""Where Hydra is typed into: the component search, names, values
and panels, and its dialogs."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit,
    QVBoxLayout, QWidget,
)

from ...core import hydra
from ...core.hydra import COMPONENTS
from ..dialogs import untether
from .style import component_icon


SEARCH_ROWS = 12            # the most the search lists before it scrolls


class ComponentSearch(QFrame):
    """Type to find a component. Before anything is typed it offers the
    components every graph starts from; typing searches them all, and hides
    the ones whose name does not fit."""

    chosen = Signal(str, object)     # a component, and settings if typed

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setObjectName("hydraSearch")
        self.setStyleSheet(
            "#hydraSearch { background: #2b2d31; border: 1px solid #1b1c1f;"
            " border-radius: 5px; }"
            "QLineEdit { background: #25272b; color: #e4e5e7;"
            " border: 1px solid #d9a441; border-radius: 3px;"
            " padding: 3px 6px; }"
            "QListWidget { background: transparent; color: #e4e5e7;"
            " border: none; outline: none; }"
            "QListWidget::item { padding: 3px 4px; border-radius: 3px; }"
            "QListWidget::item:selected { background: #4a4d55; }")
        self.field = QLineEdit()
        self.field.setPlaceholderText("Type to find a component")
        self.list = QListWidget()
        self.list.setIconSize(QSize(18, 18))
        self.list.setFixedWidth(230)
        # sized to what it lists, so it has nothing to scroll; past
        # SEARCH_ROWS the wheel still walks it, without a bar
        for policy in (self.list.setVerticalScrollBarPolicy,
                       self.list.setHorizontalScrollBarPolicy):
            policy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)
        root.addWidget(self.field)
        root.addWidget(self.list)
        self.field.textChanged.connect(self.show_found)
        self.field.installEventFilter(self)
        self.list.itemClicked.connect(self._take)
        self.show_found("")

    def show_found(self, text):
        self.list.clear()
        # a sign and a number, +2 or *3, is the operation with B set to it,
        # offered first; but -2 is first of all a number
        operation = hydra.operation_from_text(text)
        if operation is not None and not text.strip().startswith("-"):
            self.list.addItem(self._typed_operation(*operation))
        # a number or a range typed is a slider set to it
        typed = hydra.slider_from_text(text)
        if typed is not None:
            self.list.addItem(self._typed_slider(typed))
        if operation is not None and text.strip().startswith("-"):
            self.list.addItem(self._typed_operation(*operation))
        note = hydra.panel_from_text(text)
        if note is not None:
            self.list.addItem(self._typed_panel(note))
        for key in hydra.find_components(text):
            comp = COMPONENTS[key]
            item = QListWidgetItem(comp.title)
            icon = component_icon(comp)
            if icon is not None:
                item.setIcon(icon)
            item.setToolTip(comp.description)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)
        row = max(self.list.sizeHintForRow(0), 1) if self.list.count() else 26
        rows = min(max(self.list.count(), 1), SEARCH_ROWS)
        self.list.setFixedHeight(rows * row + 2 * self.list.frameWidth() + 2)
        self.adjustSize()

    def eventFilter(self, obj, event):
        # the arrows walk the list while the typing stays in the field
        if obj is self.field and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                step = 1 if key == Qt.Key.Key_Down else -1
                row = self.list.currentRow() + step
                if 0 <= row < self.list.count():
                    self.list.setCurrentRow(row)
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._take(self.list.currentItem())
                return True
            if key == Qt.Key.Key_Escape:
                self.close()
                return True
        return super().eventFilter(obj, event)

    def _typed_slider(self, params):
        comp = COMPONENTS["slider"]
        places = params["decimals"]
        low, high = (hydra.format_number(params[k], places)
                     for k in ("min", "max"))
        value = hydra.format_number(params["value"], places)
        item = QListWidgetItem(f"Number Slider  {low} to {high}, at {value}")
        icon = component_icon(comp)
        if icon is not None:
            item.setIcon(icon)
        item.setToolTip("A slider set to what was typed")
        item.setData(Qt.ItemDataRole.UserRole, "slider")
        item.setData(Qt.ItemDataRole.UserRole + 1, params)
        return item

    def _typed_panel(self, params):
        comp = COMPONENTS["panel"]
        item = QListWidgetItem(f"Panel  \u201c{params['text']}\u201d")
        icon = component_icon(comp)
        if icon is not None:
            item.setIcon(icon)
        item.setToolTip("A panel holding what was typed")
        item.setData(Qt.ItemDataRole.UserRole, "panel")
        item.setData(Qt.ItemDataRole.UserRole + 1, params)
        return item

    def _typed_operation(self, key, params, said):
        comp = COMPONENTS[key]
        item = QListWidgetItem(f"{comp.title}  {said}")
        icon = component_icon(comp)
        if icon is not None:
            item.setIcon(icon)
        item.setToolTip(f"{comp.description}, with B kept at what was typed")
        item.setData(Qt.ItemDataRole.UserRole, key)
        item.setData(Qt.ItemDataRole.UserRole + 1, params)
        return item

    def _take(self, item):
        if item is None:
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        params = item.data(Qt.ItemDataRole.UserRole + 1)
        self.close()
        self.chosen.emit(key, params)


def add_command(menu, text, slot, tip="", keys=""):
    """A menu entry, with its keys shown beside it but not taken: the keys
    are Hydra's already, and taken here too they would clash with the main
    window's."""
    action = menu.addAction(f"{text}\t{keys}" if keys else text)
    action.triggered.connect(lambda checked=False: slot())
    if tip:
        action.setToolTip(tip)
    menu.setToolTipsVisible(True)
    return action


class NameField(QLineEdit):
    """A component's name, at the top of its menu: clicked into, the whole
    of it is chosen, to be typed over."""

    def __init__(self, text):
        super().__init__(text)
        self.setMinimumWidth(180)
        self.setStyleSheet(
            "QLineEdit { background: #25272b; color: #e4e5e7;"
            " border: 1px solid #45484f; border-radius: 3px;"
            " padding: 3px 6px; margin: 4px 6px; font-weight: bold; }"
            "QLineEdit:focus { border-color: #d9a441; }")

    def mousePressEvent(self, event):
        chosen = self.hasSelectedText() and len(self.selectedText()) == len(
            self.text())
        super().mousePressEvent(event)
        if not chosen and not getattr(self, "_typed_in", False):
            self.selectAll()
            self._typed_in = True

    def focusInEvent(self, event):
        super().focusInEvent(event)
        QTimer.singleShot(0, self.selectAll)


class PanelField(QPlainTextEdit):
    """Typing into a panel: Ctrl+Enter or a click elsewhere keeps the text,
    Escape leaves the panel as it was. Enter alone starts a new line."""

    finished = Signal(bool)          # True to keep what was typed

    def __init__(self, text, parent):
        super().__init__(text, parent)
        self._done = False
        self.setStyleSheet(
            "QPlainTextEdit { background: #25272b; color: #e4e5e7;"
            " border: 1px solid #d9a441; border-radius: 3px; }")
        self.setPlaceholderText("One item a line")

    def event(self, event):
        if (event.type() == QEvent.Type.ShortcutOverride
                and event.key() == Qt.Key.Key_Escape):
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._finish(False)
            return
        if (event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self._finish(True)
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self._finish(True)

    def _finish(self, keep):
        if not self._done:
            self._done = True
            self.finished.emit(keep)


class ValueField(QLineEdit):
    """Typing into a slider: Enter or a click elsewhere keeps what is
    typed, Escape leaves the slider as it was."""

    committed = Signal(bool)        # True when focus is leaving
    cancelled = Signal()

    def __init__(self, text, parent):
        super().__init__(text, parent)
        self._done = False
        self.setStyleSheet(
            "QLineEdit { background: #25272b; color: #e4e5e7;"
            " border: 1px solid #d9a441; border-radius: 3px;"
            " padding: 0 4px; font-size: 10.5pt; }")
        self.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.setPlaceholderText("5 or 0.0-12")
        self.setToolTip("A number sets the value, a range such as 0.0-12 "
                        "sets the range and its decimal places")

    def event(self, event):
        # Escape here is this field's, not a command's to cancel
        if (event.type() == QEvent.Type.ShortcutOverride
                and event.key() == Qt.Key.Key_Escape):
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._finish(self.cancelled)
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.committed.emit(False)
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        if not self._done:
            self._done = True
            self.committed.emit(True)

    def _finish(self, signal):
        self._done = True
        signal.emit()


class CastDialog(QDialog):
    """Where cast geometry goes: a layer, and for more than one object
    whether they go as one group."""

    def __init__(self, layers, count, grouped, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cast")
        self.layers = QComboBox()
        for layer in layers.all():
            self.layers.addItem(layers.full_path(layer.id), layer.id)
        self.layers.setCurrentIndex(
            max(self.layers.findData(layers.current_id), 0))
        said = f"{count} object" + ("" if count == 1 else "s")
        self.group = QCheckBox(f"Group the {said}")
        self.group.setChecked(grouped)
        self.group.setVisible(count > 1)
        form = QFormLayout()
        form.addRow("Layer", self.layers)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
            f"Cast {said}")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addWidget(self.group)
        root.addWidget(buttons)
        untether(self, over=QWidget.window(parent) if parent else None)

    def layer_id(self):
        return self.layers.currentData()


class RangeDialog(QDialog):
    """A slider's minimum and maximum, typed. A number keeps the decimal
    places it is typed to, with a comma or a point."""

    def __init__(self, params, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Change Range")
        places = params["decimals"]
        self.low = QLineEdit(hydra.format_number(params["min"], places))
        self.high = QLineEdit(hydra.format_number(params["max"], places))
        self.hint = QLabel()
        self.hint.setStyleSheet("color: #d9824a;")
        form = QFormLayout()
        form.addRow("Minimum", self.low)
        form.addRow("Maximum", self.high)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addWidget(self.hint)
        root.addWidget(self.buttons)
        for field in (self.low, self.high):
            field.textChanged.connect(self._check)
        self._check()
        # the editor's own `window` is the main window, so ask Qt for the
        # floating one it sits in
        untether(self, over=QWidget.window(parent) if parent else None)

    def values(self):
        """Minimum, maximum and the most decimal places either was typed to."""
        (low, a), (high, b) = (hydra.parse_number(f.text())
                               for f in (self.low, self.high))
        return low, high, max(a, b)

    def _check(self):
        try:
            low, high, _places = self.values()
            problem = ("" if low < high
                       else "The minimum has to be below the maximum")
        except ValueError:
            problem = "Type a number in both fields"
        self.hint.setText(problem)
        self.hint.setVisible(bool(problem))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            not problem)
