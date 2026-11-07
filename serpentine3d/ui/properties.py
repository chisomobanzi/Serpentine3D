"""Properties panel: shows and edits the selected object, or a picked layer.

Two things can be live at once: what the viewport has selected, and the
layers picked in the Layers list. Properties shows one of them, and the
title bar (`SubjectTitleBar`) offers a tab for each when both are, so a
look at a layer never costs the selection. While the layer is shown the
selection is held, which every pane draws dimmed: full gold keeps meaning
"this is what Properties is editing".
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from itertools import product
from math import atan, dist, isclose, pi, sin, tan
from typing import NamedTuple

from PySide6.QtCore import QEvent, QSignalBlocker, QSize, QTimer, Signal, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFontComboBox,
    QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QStackedWidget, QTabBar, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ..core import clipping
from ..core import geometry as g
from ..core import user_text as ut
from ..core.layers import (HATCH_BACKGROUND_NONE, HATCH_INK,
                           HATCH_LAYER_COLOR, MAX_CUT_LINE_WIDTH,
                           MIN_HATCH_SPACING, PATH_SEPARATOR,
                           hatch_token_rgb, section_fill_dict)
from ..core.layout import (PAPER_SIZES, SECTION_FILLS, DetailView,
                           PaperObject, TextNote, hatch_patterns_of,
                           parse_scale, pattern_label, scale_presets,
                           section_fills_of, sheet_label)
from ..core.text import TextShape
from ..core.linetype import LINETYPES
from ..utils.units import (TO_MM, format_paper_length, format_paper_size,
                           paper_units)
from . import icons, theme
from .dock_title import DockTitleBar
from .layout_view import LINE_VISIBLE
from .object_chooser import kind_label
from .camera import STANDARD_VIEWS

# What the layer page offers for its two widths. Typed values work too; these
# are the ones worth a click. Screen widths are pixels, print widths the
# standard pen sizes in millimetres, the same list the Layers panel offers.
SCREEN_WIDTHS = ("1", "1.4", "2", "3", "4")
FROM_PRINT = "From print"       # a screen width worked out from print width
PRINT_WIDTHS = ("0.13", "0.18", "0.25", "0.35", "0.5", "0.7", "1.0")
# A section hatch's lines: angles on the paper in degrees, spacings in
# millimetres of paper. Typed values work too.
HATCH_ANGLES = ("0", "30", "45", "60", "90", "135")
HATCH_SPACINGS = ("1", "1.5", "2", "2.5", "3", "4", "5")
CUT_LINE_NONE = "None"                 # a cut with no line round it
_INK_SWATCH = (0.06, 0.06, 0.07)       # how Ink shows in the colour list
_UNLINED = ("none", "solid")           # the fills with no lines to space
# the pattern lists' last entries: {item data: hatchpatterns action}
_PATTERN_ACTIONS = {"load-patterns": "Load", "delete-patterns": "Delete"}


def _fill_patterns(combo, names, keep: int = 0):
    """Put a drawing's patterns in a pattern drop-down, after its first
    `keep` entries, then Load patterns… and Delete patterns…, which run
    `hatchpatterns` (#92).
    A pattern list is filled each time it is shown, so a pattern loaded
    since is offered at once."""
    with QSignalBlocker(combo):
        while combo.count() > keep:
            combo.removeItem(keep)
        for name in names:
            combo.addItem(pattern_label(name), name)
        combo.insertSeparator(combo.count())
        combo.addItem("Load patterns…", "load-patterns")
        combo.addItem("Delete patterns…", "delete-patterns")


def _with(names, extra) -> tuple:
    """`names`, then whichever of `extra` they leave out: a pattern a
    layer or a hatch names that the drawing has not loaded is still
    shown as what it is."""
    known = {n.lower() for n in names}
    return (*names, *(e for e in extra if e and e.lower() not in known))
_BY_LAYER = "By layer"                 # an object taking its layer's value
_BY_LAYER_TOKEN = "bylayer"

# the tab mark for more than one layer, which have no one colour between them
_MIXED_MARK = (0.6, 0.6, 0.62)

# what the Convert button says for each geometry output of model text
CONVERT_LABELS = {"curves": "Convert to curves",
                  "surface": "Convert to surfaces",
                  "solid": "Convert to solid"}


@dataclass(frozen=True)
class Subject:
    """What one page of Properties shows, said once for the page's header
    and for its tab."""
    kind: str      # what sort of thing, in the header's gold capitals
    title: str     # which one: its name, or how many
    detail: str    # one muted line of what and where
    mark: QIcon    # beside the kind, and on the tab
    tab: str       # the tab's few words
    tip: str       # the tab's tooltip


# How far a page's contents stand in from its sides: the form rows'
# margin, which the header and the links under it line up with.
_INSET = theme.PANEL_INSET


def _seam() -> QWidget:
    """The dark line that closes a page's header off from its fields."""
    seam = QWidget()
    seam.setObjectName("seam")
    seam.setFixedHeight(1)
    seam.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    seam.setStyleSheet(f"background: {theme.SEAM};")
    return seam


def _link(text: str = "") -> QPushButton:
    """A push button drawn as a gold link, for an action that sits in a
    line of text rather than standing on its own."""
    button = QPushButton(text)
    button.setProperty("link", True)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


class _Look(NamedTuple):
    """One section style as the look rows show it: for the hatch and for
    the cut line, the token each colour is kept as and the (r, g, b) that
    draws in."""
    pattern: str
    angle: float
    spacing: float
    color: str
    rgb: tuple | None
    cut_line_width: float
    cut_line_color: str
    cut_rgb: tuple | None
    background: str = HATCH_BACKGROUND_NONE
    background_rgb: tuple | None = None


# how each part of a section's look is named in an undo step
_LOOK_WORDS = {"angle": "angle", "spacing": "spacing", "color": "colour",
               "background": "background",
               "cut_line_width": "cut line width",
               "cut_line_color": "cut line colour"}


def _number_combo(values, setter, tip: str) -> QComboBox:
    """An editable drop-down of round numbers, for a value that is mostly
    one of a few but can be typed as anything."""
    combo = QComboBox()
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    combo.addItems(values)
    combo.setToolTip(tip)
    combo.textActivated.connect(setter)
    combo.lineEdit().editingFinished.connect(setter)
    return combo


class _TokenColour:
    """A colour kept as a token, "ink", "layer" or "#rrggbb", as a
    drop-down: Ink, Layer colour, the colour of its own when it has one,
    and Choose…, which asks for one. Other lists start from other entries
    (`first`): a background from None, a hatch's own from By layer.

    `chosen(token)` is told of every pick; `revert()` puts the page back
    when the colour dialog is closed without a choice.
    """

    def __init__(self, chosen, revert, title: str, tip: str,
                 first=(("Ink", HATCH_INK, _INK_SWATCH),)):
        self._chosen = chosen
        self._revert = revert
        self._title = title
        self._start = None
        self._showing = False
        self.combo = QComboBox()
        for label, token, swatch in first:
            if swatch is None:
                self.combo.addItem(label, token)
            else:
                self.combo.addItem(icons.swatch(swatch), label, token)
        self.combo.addItem("Layer colour", HATCH_LAYER_COLOR)
        self.combo.addItem("Choose…", "choose")
        self.combo.setToolTip(tip)
        self.combo.currentIndexChanged.connect(self._picked)

    def show(self, tokens: set, own_rgb, layer_rgb):
        """Show the one token in `tokens`, or a blank for several; a
        colour of its own is listed with `own_rgb` as its swatch, and
        `layer_rgb` is the Layer colour entry's."""
        self._showing = True
        try:
            combo = self.combo
            combo.setItemIcon(combo.findData(HATCH_LAYER_COLOR),
                              icons.swatch(layer_rgb))
            for i in reversed(range(combo.count())):
                if str(combo.itemData(i)).startswith("#"):
                    combo.removeItem(i)
            current = next(iter(tokens)) if len(tokens) == 1 else None
            if current is not None and current.startswith("#"):
                combo.insertItem(combo.findData("choose"),
                                 icons.swatch(own_rgb), current.upper(),
                                 current)
            combo.setCurrentIndex(-1 if current is None
                                  else combo.findData(current))
            self._start = own_rgb
        finally:
            self._showing = False

    def _picked(self, index):
        if self._showing or index < 0:
            return
        token = self.combo.itemData(index)
        if token == "choose":
            from PySide6.QtWidgets import QColorDialog
            color = QColorDialog.getColor(
                QColor.fromRgbF(*(self._start or _INK_SWATCH)), self.combo,
                self._title)
            if not color.isValid():
                self._revert()          # put back what it was
                return
            token = color.name()
        self._chosen(token)


class _HatchLook:
    """A section style's look as form rows, on a layer's page and on an
    object's that has a style of its own: the hatch's angle, spacing and
    colour, then the width and colour of the line round the cut (#82).

    `changed(key, value)` is told of an edit, key "angle", "spacing",
    "color", "cut_line_width" or "cut_line_color", and only of one that
    changes something; `revert()` puts the page back when what was typed
    is not a number, or a colour dialog closed without a choice. A hatch
    row shows only where the patterns shown have a use for it: angle,
    spacing and background are a line pattern's, and None has no colour
    to be drawn in. Every pattern has a cut line, None too: an empty cut
    is all outline.
    """

    def __init__(self, changed, revert):
        self._changed = changed
        self._revert = revert
        self._form = None
        self._looks: list = []
        self._showing = False
        self.angle = _number_combo(
            HATCH_ANGLES, self._angle_edited,
            "The angle of the hatch lines on the paper, in degrees from "
            "the sheet's horizontal")
        self.spacing = _number_combo(
            HATCH_SPACINGS, self._spacing_edited,
            "How far apart the hatch lines are on the printed sheet, in "
            "millimetres, whatever the detail's scale")
        self._hatch_ink = _TokenColour(
            lambda token: self._offer("color", token), revert,
            "Hatch colour",
            "The colour a cut's hatch or fill is drawn in: Ink is the near "
            "black the rest of the sheet is drawn in")
        self.color = self._hatch_ink.combo
        self._ground = _TokenColour(
            lambda token: self._offer("background", token), revert,
            "Hatch background",
            "What a hatch shows under its lines: None leaves it bare, a "
            "cut a darker shade of its object on screen; a colour fills it, "
            "on screen and on paper",
            first=(("None", HATCH_BACKGROUND_NONE, None),))
        self.background = self._ground.combo
        self.cut_width = _number_combo(
            (CUT_LINE_NONE, *PRINT_WIDTHS), self._cut_width_edited,
            "How wide the line round a cut face is on the printed sheet, in "
            "millimetres; None draws no line round it")
        self._cut_ink = _TokenColour(
            lambda token: self._offer("cut_line_color", token), revert,
            "Cut line colour",
            "The colour of the line round a cut face: Ink is the near black "
            "the rest of the sheet is drawn in")
        self.cut_color = self._cut_ink.combo

    def add_rows(self, form: QFormLayout):
        self._form = form
        form.addRow("Hatch angle (°)", self.angle)
        form.addRow("Hatch spacing (mm)", self.spacing)
        form.addRow("Hatch colour", self.color)
        form.addRow("Hatch background", self.background)
        form.addRow("Cut line (mm)", self.cut_width)
        form.addRow("Cut line colour", self.cut_color)

    def show(self, looks: list, layer_rgb):
        """Show `looks` (`_Look`s; a value they disagree on shows blank),
        with `layer_rgb` as the Layer colour entries' swatch."""
        self._showing = True
        try:
            self._looks = looks
            _show_common_text(self.angle,
                              {_width_text(k.angle) for k in looks})
            _show_common_text(self.spacing,
                              {_width_text(k.spacing) for k in looks})
            self._hatch_ink.show({k.color for k in looks}, looks[0].rgb,
                                 layer_rgb)
            self._ground.show({k.background for k in looks},
                              looks[0].background_rgb, layer_rgb)
            _show_common_text(self.cut_width,
                              {_cut_width_text(k.cut_line_width)
                               for k in looks})
            self._cut_ink.show({k.cut_line_color for k in looks},
                               looks[0].cut_rgb, layer_rgb)
            patterns = {k.pattern for k in looks}
            lined = any(p.lower() not in _UNLINED for p in patterns)
            self._form.setRowVisible(self.angle, lined)
            self._form.setRowVisible(self.spacing, lined)
            self._form.setRowVisible(self.background, lined)
            self._form.setRowVisible(self.color, bool(patterns - {"none"}))
            self._form.setRowVisible(self.cut_width, True)
            self._form.setRowVisible(self.cut_color, True)
        finally:
            self._showing = False

    def hide(self):
        for row in (self.angle, self.spacing, self.color, self.background,
                    self.cut_width, self.cut_color):
            self._form.setRowVisible(row, False)

    def _offer(self, key: str, value):
        """Pass an edit on, unless every look shown has it already."""
        if all(getattr(k, key) == value for k in self._looks):
            if key in ("color", "background", "cut_line_color",
                       "cut_line_width"):
                self._revert()          # the row has moved off it
            return
        self._changed(key, value)

    def _angle_edited(self, *_args):
        if self._showing:
            return
        angle = _parse_number(self.angle.currentText(), ("°", "deg"))
        if angle is None:
            self._revert()
            return
        self._offer("angle", angle % 180.0)

    def _spacing_edited(self, *_args):
        if self._showing:
            return
        spacing = _parse_width(self.spacing.currentText())
        if not spacing:
            self._revert()
            return
        self._offer("spacing", max(MIN_HATCH_SPACING, spacing))

    def _cut_width_edited(self, *_args):
        if self._showing:
            return
        text = self.cut_width.currentText().strip()
        width = 0.0 if text.lower() == CUT_LINE_NONE.lower() \
            else _parse_width(text)
        if width is None:
            self._revert()
            return
        self._offer("cut_line_width", min(width, MAX_CUT_LINE_WIDTH))


def _paper_and_turn(layout) -> tuple:
    """("A3", "Landscape") for a sheet, or (None, turn) for a size that is
    not one of the standard ones."""
    w, h = layout.paper_w, layout.paper_h
    turn = "Landscape" if w >= h else "Portrait"
    long_side, short_side = max(w, h), min(w, h)
    for name, (pw, ph) in PAPER_SIZES.items():
        if abs(long_side - max(pw, ph)) < 0.5 \
                and abs(short_side - min(pw, ph)) < 0.5:
            return name, turn
    return None, turn


def _paper_name(w: float, h: float, units: str) -> str:
    """A3 landscape, or the size when it is not a standard, in the units
    the sheet is read in."""
    class _Sheet:
        paper_w, paper_h = w, h
    name, turn = _paper_and_turn(_Sheet)
    return (f"{name} {turn.lower()}" if name
            else f"{format_paper_size(w, h, units)} {turn.lower()}")


class _DetailLayers(QWidget):
    """The layers a detail leaves out: each with Show beside it, a list to
    leave another out, and Show all. `edit(hidden)` is told the new list."""

    def __init__(self, edit):
        super().__init__()
        self._edit = edit
        self._hidden: list = []
        self._names: dict = {}
        self._rows = QVBoxLayout()
        self._rows.setContentsMargins(0, 0, 0, 0)
        self._rows.setSpacing(2)
        self.none_label = QLabel("None: it shows what the model shows")
        self.none_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        self.none_label.setWordWrap(True)
        self.add = QComboBox()
        self.add.setToolTip("Leave a layer out of this detail only; the "
                            "model and other details keep it")
        self.add.activated.connect(self._chosen)
        self.show_all_link = _link("Show all")
        self.show_all_link.clicked.connect(self.show_all)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)
        column.addWidget(self.none_label)
        column.addLayout(self._rows)
        column.addWidget(self.add)
        column.addWidget(self.show_all_link)

    def show_for(self, detail, layers):
        known = {la.id for la in layers.all()}
        self._hidden = [i for i in detail.hidden_layers if i in known]
        self._names = {la.id: layers.full_path(la.id) for la in layers.all()}
        while self._rows.count():
            row = self._rows.takeAt(0)
            if row.widget() is not None:
                row.widget().deleteLater()
        for layer_id in self._hidden:
            row = QWidget()
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            line.addWidget(QLabel(self._names[layer_id]), 1)
            show = _link("Show")
            show.setToolTip("Show this layer in this detail again")
            show.clicked.connect(lambda _c=False, i=layer_id:
                                 self.show_layer(i))
            line.addWidget(show)
            self._rows.addWidget(row)
        self.none_label.setVisible(not self._hidden)
        self.show_all_link.setVisible(len(self._hidden) > 1)
        self.add.blockSignals(True)
        self.add.clear()
        self.add.addItem("Hide a layer here…", None)
        for la in layers.all():
            if la.id not in self._hidden:
                self.add.addItem(self._names[la.id], la.id)
        self.add.setCurrentIndex(0)
        self.add.blockSignals(False)

    def hidden_names(self) -> list:
        return [self._names[i] for i in self._hidden]

    def offered(self) -> list:
        return [self.add.itemText(i) for i in range(1, self.add.count())]

    def hide_layer(self, layer_id):
        if layer_id not in self._hidden:
            self._edit(self._hidden + [layer_id])

    def show_layer(self, layer_id):
        self._edit([i for i in self._hidden if i != layer_id])

    def show_all(self):
        if self._hidden:
            self._edit([])

    def _chosen(self, index: int):
        layer_id = self.add.itemData(index)
        if layer_id is not None:
            self.hide_layer(layer_id)


def _cleared(layout):
    """Empty a layout of the rows a list widget built last time."""
    while layout.count():
        row = layout.takeAt(0)
        if row.widget() is not None:
            row.widget().deleteLater()


def _detail_label(detail, view_name: str, units: str) -> str:
    """A detail as a list of views names it: the view it looks along and
    its scale, which is what tells two details on one sheet apart."""
    if detail.perspective:
        return view_name
    return f"{view_name} {detail.scale_text(units)}"


class _ClipViews(QWidget):
    """The views a clipping plane cuts, a tick each: the model panes, then
    each sheet's details under the sheet's name (core/clipping.py), and
    Paused above them, which stops it cutting any of them and keeps the
    ticks for when it resumes. `switch(key, on)` and `pause(paused)` are
    told what was clicked."""

    def __init__(self, switch, pause):
        super().__init__()
        self._switch = switch
        self._pause = pause
        self._boxes: list = []          # (key, QCheckBox), in the order shown
        self._sheets: list = []
        self.paused = QCheckBox("Paused")
        self.paused.setToolTip("Cut no view until it is unticked; the "
                               "views ticked below come back then")
        self.paused.toggled.connect(lambda on: self._pause(on))
        self._rows = QVBoxLayout()
        self._rows.setContentsMargins(0, 0, 0, 0)
        self._rows.setSpacing(2)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)
        column.addWidget(self.paused)
        column.addLayout(self._rows)

    def show_for(self, plane, panes, layouts, view_name, units):
        """`panes` is (key, label) for each model pane; `view_name` names
        the view a detail looks along, and `units` are the document's,
        which its scale is written in."""
        setting = plane.clip_plane or {}
        off = set(setting.get("off_in", ()))
        with QSignalBlocker(self.paused):
            self.paused.setChecked(not setting.get("enabled"))
        _cleared(self._rows)
        self._boxes = []
        self._sheets = []

        def tick(key, label):
            box = QCheckBox(label)
            box.setChecked(key not in off)
            box.setEnabled(bool(setting.get("enabled")))
            box.toggled.connect(lambda on, k=key: self._switch(k, on))
            self._rows.addWidget(box)
            self._boxes.append((key, box))

        def heading(text):
            label = QLabel(text)
            label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
            self._rows.addWidget(label)

        if panes:
            heading("Model")
            for key, label in panes:
                tick(key, label)
        for lay in layouts:
            if not lay.details:
                continue
            heading(lay.name)
            self._sheets.append(lay.name)
            seen = Counter()
            for detail in lay.details:
                label = _detail_label(detail, view_name(detail), units)
                seen[label] += 1
                tick(detail.id, label if seen[label] == 1
                     else f"{label} ({seen[label]})")

    # read by the tests, and a summary of what the rows say
    def views(self) -> list:
        return [(key, box.text(), box.isChecked())
                for key, box in self._boxes]

    def sheets(self) -> list:
        return list(self._sheets)

    def cutting(self) -> bool:
        return not self.paused.isChecked()

    def views_enabled(self) -> bool:
        return all(box.isEnabled() for _key, box in self._boxes)

    def set_view(self, key: str, on: bool):
        for k, box in self._boxes:
            if k == key:
                box.setChecked(on)

    def set_cutting(self, on: bool):
        self.paused.setChecked(not on)


class _DetailClips(QWidget):
    """The clipping planes that cut a detail, a tick each, so a plan can
    be cut at sill height and the elevation beside it not at all
    (core/clipping.py). `switch(plane id, on)` is told what was clicked."""

    def __init__(self, switch):
        super().__init__()
        self._switch = switch
        self._boxes: list = []          # (plane id, QCheckBox)
        self._rows = QVBoxLayout(self)
        self._rows.setContentsMargins(0, 0, 0, 0)
        self._rows.setSpacing(2)

    def show_for(self, detail, planes):
        """`planes` as (plane, the label it is listed by)."""
        _cleared(self._rows)
        self._boxes = []
        for obj, label in planes:
            setting = obj.clip_plane
            box = QCheckBox(label)
            box.setChecked(detail.id not in setting.get("off_in", ()))
            box.toggled.connect(lambda on, i=obj.id: self._switch(i, on))
            self._rows.addWidget(box)
            self._boxes.append((obj.id, box))

    def planes(self) -> list:
        return [(box.text(), box.isChecked()) for _i, box in self._boxes]

    def set_plane(self, plane_id: str, on: bool):
        for i, box in self._boxes:
            if i == plane_id:
                box.setChecked(on)


class _PairTable(QTableWidget):
    """Keys and values, a column of each.

    Delete and Backspace take the picked pairs away. Without this they
    would fall through to the window, whose Delete deletes the object the
    pairs belong to.
    """

    removeRequested = Signal()

    _REMOVE = (Qt.Key.Key_Delete, Qt.Key.Key_Backspace)
    _BARE = (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.KeypadModifier)

    def event(self, ev):
        if (ev.type() == QEvent.Type.ShortcutOverride
                and ev.key() in self._REMOVE and ev.modifiers() in self._BARE):
            ev.accept()
            return True
        return super().event(ev)

    def keyPressEvent(self, ev):
        if ev.key() in self._REMOVE and ev.modifiers() in self._BARE:
            self.removeRequested.emit()
            ev.accept()
            return
        super().keyPressEvent(ev)

    def sizeHint(self):
        """As tall as it is allowed to be: every pair, up to a point."""
        return QSize(super().sizeHint().width(), self.maximumHeight())


# The key a row of the user text stands for, as the object spells it; None
# on a row still being typed in, which the object does not hold yet.
_HELD_KEY = Qt.ItemDataRole.UserRole
# How many pairs show before the table scrolls instead of growing, and how
# few it shrinks to in a short dock before the dock has to give way.
_USER_TEXT_ROWS = 8
_USER_TEXT_MIN_ROWS = 2
# The key column fits its keys between these widths, wide enough to type a
# new one into; the value has the rest.
_KEY_WIDTHS = (72, 120)


class _UserText(QWidget):
    """A model object's user text, Rhino's Attribute User Text: a table of
    keys and values to edit in place, under a line with Add and Remove.

    The whole width of the page, not the field column: a value is the long
    half, and the column beside the labels cut most of them off.

    `edit(label, text)` is told the object's whole new text, None for none,
    and `label` names the undo step. A pair being added belongs to the table
    until both halves are in: Rhino has no way to keep a key with no value.
    """

    def __init__(self, edit):
        super().__init__()
        self._edit = edit
        self._shown = None          # (object id, its text) as last filled
        self._text = None
        self._filling = False
        self.caption = QLabel("User text")
        self.caption.setToolTip(
            "Keys and values this object carries, which Rhino calls "
            "Attribute User Text; a .3dm brings them in and takes them "
            "back out")
        self.none_label = QLabel("None")
        self.none_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        self.table = _PairTable(0, 2)
        self.table.setHorizontalHeaderLabels(["Key", "Value"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setMinimumSectionSize(_KEY_WIDTHS[0])
        header.setMaximumSectionSize(_KEY_WIDTHS[1])
        header.setStretchLastSection(True)
        header.setHighlightSections(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(
            theme.LIST_ROW_HEIGHT)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setWordWrap(False)
        self.table.itemChanged.connect(self._changed)
        self.table.itemSelectionChanged.connect(self._picked)
        self.table.removeRequested.connect(self.remove_selected)
        self.add_link = _link("Add")
        self.add_link.setToolTip("Add a key and its value")
        self.add_link.clicked.connect(self.add)
        self.remove_link = _link("Remove")
        self.remove_link.setToolTip("Take the picked keys away")
        self.remove_link.clicked.connect(self.remove_selected)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(12)
        top.addWidget(self.caption)
        top.addWidget(self.none_label)
        top.addStretch(1)
        top.addWidget(self.add_link)
        top.addWidget(self.remove_link)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 4, 0, 0)
        column.setSpacing(6)
        column.addLayout(top)
        column.addWidget(self.table)
        self._fill(None)

    def show_for(self, obj):
        """Show this object's text, unless it is what is shown already: a
        refresh for some other reason must not lose a pair being typed."""
        shown = None if obj is None else (obj.id, obj.user_text)
        if shown == self._shown:
            return
        self._shown = shown
        self._text = None if obj is None else obj.user_text
        self._fill(self._text)

    def pairs(self) -> list:
        """What the table shows, row by row."""
        return [(self.table.item(r, 0).text(), self.table.item(r, 1).text())
                for r in range(self.table.rowCount())]

    def add(self):
        """A new row, its key ready to type."""
        row = self._append("", "", None)
        self._fit()
        key = self.table.item(row, 0)
        self.table.setCurrentItem(key)
        self.table.editItem(key)

    def remove_selected(self):
        rows = {i.row() for i in self.table.selectionModel().selectedRows()}
        if not rows and self.table.currentRow() >= 0:
            rows = {self.table.currentRow()}
        if not rows:
            return
        text = self._text
        for row in rows:
            held = self.table.item(row, 0).data(_HELD_KEY)
            if held is not None:
                text = ut.with_value(text, held, "")
        self._commit("remove user text", text)

    # -- filling

    def _fill(self, text):
        self._filling = True
        try:
            self.table.setRowCount(0)
            for key, value in (text or {}).items():
                self._append(key, value, key)
        finally:
            self._filling = False
        self._fit()

    def _append(self, key: str, value: str, held) -> int:
        was, self._filling = self._filling, True
        row = self.table.rowCount()
        self.table.insertRow(row)
        key_item, value_item = QTableWidgetItem(key), QTableWidgetItem(value)
        key_item.setData(_HELD_KEY, held)
        # a long value is cut off in a narrow dock; hovering reads it whole
        key_item.setToolTip(key)
        value_item.setToolTip(value)
        self.table.setItem(row, 0, key_item)
        self.table.setItem(row, 1, value_item)
        self._filling = was
        return row

    def _fit(self):
        """Tall enough for every pair, up to a point, and there only when
        there is a pair to show. A short dock squeezes it to two rows and a
        scroll bar rather than push Add off the bottom, or Layers out."""
        rows = self.table.rowCount()
        self.none_label.setVisible(rows == 0)
        self.table.setVisible(rows > 0)
        self.remove_link.setVisible(rows > 0)
        frame = (self.table.horizontalHeader().sizeHint().height()
                 + 2 * self.table.frameWidth())
        row = self.table.verticalHeader().defaultSectionSize()
        self.table.setMinimumHeight(
            frame + row * min(rows, _USER_TEXT_MIN_ROWS))
        self.table.setMaximumHeight(frame + row * min(rows, _USER_TEXT_ROWS))
        self.table.updateGeometry()
        self._picked()

    def _picked(self):
        self.remove_link.setEnabled(
            bool(self.table.selectionModel().selectedRows()))

    # -- editing

    def _changed(self, item):
        if self._filling:
            return
        row = item.row()
        key_item, value_item = self.table.item(row, 0), self.table.item(row, 1)
        if key_item is None or value_item is None:
            return
        change = (row, item.column(), key_item.data(_HELD_KEY),
                  key_item.text().strip(), value_item.text())
        # Once the table has finished with the item: the edit refills the
        # table, which would free the item under the call telling us of it.
        QTimer.singleShot(0, self, lambda: self._apply(*change))

    def _apply(self, row, column, held, key, value):
        text = self._text
        if held is None:                            # a pair being added
            if key and value:
                self._commit("user text", ut.with_value(text, key, value))
            elif (key and column == 0 and self.table.state()
                    != QAbstractItemView.State.EditingState):
                cell = self.table.item(row, 1)      # on to its value
                if cell is not None:
                    self.table.editItem(cell)
            return
        if column == 0:                             # a key renamed
            if key == held:
                return
            try:
                self._commit("rename user text", ut.renamed(text, held, key))
            except (KeyError, ValueError):
                self._fill(text)                    # put back what it was
            return
        if value != ut.value_of(text, held):        # a value changed
            self._commit("user text" if value else "remove user text",
                         ut.with_value(text, held, value))

    def _commit(self, label: str, text):
        before = self._shown
        self._edit(label, text)
        if self._shown == before:
            # Nothing changed, so nothing refilled the table: put back what
            # the object holds rather than leave a typed row that is not.
            self._fill(self._text)


def _show_common_text(combo, values):
    """An editable drop-down showing the one value shared, or blank."""
    combo.setEditText(next(iter(values)) if len(values) == 1 else "")


class SubjectHeader(QWidget):
    """The top of every Properties page: a mark and the kind of thing in
    gold capitals, then its name, then one muted line of what and where.
    Whatever a page shows, it opens by saying what that is."""

    def __init__(self, empty_title: str = "", empty_detail: str = ""):
        super().__init__()
        self._empty = (empty_title, empty_detail)
        self.mark = QLabel()
        self.kind = QLabel()
        # The design system's app section label: monospace, capitals,
        # tracked 1.5 px. Family and size go in the style sheet, which would
        # override them from setFont; capitals and tracking it leaves alone.
        # The family is one really installed: "monospace" names no font on
        # Windows, where the label drew in the proportional default.
        mono = theme.mono_family()
        font = QFont(mono)
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPixelSize(11)
        font.setCapitalization(QFont.Capitalization.AllUppercase)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
        self.kind.setFont(font)
        self.kind.setStyleSheet(f'color: {theme.ACCENT}; font-family: '
                                f'"{mono}"; font-size: 11px;')
        self._kind_row = QWidget()
        row = QHBoxLayout(self._kind_row)
        row.setContentsMargins(_INSET, 8, _INSET, 0)
        row.setSpacing(6)
        row.addWidget(self.mark)
        row.addWidget(self.kind)
        row.addStretch(1)
        self.title = QLabel()
        # wraps rather than widening the dock for a long name
        self.title.setWordWrap(True)
        self.detail = QLabel()
        self.detail.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; padding: 0 {_INSET}px 4px;")
        self.detail.setWordWrap(True)
        # A styled label indents its text half an x past its padding
        # unless told not to, which put the name out of line with the rows.
        for label in (self.title, self.detail):
            label.setIndent(0)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self._kind_row)
        column.addWidget(self.title)
        column.addWidget(self.detail)
        self.show_subject(None)

    def show_subject(self, subject: Subject | None):
        """Say what the page shows, or, with nothing, what to do about it."""
        # With no kind line above it, the name keeps that line's gap. Set in
        # the style sheet: setContentsMargins on a styled label replaces its
        # padding, sides and all, and the name slid out of line.
        self.title.setStyleSheet(
            "font-weight: 600; font-size: 14px; padding: %dpx %dpx 0;"
            % (8 if subject is None else 4, _INSET))
        if subject is None:
            self._kind_row.hide()
            self.title.setText(self._empty[0])
            self.detail.setText(self._empty[1])
            self.detail.setVisible(bool(self._empty[1]))
            return
        self._kind_row.show()
        self.mark.setPixmap(subject.mark.pixmap(14, 14))
        self.kind.setText(subject.kind)
        self.title.setText(subject.title)
        self.detail.setText(subject.detail)
        self.detail.setVisible(bool(subject.detail))


class PropertiesPanel(QWidget):
    # How long a selection has to sit still before its exact volume and area
    # are worked out. Long enough that clicking through a drawing measures
    # none of what you pass over, short enough that resting on something
    # feels like it answered at once.
    measure_delay_ms = 150

    modelTextChanged = Signal(str, str)
    textTypographyChanged = Signal(str, object)
    textPlacementChanged = Signal(str)
    lookAtTextRequested = Signal()
    # What is live, or which of it is shown, may have changed: the title bar
    # redraws its tabs from subjects() and shown().
    subjectsChanged = Signal()
    # Load or Delete patterns… was picked in a pattern list: the
    # hatchpatterns action to run (#92)
    hatchPatternsRequested = Signal(str)

    def __init__(self, scene, selection, history, parent=None,
                 viewport_source=None, panes_source=None):
        super().__init__(parent)
        self.scene = scene
        self.selection = selection
        self.history = history
        # What is picked on a sheet is held by the layout view of whichever
        # pane is showing it, so the panel has to be able to go and ask.
        self._viewport_source = viewport_source
        # The window's model panes, (view key, title), which a clipping
        # plane lists among the views it cuts
        self._panes_source = panes_source
        self._updating = False
        # {object id: (scene revision, what it measured)}. Exact mass
        # properties cost between 86 and 486 ms on one solid of an ordinary
        # NURBS model, and the same object used to pay it on every click.
        self._measured: dict = {}
        self._measure_timer = QTimer(self)
        self._measure_timer.setSingleShot(True)
        self._measure_timer.timeout.connect(self._measure_settled)
        self._measuring: tuple | None = None      # (object id, revision)
        self._live_text_id = None
        self._text_checkpoint_id = None
        self._text_edit_selection_id = None
        self._model_text_command_active = False

        # The page opens like every page here: kind, name, what and where.
        # `header` is its name line, which older callers read by that name.
        self.object_head = SubjectHeader(
            empty_title="No selection",
            empty_detail="Select objects, or pick a layer in Layers.")
        self.header = self.object_head.title

        self.name_edit = QLineEdit()
        self.name_edit.editingFinished.connect(self._rename)

        self.layer_combo = QComboBox()
        self.layer_combo.currentIndexChanged.connect(self._change_layer)

        from PySide6.QtWidgets import QHBoxLayout
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

        # a model object's own print width and section hatch, or its layer's
        self.print_width_combo = QComboBox()
        self.print_width_combo.setEditable(True)
        self.print_width_combo.setInsertPolicy(
            QComboBox.InsertPolicy.NoInsert)
        self.print_width_combo.addItems([_BY_LAYER, "Default", *PRINT_WIDTHS])
        self.print_width_combo.setToolTip(
            "Pen width this object plots with, in millimetres: By layer "
            "takes its layer's, Default leaves it to the printer")
        self.print_width_combo.textActivated.connect(self._change_print_width)
        self.print_width_combo.lineEdit().editingFinished.connect(
            self._change_print_width)
        self.faceted_box = QCheckBox("Flat triangles, every edge shown")
        self.faceted_box.setToolTip(
            "Draw this mesh as flat triangles with all their edges, as a "
            "terrain is drawn; off, it is shaded smooth across its gentler "
            "folds, as a scan is")
        self.faceted_box.toggled.connect(self._change_faceted)
        self.section_hatch = QComboBox()
        self.section_hatch.addItem(_BY_LAYER, "bylayer")
        _fill_patterns(self.section_hatch, SECTION_FILLS, keep=1)
        self.section_hatch.setToolTip(
            "What a section cut through this object is filled with: By "
            "layer takes its layer's, anything else is its own, starting "
            "from the layer's angle, spacing and colour")
        self.section_hatch.currentIndexChanged.connect(
            self._change_section_hatch)
        self.section_look = _HatchLook(self._set_object_look, self.refresh)

        # paper geometry only: a dash pattern and a printed width, both of
        # which the sheet reads straight off the object
        self.linetype_combo = QComboBox()
        self.linetype_combo.addItems(list(LINETYPES))
        self.linetype_combo.currentIndexChanged.connect(self._change_linetype)
        self.lineweight_edit = QLineEdit()
        self.lineweight_edit.setToolTip("Printed width in millimetres")
        self.lineweight_edit.editingFinished.connect(self._change_lineweight)

        # a detail only: its scale, picked from the presets or typed, and
        # read by the same rules as the `detailscale` command. Picking
        # applies at once; typing applies on Enter, so the half-typed "1:1"
        # on the way to "1:100" is never taken for a choice. The presets
        # are the document's units' (`_show_scale`).
        self.scale_combo = QComboBox()
        self.scale_combo.setEditable(True)
        self.scale_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.scale_combo.addItems(scale_presets(self.scene.units))
        self.scale_combo.setToolTip("Detail scale, e.g. 1:50")
        self.scale_combo.currentTextChanged.connect(self._scale_chosen)
        self.scale_combo.lineEdit().editingFinished.connect(self._scale_typed)

        self.detail_view_combo = QComboBox()
        self.detail_view_combo.addItems(
            ["Custom", "Top", "Front", "Right", "Left", "Back", "Bottom",
             "Perspective"])
        self.detail_view_combo.model().item(0).setEnabled(False)
        self.detail_view_combo.setToolTip("View shown inside the selected detail")
        self.detail_view_combo.currentTextChanged.connect(self._change_detail_view)

        self.measure_label = QLabel("—")
        self.measure_label.setWordWrap(True)

        self.form = form = QFormLayout()
        form.setContentsMargins(_INSET, 8, _INSET, _INSET)
        form.setSpacing(6)
        form.addRow("Name", self.name_edit)
        form.addRow("Layer", self.layer_combo)
        form.addRow("Colour", self.color_widget)
        form.addRow("Print width (mm)", self.print_width_combo)
        form.addRow("Faceted", self.faceted_box)
        form.addRow("Section hatch", self.section_hatch)
        self.section_look.add_rows(form)
        form.addRow("Linetype", self.linetype_combo)
        form.addRow("Lineweight", self.lineweight_edit)
        form.addRow("View", self.detail_view_combo)
        form.addRow("Scale", self.scale_combo)
        # a detail only: the layers it leaves out (#38)
        self.detail_layers = _DetailLayers(self._set_detail_layers)
        form.addRow("Hidden here", self.detail_layers)
        # a detail's clipping planes, and a clipping plane's views
        self.detail_clips = _DetailClips(self._set_detail_clip)
        form.addRow("Clipped by", self.detail_clips)
        self.clip_views = _ClipViews(self._set_clip_view, self._pause_clip)
        form.addRow("Cuts", self.clip_views)
        form.addRow("Info", self.measure_label)
        self.text_content = QPlainTextEdit()
        self.text_content.setObjectName("text_content")
        self.text_content.setPlaceholderText("Type text…")
        self.text_content.setMinimumHeight(90)
        self.text_content.textChanged.connect(self._change_text_content)
        form.addRow("Content", self.text_content)

        self.text_font_family = QFontComboBox()
        self.text_font_family.setObjectName("text_font_family")
        self.text_font_family.currentFontChanged.connect(
            self._text_family_changed)
        form.addRow("Font family", self.text_font_family)
        self.text_font_style = QComboBox()
        self.text_font_style.setObjectName("text_font_style")
        self.text_font_style.currentIndexChanged.connect(
            self._change_text_typography)
        form.addRow("Font style", self.text_font_style)
        self.text_height = QDoubleSpinBox()
        self.text_height.setObjectName("text_height")
        self.text_height.setDecimals(3)
        self.text_height.setRange(.001, 1e9)
        self.text_height.setToolTip(
            "Height of a capital letter, measured on its plane")
        self.text_height.valueChanged.connect(self._change_text_typography)
        form.addRow("Cap height", self.text_height)
        self.text_alignment = QComboBox()
        self.text_alignment.setObjectName("text_alignment")
        for label in ("Left", "Center", "Right"):
            self.text_alignment.addItem(label, label.lower())
        self.text_alignment.currentIndexChanged.connect(
            self._change_text_typography)
        form.addRow("Alignment", self.text_alignment)

        self.text_output = QComboBox()
        self.text_output.setObjectName("text_output")
        self.text_output.addItem("Editable text", "editable")
        self.text_output.addItem("Curves", "curves")
        self.text_output.addItem("Planar surfaces", "surface")
        self.text_output.addItem("Solid", "solid")
        self.text_output.setToolTip(
            "Keep the lettering editable, or choose curves, surfaces or a "
            "solid and press the Convert button that appears")
        self.text_output.currentIndexChanged.connect(
            self._update_text_output_controls)
        form.addRow("Output", self.text_output)
        self.text_group_output = QCheckBox("Group contours")
        self.text_group_output.setObjectName("text_group_output")
        self.text_group_output.setChecked(True)
        self.text_group_output.setToolTip(
            "Select and move the separate letter contours together")
        form.addRow("", self.text_group_output)
        self.text_solid_depth = QDoubleSpinBox()
        self.text_solid_depth.setObjectName("text_solid_depth")
        self.text_solid_depth.setDecimals(3)
        self.text_solid_depth.setRange(.001, 1e9)
        self.text_solid_depth.setValue(1.)
        self.text_solid_depth.setSuffix(" " + self.scene.units)
        self.text_solid_depth.setToolTip(
            "Extrusion depth along the text-plane normal")
        form.addRow("Depth", self.text_solid_depth)
        self.text_convert = QPushButton("Convert to geometry")
        self.text_convert.setObjectName("text_convert")
        self.text_convert.clicked.connect(self._convert_text_output)
        form.addRow(self.text_convert)

        self.text_placement_plane = QComboBox()
        self.text_placement_plane.setObjectName("text_placement_plane")
        self.text_placement_plane.addItems(
            ["CPlane", "Selected face", "View plane"])
        self.text_placement_plane.setToolTip(
            "Plane on which model lettering is placed")
        self.text_placement_plane.currentTextChanged.connect(
            self.textPlacementChanged)
        form.addRow("Placement", self.text_placement_plane)
        self.look_at_text = QPushButton("Look at text")
        self.look_at_text.setObjectName("look_at_text")
        self.look_at_text.setToolTip(
            "Turn the camera square to the text plane so it reads upright "
            "(Zoom Selected keeps the current angle); click again to "
            "restore the view")
        self.look_at_text.clicked.connect(self.lookAtTextRequested)
        form.addRow(self.look_at_text)

        # A hatch in the model is edited here after it is placed (#33): its
        # region stays, and pattern, spacing and angle redraw it in place.
        self.hatch_pattern = QComboBox()
        self.hatch_pattern.setObjectName("hatch_pattern")
        from ..core.layout import HATCH_PATTERNS
        _fill_patterns(self.hatch_pattern, HATCH_PATTERNS)
        self.hatch_pattern.currentIndexChanged.connect(self._change_hatch)
        form.addRow("Pattern", self.hatch_pattern)
        self.hatch_spacing = QDoubleSpinBox()
        self.hatch_spacing.setObjectName("hatch_spacing")
        self.hatch_spacing.setDecimals(4)
        self.hatch_spacing.setRange(1e-4, 1e9)
        self.hatch_spacing.setToolTip("Distance between the pattern's lines")
        self.hatch_spacing.valueChanged.connect(self._change_hatch)
        form.addRow("Spacing", self.hatch_spacing)
        self.hatch_angle = QDoubleSpinBox()
        self.hatch_angle.setObjectName("hatch_angle")
        self.hatch_angle.setDecimals(2)
        self.hatch_angle.setRange(-360.0, 360.0)
        self.hatch_angle.setSuffix("°")
        self.hatch_angle.setToolTip(
            "Angle of the lines, from the x axis of the plane it was drawn on")
        self.hatch_angle.valueChanged.connect(self._change_hatch)
        form.addRow("Angle", self.hatch_angle)
        # Its colour and background: its layer's hatch colour and
        # background unless it says otherwise (#91).
        self._hatch_ink = _TokenColour(
            lambda token: self._set_hatch_style("color", token),
            self._show_hatch, "Hatch colour",
            "The colour the hatch's lines are drawn in: By layer is its "
            "layer's hatch colour",
            first=((_BY_LAYER, _BY_LAYER_TOKEN, None),
                   ("Ink", HATCH_INK, _INK_SWATCH)))
        self.hatch_color = self._hatch_ink.combo
        self.hatch_color.setObjectName("hatch_color")
        form.addRow("Hatch colour", self.hatch_color)
        self._hatch_ground = _TokenColour(
            lambda token: self._set_hatch_style("background", token),
            self._show_hatch, "Hatch background",
            "What the hatch shows under its lines: By layer is its layer's "
            "hatch background, None leaves it bare",
            first=((_BY_LAYER, _BY_LAYER_TOKEN, None),
                   ("None", HATCH_BACKGROUND_NONE, None)))
        self.hatch_background = self._hatch_ground.combo
        self.hatch_background.setObjectName("hatch_background")
        form.addRow("Hatch background", self.hatch_background)
        self._hatch_checkpoint_id = None

        # The keys and values a model object carries, Rhino's Attribute User
        # Text: what a .3dm brings in and takes back out, edited here the way
        # Rhino's own panel edits it. Last, so it pushes no editor down.
        self.user_text = _UserText(self._set_user_text)
        form.addRow(self.user_text)

        self.object_page = QWidget()
        page = QVBoxLayout(self.object_page)
        page.setContentsMargins(0, 0, 0, 0)
        page.setSpacing(0)
        page.addWidget(self.object_head)
        page.addSpacing(6)
        page.addWidget(_seam())
        page.addLayout(form)
        page.addStretch(1)
        self._build_layer_page()
        self._build_sheet_page()
        self.pages = QStackedWidget()
        self.pages.addWidget(self.object_page)
        self.pages.addWidget(self.layer_page)
        self.pages.addWidget(self.sheet_page)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.pages)

        # Which subject the user last chose to see, "objects" or "layers";
        # shown() falls back to whatever is live when it is not.
        self._layers_panel = None
        self._sheets_panel = None
        self._chosen = "objects"
        self._picks_seen = self._objects_signature()
        self._letting_go = False

        selection.add_listener(self.refresh)
        scene.add_listener(self.refresh, kinds=("objects", "layers",
                                                "layouts"))
        self.refresh()

    # -------------------------------------------------------- what is picked

    def _selected(self):
        objs = self.selection.objects()
        return objs[0] if len(objs) == 1 else None

    def _sheet_picks(self, kind: str) -> list:
        """What is picked on the sheet of one kind: "object" or "detail".

        A sheet's selection lives in the layout view rather than in the
        model-space selection the rest of this panel reads, which is why a
        picked border used to leave the panel saying "No selection".
        """
        src = self._viewport_source
        vp = src() if src is not None else None
        if vp is None or getattr(vp, "space", "model") == "model":
            return []
        lay = vp.layout_view.layout
        # Only what is on the sheet now: an undo swaps the whole sheet for a
        # clone, and a panel still offering to edit the thing that used to
        # be there would be editing something nothing draws.
        on_sheet = () if lay is None else {
            "object": lay.objects, "detail": lay.details, "note": lay.notes}[kind]
        return [o for k, o in vp.layout_view.selected
                if k == kind and any(x is o for x in on_sheet)]

    def _paper_picks(self) -> list:
        """The paper geometry picked on the sheet."""
        return self._sheet_picks("object")

    def _detail_pick(self) -> DetailView | None:
        """The one detail picked on the sheet, or the one you are inside
        with nothing picked, or None: the scale row, like every other row
        here, edits a single thing."""
        picks = self._sheet_picks("detail")
        if picks:
            return picks[0] if len(picks) == 1 else None
        return self._detail_here()

    def _detail_here(self) -> DetailView | None:
        """The detail the pane is inside, while nothing in the model is
        picked: what you are looking through is what there is to show, as
        Rhino's Properties show an active detail (#93). Once something is
        picked inside it, that is what the panel is about."""
        src = self._viewport_source
        vp = src() if src is not None else None
        if (vp is None or getattr(vp, "space", "model") == "model"
                or self.selection.ids or self.selection.subobjects):
            return None
        return vp.layout_view._entered()

    def _current(self) -> tuple:
        """What the editors here act on: (object, on_paper).

        None when nothing or more than one thing is picked — every row on this
        panel edits a single object, on paper as in the model.
        """
        papers = self._paper_picks()
        if papers:
            return (papers[0] if len(papers) == 1 else None), True
        return self._selected(), False

    # --------------------------------------------------------------- showing

    def refresh(self):
        self._let_go_if_moved_on()
        self._updating = True
        papers = self._paper_picks()
        detail = self._detail_pick()
        notes = self._sheet_picks("note")
        self._show_rows(paper=bool(papers), detail=detail is not None)
        if notes:
            self._blank_editors()
            self.form.setRowVisible(self.layer_combo, False)
            if len(notes) == 1:
                self.measure_label.setText(notes[0].text)
        elif papers:
            self._refresh_paper(papers)
        elif detail is not None:
            self._refresh_detail(detail)
        else:
            self._refresh_model()
        if detail is not None:
            self._show_scale(detail)
            self._show_detail_view(detail)
            self._show_detail_layers(detail)
            self._show_detail_clips(detail)
        self._show_hatch()
        editable = self._editable_text()
        editable_id = editable.id if editable is not None else None
        selection_changed = editable_id != self._text_edit_selection_id
        if selection_changed:
            self._text_checkpoint_id = None
            self._text_edit_selection_id = editable_id
        model_text = (editable if editable is not None
                      and not isinstance(editable, TextNote) else None)
        self.form.setRowVisible(self.text_content, editable is not None)
        self.text_content.setEnabled(editable is not None)
        if editable is not None:
            text = (editable.text if isinstance(editable, TextNote)
                    else editable.shape.text)
            if self.text_content.toPlainText() != text:
                self.text_content.setPlainText(text)
        self._show_text_typography(editable)
        tools_visible = (self._model_text_command_active
                         or model_text is not None)
        if (selection_changed and model_text is not None
                and not self._model_text_command_active):
            blocker = QSignalBlocker(self.text_output)
            self.text_output.setCurrentIndex(
                self.text_output.findData("editable"))
            del blocker
            self.text_group_output.setChecked(True)
        self.form.setRowVisible(self.text_output, tools_visible)
        self.text_output.setEnabled(tools_visible)
        self._update_text_output_controls(model_text=model_text)
        self.form.setRowVisible(self.text_placement_plane, tools_visible)
        self.text_placement_plane.setEnabled(tools_visible)
        self.form.setRowVisible(self.look_at_text, model_text is not None)
        self.look_at_text.setEnabled(model_text is not None)
        self.object_head.show_subject(self.describe("objects"))
        self._updating = False
        self._sync_subject()

    # ------------------------------------------------------------- subjects

    def follow_layers(self, panel):
        """Show the layers picked in this Layers panel as well."""
        self._layers_panel = panel
        panel.pickedChanged.connect(self._layers_picked)
        self._sync_subject()

    def follow_sheets(self, panel):
        """Show the sheets picked in this Sheets list as well (#38)."""
        self._sheets_panel = panel
        panel.pickedChanged.connect(self._sheets_picked)
        self._sync_subject()

    def subjects(self) -> list[str]:
        """What could be shown, in tab order: "objects" while anything is
        selected (in the model or on a sheet) or a detail is being looked
        through, then "layers" or "sheets", whichever is picked in its
        list: one look at a time."""
        out = []
        # the detail you are inside counts, but is not a pick: going in
        # is no reason to let go of a layer you were looking at
        if any(self._objects_signature()) or self._detail_here() is not None:
            out.append("objects")
        if self._picked_layers():
            out.append("layers")
        elif self._picked_sheets():
            out.append("sheets")
        return out

    def shown(self) -> str | None:
        """The subject on show: the one last chosen while it is live, else
        whichever is."""
        live = self.subjects()
        if self._chosen in live:
            return self._chosen
        return live[-1] if live else None

    def show_subject(self, subject: str):
        """Show the objects or the layers, which is what a tab does."""
        self._chosen = subject
        self._sync_subject()

    def describe(self, subject: str) -> Subject | None:
        """What a subject is, said once for both its page's header and its
        tab, so the two cannot disagree: "objects" (whatever is selected,
        in the model or on a sheet) or "layers". None when there is none.

        A new kind of thing for Properties to show (a sheet, say) gets a
        page and a description here; its header and its tab follow.
        """
        if subject == "layers":
            return self._describe_layers()
        if subject == "sheets":
            return self._describe_sheets()
        return self._describe_selection()

    def _describe_selection(self) -> Subject | None:
        """In the order refresh() chooses its page: notes, then paper
        geometry, then details, then the model. Nothing here measures or
        converts anything, since it runs on every change of selection."""
        mark = icons.selection_mark()

        def said(kind, title, detail, tab=None):
            tab = tab or title
            return Subject(kind, title, detail, mark, tab,
                           f"The selection: {tab}")

        notes = self._sheet_picks("note")
        if notes:
            n = len(notes)
            if n == 1:
                first = next((line.strip() for line
                              in notes[0].text.splitlines() if line.strip()),
                             "")
                return said("Text note", _clip(first) or "Empty note",
                            "Text on paper")
            return said("Text notes", f"{n} notes selected", "Text on paper",
                        f"{n} notes")
        papers = self._paper_picks()
        if papers:
            # said out loud, because a curve on the paper and a curve in the
            # model look the same and are not the same thing at all
            kinds = [kind_label(g.shape_kind(o.shape)) for o in papers]
            n = len(papers)
            if n == 1:
                return said("Object", papers[0].name, f"{kinds[0]} on paper")
            return said("Objects", f"{n} objects selected",
                        f"{_kinds_text(kinds)} on paper", f"{n} objects")
        details = self._sheet_picks("detail")
        here = None if details else self._detail_here()
        if here is not None:
            details = [here]
        if details:
            n = len(details)
            if n == 1:
                detail = details[0]
                frame = ("frame "
                         + format_paper_size(detail.w, detail.h, self.scene.units))
                line = (frame if detail.perspective else
                        f"{detail.scale_text(self.scene.units)} · {frame}")
                return said("Detail", f"{self._detail_view_name(detail)} view",
                            _capital(line), "Detail")
            return said("Details", f"{n} details selected", "On paper",
                        f"{n} details")
        objs = self.selection.objects()
        if not objs:
            return None
        on = {o.layer_id for o in objs}
        where = (f"on {self.scene.layers.get(next(iter(on))).name}"
                 if len(on) == 1 else f"on {len(on)} layers")
        n = len(objs)
        if n == 1:
            obj = objs[0]
            kind = ("Editable text" if isinstance(obj.shape, TextShape)
                    else kind_label(obj.kind))
            return said("Object", obj.name, f"{kind} {where}")
        kinds = [kind_label(o.kind) for o in objs]
        return said("Objects", f"{n} objects selected",
                    f"{_kinds_text(kinds)} {where}", f"{n} objects")

    def _describe_layers(self) -> Subject | None:
        """Counted as what is on the layer, in words the selection tab's
        "3 objects" cannot be mistaken for."""
        layers = self._picked_layers()
        if not layers:
            return None
        count = self._count_on({la.id for la in layers})
        if len(layers) == 1:
            layer = layers[0]
            path = self.scene.layers.full_path(layer.id).split(PATH_SEPARATOR)
            where = " › ".join(path) + " · " if len(path) > 1 else ""
            return Subject("Layer", layer.name,
                           where + _on_count(count, "this layer"),
                           icons.layer_mark(layer.color), layer.name,
                           f"Layer: {layer.name}")
        names = ", ".join(la.name for la in layers)
        title = f"{len(layers)} layers"
        return Subject("Layers", title,
                       f"{names} · " + _on_count(count, "these layers"),
                       icons.layer_mark(_MIXED_MARK), title,
                       f"Layers: {names}")

    def _describe_sheets(self) -> Subject | None:
        sheets = self._picked_sheets()
        if not sheets:
            return None
        if len(sheets) == 1:
            lay = sheets[0]
            n = len(lay.details)
            parts = [_paper_name(lay.paper_w, lay.paper_h, self.scene.units),
                     "no details" if n == 0 else
                     f"{n} detail{'s' if n != 1 else ''}"]
            path = self._group_path(lay.group)
            if path:
                parts.append(f"in {path}")
            label = sheet_label(lay)
            return Subject("Sheet", label, " · ".join(parts),
                           icons.sheet_mark(), label, f"Sheet: {label}")
        title = f"{len(sheets)} sheets"
        names = ", ".join(sheet_label(lay) for lay in sheets)
        return Subject("Sheets", title, names, icons.sheet_mark(), title,
                       f"Sheets: {names}")

    def _group_path(self, group_id) -> str:
        """Plans › Level 1, for a group; "" for none."""
        by_id = {gr.id: gr for gr in self.scene.sheet_groups}
        names, seen = [], set()
        while group_id in by_id and group_id not in seen:
            seen.add(group_id)
            names.append(by_id[group_id].name)
            group_id = by_id[group_id].parent
        return " › ".join(reversed(names))

    def _picked_sheets(self) -> list:
        """The picked sheets in the set's order, the ones that still exist."""
        if self._sheets_panel is None:
            return []
        ids = set(self._sheets_panel.picked_sheet_ids())
        return [lay for lay in self.scene.layouts if lay.id in ids]

    def _sheets_picked(self):
        """A sheet picked is a look, as a layer is, and one at a time."""
        if self._picked_sheets():
            self._chosen = "sheets"
            if self._layers_panel is not None and self._picked_layers():
                self._layers_panel.clear_picked()
        elif self._chosen == "sheets":
            self._chosen = "objects"
        self._sync_subject()

    def _count_on(self, layer_ids: set) -> int:
        return sum(1 for o in self.scene.all() if o.layer_id in layer_ids)

    def _picked_layers(self) -> list:
        """The picked layers in list order, the ones that still exist."""
        if self._layers_panel is None:
            return []
        ids = self._layers_panel.picked_layer_ids()
        return [la for la in self.scene.layers.all() if la.id in ids]

    def _objects_signature(self) -> tuple:
        """What the object page would show, as something to compare."""
        sheet = tuple(id(o) for kind in ("object", "detail", "note")
                      for o in self._sheet_picks(kind))
        return (tuple(self.selection.ids), sheet)

    def _layers_picked(self):
        """Rows picked are what you asked to see; none picked hands the
        panel back to the objects. One look at a time: a layer picked lets
        go of a picked sheet."""
        if self._picked_layers():
            self._chosen = "layers"
            if self._sheets_panel is not None and self._picked_sheets():
                self._sheets_panel.clear_picked()
        elif self._chosen == "layers":
            self._chosen = "objects"
        self._sync_subject()

    def _let_go_if_moved_on(self):
        """Selecting other objects is moving on from the layer: let go of
        it, so its tab does not hang about. Clearing the selection is not,
        nor is a command handing back the selection it was given."""
        seen, self._picks_seen = self._picks_seen, self._objects_signature()
        if (self._picks_seen == seen or not any(self._picks_seen)
                or self._letting_go
                or not (self._picked_layers() or self._picked_sheets())):
            return
        self._letting_go = True
        try:
            self._chosen = "objects"
            for panel in (self._layers_panel, self._sheets_panel):
                if panel is not None:
                    panel.clear_picked()
        finally:
            self._letting_go = False

    def _sync_subject(self):
        """Show the page for the subject on show, then hold the selection
        while it is not the one being edited. Holding tells the selection's
        listeners, this panel among them, so it comes last."""
        shown = self.shown()
        if shown == "layers":
            self._refresh_layer_page()
            self.pages.setCurrentWidget(self.layer_page)
        elif shown == "sheets":
            self._refresh_sheet_page()
            self.pages.setCurrentWidget(self.sheet_page)
        else:
            self.pages.setCurrentWidget(self.object_page)
        self.subjectsChanged.emit()
        # Only while the panel can be seen: with Properties closed nothing
        # on screen says why the selection went dim.
        self.selection.set_held(
            shown in ("layers", "sheets") and bool(self.selection.ids)
            and self.isVisible())

    def showEvent(self, ev):
        super().showEvent(ev)
        self._sync_subject()

    def hideEvent(self, ev):
        super().hideEvent(ev)
        if not ev.spontaneous():        # not for a minimised window
            self.selection.set_held(False)

    # ------------------------------------------------------------ sheet page

    def _build_sheet_page(self):
        """A sheet: its number and name, its paper and which group it is
        in, and links to open it and to print it."""
        self._sheet_updating = False
        self.sheet_page = QWidget()
        self.sheet_head = SubjectHeader()
        self.sheet_open = _link("Open sheet")
        self.sheet_open.setToolTip("Open the sheet to draw on it")
        self.sheet_open.clicked.connect(self._open_picked_sheet)
        self.sheet_print = _link("Print…")
        self.sheet_print.setToolTip("Print the picked sheets, or make a PDF")
        self.sheet_print.clicked.connect(self._print_picked_sheets)
        acts = QHBoxLayout()
        acts.setContentsMargins(_INSET, 2, _INSET, 6)
        acts.setSpacing(16)
        acts.addWidget(self.sheet_open)
        acts.addWidget(self.sheet_print)
        acts.addStretch(1)

        self.sheet_number = QLineEdit()
        self.sheet_number.setPlaceholderText("A-101")
        self.sheet_number.setToolTip("The sheet number, the way a set is "
                                     "referenced")
        self.sheet_number.editingFinished.connect(self._set_sheet_number)
        self.sheet_name = QLineEdit()
        self.sheet_name.editingFinished.connect(self._set_sheet_name)
        self.sheet_paper = QComboBox()
        self.sheet_paper.addItems(list(PAPER_SIZES))
        self.sheet_paper.currentTextChanged.connect(self._set_sheet_paper)
        self.sheet_orientation = QComboBox()
        self.sheet_orientation.addItems(["Landscape", "Portrait"])
        self.sheet_orientation.currentTextChanged.connect(
            self._set_sheet_orientation)
        self.sheet_group = QComboBox()
        self.sheet_group.setToolTip("The group the sheet sits in, in the "
                                    "Sheets list")
        self.sheet_group.currentIndexChanged.connect(self._set_sheet_group)

        self.sheet_form = form = QFormLayout()
        form.setContentsMargins(_INSET, 8, _INSET, _INSET)
        form.setSpacing(6)
        form.addRow("Number", self.sheet_number)
        form.addRow("Name", self.sheet_name)
        form.addRow("Paper", self.sheet_paper)
        form.addRow("Orientation", self.sheet_orientation)
        form.addRow("Group", self.sheet_group)

        page = QVBoxLayout(self.sheet_page)
        page.setContentsMargins(0, 0, 0, 0)
        page.setSpacing(0)
        page.addWidget(self.sheet_head)
        page.addLayout(acts)
        page.addWidget(_seam())
        page.addLayout(form)
        page.addStretch(1)

    def _refresh_sheet_page(self):
        sheets = self._picked_sheets()
        if not sheets:
            return
        self._sheet_updating = True
        try:
            one = sheets[0] if len(sheets) == 1 else None
            self.sheet_head.show_subject(self.describe("sheets"))
            self.sheet_open.setVisible(one is not None)
            for edit, value in ((self.sheet_number, "number"),
                                (self.sheet_name, "name")):
                edit.setEnabled(one is not None)
                edit.setText(getattr(one, value) if one is not None else "")
            self.sheet_name.setPlaceholderText(
                "" if one is not None else f"{len(sheets)} sheets")
            papers = {_paper_and_turn(lay)[0] for lay in sheets}
            turns = {_paper_and_turn(lay)[1] for lay in sheets}
            paper = next(iter(papers)) if len(papers) == 1 else None
            self.sheet_paper.setCurrentIndex(
                self.sheet_paper.findText(paper) if paper else -1)
            turn = next(iter(turns)) if len(turns) == 1 else None
            self.sheet_orientation.setCurrentIndex(
                self.sheet_orientation.findText(turn) if turn else -1)
            combo = self.sheet_group
            combo.clear()
            combo.addItem("None", None)
            for group in self.scene.sheet_groups:
                combo.addItem(self._group_path(group.id), group.id)
            groups = {lay.group for lay in sheets}
            combo.setCurrentIndex(combo.findData(next(iter(groups)))
                                  if len(groups) == 1 else -1)
        finally:
            self._sheet_updating = False

    def _edit_sheets(self, label: str, apply):
        """One undo step for a change to every picked sheet."""
        if self._sheet_updating:
            return
        sheets = self._picked_sheets()
        if not sheets:
            return
        self.history.checkpoint(label)
        for lay in sheets:
            apply(lay)
        self.scene.notify("layouts")

    def _set_sheet_number(self):
        sheets = self._picked_sheets()
        text = self.sheet_number.text().strip()
        if len(sheets) == 1 and text != sheets[0].number:
            self._edit_sheets("sheet number",
                              lambda lay: setattr(lay, "number", text))

    def _set_sheet_name(self):
        sheets = self._picked_sheets()
        text = self.sheet_name.text().strip()
        if len(sheets) == 1 and text and text != sheets[0].name:
            self._edit_sheets("rename sheet",
                              lambda lay: setattr(lay, "name", text))

    def _set_sheet_paper(self, name: str):
        if name not in PAPER_SIZES:
            return

        def apply(lay):
            w, h = PAPER_SIZES[name]
            if _paper_and_turn(lay)[1] == "Portrait":
                w, h = h, w
            lay.paper_w, lay.paper_h = float(w), float(h)
        self._edit_sheets("sheet paper", apply)

    def _set_sheet_orientation(self, turn: str):
        if turn not in ("Landscape", "Portrait"):
            return

        def apply(lay):
            long_side = max(lay.paper_w, lay.paper_h)
            short_side = min(lay.paper_w, lay.paper_h)
            lay.paper_w, lay.paper_h = ((long_side, short_side)
                                        if turn == "Landscape"
                                        else (short_side, long_side))
        self._edit_sheets("sheet orientation", apply)

    def _set_sheet_group(self, index: int):
        if index < 0 or self._sheet_updating:
            return
        group = self.sheet_group.itemData(index)
        if {lay.group for lay in self._picked_sheets()} == {group}:
            return
        self._edit_sheets("sheet group",
                          lambda lay: setattr(lay, "group", group))

    def _open_picked_sheet(self):
        sheets = self._picked_sheets()
        if len(sheets) == 1 and self._sheets_panel is not None:
            self._sheets_panel.openRequested.emit(sheets[0].id)

    def _print_picked_sheets(self):
        sheets = self._picked_sheets()
        if sheets and self._sheets_panel is not None:
            self._sheets_panel.printRequested.emit([s.id for s in sheets])

    def _show_detail_layers(self, detail):
        self.form.setRowVisible(self.detail_layers, True)
        self.detail_layers.show_for(detail, self.scene.layers)

    def _set_detail_layers(self, hidden: list):
        detail = self._detail_pick()
        if detail is not None and list(detail.hidden_layers) != hidden:
            self._paper_edit("detail layers", detail,
                             hidden_layers=list(hidden))

    def _show_detail_clips(self, detail):
        """The clipping planes there are, hidden ones too since they cut as
        well, ticked where they cut this detail; no row when there are
        none."""
        planes = clipping.planes_of(self.scene)
        self.form.setRowVisible(self.detail_clips, bool(planes))
        if planes:
            self.detail_clips.show_for(
                detail, [(o, clipping.label(self.scene, o)) for o in planes])

    def _set_detail_clip(self, plane_id: str, on: bool):
        detail = self._detail_pick()
        if detail is not None:
            clipping.switch(self.scene, plane_id, detail.id, on,
                            before=self._clip_checkpoint)

    def _clip_checkpoint(self):
        self.history.checkpoint("clipping plane views")

    def _show_clip_views(self, obj):
        """A clipping plane's views, ticked where it cuts them."""
        shown = bool(obj.clip_plane)
        self.form.setRowVisible(self.clip_views, shown)
        if shown:
            panes = self._panes_source() if self._panes_source else []
            self.clip_views.show_for(obj, panes, self.scene.layouts,
                                     self._detail_view_name,
                                     self.scene.units)

    def _set_clip_view(self, view: str, on: bool):
        obj = self._selected()
        if obj is not None and obj.clip_plane:
            clipping.switch(self.scene, obj.id, view, on,
                            before=self._clip_checkpoint)

    def _pause_clip(self, paused: bool):
        obj = self._selected()
        if obj is None or not obj.clip_plane \
                or bool(obj.clip_plane.get("enabled")) != paused:
            return
        self.history.checkpoint("pause clipping plane" if paused
                                else "resume clipping plane")
        self.scene.update(obj.id, clip_plane={**obj.clip_plane,
                                              "enabled": not paused})

    # ------------------------------------------------------------ layer page

    def _build_layer_page(self):
        """A layer's look, a row per thing with its unit in the label: the
        Layers list keeps only the switches, so nothing here has to be a
        narrow cell whose meaning lives in a column header."""
        self._layer_updating = False
        self.layer_page = QWidget()
        self.layer_head = SubjectHeader()

        self.layer_select = _link("Select objects")
        self.layer_select.setToolTip("Select everything on the picked layers")
        self.layer_select.clicked.connect(self._select_layer_objects)
        self.layer_move_here = _link()
        self.layer_move_here.setToolTip(
            "Move the selected objects onto this layer")
        self.layer_move_here.clicked.connect(self._move_selection_here)
        acts = QHBoxLayout()
        acts.setContentsMargins(_INSET, 2, _INSET, 6)
        acts.setSpacing(16)
        acts.addWidget(self.layer_select)
        acts.addWidget(self.layer_move_here)
        acts.addStretch(1)

        self.layer_name = QLineEdit()
        self.layer_name.editingFinished.connect(self._rename_layer)
        self.layer_color = QPushButton()
        self.layer_color.setFixedSize(40, 22)
        self.layer_color.setToolTip("Layer colour")
        self.layer_color.clicked.connect(self._pick_layer_color)
        self.layer_linetype = QComboBox()
        self.layer_linetype.addItems(list(LINETYPES))
        self.layer_linetype.currentIndexChanged.connect(self._set_layer_linetype)
        self.layer_screen = QComboBox()
        self.layer_screen.setEditable(True)
        self.layer_screen.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.layer_screen.addItems([FROM_PRINT, *SCREEN_WIDTHS])
        self.layer_screen.setToolTip(
            "How thick the layer's lines are drawn on screen, in pixels. "
            "From print works it out from the print width; a number of "
            "your own stays put")
        self.layer_screen.textActivated.connect(self._set_layer_screen)
        self.layer_screen.lineEdit().editingFinished.connect(
            self._set_layer_screen)
        self.layer_print = QComboBox()
        self.layer_print.setEditable(True)
        self.layer_print.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.layer_print.addItems(["Default", *PRINT_WIDTHS])
        self.layer_print.setToolTip(
            "Pen width on a printed sheet, in millimetres; Default leaves it "
            "to the printer")
        self.layer_print.textActivated.connect(self._set_layer_print)
        self.layer_print.lineEdit().editingFinished.connect(
            self._set_layer_print)
        self.layer_hatch = QComboBox()
        _fill_patterns(self.layer_hatch, SECTION_FILLS)
        self.layer_hatch.setToolTip(
            "What a section cut through this layer's objects is filled with, "
            "and what a hatch drawn on it starts out as")
        self.layer_hatch.currentIndexChanged.connect(self._set_layer_hatch)
        self.layer_look = _HatchLook(self._set_layer_look,
                                     self._refresh_layer_page)
        # the rows by the names the page has always had for them
        self.layer_hatch_angle = self.layer_look.angle
        self.layer_hatch_spacing = self.layer_look.spacing
        self.layer_hatch_color = self.layer_look.color
        self.layer_hatch_background = self.layer_look.background
        self.layer_cut_width = self.layer_look.cut_width
        self.layer_cut_color = self.layer_look.cut_color
        self.layer_visible = QCheckBox("Visible")
        self.layer_visible.clicked.connect(lambda: self._layer_switch(
            self.layer_visible, "layer visibility",
            self.scene.layers.set_visible))
        self.layer_locked = QCheckBox("Locked")
        self.layer_locked.clicked.connect(lambda: self._layer_switch(
            self.layer_locked, "layer lock", self.scene.layers.set_locked))
        state = QHBoxLayout()
        state.setContentsMargins(0, 0, 0, 0)
        state.addWidget(self.layer_visible)
        state.addWidget(self.layer_locked)
        state.addStretch(1)
        state_widget = QWidget()
        state_widget.setLayout(state)

        self.layer_form = form = QFormLayout()
        form.setContentsMargins(_INSET, 8, _INSET, _INSET)
        form.setSpacing(6)
        form.addRow("Name", self.layer_name)
        form.addRow("Colour", self.layer_color)
        form.addRow("Linetype", self.layer_linetype)
        form.addRow("Screen width (px)", self.layer_screen)
        form.addRow("Print width (mm)", self.layer_print)
        form.addRow("Section hatch", self.layer_hatch)
        self.layer_look.add_rows(form)
        form.addRow("", state_widget)

        page = QVBoxLayout(self.layer_page)
        page.setContentsMargins(0, 0, 0, 0)
        page.setSpacing(0)
        page.addWidget(self.layer_head)
        page.addLayout(acts)
        page.addWidget(_seam())
        page.addLayout(form)
        page.addStretch(1)

    def _refresh_layer_page(self):
        layers = self._picked_layers()
        if not layers:
            return
        self._layer_updating = True
        try:
            one = layers[0] if len(layers) == 1 else None
            self.layer_head.show_subject(self.describe("layers"))
            self.layer_select.setVisible(
                bool(self._count_on({la.id for la in layers})))
            moving = self._movable_here()
            self.layer_move_here.setVisible(bool(moving))
            if moving:
                n = len(moving)
                self.layer_move_here.setText(
                    f"Move {n} selected here" if n > 1 else "Move selected here")

            self.layer_name.setEnabled(one is not None)
            self.layer_name.setText(one.name if one is not None else "")
            self.layer_name.setPlaceholderText(
                "" if one is not None else f"{len(layers)} layers")
            colors = {la.color for la in layers}
            if len(colors) == 1:
                (color,) = colors
                self.layer_color.setStyleSheet(
                    "QPushButton { background: rgb(%d,%d,%d); border: 1px "
                    "solid #55565e; }" % tuple(int(c * 255) for c in color))
            else:
                self.layer_color.setStyleSheet("")
            self._show_common(self.layer_linetype,
                              {la.linetype for la in layers})
            self._show_common_text(self.layer_screen,
                                   {_screen_text(la) for la in layers})
            self._show_common_text(self.layer_print,
                                   {"Default" if la.print_width == 0
                                    else _width_text(la.print_width)
                                    for la in layers})
            hatches = {la.hatch for la in layers}
            _fill_patterns(self.layer_hatch,
                           _with(section_fills_of(self.scene), hatches))
            self.layer_hatch.setCurrentIndex(
                self.layer_hatch.findData(next(iter(hatches)))
                if len(hatches) == 1 else -1)
            self.layer_look.show(
                [_Look(la.hatch, la.hatch_angle, la.hatch_spacing,
                       la.hatch_color, self.scene.layers.hatch_rgb(la.id),
                       la.cut_line_width, la.cut_line_color,
                       hatch_token_rgb(la.cut_line_color, la.color),
                       la.hatch_background,
                       hatch_token_rgb(la.hatch_background, la.color))
                 for la in layers],
                layers[0].color if len({la.color for la in layers}) == 1
                else _MIXED_MARK)
            self._show_check(self.layer_visible, {la.visible for la in layers})
            self._show_check(self.layer_locked, {la.locked for la in layers})
        finally:
            self._layer_updating = False

    @staticmethod
    def _show_common(combo, values):
        """The one value they share, or a blank for layers that differ."""
        combo.setCurrentIndex(
            combo.findText(next(iter(values))) if len(values) == 1 else -1)

    @staticmethod
    def _show_common_text(combo, values):
        _show_common_text(combo, values)

    @staticmethod
    def _show_check(box, values):
        box.setTristate(len(values) > 1)
        box.setCheckState(
            Qt.CheckState.PartiallyChecked if len(values) > 1
            else Qt.CheckState.Checked if values == {True}
            else Qt.CheckState.Unchecked)

    def _layer_switch(self, box, label: str, setter):
        """A click on Visible or Locked. On a mixed box it switches them
        all on and the box stops being mixed; it never goes back to mixed,
        which is not a state a layer can be put in."""
        on = box.checkState() != Qt.CheckState.Unchecked
        if box.isTristate():
            box.setTristate(False)
            on = True
        with QSignalBlocker(box):
            box.setChecked(on)
        self._edit_layers(label, lambda i: setter(i, on))

    def _edit_layers(self, label: str, apply):
        """One undo step for a change to every picked layer."""
        if self._layer_updating:
            return
        layers = self._picked_layers()
        if not layers:
            return
        self.history.checkpoint(label)
        with self.scene.batched():
            for layer in layers:
                apply(layer.id)
            self.scene.notify()

    def _rename_layer(self):
        text = self.layer_name.text().strip()
        layers = self._picked_layers()
        if len(layers) != 1 or not text or text == layers[0].name:
            return
        self._edit_layers("rename layer",
                          lambda i: self.scene.layers.rename(i, text))

    def _pick_layer_color(self):
        from PySide6.QtWidgets import QColorDialog
        layers = self._picked_layers()
        if not layers:
            return
        color = QColorDialog.getColor(
            QColor.fromRgbF(*layers[0].color), self, "Layer colour")
        if color.isValid():
            rgb = (color.redF(), color.greenF(), color.blueF())
            self._edit_layers("layer colour",
                              lambda i: self.scene.layers.set_color(i, rgb))

    def _set_layer_linetype(self, _index=None):
        name = self.layer_linetype.currentText()
        if name in LINETYPES:
            self._edit_layers("layer linetype",
                              lambda i: self.scene.layers.set_linetype(i, name))

    def _set_layer_screen(self, *_args):
        if self._layer_updating:
            return
        text = self.layer_screen.currentText().strip()
        layers = self._picked_layers()
        if text.lower().startswith(FROM_PRINT.lower()):
            if any(la.screen_pinned for la in layers):
                self._edit_layers("layer screen width",
                                  self.scene.layers.follow_print)
            return
        width = _parse_width(text)
        if width is None or width <= 0:
            self._refresh_layer_page()      # put back what the layer says
            return
        if all(la.screen_pinned and la.lineweight == width for la in layers):
            return
        self._edit_layers("layer screen width",
                          lambda i: self.scene.layers.set_lineweight(i, width))

    def _set_layer_print(self, *_args):
        if self._layer_updating:
            return
        text = self.layer_print.currentText().strip()
        width = 0.0 if text.lower() in ("", "default") else _parse_width(text)
        if width is None:
            self._refresh_layer_page()
            return
        if {la.print_width for la in self._picked_layers()} == {width}:
            return
        self._edit_layers("layer print width",
                          lambda i: self.scene.layers.set_print_width(i, width))

    def _set_layer_hatch(self, index):
        if index < 0:
            return
        pattern = self.layer_hatch.itemData(index)
        if pattern in _PATTERN_ACTIONS:
            self._refresh_layer_page()
            self._ask_patterns(pattern, self.layer_hatch)
            return
        self._edit_layers("layer hatch",
                          lambda i: self.scene.layers.set_hatch(i, pattern))

    def _set_layer_look(self, key: str, value):
        """An edit to the picked layers' hatch angle, spacing or colour, or
        to the width or colour of their cut line."""
        layers = self.scene.layers
        setter = {"angle": layers.set_hatch_angle,
                  "spacing": layers.set_hatch_spacing,
                  "color": layers.set_hatch_color,
                  "background": layers.set_hatch_background,
                  "cut_line_width": layers.set_cut_line_width,
                  "cut_line_color": layers.set_cut_line_color}[key]
        what = _LOOK_WORDS[key]
        self._edit_layers(f"layer {what}" if key.startswith("cut_line")
                          else f"layer hatch {what}",
                          lambda i: setter(i, value))

    def _movable_here(self) -> list[str]:
        """Selected objects not yet on the one picked layer."""
        layers = self._picked_layers()
        if len(layers) != 1:
            return []
        return [o.id for o in self.selection.objects()
                if o.layer_id != layers[0].id]

    def _move_selection_here(self):
        ids = self._movable_here()
        if not ids:
            return
        self.history.checkpoint("move to layer")
        self.scene.update_many(ids, layer_id=self._picked_layers()[0].id)
        self.scene.notify("layers")

    def _select_layer_objects(self):
        """Selecting them is moving on to them, so the objects are shown."""
        ids = {la.id for la in self._picked_layers()}
        self.selection.set([o.id for o in self.scene.selectable_objects()
                            if o.layer_id in ids])

    def _show_text_typography(self, editable):
        controls = (self.text_font_family, self.text_font_style,
                    self.text_height, self.text_alignment)
        visible = editable is not None
        for control in controls:
            self.form.setRowVisible(control, visible)
            control.setEnabled(visible)
        if not visible:
            return
        source = editable if isinstance(editable, TextNote) else editable.shape
        family = source.font_family
        if not family:
            from .text_editor import default_typography
            family = default_typography()["font_family"]
        self.text_font_family.setCurrentFont(QFont(family))
        self._populate_text_styles(family, source.font_style)
        unit, per = self._text_height_units(editable)
        self.text_height.setSuffix(" " + unit)
        # a step of one inch would take 1/8" text to 1 1/8"
        self.text_height.setSingleStep(0.01 if unit == "in" else 1.0)
        self.text_height.setValue(self._text_height_of(editable) / per)
        index = self.text_alignment.findData(source.alignment)
        self.text_alignment.setCurrentIndex(max(0, index))

    def _text_height_units(self, editable) -> tuple[str, float]:
        """The units the cap height box reads, and the millimetres in one
        of them for a note, which is kept in millimetres but read in the
        sheet's units; model lettering is in the document's."""
        if isinstance(editable, TextNote):
            unit = paper_units(self.scene.units)
            return unit, TO_MM[unit]
        return self.scene.units, 1.0

    def _text_height_of(self, editable) -> float:
        """The cap height `editable` is drawn at, a named style's if any."""
        if isinstance(editable, TextNote):
            from ..core.layout import note_text_height
            return note_text_height(editable, self.scene)
        return float(editable.shape.height)

    def _typed_text_height(self, editable) -> float:
        """The box's cap height, kept in the units the text is kept in.

        The box rounds what it shows, a 3.2 mm note reading 0.126" on an
        inch sheet, so while it still shows the height the text has, that
        height is kept exactly rather than 0.126" of it."""
        _unit, per = self._text_height_units(editable)
        current = self._text_height_of(editable)
        shown = round(current / per, self.text_height.decimals())
        if abs(self.text_height.value() - shown) < 1e-9:
            return current
        return self.text_height.value() * per

    def _populate_text_styles(self, family, preferred=""):
        blocker = QSignalBlocker(self.text_font_style)
        self.text_font_style.clear()
        styles = QFontDatabase.styles(family)
        self.text_font_style.addItems(styles)
        style = preferred if preferred in styles else next(
            (name for name in styles
             if name in ("Regular", "Book", "Normal")), "")
        index = self.text_font_style.findText(style)
        self.text_font_style.setCurrentIndex(index)
        del blocker

    def set_model_text_command_active(self, active: bool):
        """Show the model-lettering controls while TextObject is running."""
        active = bool(active)
        if active == self._model_text_command_active:
            return
        self._model_text_command_active = active
        if active:
            blocker = QSignalBlocker(self.text_output)
            self.text_output.setCurrentIndex(
                self.text_output.findData("editable"))
            del blocker
            self.text_group_output.setChecked(True)
        self.refresh()

    def model_text_output(self) -> dict:
        """Current non-modal output choices for a running text command."""
        return dict(output=self.text_output.currentData(),
                    group_output=self.text_group_output.isChecked(),
                    solid_depth=self.text_solid_depth.value())

    def _update_text_output_controls(self, *_args, model_text=None):
        output = self.text_output.currentData()
        selected = model_text
        if selected is None:
            candidate = self._editable_text()
            if candidate is not None and not isinstance(candidate, TextNote):
                selected = candidate
        tools_visible = self._model_text_command_active or selected is not None
        grouped = tools_visible and output in ("curves", "surface")
        solid = tools_visible and output == "solid"
        self.form.setRowVisible(self.text_group_output, grouped)
        self.text_group_output.setEnabled(grouped)
        self.form.setRowVisible(self.text_solid_depth, solid)
        self.text_solid_depth.setEnabled(solid)
        # The button only exists once there is something to convert *to*:
        # under "Editable text" a greyed "Convert to geometry" reads as a
        # broken control (issue #24), so it is hidden rather than disabled,
        # and when shown it names the output it will make.
        label = CONVERT_LABELS.get(output)
        can_convert = (selected is not None and label is not None
                       and self._live_text_id != selected.id)
        if label is not None:
            self.text_convert.setText(label)
        self.form.setRowVisible(self.text_convert, can_convert)
        self.text_convert.setEnabled(can_convert)

    def _convert_text_output(self):
        obj = self._editable_text()
        if obj is None or isinstance(obj, TextNote):
            return
        output = self.text_output.currentData()
        if output == "editable":
            return
        from ..core.text_object import output_shapes
        import uuid

        shapes = output_shapes(obj.shape, output,
                               self.text_solid_depth.value())
        self.history.checkpoint("convert text")
        group_id = (uuid.uuid4().hex if self.text_group_output.isChecked()
                    and output in ("curves", "surface") else None)
        with self.scene.batched():
            self.scene.remove(obj.id)
            made = [self.scene.add_from(shape, obj) for shape in shapes]
            if group_id:
                self.scene.update_many([item.id for item in made],
                                       group_id=group_id)
        self.selection.set([item.id for item in made])

    def _show_rows(self, paper: bool, detail: bool):
        """A layer belongs to the model; a lineweight belongs to the paper;
        a scale belongs to a detail.

        Paper geometry is not on a model layer — the sheet is its own ink — and
        a model object has no printed width to give, so each side is only asked
        what it can answer.
        """
        self.form.setRowVisible(self.layer_combo, not (paper or detail))
        self.form.setRowVisible(self.linetype_combo, paper)
        self.form.setRowVisible(self.lineweight_edit, paper)
        self.form.setRowVisible(self.scale_combo, detail)
        self.form.setRowVisible(self.detail_view_combo, detail)
        # one detail's own; refresh shows it again for a single detail
        self.form.setRowVisible(self.detail_layers, False)
        self.form.setRowVisible(self.detail_clips, False)
        self.form.setRowVisible(self.clip_views, False)
        # a model object's own, which _refresh_model shows when there is one
        self.form.setRowVisible(self.print_width_combo, False)
        self.form.setRowVisible(self.faceted_box, False)
        self.form.setRowVisible(self.section_hatch, False)
        self.form.setRowVisible(self.user_text, False)
        self.section_look.hide()
        self.color_reset.setText("By sheet" if paper else "By layer")
        self.color_reset.setToolTip(
            "Remove the override, use the sheet's ink" if paper
            else "Remove the override, use layer colour")

    def _refresh_model(self):
        obj = self._selected()

        self.layer_combo.clear()
        for layer in self.scene.layers.all():
            self.layer_combo.addItem(layer.name, layer.id)

        if obj is None:
            self._blank_editors()
            self.layer_combo.setEnabled(False)
            self.user_text.show_for(None)
        else:
            self.name_edit.setEnabled(True)
            self.name_edit.setText(obj.name)
            self.layer_combo.setEnabled(True)
            idx = self.layer_combo.findData(obj.layer_id)
            if idx >= 0:
                self.layer_combo.setCurrentIndex(idx)
            self.measure_label.setText(self._measures(obj))
            self.color_widget.setEnabled(True)
            self._show_swatch(self._ink_of(obj))
            self.color_reset.setEnabled(obj.color is not None)
            self._show_own_looks(obj)
            self._show_clip_views(obj)
            self.form.setRowVisible(self.user_text, True)
            self.user_text.show_for(obj)

    def _show_own_looks(self, obj):
        """A model object's print width and section hatch, its own or its
        layer's. Only something solid leaves a face where it is cut, and
        only what a hidden-line detail draws has a width to plot."""
        layer = self.scene.layers.get(obj.layer_id)
        plots = obj.kind not in ("point", "mesh", "pointcloud", "picture")
        self.form.setRowVisible(self.print_width_combo, plots)
        if plots:
            def text(width):
                return "Default" if width == 0 else _width_text(width)
            self.print_width_combo.setEditText(
                f"{_BY_LAYER} ({text(layer.print_width)})"
                if obj.print_width is None else text(obj.print_width))
        mesh = obj.kind == "mesh" and hasattr(obj.shape, "faceted")
        self.form.setRowVisible(self.faceted_box, mesh)
        if mesh:
            self.faceted_box.blockSignals(True)
            self.faceted_box.setChecked(obj.shape.faceted)
            self.faceted_box.blockSignals(False)
        cut = obj.kind in ("solid", "compound")
        self.form.setRowVisible(self.section_hatch, cut)
        own = obj.section_fill
        if not cut:
            self.section_look.hide()
            return
        _fill_patterns(self.section_hatch,
                       _with(section_fills_of(self.scene),
                             {own["pattern"]} if own else ()), keep=1)
        self.section_hatch.setItemText(
            0, f"{_BY_LAYER} ({pattern_label(layer.hatch)})")
        self.section_hatch.setCurrentIndex(
            0 if not own else self.section_hatch.findData(own["pattern"]))
        if own:
            fill = self.scene.section_fill_of(obj)
            self.section_look.show(
                [_Look(own["pattern"], own["angle"], own["spacing"],
                       own["color"], fill.color, fill.cut_line_width,
                       own.get("cut_line_color", HATCH_INK),
                       fill.cut_line_color,
                       own.get("background", HATCH_BACKGROUND_NONE),
                       fill.background)],
                layer.color)
        else:
            self.section_look.hide()

    def _set_user_text(self, label: str, text):
        """A change to the picked object's user text, as one undo step."""
        obj, paper = self._current()
        if obj is None or paper or text == obj.user_text:
            return
        self.history.checkpoint(label)
        self.scene.update(obj.id, user_text=text)

    def _change_faceted(self, on):
        """A mesh drawn flat with every edge, or smooth, as one undo step."""
        if self._updating:
            return
        obj, paper = self._current()
        if (obj is None or paper or obj.kind != "mesh"
                or obj.shape.faceted == bool(on)):
            return
        from ..core.mesh import MeshShape
        shape = obj.shape
        self.history.checkpoint("Faceted" if on else "Smooth")
        self.scene.replace_shape(obj.id, MeshShape(
            shape.vertices, shape.triangles, shape.normals, faceted=on))

    def _change_print_width(self, *_args):
        if self._updating:
            return
        obj, paper = self._current()
        if obj is None or paper:
            return
        text = self.print_width_combo.currentText().strip()
        said = text.lower()
        if said.startswith(_BY_LAYER.lower()) or said == "bylayer":
            width = None
        elif said == "default":
            width = 0.0
        else:
            width = _parse_width(text)
            if width is None:
                self.refresh()              # put back what it says
                return
        if width == obj.print_width:
            return
        self.history.checkpoint("object print width")
        self.scene.update(obj.id, print_width=width)

    def _change_section_hatch(self, index):
        if self._updating or index < 0:
            return
        obj, paper = self._current()
        if obj is None or paper:
            return
        choice = self.section_hatch.itemData(index)
        if choice in _PATTERN_ACTIONS:
            self.refresh()
            self._ask_patterns(choice, self.section_hatch)
            return
        own = obj.section_fill
        if choice == "bylayer":
            if own is None:
                return
            fill = None
        elif own is not None:
            if own["pattern"] == choice:
                return
            fill = dict(own, pattern=choice)
        else:
            layer = self.scene.layers.get(obj.layer_id)
            fill = section_fill_dict(choice, layer.hatch_angle,
                                     layer.hatch_spacing, layer.hatch_color,
                                     layer.cut_line_width,
                                     layer.cut_line_color,
                                     layer.hatch_background)
        self.history.checkpoint("object section hatch")
        self.scene.update(obj.id, section_fill=fill)

    def _ask_patterns(self, item: str, combo):
        """Load or Delete patterns… picked in a pattern list. A load
        remembers the list it was picked in, so the first pattern the file
        brings is what the layer, object or hatch is set to next."""
        action = _PATTERN_ACTIONS[item]
        self._pattern_combo = combo if action == "Load" else None
        self.hatchPatternsRequested.emit(action)

    def use_loaded_pattern(self, names):
        """Set the list Load patterns… was picked in to the first of the
        patterns that load brought, as if it had been picked there."""
        combo, self._pattern_combo = \
            getattr(self, "_pattern_combo", None), None
        if combo is None or not names:
            return
        if combo is self.layer_hatch:
            self._refresh_layer_page()
        else:
            self.refresh()
        if combo.isEnabled() and combo.findData(names[0]) >= 0:
            combo.setCurrentIndex(combo.findData(names[0]))

    def _set_object_look(self, key: str, value):
        """An edit to the hatch angle, spacing or colour of an object's own
        section style, or to the width or colour of its cut line."""
        obj, paper = self._current()
        if obj is None or paper or not obj.section_fill:
            return
        what = _LOOK_WORDS[key]
        self.history.checkpoint(f"object {what}" if key.startswith("cut_line")
                                else f"object hatch {what}")
        self.scene.update(obj.id, section_fill=section_fill_dict(
            **dict(obj.section_fill, **{key: value})))

    def _refresh_paper(self, papers: list):
        obj = papers[0] if len(papers) == 1 else None
        if obj is None:
            self._blank_editors()
            self.linetype_combo.setEnabled(False)
            # blank, not the last one's pattern: a greyed-out "Dashed" reads as
            # something these two have in common
            self.linetype_combo.setCurrentIndex(-1)
            self.lineweight_edit.setEnabled(False)
            self.lineweight_edit.setText("")
            return
        self.name_edit.setEnabled(True)
        self.name_edit.setText(obj.name)
        self.measure_label.setText(self._paper_measures(obj))
        self.color_widget.setEnabled(True)
        self._show_swatch(self._ink_of(obj))
        self.color_reset.setEnabled(obj.color is not None)
        self.linetype_combo.setEnabled(True)
        self.linetype_combo.setCurrentText(obj.linetype or "Continuous")
        self.lineweight_edit.setEnabled(True)
        self.lineweight_edit.setText(f"{obj.lineweight:g}")

    def _refresh_detail(self, detail: DetailView):
        """A detail has no name, layer or ink of its own; what it has is a
        frame on the sheet, in paper millimetres like `_paper_measures`, and
        the scale row below."""
        self._blank_editors()
        self.measure_label.setText(
            "Frame: " + format_paper_size(detail.w, detail.h, self.scene.units))

    def _show_scale(self, detail: DetailView):
        """Say what the detail's scale is: the list highlights it when it is a
        preset, the text says it either way. The list is the one the
        document's units are offered, which a change of units changes."""
        units = self.scene.units
        presets = list(scale_presets(units))
        if [self.scale_combo.itemText(i)
                for i in range(self.scale_combo.count())] != presets:
            # filling the list makes its first scale current, which is
            # not a choice anyone made
            with QSignalBlocker(self.scale_combo):
                self.scale_combo.clear()
                self.scale_combo.addItems(presets)
        text = detail.scale_text(units)
        self.scale_combo.setCurrentIndex(self.scale_combo.findText(text))
        self.scale_combo.setEditText(text)

    def _show_detail_view(self, detail: DetailView):
        self.detail_view_combo.setCurrentText(self._detail_view_name(detail))

    def _detail_view_name(self, detail: DetailView) -> str:
        """The standard view a detail looks along, or Custom."""
        for index in range(1, self.detail_view_combo.count()):
            candidate = self.detail_view_combo.itemText(index)
            azimuth, elevation = STANDARD_VIEWS[candidate.lower()]
            delta = (detail.azimuth - azimuth + pi) % (2 * pi) - pi
            if (detail.perspective == (candidate == "Perspective")
                    and isclose(delta, 0, abs_tol=1e-7)
                    and isclose(detail.elevation, elevation, abs_tol=1e-7)):
                return candidate
        return "Custom"

    def _change_detail_view(self, name: str):
        if self._updating or name == "Custom":
            return
        detail = self._detail_pick()
        if detail is None:
            return
        azimuth, elevation = STANDARD_VIEWS[name.lower()]
        perspective = name == "Perspective"
        fields = dict(azimuth=azimuth, elevation=elevation,
                      perspective=perspective)
        if all(getattr(detail, key) == value for key, value in fields.items()):
            return
        if perspective and not detail.perspective:
            bounds = self.scene.bbox()
            if bounds is not None:
                # Enclose the model about the existing target in a sphere,
                # then stand back beyond both the horizontal and vertical FOV.
                radius = max(dist(point, detail.target)
                             for point in product(*zip(*bounds)))
                aspect = max(detail.w, 1e-6) / max(detail.h, 1e-6)
                half_angle = atan(tan(pi / 8) * min(aspect, 1.0))
                fields["perspective_distance"] = max(
                    detail.perspective_distance, radius * 1.1 / sin(half_angle))
        self._paper_edit("detail view", detail, **fields)

    def _blank_editors(self):
        """Nothing to edit: emptied and greyed, not left saying what the last
        pick said."""
        self.name_edit.setText("")
        self.name_edit.setEnabled(False)
        self.color_widget.setEnabled(False)
        self.color_btn.setStyleSheet("")
        self.measure_label.setText("—")

    def _show_swatch(self, color):
        self.color_btn.setStyleSheet(
            "QPushButton { background: rgb(%d,%d,%d); border: 1px solid"
            " #55565e; }" % tuple(int(c * 255) for c in color))

    def _ink_of(self, obj) -> tuple:
        """The colour the swatch should show.

        With no override of its own, paper geometry falls back to the sheet's
        ink and a model object to its layer's.
        """
        if isinstance(obj, PaperObject):
            return tuple(obj.color) if obj.color else LINE_VISIBLE[:3]
        return self.scene.color_of(obj)

    # -------------------------------------------------------------- editing

    def begin_live_text(self, obj_id):
        self._live_text_id = obj_id

    def end_live_text(self, obj_id):
        if self._live_text_id == obj_id:
            self._live_text_id = None

    def _change_text_content(self):
        if self._updating:
            return
        obj = self._editable_text()
        if obj is None:
            return
        text = self.text_content.toPlainText()
        current = obj.text if isinstance(obj, TextNote) else obj.shape.text
        if text == current or not text.strip():
            return
        if (self._live_text_id != obj.id
                and self._text_checkpoint_id != obj.id):
            self.history.checkpoint("edit text")
            self._text_checkpoint_id = obj.id
        if isinstance(obj, TextNote):
            obj.text = text
            obj.style = ""
            self.scene.notify("layouts")
        else:
            self.scene.replace_shape(obj.id, obj.shape.edited(text=text))
        self.modelTextChanged.emit(obj.id, text)

    def _text_family_changed(self, font):
        if self._updating:
            return
        self._populate_text_styles(font.family(),
                                   self.text_font_style.currentText())
        self._change_text_typography()

    def _change_text_typography(self, *_):
        if self._updating:
            return
        obj = self._editable_text()
        if obj is None:
            return
        values = dict(
            font_family=self.text_font_family.currentFont().family(),
            font_style=self.text_font_style.currentText(),
            height=self._typed_text_height(obj),
            alignment=self.text_alignment.currentData(),
        )
        source = obj if isinstance(obj, TextNote) else obj.shape
        changed = any(getattr(source, name) != value
                      for name, value in values.items())
        if isinstance(obj, TextNote) and obj.style:
            changed = True
        if not changed:
            return
        if (self._live_text_id != obj.id
                and self._text_checkpoint_id != obj.id):
            self.history.checkpoint("edit text")
            self._text_checkpoint_id = obj.id
        if isinstance(obj, TextNote):
            for name, value in values.items():
                setattr(obj, name, value)
            obj.style = ""
            self.scene.notify("layouts")
        else:
            self.scene.replace_shape(obj.id, obj.shape.edited(**values))
        self.textTypographyChanged.emit(obj.id, values)

    def _editable_hatch(self):
        obj, paper = self._current()
        if obj is None or paper or getattr(obj, "kind", None) != "hatch":
            return None
        return obj

    def _show_hatch(self):
        """The hatch rows, for exactly one hatch in the model; spacing and
        angle only where there are lines to space and turn."""
        obj = self._editable_hatch()
        if obj is None or obj.id != self._hatch_checkpoint_id:
            self._hatch_checkpoint_id = None
        lines = obj is not None and not obj.shape.solid
        self.form.setRowVisible(self.hatch_pattern, obj is not None)
        self.form.setRowVisible(self.hatch_spacing, lines)
        self.form.setRowVisible(self.hatch_angle, lines)
        self.form.setRowVisible(self.hatch_color, obj is not None)
        self.form.setRowVisible(self.hatch_background, lines)
        if obj is None:
            return
        hatch = obj.shape
        own = obj.hatch_style or {}
        layer = self.scene.layers.get(obj.layer_id)
        color, ground = self.scene.hatch_look_of(obj)
        self._hatch_ink.show({own.get("color") or _BY_LAYER_TOKEN}, color,
                             layer.color)
        self._hatch_ground.show({own.get("background") or _BY_LAYER_TOKEN},
                                ground, layer.color)
        for widget, value in ((self.hatch_spacing, hatch.spacing),
                              (self.hatch_angle, hatch.angle)):
            with QSignalBlocker(widget):
                widget.setValue(value)
        _fill_patterns(self.hatch_pattern,
                       _with(hatch_patterns_of(self.scene), {hatch.pattern}))
        with QSignalBlocker(self.hatch_pattern):
            self.hatch_pattern.setCurrentIndex(
                self.hatch_pattern.findData(hatch.pattern))
        self.hatch_spacing.setSuffix(f" {self.scene.units}")

    def _set_hatch_style(self, key: str, token):
        """A hatch's own colour or background, or By layer again."""
        obj = self._editable_hatch()
        if obj is None:
            return
        style = dict(obj.hatch_style or {})
        if token == _BY_LAYER_TOKEN:
            style.pop(key, None)
        else:
            style[key] = token
        if style == (obj.hatch_style or {}):
            return
        self.history.checkpoint(f"hatch {_LOOK_WORDS[key]}")
        self.scene.update(obj.id, hatch_style=style or None)

    def _change_hatch(self, *_):
        if self._updating:
            return
        obj = self._editable_hatch()
        if obj is None:
            return
        values = dict(pattern=self.hatch_pattern.currentData(),
                      spacing=self.hatch_spacing.value(),
                      angle=self.hatch_angle.value())
        hatch = obj.shape
        if values["pattern"] in _PATTERN_ACTIONS:
            self._show_hatch()
            self._ask_patterns(values["pattern"], self.hatch_pattern)
            return
        # A pattern from a .pat file is drawn from its definition: the
        # drawing's, or the one the hatch carries from where it was made.
        values["definition"] = (hatch.definition
                                if values["pattern"] == hatch.pattern
                                else self.scene.hatch_pattern(
                                    values["pattern"]))
        if (values["pattern"], values["spacing"], values["angle"]) == \
                (hatch.pattern, hatch.spacing, hatch.angle):
            return
        try:
            edited = hatch.edited(**values)
        except g.GeometryError as exc:
            self.measure_label.setText(str(exc))
            return
        # one undo step for a run of edits to the same hatch, as for text
        if self._hatch_checkpoint_id != obj.id:
            self.history.checkpoint("edit hatch")
            self._hatch_checkpoint_id = obj.id
        self.scene.replace_shape(obj.id, edited)

    def _editable_text(self):
        notes = self._sheet_picks("note")
        if notes:
            return notes[0] if len(notes) == 1 else None
        obj, _paper = self._current()
        return obj if obj is not None and isinstance(obj.shape, TextShape) else None

    def _paper_edit(self, label: str, obj, **fields):
        """One undo step, then tell the scene its sheet changed.

        Fields are assigned rather than mutated because a checkpoint holds a
        shallow twin of this object (see `PaperObject.__deepcopy__`), and the
        notify is not optional: paper geometry is not in the scene's object
        table, so nothing else would notice it had been edited.
        """
        self.history.checkpoint(label)
        for key, value in fields.items():
            setattr(obj, key, value)
        self.scene.notify("layouts")

    def _pick_color(self):
        obj, _paper = self._current()
        if obj is None:
            return
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QColorDialog
        current = QColor.fromRgbF(*self._ink_of(obj))
        color = QColorDialog.getColor(current, self, "Object colour")
        if color.isValid():
            self._set_color((color.redF(), color.greenF(), color.blueF()))

    def _set_color(self, rgb):
        obj, paper = self._current()
        if obj is None:
            return
        if paper:
            self._paper_edit("object colour", obj, color=tuple(rgb))
        else:
            self.history.checkpoint("object colour")
            self.scene.update(obj.id, color=tuple(rgb))

    def _reset_color(self):
        obj, paper = self._current()
        if obj is None or obj.color is None:
            return
        if paper:
            self._paper_edit("object colour", obj, color=None)
        else:
            self.history.checkpoint("object colour")
            self.scene.update(obj.id, color=None)

    # Volume and area are integrated over the real NURBS geometry, which is
    # the one thing in this panel that can take longer than a frame. Asking
    # for it is what made clicking a solid feel slow, so it waits until the
    # selection has settled and is then remembered.
    _SLOW_KINDS = ("solid", "surface")

    def _measures(self, obj) -> str:
        """What to show on the Info row now, measuring later if need be."""
        revision = getattr(self.scene, "revision", 0)
        remembered = self._measured.get(obj.id)
        if remembered is not None and remembered[0] == revision:
            return remembered[1]
        if obj.kind in self._SLOW_KINDS:
            self._measuring = (obj.id, revision)
            self._measure_timer.start(max(0, int(self.measure_delay_ms)))
            # the row keeps the last thing it knew about this object rather
            # than going blank and coming back
            return remembered[1] if remembered is not None else "Measuring…"
        return self._remember(obj, revision)

    def _remember(self, obj, revision) -> str:
        text = self._measured_now(obj)
        if len(self._measured) > 512:
            self._measured.clear()
        self._measured[obj.id] = (revision, text)
        return text

    def _measure_settled(self):
        """The selection stopped moving, so it is worth the wait now."""
        pending, self._measuring = self._measuring, None
        if pending is None:
            return
        obj_id, revision = pending
        obj = self.scene.get(obj_id)
        if obj is None or getattr(self.scene, "revision", 0) != revision:
            return
        current = self._selected()
        if current is None or current.id != obj_id:
            return                       # you have picked something else
        self.measure_label.setText(self._remember(obj, revision))

    def _measured_now(self, obj) -> str:
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
            if obj.kind == "pointcloud":
                return cloud_measures(obj, fmt)
            if obj.kind == "hatch":
                return f"Area: {g.surface_area(obj.shape):.3f} {u}²"
        except Exception:
            pass
        return "—"

    def _paper_measures(self, obj) -> str:
        """In the sheet's units, not the model's: a border is 320 mm around on
        a sheet whether the model is drawn in metres or in millimetres, and
        12.6" in an inch or a feet document, as its sheet is read."""
        try:
            kind = g.shape_kind(obj.shape)
            units = self.scene.units
            if kind == "curve":
                length = g.curve_length(obj.shape)
                if paper_units(units) == "mm":
                    return f"Length: {length:.2f} mm"
                return f"Length: {format_paper_length(length, units)}"
            if kind in ("surface", "solid"):
                area = g.surface_area(obj.shape)
                unit = paper_units(units)
                return f"Area: {area / TO_MM[unit] ** 2:.2f} {unit}²"
        except Exception:
            pass
        return "—"

    def _rename(self):
        if self._updating:
            return
        obj, paper = self._current()
        name = self.name_edit.text().strip()
        if obj is None or not name or name == obj.name:
            return
        if paper:
            self._paper_edit("rename", obj, name=name)
        else:
            self.history.checkpoint("rename")
            self.scene.update(obj.id, name=name)

    def _change_layer(self):
        if self._updating:
            return
        obj, paper = self._current()
        if obj is None or paper:            # paper geometry has no layer
            return
        layer_id = self.layer_combo.currentData()
        if layer_id and layer_id != obj.layer_id:
            self.history.checkpoint("change layer")
            self.scene.update(obj.id, layer_id=layer_id)

    def _change_linetype(self):
        if self._updating:
            return
        obj, paper = self._current()
        if obj is None or not paper:
            return
        name = self.linetype_combo.currentText()
        if name and name != obj.linetype:
            self._paper_edit("linetype", obj, linetype=name)

    def _change_lineweight(self):
        if self._updating:
            return
        obj, paper = self._current()
        if obj is None or not paper:
            return
        try:
            mm = float(self.lineweight_edit.text())
        except ValueError:
            mm = 0.0
        if mm > 0.0 and mm != obj.lineweight:
            self._paper_edit("lineweight", obj, lineweight=mm)
        else:
            # nothing typed that is a width, or the width it already had: put
            # back what it still is rather than leaving the box lying
            self.refresh()

    def _scale_chosen(self, text: str):
        """A preset picked from the list, or set on the control outright."""
        if self._updating:
            return
        # the same signal fires for every keystroke: a preset the user is
        # typing through is not yet a choice, and neither is anything off the
        # list — Enter says when either is, and `_scale_typed` takes it then
        if (self.scale_combo.lineEdit().isModified()
                or self.scale_combo.findText(text) < 0):
            return
        self._set_scale(text)

    def _scale_typed(self):
        """A scale typed in and confirmed with Enter, preset or not."""
        if self._updating:
            return
        self._set_scale(self.scale_combo.currentText())

    def _set_scale(self, text: str):
        detail = self._detail_pick()
        if detail is None:
            return
        denom = parse_scale(text, self.scene.units)
        if denom is None or denom == detail.scale_denom:
            # not a scale, or the one it already has: put back what it still
            # is rather than leaving the box lying
            self.refresh()
            return
        self._paper_edit("detail scale", detail, scale_denom=denom)


def _plural(name: str) -> str:
    return name + ("es" if name.endswith(("s", "sh", "ch", "x")) else "s")


def _kinds_text(names: list[str]) -> str:
    """What a set of things is, by kind: "Solids", or "2 solids, 1 curve",
    the commonest first, and the rest summed after three kinds."""
    counts = Counter(names).most_common()
    if len(counts) == 1:
        return _plural(counts[0][0])
    parts = [f"{n} {(name if n == 1 else _plural(name)).lower()}"
             for name, n in counts[:3]]
    rest = sum(n for _name, n in counts[3:])
    if rest:
        parts.append(f"{rest} other" + ("" if rest == 1 else "s"))
    return ", ".join(parts)


def _on_count(n: int, these: str) -> str:
    if not n:
        return f"Nothing on {these} yet"
    return f"{n} object{'' if n == 1 else 's'} on {these}"


def _clip(text: str, limit: int = 48) -> str:
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _capital(text: str) -> str:
    return text[:1].upper() + text[1:]


def _width_text(width: float) -> str:
    """A width as the drop-downs write it: 1.4, 2, 0.25."""
    return f"{width:g}"


def _cut_width_text(width: float) -> str:
    """A cut line's width as its row shows it: None for no line at all."""
    return CUT_LINE_NONE if width <= 0 else _width_text(width)


def _screen_text(layer) -> str:
    """A layer's screen width as its row shows it, saying where a width
    that follows the print width came from."""
    width = _width_text(layer.lineweight)
    return width if layer.screen_pinned else f"{FROM_PRINT} ({width})"


def _parse_number(text: str, units=()):
    """A number typed into the layer page, with or without one of its
    units, or None for anything that is not one."""
    t = (text or "").strip().lower()
    for unit in units:
        t = t.removesuffix(unit).strip()
    try:
        return float(t)
    except ValueError:
        return None


def _parse_width(text: str):
    """A width typed into the layer page, with or without its unit, or None
    for anything that is not one."""
    t = (text or "").strip().lower()
    for unit in ("mm", "px"):
        t = t.removesuffix(unit).strip()
    try:
        width = float(t)
    except ValueError:
        return None
    return width if width >= 0 else None




class SubjectTitleBar(DockTitleBar):
    """The Properties dock's title, which becomes tabs once two things are
    live: the selection and the picked layers. Each tab carries a mark that
    says what it is: the selection's pointer in gold, and for a layer the
    Layers panel's own glyph in that layer's colour. A click shows that
    one. With one thing live it is the plain title it always was.
    """

    def __init__(self, props: PropertiesPanel, dock=None):
        super().__init__(icons.panel_icon("properties"), "Properties", dock)
        self._props = props
        self._live: list[str] = []
        self.tabs = QTabBar()
        self.tabs.setDrawBase(False)
        self.tabs.setExpanding(False)
        self.tabs.setElideMode(Qt.TextElideMode.ElideRight)
        self.tabs.setIconSize(QSize(14, 14))
        self.tabs.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tabs.currentChanged.connect(self._tab_chosen)
        self.tabs.hide()
        self.add_widget(self.tabs, 0, Qt.AlignmentFlag.AlignBottom)
        props.subjectsChanged.connect(self.refresh)
        self.refresh()

    def tab_texts(self) -> list[str]:
        return [self.tabs.tabText(i) for i in range(self.tabs.count())] \
            if self._live else []

    def refresh(self):
        live = self._props.subjects()
        self._live = live if len(live) > 1 else []
        self.title.setVisible(not self._live)
        self.tabs.setVisible(bool(self._live))
        if not self._live:
            return
        blocker = QSignalBlocker(self.tabs)
        while self.tabs.count() > len(self._live):
            self.tabs.removeTab(self.tabs.count() - 1)
        while self.tabs.count() < len(self._live):
            self.tabs.addTab("")
        for i, subject in enumerate(self._live):
            text, mark, tip = self._label(subject)
            self.tabs.setTabText(i, text)
            self.tabs.setTabIcon(i, mark)
            self.tabs.setTabToolTip(i, tip)
        self.tabs.setCurrentIndex(self._live.index(self._props.shown()))
        del blocker

    def _label(self, subject: str):
        """From the description the page's header is drawn from, so a tab
        and its page say the same thing."""
        said = self._props.describe(subject)
        if said is None:
            return "", QIcon(), ""
        return said.tab, said.mark, said.tip

    def _tab_chosen(self, index: int):
        if 0 <= index < len(self._live):
            self._props.show_subject(self._live[index])


def cloud_measures(obj, fmt) -> str:
    """What the panel says about a scan: how many points, how big a box
    they fill, and which of them are being drawn when not all are."""
    cloud = obj.shape
    (x0, y0, z0), (x1, y1, z1) = cloud.bbox()
    lines = [f"Points: {cloud.count:,}",
             f"Size: {fmt(x1 - x0)} × {fmt(y1 - y0)} × {fmt(z1 - z0)}"]
    counts = cloud.level_counts()
    if counts is not None:
        lines.append("Levels: " + ", ".join(
            f"{n:,} at {lvl}" for lvl, n in enumerate(counts) if n))
    if cloud.rgb is None:
        lines.append("No colour: drawn in the layer colour")
    return "\n".join(lines)
