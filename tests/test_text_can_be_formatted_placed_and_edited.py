"""Issue #18: direct text editing, geometry and print share typography.

The GUI tests place the anchor first, type into the viewport editor and use
the live Properties controls.  Text creation and editing must stay non-modal.
"""

from dataclasses import fields

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFont, QFontDatabase, QImage, QPainter, QPen, QTransform
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox,
    QPlainTextEdit, QPushButton,
)

from serpentine3d.app import MainWindow
from serpentine3d.commands.base import PointReq
from serpentine3d.core import geometry as g
from serpentine3d.core.cplane import CPlane
from serpentine3d.core.layout import (
    Hatch, Layout, Leader, LinearDim, TextNote, annotation_at, annotation_bounds,
    layouts_from_json,
)
from serpentine3d.core.scene import Scene
from serpentine3d.core.text import TextShape, text_path
from serpentine3d.fileio import native
from serpentine3d.ui.annot_paint import INK, draw_note


@pytest.fixture
def window():
    w = MainWindow()
    w.resize(1200, 850)
    w.show()
    QApplication.processEvents()
    yield w
    w.processor.cancel()
    w.viewport.end_inline_text()
    # No real developer document or close/save confirmation is involved.
    w.hide()


@pytest.fixture
def typography():
    families = set(QFontDatabase.families())
    for family in ("DejaVu Sans", "Liberation Sans", "Arial", "Noto Sans"):
        if family in families:
            styles = QFontDatabase.styles(family)
            regular = next((s for s in styles if s in ("Book", "Regular")), styles[0])
            bold = next((s for s in styles if "Bold" in s), regular)
            return dict(text="BOR\nHI", height=7., font_family=family,
                        font_style=bold, alignment="center")
    pytest.skip("No installed lettering font")


def _control(window, cls, name):
    obj = window.properties.findChild(cls, name)
    assert obj is not None, f"Properties needs its {name} control"
    assert obj.isEnabled() and not obj.isHidden(), (
        f"Properties must expose {name} while text is active")
    return obj


def _inline_editor(window):
    controls = [
        control for control in window.viewport.findChildren(QPlainTextEdit)
        if control.objectName() == "model_text_content"
        and control.isEnabled() and not control.isHidden()
    ]
    assert len(controls) == 1, (
        "Picking the anchor must open the multiline editor in the viewport")
    return controls[0]


def _properties_content(window):
    return _control(window, QPlainTextEdit, "text_content")


def _choose(combo, value):
    index = next((i for i in range(combo.count())
                  if str(combo.itemData(i)).lower() == value.lower() or
                  combo.itemText(i).lower() == value.lower()), -1)
    assert index >= 0, f"{value!r} is not offered by {combo.objectName()}"
    combo.setCurrentIndex(index)
    QApplication.processEvents()


def _type_live(window, text, output=None, grouped=True):
    content = _inline_editor(window)
    content.setPlainText(text)
    QApplication.processEvents()
    if output is not None:
        choice = _control(window, QComboBox, "text_output")
        assert choice.currentData() == "editable", (
            "New text should remain editable by default")
        _choose(choice, output)
        if output in ("curves", "surface"):
            group = _control(window, QCheckBox, "text_group_output")
            assert group.isChecked(), "Group output must be on by default"
            group.setChecked(grouped)
            QApplication.processEvents()


def _configure_live(window, values, *, in_properties=False):
    content = (_properties_content(window) if in_properties
               else _inline_editor(window))
    content.setPlainText(values["text"])
    QApplication.processEvents()
    family = _control(window, QComboBox, "text_font_family")
    if family.currentText().casefold() == values["font_family"].casefold():
        other = next((i for i in range(family.count())
                      if family.itemText(i).casefold()
                      != values["font_family"].casefold()), -1)
        if other >= 0:
            family.setCurrentIndex(other)
            QApplication.processEvents()
    _choose(family, values["font_family"])
    styles = _control(window, QComboBox, "text_font_style")
    assert values["font_style"] in {
        styles.itemText(i) for i in range(styles.count())}, (
        "The chosen installed font style must be available in Properties")
    _choose(styles, values["font_style"])
    height = _control(window, QDoubleSpinBox, "text_height")
    assert height.minimum() > 0, "Text height must stay positive"
    height.setValue(values["height"])
    QApplication.processEvents()
    _choose(_control(window, QComboBox, "text_alignment"), values["alignment"])


def _forbid_modal(monkeypatch):
    monkeypatch.setattr(
        QDialog, "exec",
        lambda _dialog: pytest.fail("Text opened a blocking editor dialog"))


def _finish_inline(window):
    inline = _inline_editor(window)
    QTest.keyClick(inline, Qt.Key.Key_Escape)
    QApplication.processEvents()
    assert inline.isHidden()


def _click_drawing_outside_editor(window, editor):
    viewport = window.viewport
    candidates = (
        QPoint(5, 5), QPoint(viewport.width() - 5, 5),
        QPoint(5, viewport.height() - 5),
        QPoint(viewport.width() - 5, viewport.height() - 5),
    )
    point = next(candidate for candidate in candidates
                 if not editor.geometry().contains(candidate))
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=point)
    QApplication.processEvents()


def _place_model(window, typography, *, position=(25., 35., 0.)):
    window.processor.run("textobject")
    assert isinstance(window.processor.request, PointReq), (
        "Text must ask for its baseline anchor before opening an editor")
    window.processor.provide(position)
    QApplication.processEvents()
    _type_live(window, typography["text"])
    _finish_inline(window)
    assert not window.processor.busy
    obj, = window.scene.all()
    window._edit_model_text_in_viewport(window.viewport, obj.id)
    QApplication.processEvents()
    _configure_live(window, typography, in_properties=True)
    _finish_inline(window)
    return window.scene.all()


def _convert_to_curves(window, grouped=True):
    source, = window.scene.all()
    window.selection.set([source.id])
    QApplication.processEvents()
    _choose(_control(window, QComboBox, "text_output"), "curves")
    group = _control(window, QCheckBox, "text_group_output")
    assert group.isChecked(), "Curve contours must group by default"
    group.setChecked(grouped)
    convert = _control(window, QPushButton, "text_convert")
    QTest.mouseClick(convert, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    return source


def _same_typography(obj, values):
    for name, value in values.items():
        assert getattr(obj, name, None) == value, name


def _sheet(window):
    lay = Layout(name="Typography sheet")
    window.scene.layouts.append(lay)
    window.switch_space(lay.id)
    return lay


def _pick_note(window, note):
    window.viewport.layout_view.selected = [("note", note)]
    window.viewport.layoutSelectionChanged.emit()


def _formatted_note(values, **placement):
    expected = {"font_family", "font_style", "alignment"}
    assert expected <= {f.name for f in fields(TextNote)}, (
        "Layout notes must retain font family, style and alignment")
    return TextNote(**values, **placement)


def test_textobject_places_live_typography_on_the_cplane(
        window, monkeypatch, typography):
    _forbid_modal(monkeypatch)
    plane = CPlane(origin=(0., 8., 0.), normal=(0., -1., 0.), xdir=(1., 0., 0.))
    window.viewport.cplane = plane
    window.processor.run("textobject")
    assert isinstance(window.processor.request, PointReq)
    position = (25., 8., 40.)
    window.processor.provide(position)
    QApplication.processEvents()
    _type_live(window, typography["text"])
    obj, = window.scene.all()
    assert isinstance(obj.shape, TextShape), (
        "Typing must create visible editable lettering at the chosen anchor")
    lo, hi = obj.bbox()
    assert lo[1] == pytest.approx(8., abs=1e-5)
    assert hi[1] == pytest.approx(8., abs=1e-5)
    assert hi[2] > lo[2] + typography["height"]
    _finish_inline(window)
    assert not window.processor.busy
    window._edit_model_text_in_viewport(window.viewport, obj.id)
    QApplication.processEvents()
    _configure_live(window, typography, in_properties=True)
    _finish_inline(window)
    current = window.scene.get(obj.id)
    _same_typography(current.shape, typography)
    np.testing.assert_allclose(current.shape.origin, position)
    assert len(window.history._undo) == 2
    window.history.undo()
    assert window.scene.all(), "Undoing formatting must retain the placed text"
    window.history.undo()
    assert window.scene.all() == []
    window.history.redo()
    window.history.redo()
    _same_typography(window.scene.all()[0].shape, typography)


def test_new_text_keeps_live_style_and_clicking_the_drawing_finishes(
        window, typography):
    window.processor.run("textobject")
    window.processor.provide((25., 35., 0.))
    QApplication.processEvents()
    editor = _inline_editor(window)
    editor.setPlainText("Live bold text")
    QApplication.processEvents()

    family = _control(window, QComboBox, "text_font_family")
    _choose(family, typography["font_family"])
    regular_geometry = g.shape_to_bytes(window.scene.all()[0].shape)
    style = _control(window, QComboBox, "text_font_style")
    _choose(style, typography["font_style"])
    obj, = window.scene.all()
    assert obj.shape.font_style == typography["font_style"]
    assert g.shape_to_bytes(obj.shape) != regular_geometry, (
        "Live style changes must rebuild the rendered model outlines")

    # Editing content after applying the style must not rebuild from the
    # typography that was active when the placement editor first opened.
    editor.setPlainText("Still live and bold")
    QApplication.processEvents()
    assert window.scene.get(obj.id).shape.font_style == typography["font_style"]

    _click_drawing_outside_editor(window, editor)
    assert editor.isHidden()
    assert not window.processor.busy
    final = window.scene.get(obj.id).shape
    assert final.text == "Still live and bold"
    assert final.font_style == typography["font_style"]


@pytest.mark.parametrize("grouped", [True, False])
def test_curve_output_keeps_contours_and_has_real_group_selection(
        window, monkeypatch, typography, grouped):
    _forbid_modal(monkeypatch)
    values = dict(typography, text="BOR")
    _place_model(window, values)
    before_conversion = len(window.history._undo)
    source = _convert_to_curves(window, grouped)
    objects = window.scene.all()
    assert len(objects) == 7, "B, O, R need three outside contours and four counters"
    assert all(o.kind == "curve" and g.is_closed_curve(o.shape) for o in objects)
    assert not any(isinstance(o.shape, TextShape) for o in objects)
    ids = {o.id for o in objects}
    window.selection.clear()
    window._on_object_clicked(objects[0].id, Qt.KeyboardModifier.NoModifier)
    assert set(window.selection.ids) == (ids if grouped else {objects[0].id})
    assert len(window.history._undo) == before_conversion + 1
    window.history.undo()
    restored, = window.scene.all()
    assert isinstance(restored.shape, TextShape)
    _same_typography(restored.shape, values)
    assert restored.id == source.id
    window.history.redo()
    assert len(window.scene.all()) == 7


@pytest.mark.parametrize("stage", ["anchor", "inline"])
def test_cancelling_model_text_leaves_no_objects_or_undo_entry(
        window, monkeypatch, typography, stage):
    _forbid_modal(monkeypatch)
    window.processor.run("textobject")
    assert isinstance(window.processor.request, PointReq)
    if stage == "anchor":
        window.processor.cancel()
    else:
        window.processor.provide((10., 20., 0.))
        QApplication.processEvents()
        _finish_inline(window)  # Empty inline text cancels the command.
    assert not window.processor.busy
    assert not window.scene.all()
    assert not window.history.can_undo


def test_properties_edits_model_text_in_one_undoable_operation(
        window, monkeypatch, typography):
    _forbid_modal(monkeypatch)
    original = TextShape(**typography, origin=(25., 35., 0.))
    obj = window.scene.add(original, name="Drawing title")
    window.selection.set([obj.id])
    edited = dict(typography, text="First floor\nSouth wing", height=5., alignment="right")
    window._edit_model_text_in_viewport(window.viewport, obj.id)
    QApplication.processEvents()
    assert _properties_content(window).toPlainText() == original.text
    _configure_live(window, edited, in_properties=True)
    _finish_inline(window)
    current = window.scene.get(obj.id)
    assert current.name == "Drawing title"
    _same_typography(current.shape, edited)
    np.testing.assert_allclose(current.shape.origin, original.origin)
    assert len(window.history._undo) == 1
    assert not np.allclose(g.bbox(current.shape), g.bbox(original))
    window.history.undo()
    _same_typography(window.scene.get(obj.id).shape, typography)
    window.history.redo()
    _same_typography(window.scene.get(obj.id).shape, edited)


def test_text_command_places_a_live_formatted_note(
        window, monkeypatch, typography):
    _forbid_modal(monkeypatch)
    lay = _sheet(window)
    window.processor.run("text")
    assert isinstance(window.processor.request, PointReq)
    window.processor.provide((50., 70., 0.))
    QApplication.processEvents()
    _type_live(window, typography["text"])
    note, = lay.notes
    assert (note.x, note.y) == (50., 70.)
    _finish_inline(window)
    assert not window.processor.busy
    window._edit_paper_text_in_viewport(window.viewport, note.id)
    QApplication.processEvents()
    _configure_live(window, typography, in_properties=True)
    _finish_inline(window)
    current = next(item for item in lay.notes if item.id == note.id)
    _same_typography(current, typography)
    assert len(window.history._undo) == 2


@pytest.mark.parametrize("stage", ["anchor", "inline"])
def test_cancelling_a_layout_note_leaves_the_sheet_and_history_unchanged(
        window, monkeypatch, typography, stage):
    _forbid_modal(monkeypatch)
    lay = _sheet(window)
    window.processor.run("text")
    assert isinstance(window.processor.request, PointReq)
    if stage == "anchor":
        window.processor.cancel()
    else:
        window.processor.provide((20., 30., 0.))
        QApplication.processEvents()
        _finish_inline(window)
    assert not lay.notes and not lay.objects and not window.scene.all()
    assert not window.processor.busy and not window.history.can_undo


def test_properties_edit_layout_note_typography_and_support_undo(
        window, monkeypatch, typography):
    _forbid_modal(monkeypatch)
    lay = _sheet(window)
    note = TextNote(x=50., y=70., text="Original note", height=4.)
    lay.notes.append(note)
    window.scene.notify()
    _pick_note(window, note)
    window._edit_paper_text_in_viewport(window.viewport, note.id)
    QApplication.processEvents()
    _configure_live(window, typography, in_properties=True)
    _finish_inline(window)
    current = window.scene.layouts[0].notes[0]
    assert (current.id, current.x, current.y) == (note.id, 50., 70.)
    assert len(window.history._undo) == 1
    _same_typography(current, typography)
    window.history.undo()
    assert window.scene.layouts[0].notes[0].text == "Original note"
    window.history.redo()
    _same_typography(window.scene.layouts[0].notes[0], typography)


def test_formatted_note_survives_native_save_and_reopen(tmp_path, typography):
    note = _formatted_note(typography, x=50., y=70.)
    scene = Scene()
    lay = Layout(name="Notes")
    lay.notes.append(note)
    scene.layouts.append(lay)
    path = str(tmp_path / "Formatted notes.serp")
    native.save_scene(scene, path)
    restored = Scene()
    native.load_scene(restored, path)
    loaded, = restored.layouts[0].notes
    _same_typography(loaded, typography)
    assert (loaded.id, loaded.x, loaded.y) == (note.id, note.x, note.y)


def _render_note(note, k=5., *, legacy=False):
    image = QImage(900, 650, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.white)
    painter = QPainter(image)
    to_dev = lambda x, y: (x * k, 600. - y * k)
    try:
        if legacy:
            font = QFont("sans")
            font.setPixelSize(max(int(note.height * k), 4))
            painter.setFont(font)
            painter.setPen(QPen(INK))
            for i, line in enumerate(note.text.split("\n")):
                x, y = to_dev(note.x, note.y - i * note.height * 1.6)
                painter.drawText(int(x), int(y), line)
        else:
            draw_note(painter, to_dev, k, note)
    finally:
        painter.end()
    return image


@pytest.mark.parametrize("alignment", ["left", "center", "right"])
def test_note_selection_bounds_match_the_formatted_ink_on_paper(typography, alignment):
    values = dict(typography, alignment=alignment)
    note = _formatted_note(values, x=70., y=70.)
    image = _render_note(note)
    pixels = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(650, 900, 4)
    ys, xs = np.nonzero(np.any(pixels[:, :, :3] != 255, axis=2))
    assert len(xs), "Formatted notes must actually draw on a QPainter used for printing"
    ink = (xs.min() / 5., (600. - ys.max()) / 5.,
           (xs.max() + 1) / 5., (600. - ys.min() + 1) / 5.)
    bounds = annotation_bounds("note", note)
    np.testing.assert_allclose(bounds, ink, atol=.45)
    path = text_path(**values).boundingRect()
    # Qt glyph paths point down; paper coordinates point up.
    expected = (70. + path.left(), 70. - path.bottom(),
                70. + path.right(), 70. - path.top())
    np.testing.assert_allclose(bounds, expected, atol=1e-6)
    lay = Layout()
    lay.notes.append(note)
    assert annotation_at(lay, (bounds[0] + bounds[2]) / 2,
                         (bounds[1] + bounds[3]) / 2, tol=.01) == ("note", note)


def test_legacy_notes_keep_their_existing_rendering_when_loaded():
    data = [{"name": "Older drawing", "notes": [dict(
        id="existing-note", x=50., y=70., text="First floor\nNorth wing", height=4.)]}]
    lay, = layouts_from_json(data)
    note, = lay.notes
    assert _render_note(note) == _render_note(note, legacy=True), (
        "Loading an old file must not silently change the note size or line spacing")


def test_extrude_offers_caps_for_editable_text_and_keeps_the_counters(env, typography):
    scene, selection, _history, _ctx, proc = env
    values = dict(typography, text="BOR")
    text = TextShape(**values)
    obj = scene.add(text)
    selection.set([obj.id])
    proc.run("extrude")
    assert isinstance(proc.request, PointReq)
    assert proc.request.choices.get("Cap") == ["Yes", "No"], (
        "Editable lettering must offer the same Cap choice as closed outline curves")
    proc.provide_text("5")
    assert not proc.busy
    solids = [o.shape for o in scene.all() if o.id != obj.id]
    assert len(solids) == 3 and all(g.shape_kind(s) == "solid" for s in solids)
    assert all(g.is_valid(s) and g.volume(s) > 0 for s in solids)
    path = text_path(**values)
    # The signed area of every painter subpath includes the letter counters.
    area = 0.
    for polygon in path.toSubpathPolygons(QTransform().scale(20., 20.)):
        pts = [(p.x(), p.y()) for p in polygon]
        area += sum(x1*y2 - x2*y1 for (x1, y1), (x2, y2)
                    in zip(pts, pts[1:] + pts[:1])) / 2
    assert sum(g.volume(s) for s in solids) == pytest.approx(abs(area)*5./400., rel=.001)


def test_existing_scripted_textobject_and_text_input_still_work(env):
    scene, _sel, _hist, ctx, proc = env
    proc.run("textobject")
    for value in ("Hi", "0,0,0", "10"):
        proc.provide_text(value)
    assert not proc.busy and scene.all()
    from tests.conftest import StubViewport
    lay = Layout(name="Scripted sheet")
    scene.layouts.append(lay)
    ctx.viewport = StubViewport(lay.id)
    proc.run("text")
    for value in ("50,50", "First line\\nSecond line", "4"):
        proc.provide_text(value)
    assert not proc.busy
    assert lay.notes[0].text == "First line\nSecond line"


@pytest.mark.parametrize("command,kind,answer", [
    ("annotedit", "dim", "Overall"),
    ("editnote", "leader", "Entrance"),
    ("edittext", "hatch", "Cross"),
])
def test_annotation_editor_aliases_preserve_other_annotation_types(env, command, kind, answer):
    scene, _sel, _hist, ctx, proc = env
    from tests.conftest import StubViewport
    lay = Layout(name="Existing annotations")
    scene.layouts.append(lay)
    ctx.viewport = StubViewport(lay.id)
    if kind == "dim":
        item = LinearDim(x1=10., y1=10., x2=30., y2=10., offset=8.)
        lay.dims.append(item)
        point = "20,18"
    elif kind == "leader":
        item = Leader(points=[[10., 10.], [30., 30.]], text="Original")
        lay.leaders.append(item)
        point = "20,20"
    else:
        item = Hatch(points=[[10., 10.], [30., 10.], [30., 30.], [10., 30.]])
        lay.hatches.append(item)
        point = "20,20"
    proc.run(command)
    proc.provide_text(point)
    proc.provide_text(answer)
    assert not proc.busy
    assert (item.pattern == answer.lower() if kind == "hatch" else item.text == answer)
