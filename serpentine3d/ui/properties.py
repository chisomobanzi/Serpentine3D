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

from PySide6.QtCore import QSignalBlocker, QSize, QTimer, Signal, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFontComboBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QStackedWidget, QTabBar, QVBoxLayout, QWidget,
)

from ..core import geometry as g
from ..core.layers import PATH_SEPARATOR
from ..core.layout import (HATCH_PATTERNS, DetailView, PaperObject, TextNote,
                           parse_scale)
from ..core.text import TextShape
from ..core.linetype import LINETYPES
from . import icons, theme
from .dock_title import DockTitleBar
from .layout_view import LINE_VISIBLE
from .object_chooser import kind_label
from .camera import STANDARD_VIEWS

# What the layer page offers for its two widths. Typed values work too; these
# are the ones worth a click. Screen widths are pixels, print widths the
# standard pen sizes in millimetres, the same list the Layers panel offers.
SCREEN_WIDTHS = ("1", "1.4", "2", "3", "4")
PRINT_WIDTHS = ("0.13", "0.18", "0.25", "0.35", "0.5", "0.7", "1.0")

# the tab mark for more than one layer, which have no one colour between them
_MIXED_MARK = (0.6, 0.6, 0.62)

# the scales an architect draws at, smallest denominator first; anything else
# is typed in and read by the same rules as the `detailscale` command
SCALE_PRESETS = ["1:1", "1:2", "1:5", "1:10", "1:20", "1:50", "1:100", "1:200"]

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


class SubjectHeader(QWidget):
    """The top of every Properties page: a mark and the kind of thing in
    gold capitals, then its name, then one muted line of what and where.
    Whatever a page shows, it opens by saying what that is."""

    def __init__(self, empty_title: str = "", empty_detail: str = ""):
        super().__init__()
        self._empty = (empty_title, empty_detail)
        self.mark = QLabel()
        self.kind = QLabel()
        font = self.kind.font()
        font.setCapitalization(QFont.Capitalization.AllUppercase)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
        font.setPointSizeF(font.pointSizeF() * 0.85)
        self.kind.setFont(font)
        self.kind.setStyleSheet(f"color: {theme.ACCENT};")
        self._kind_row = QWidget()
        row = QHBoxLayout(self._kind_row)
        row.setContentsMargins(4, 6, 4, 0)
        row.setSpacing(5)
        row.addWidget(self.mark)
        row.addWidget(self.kind)
        row.addStretch(1)
        self.title = QLabel()
        # wraps rather than widening the dock for a long name
        self.title.setWordWrap(True)
        self.detail = QLabel()
        self.detail.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; padding: 0 4px 4px;")
        self.detail.setWordWrap(True)
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
        self.title.setStyleSheet("font-weight: bold; padding: %dpx 4px 0;"
                                 % (8 if subject is None else 2))
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

    def __init__(self, scene, selection, history, parent=None,
                 viewport_source=None):
        super().__init__(parent)
        self.scene = scene
        self.selection = selection
        self.history = history
        # What is picked on a sheet is held by the layout view of whichever
        # pane is showing it, so the panel has to be able to go and ask.
        self._viewport_source = viewport_source
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

        # paper geometry only: a dash pattern and a printed width, both of
        # which the sheet reads straight off the object
        self.linetype_combo = QComboBox()
        self.linetype_combo.addItems(list(LINETYPES))
        self.linetype_combo.currentIndexChanged.connect(self._change_linetype)
        self.lineweight_edit = QLineEdit()
        self.lineweight_edit.setToolTip("Printed width in millimetres")
        self.lineweight_edit.editingFinished.connect(self._change_lineweight)

        # a detail only: its scale, picked from the presets or typed. Picking
        # applies at once; typing applies on Enter, so the half-typed "1:1"
        # on the way to "1:100" is never taken for a choice.
        self.scale_combo = QComboBox()
        self.scale_combo.setEditable(True)
        self.scale_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.scale_combo.addItems(SCALE_PRESETS)
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
        form.setContentsMargins(8, 4, 8, 8)
        form.setSpacing(6)
        form.addRow("Name", self.name_edit)
        form.addRow("Layer", self.layer_combo)
        form.addRow("Colour", self.color_widget)
        form.addRow("Linetype", self.linetype_combo)
        form.addRow("Lineweight", self.lineweight_edit)
        form.addRow("View", self.detail_view_combo)
        form.addRow("Scale", self.scale_combo)
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
        for name in HATCH_PATTERNS:
            self.hatch_pattern.addItem(name.capitalize(), name)
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
        self._hatch_checkpoint_id = None

        self.object_page = QWidget()
        page = QVBoxLayout(self.object_page)
        page.setContentsMargins(0, 0, 0, 0)
        page.addWidget(self.object_head)
        page.addLayout(form)
        page.addStretch(1)
        self._build_layer_page()
        self.pages = QStackedWidget()
        self.pages.addWidget(self.object_page)
        self.pages.addWidget(self.layer_page)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.pages)

        # Which subject the user last chose to see, "objects" or "layers";
        # shown() falls back to whatever is live when it is not.
        self._layers_panel = None
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
        """The one detail picked on the sheet, or None: the scale row, like
        every other row here, edits a single thing."""
        picks = self._sheet_picks("detail")
        return picks[0] if len(picks) == 1 else None

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

    def subjects(self) -> list[str]:
        """What could be shown, in tab order: "objects" while anything is
        selected (in the model or on a sheet), "layers" while any are
        picked in the Layers list."""
        out = []
        if any(self._objects_signature()):
            out.append("objects")
        if self._picked_layers():
            out.append("layers")
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
        if details:
            n = len(details)
            if n == 1:
                detail = details[0]
                frame = f"frame {detail.w:g} × {detail.h:g} mm"
                line = (frame if detail.perspective
                        else f"{detail.scale_text()} · {frame}")
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
        panel back to the objects."""
        self._chosen = "layers" if self._picked_layers() else "objects"
        self._sync_subject()

    def _let_go_if_moved_on(self):
        """Selecting other objects is moving on from the layer: let go of
        it, so its tab does not hang about. Clearing the selection is not,
        nor is a command handing back the selection it was given."""
        seen, self._picks_seen = self._picks_seen, self._objects_signature()
        if (self._picks_seen == seen or not any(self._picks_seen)
                or self._letting_go or not self._picked_layers()):
            return
        self._letting_go = True
        try:
            self._chosen = "objects"
            self._layers_panel.clear_picked()
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
        else:
            self.pages.setCurrentWidget(self.object_page)
        self.subjectsChanged.emit()
        # Only while the panel can be seen: with Properties closed nothing
        # on screen says why the selection went dim.
        self.selection.set_held(
            shown == "layers" and bool(self.selection.ids)
            and self.isVisible())

    def showEvent(self, ev):
        super().showEvent(ev)
        self._sync_subject()

    def hideEvent(self, ev):
        super().hideEvent(ev)
        if not ev.spontaneous():        # not for a minimised window
            self.selection.set_held(False)

    # ------------------------------------------------------------ layer page

    def _build_layer_page(self):
        """A layer's look, a row per thing with its unit in the label: the
        Layers list keeps only the switches, so nothing here has to be a
        narrow cell whose meaning lives in a column header."""
        self._layer_updating = False
        self.layer_page = QWidget()
        self.layer_head = SubjectHeader()

        self.layer_select = QPushButton("Select objects")
        self.layer_select.setToolTip("Select everything on the picked layers")
        self.layer_select.clicked.connect(self._select_layer_objects)
        self.layer_move_here = QPushButton()
        self.layer_move_here.setToolTip(
            "Move the selected objects onto this layer")
        self.layer_move_here.clicked.connect(self._move_selection_here)
        acts = QHBoxLayout()
        acts.setContentsMargins(4, 0, 4, 4)
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
        self.layer_screen.addItems(SCREEN_WIDTHS)
        self.layer_screen.setToolTip(
            "How thick the layer's lines are drawn on screen, in pixels")
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
        self.layer_hatch.addItem("None", "")
        for name in HATCH_PATTERNS:
            self.layer_hatch.addItem(name.capitalize(), name)
        self.layer_hatch.setToolTip(
            "What a section cut through this layer's objects is filled with, "
            "and what a hatch drawn on it starts out as")
        self.layer_hatch.currentIndexChanged.connect(self._set_layer_hatch)
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
        form.setContentsMargins(8, 4, 8, 8)
        form.setSpacing(6)
        form.addRow("Name", self.layer_name)
        form.addRow("Colour", self.layer_color)
        form.addRow("Linetype", self.layer_linetype)
        form.addRow("Screen width (px)", self.layer_screen)
        form.addRow("Print width (mm)", self.layer_print)
        form.addRow("Section hatch", self.layer_hatch)
        form.addRow("", state_widget)

        page = QVBoxLayout(self.layer_page)
        page.setContentsMargins(0, 0, 0, 0)
        page.addWidget(self.layer_head)
        page.addLayout(acts)
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
                                   {_width_text(la.lineweight)
                                    for la in layers})
            self._show_common_text(self.layer_print,
                                   {"Default" if la.print_width == 0
                                    else _width_text(la.print_width)
                                    for la in layers})
            hatches = {la.hatch for la in layers}
            self.layer_hatch.setCurrentIndex(
                self.layer_hatch.findData(next(iter(hatches)))
                if len(hatches) == 1 else -1)
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
        combo.setEditText(next(iter(values)) if len(values) == 1 else "")

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
        width = _parse_width(self.layer_screen.currentText())
        if width is None or width <= 0:
            self._refresh_layer_page()      # put back what the layer says
            return
        if {la.lineweight for la in self._picked_layers()} == {width}:
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
        self._edit_layers("layer hatch",
                          lambda i: self.scene.layers.set_hatch(i, pattern))

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
        height = source.height
        if isinstance(editable, TextNote) and editable.style:
            from .annot_paint import style_of
            height = style_of(self.scene, editable.style)["text_height"]
        self.text_height.setSuffix(
            " mm" if isinstance(editable, TextNote)
            else " " + self.scene.units)
        self.text_height.setValue(float(height))
        index = self.text_alignment.findData(source.alignment)
        self.text_alignment.setCurrentIndex(max(0, index))

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
        self.measure_label.setText(f"Frame: {detail.w:g} × {detail.h:g} mm")

    def _show_scale(self, detail: DetailView):
        """Say what the detail's scale is: the list highlights it when it is a
        preset, the text says it either way."""
        text = detail.scale_text()
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
            height=self.text_height.value(),
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
        lines = obj is not None and obj.shape.pattern != "solid"
        self.form.setRowVisible(self.hatch_pattern, obj is not None)
        self.form.setRowVisible(self.hatch_spacing, lines)
        self.form.setRowVisible(self.hatch_angle, lines)
        if obj is None:
            return
        hatch = obj.shape
        for widget, value in ((self.hatch_spacing, hatch.spacing),
                              (self.hatch_angle, hatch.angle)):
            with QSignalBlocker(widget):
                widget.setValue(value)
        with QSignalBlocker(self.hatch_pattern):
            self.hatch_pattern.setCurrentIndex(
                self.hatch_pattern.findData(hatch.pattern))
        self.hatch_spacing.setSuffix(f" {self.scene.units}")

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
        """Millimetres of paper, not the document's units: a border is 320mm
        around on the sheet whether the model is drawn in metres or inches."""
        try:
            kind = g.shape_kind(obj.shape)
            if kind == "curve":
                return f"Length: {g.curve_length(obj.shape):.2f} mm"
            if kind in ("surface", "solid"):
                return f"Area: {g.surface_area(obj.shape):.2f} mm²"
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
        denom = parse_scale(text)
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
