"""Editable text typography lives in Properties, beside its live content.

These tests exercise the real MainWindow, installed fonts, model TextShape
geometry and paper TextNote rendering.  Typography changes made while an
inline editor is active are one editing session and therefore one Undo step.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QPlainTextEdit,
    QPushButton,
)

from serpentine3d.app import MainWindow
from serpentine3d.core.layout import Layout, TextNote
from serpentine3d.core.text import TextShape
from serpentine3d.ui.annot_paint import style_of


@pytest.fixture
def window():
    result = MainWindow()
    result.resize(1200, 850)
    result.show()
    QApplication.processEvents()
    yield result
    result.processor.cancel()
    result.viewport.end_inline_text()
    result.hide()


@pytest.fixture
def fonts():
    """Two real families whose style menus visibly differ."""
    families = set(QFontDatabase.families())
    preferred = [
        ("DejaVu Sans", "Liberation Serif"),
        ("Liberation Sans", "DejaVu Serif"),
        ("Noto Sans", "Noto Serif"),
    ]
    pair = next(((first, second) for first, second in preferred
                 if first in families and second in families), None)
    if pair is None:
        candidates = [family for family in families
                      if QFontDatabase.styles(family)]
        pair = next(((first, second)
                     for first in candidates for second in candidates
                     if first != second
                     and set(QFontDatabase.styles(first))
                     != set(QFontDatabase.styles(second))), None)
    if pair is None:
        pytest.skip("Two installed font families with different styles required")
    first, second = pair
    first_style = QFontDatabase.styles(first)[0]
    second_styles = QFontDatabase.styles(second)
    second_style = next((style for style in second_styles
                         if style != first_style), second_styles[-1])
    return first, first_style, second, second_style


def _control(window, cls, name):
    control = window.properties.findChild(cls, name)
    assert control is not None, f"Properties needs an enabled {name} control"
    assert control.isEnabled() and not control.isHidden(), (
        f"{name} must be directly editable for selected text")
    return control


def _typography_controls(window):
    return (
        _control(window, QComboBox, "text_font_family"),
        _control(window, QComboBox, "text_font_style"),
        _control(window, QDoubleSpinBox, "text_height"),
        _control(window, QComboBox, "text_alignment"),
    )


def _choose(combo, value):
    index = next((i for i in range(combo.count())
                  if combo.itemText(i).casefold() == str(value).casefold()
                  or str(combo.itemData(i)).casefold() == str(value).casefold()), -1)
    assert index >= 0, f"{value!r} is not offered by {combo.objectName()}"
    combo.setCurrentIndex(index)
    QApplication.processEvents()


def _inline_editor(window):
    editor = window.viewport.findChild(QPlainTextEdit, "model_text_content")
    assert editor is not None and editor.isEnabled() and not editor.isHidden()
    return editor


def _assert_no_modal_edit_button(window, monkeypatch):
    monkeypatch.setattr(
        QDialog, "exec",
        lambda _dialog: pytest.fail("Typography opened a blocking dialog"),
    )
    visible = [button for button in window.properties.findChildren(QPushButton)
               if not button.isHidden()
               and button.text().replace("&", "").strip().casefold()
               == "edit text"]
    assert not visible, "Properties must not offer a modal Edit text button"


def _assert_inline_style(editor, family, style, alignment):
    expected = QFontDatabase.font(family, style, 12)
    assert editor.font().family() == expected.family()
    assert editor.font().styleName() == expected.styleName()
    expected_alignment = {
        "left": Qt.AlignmentFlag.AlignLeft,
        "center": Qt.AlignmentFlag.AlignHCenter,
        "right": Qt.AlignmentFlag.AlignRight,
    }[alignment]
    assert editor.alignment() & expected_alignment


def test_model_text_typography_is_live_in_properties_and_one_undo_step(
        window, fonts, monkeypatch):
    old_family, old_style, family, font_style = fonts
    original = dict(text="Existing label", height=4.,
                    font_family=old_family, font_style=old_style,
                    alignment="left")
    obj = window.scene.add(
        TextShape(**original, origin=(10., 20., 0.)), name="Room label")
    window.selection.set([obj.id])
    window._edit_model_text_in_viewport(window.viewport, obj.id)
    QApplication.processEvents()

    family_box, style_box, height_box, alignment_box = (
        _typography_controls(window))
    assert family_box.currentText() == old_family
    assert style_box.currentText() == old_style
    assert height_box.value() == pytest.approx(4.)
    assert alignment_box.currentData() == "left"
    _assert_no_modal_edit_button(window, monkeypatch)

    _choose(family_box, family)
    assert window.scene.get(obj.id).shape.font_family == family
    assert {style_box.itemText(i) for i in range(style_box.count())} == set(
        QFontDatabase.styles(family))

    _choose(style_box, font_style)
    assert window.scene.get(obj.id).shape.font_style == font_style
    height_box.setValue(8.)
    QApplication.processEvents()
    assert window.scene.get(obj.id).shape.height == pytest.approx(8.)
    _choose(alignment_box, "right")
    current = window.scene.get(obj.id).shape
    assert current.alignment == "right"
    _assert_inline_style(_inline_editor(window), family, font_style, "right")

    QTest.keyClick(_inline_editor(window), Qt.Key.Key_Escape)
    QApplication.processEvents()
    assert len(window.history._undo) == 1
    window.history.undo()
    restored = window.scene.get(obj.id).shape
    assert (restored.font_family, restored.font_style, restored.height,
            restored.alignment) == (old_family, old_style, 4., "left")
    window.history.redo()
    revised = window.scene.get(obj.id).shape
    assert (revised.font_family, revised.font_style, revised.height,
            revised.alignment) == (family, font_style, 8., "right")


def test_paper_text_uses_the_same_controls_and_explicit_formatting_unstyles_it(
        window, fonts, monkeypatch):
    old_family, old_style, family, font_style = fonts
    layout = Layout(name="Typography sheet")
    window.scene.layouts.append(layout)
    window.switch_space(layout.id)
    note = TextNote(x=50., y=70., text="Drawing title", height=4.,
                    style="Heading", font_family=old_family,
                    font_style=old_style, alignment="left")
    layout.notes.append(note)
    window.scene.notify("layouts")
    window.viewport.layout_view.selected = [("note", note)]
    window.viewport.layoutSelectionChanged.emit()
    window._edit_paper_text_in_viewport(window.viewport, note.id)
    QApplication.processEvents()

    family_box, style_box, height_box, alignment_box = (
        _typography_controls(window))
    assert family_box.currentText() == old_family
    assert style_box.currentText() == old_style
    assert height_box.value() == pytest.approx(
        style_of(window.scene, "Heading")["text_height"])
    assert alignment_box.currentData() == "left"
    _assert_no_modal_edit_button(window, monkeypatch)

    _choose(family_box, family)
    assert note.font_family == family
    assert note.style == "", (
        "Directly formatting a note must detach it from its named style")
    assert {style_box.itemText(i) for i in range(style_box.count())} == set(
        QFontDatabase.styles(family))
    _choose(style_box, font_style)
    height_box.setValue(7.)
    QApplication.processEvents()
    _choose(alignment_box, "center")
    assert (note.font_family, note.font_style, note.height, note.alignment) == (
        family, font_style, 7., "center")
    _assert_inline_style(_inline_editor(window), family, font_style, "center")

    QTest.keyClick(_inline_editor(window), Qt.Key.Key_Escape)
    QApplication.processEvents()
    assert len(window.history._undo) == 1
    window.history.undo()
    restored = next(item for item in window.scene.layouts[0].notes
                    if item.id == note.id)
    assert (restored.style, restored.font_family, restored.font_style,
            restored.height, restored.alignment) == (
                "Heading", old_family, old_style, 4., "left")
    window.history.redo()
    revised = next(item for item in window.scene.layouts[0].notes
                   if item.id == note.id)
    assert (revised.style, revised.font_family, revised.font_style,
            revised.height, revised.alignment) == (
                "", family, font_style, 7., "center")
