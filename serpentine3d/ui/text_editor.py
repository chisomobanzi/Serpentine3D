"""Shared typography editor for model lettering and notes on paper."""

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import (
    QFont, QFontDatabase, QFontInfo, QPainter, QTextBlockFormat, QTextCursor,
)
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFontComboBox, QFormLayout, QLabel, QPlainTextEdit, QVBoxLayout, QWidget,
)

from ..core.text import text_path


def typography_of(text):
    return {name: getattr(text, name) for name in
            ("text", "height", "font_family", "font_style", "alignment")}


def default_typography(values=None):
    """Complete partial text values with usable desktop defaults."""
    values = dict(values or {})
    family = values.get("font_family") or QFontInfo(QFont("sans")).family()
    styles = QFontDatabase.styles(family)
    style = values.get("font_style", "")
    if style not in styles:
        style = next((s for s in styles
                      if s in ("Regular", "Book", "Normal")), "")
    return dict(text=values.get("text", ""),
                height=float(values.get("height", 4.)),
                font_family=family, font_style=style,
                alignment=values.get("alignment", "left"))


class InlineTextEditor(QPlainTextEdit):
    """A multiline editor laid over the model where its text is placed."""

    finished = Signal()

    def setAlignment(self, alignment):
        """Align every paragraph while leaving the user's selection intact."""
        original = self.textCursor()
        cursor = QTextCursor(self.document())
        cursor.select(QTextCursor.SelectionType.Document)
        block_format = QTextBlockFormat()
        block_format.setAlignment(alignment)
        cursor.mergeBlockFormat(block_format)
        self.setTextCursor(original)

    def alignment(self):
        return self.textCursor().blockFormat().alignment()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.finished.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class _TextPreview(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self.setMinimumHeight(110)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), self.palette().base())
        values = self.editor.typography()
        if values["text"].strip():
            path = text_path(**values)
            rect = path.boundingRect()
            if not rect.isEmpty():
                scale = min((self.width() - 24) / rect.width(),
                            (self.height() - 24) / rect.height())
                painter.translate(self.width() / 2, self.height() / 2)
                painter.scale(scale, scale)
                painter.translate(-rect.center())
                painter.fillPath(path, self.palette().text())
        painter.end()


class TextEditorDialog(QDialog):
    def __init__(self, parent=None, *, values=None, curve_output=False,
                 units="mm"):
        super().__init__(parent)
        self.setWindowTitle("Text")
        self.resize(540, 560)
        values = values or {}
        self.content = QPlainTextEdit()
        self.content.setObjectName("text_content")
        self.content.setPlaceholderText("Type your text…")
        self.content.setPlainText(values.get("text", ""))
        self.content.setMinimumHeight(130)

        self.family = QFontComboBox()
        self.family.setObjectName("text_font_family")
        self.family.setCurrentFont(QFont(values.get("font_family") or
                                        QFontInfo(QFont("sans")).family()))
        self.style = QComboBox()
        self.style.setObjectName("text_font_style")
        self.height = QDoubleSpinBox()
        self.height.setObjectName("text_height")
        self.height.setDecimals(3)
        self.height.setRange(.001, 1e9)
        self.height.setValue(values.get("height", 4.))
        self.height.setSuffix(" " + units)
        self.height.setToolTip("Height of a capital letter, measured on its plane")
        self.alignment = QComboBox()
        self.alignment.setObjectName("text_alignment")
        for label in ("Left", "Center", "Right"):
            self.alignment.addItem(label, label.lower())
        self.alignment.setCurrentIndex(max(0, self.alignment.findData(
            values.get("alignment", "left"))))

        self.output = QComboBox()
        self.output.setObjectName("text_output")
        self.output.addItem("Editable text", "editable")
        self.output.addItem("Curves", "curves")
        self.group = QCheckBox("Group output")
        self.group.setObjectName("text_group_output")
        self.group.setChecked(True)
        self.group.setEnabled(False)
        self.group.setToolTip("Select and move the separate letter contours together")
        self.output.currentIndexChanged.connect(
            lambda: self.group.setEnabled(self.output.currentData() == "curves"))

        form = QFormLayout()
        form.addRow("Font family", self.family)
        form.addRow("Font style", self.style)
        form.addRow("Cap height", self.height)
        form.addRow("Alignment", self.alignment)
        form.addRow("Output", self.output)
        form.addRow("", self.group)
        form.setRowVisible(self.output, curve_output)
        form.setRowVisible(self.group, curve_output)

        self.preview = _TextPreview(self)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                       QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Text"))
        layout.addWidget(self.content, 1)
        layout.addLayout(form)
        layout.addWidget(self.preview)
        layout.addWidget(self.buttons)
        self.family.currentFontChanged.connect(self._family_changed)
        self._family_changed()
        index = self.style.findText(values.get("font_style", ""))
        if index >= 0:
            self.style.setCurrentIndex(index)
        self.content.textChanged.connect(self._changed)
        self.style.currentIndexChanged.connect(self._changed)
        self.height.valueChanged.connect(self._changed)
        self.alignment.currentIndexChanged.connect(self._changed)
        self._changed()
        self.content.setFocus()

    def _family_changed(self, *_):
        previous = self.style.currentText()
        self.style.clear()
        styles = QFontDatabase.styles(self.family.currentFont().family())
        self.style.addItems(styles)
        preferred = previous if previous in styles else next(
            (s for s in styles if s in ("Regular", "Book", "Normal")), "")
        index = self.style.findText(preferred)
        if index >= 0:
            self.style.setCurrentIndex(index)
        self._changed()

    def _changed(self, *_):
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            bool(self.content.toPlainText().strip()))
        self.preview.update()

    def typography(self):
        return dict(text=self.content.toPlainText(), height=self.height.value(),
                    font_family=self.family.currentFont().family(),
                    font_style=self.style.currentText(),
                    alignment=self.alignment.currentData())

    def result_values(self):
        return dict(self.typography(), output=self.output.currentData(),
                    group_output=self.group.isChecked())
