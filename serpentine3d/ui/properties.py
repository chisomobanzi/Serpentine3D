"""Properties panel: shows and edits the selected object."""

from __future__ import annotations

from itertools import product
from math import atan, dist, isclose, pi, sin, tan

from PySide6.QtCore import QSignalBlocker, Signal, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFontComboBox, QFormLayout, QLabel,
    QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from ..core import geometry as g
from ..core.layout import DetailView, PaperObject, TextNote, parse_scale
from ..core.text import TextShape
from ..core.linetype import LINETYPES
from .layout_view import LINE_VISIBLE
from .camera import STANDARD_VIEWS

# the scales an architect draws at, smallest denominator first; anything else
# is typed in and read by the same rules as the `detailscale` command
SCALE_PRESETS = ["1:1", "1:2", "1:5", "1:10", "1:20", "1:50", "1:100", "1:200"]


class PropertiesPanel(QWidget):
    modelTextChanged = Signal(str, str)
    textTypographyChanged = Signal(str, object)
    textPlacementChanged = Signal(str)
    lookAtTextRequested = Signal()

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
        self._live_text_id = None
        self._text_checkpoint_id = None
        self._text_edit_selection_id = None
        self._model_text_command_active = False

        self.header = QLabel("No selection")
        self.header.setStyleSheet("font-weight: bold; padding: 4px;")

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

        self.kind_label = QLabel("—")
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
        form.addRow("Type", self.kind_label)
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
            "Face the selected text while editing; click again to restore")
        self.look_at_text.clicked.connect(self.lookAtTextRequested)
        form.addRow(self.look_at_text)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.header)
        layout.addLayout(form)
        layout.addStretch(1)

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
        self._updating = True
        papers = self._paper_picks()
        detail = self._detail_pick()
        notes = self._sheet_picks("note")
        self._show_rows(paper=bool(papers), detail=detail is not None)
        if notes:
            self._blank_editors()
            self.header.setText("Text note" if len(notes) == 1 else
                                f"{len(notes)} notes selected")
            self.kind_label.setText("Text on paper")
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
        if model_text is not None:
            self.kind_label.setText("Editable text")
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
        self._updating = False

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
        can_convert = (selected is not None and output != "editable"
                       and self._live_text_id != selected.id)
        self.form.setRowVisible(self.text_convert, selected is not None)
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
            self._blank_editors()
            self.layer_combo.setEnabled(False)
        else:
            self.header.setText(obj.name)
            self.name_edit.setEnabled(True)
            self.name_edit.setText(obj.name)
            self.layer_combo.setEnabled(True)
            idx = self.layer_combo.findData(obj.layer_id)
            if idx >= 0:
                self.layer_combo.setCurrentIndex(idx)
            self.kind_label.setText("Point cloud" if obj.kind == "pointcloud"
                                    else obj.kind.capitalize())
            self.measure_label.setText(self._measures(obj))
            self.color_widget.setEnabled(True)
            self._show_swatch(self._ink_of(obj))
            self.color_reset.setEnabled(obj.color is not None)

    def _refresh_paper(self, papers: list):
        obj = papers[0] if len(papers) == 1 else None
        if obj is None:
            self.header.setText(f"{len(papers)} objects selected")
            self._blank_editors()
            self.linetype_combo.setEnabled(False)
            # blank, not the last one's pattern: a greyed-out "Dashed" reads as
            # something these two have in common
            self.linetype_combo.setCurrentIndex(-1)
            self.lineweight_edit.setEnabled(False)
            self.lineweight_edit.setText("")
            return
        self.header.setText(obj.name)
        self.name_edit.setEnabled(True)
        self.name_edit.setText(obj.name)
        # said out loud, because a curve on the paper and a curve in the model
        # look the same in a one-word row and are not the same thing at all
        self.kind_label.setText(
            f"{g.shape_kind(obj.shape).capitalize()} on paper")
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
        self.header.setText("Detail")
        self._blank_editors()
        self.kind_label.setText("Detail")
        self.measure_label.setText(f"Frame: {detail.w:g} × {detail.h:g} mm")

    def _show_scale(self, detail: DetailView):
        """Say what the detail's scale is: the list highlights it when it is a
        preset, the text says it either way."""
        text = detail.scale_text()
        self.scale_combo.setCurrentIndex(self.scale_combo.findText(text))
        self.scale_combo.setEditText(text)

    def _show_detail_view(self, detail: DetailView):
        name = "Custom"
        for index in range(1, self.detail_view_combo.count()):
            candidate = self.detail_view_combo.itemText(index)
            azimuth, elevation = STANDARD_VIEWS[candidate.lower()]
            delta = (detail.azimuth - azimuth + pi) % (2 * pi) - pi
            if (detail.perspective == (candidate == "Perspective")
                    and isclose(delta, 0, abs_tol=1e-7)
                    and isclose(detail.elevation, elevation, abs_tol=1e-7)):
                name = candidate
                break
        self.detail_view_combo.setCurrentText(name)

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
        self.kind_label.setText("—")
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
            if obj.kind == "pointcloud":
                return cloud_measures(obj, fmt)
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
