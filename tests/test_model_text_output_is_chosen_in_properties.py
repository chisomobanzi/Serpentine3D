"""Model lettering output is chosen directly in Properties.

The tests drive the real MainWindow and ``textobject`` command.  They keep
the interaction non-modal and verify the resulting OpenCascade geometry, so
the output picker cannot be satisfied by controls which do not affect the
model.
"""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QPlainTextEdit,
    QPushButton,
)

from serpentine3d.app import MainWindow
from serpentine3d.core import geometry as g
from serpentine3d.core.cplane import CPlane
from serpentine3d.core.text import TextShape


@pytest.fixture
def window():
    w = MainWindow()
    w.resize(1200, 850)
    w.show()
    QApplication.processEvents()
    yield w
    w.processor.cancel()
    w.viewport.end_inline_text()
    w.hide()


@pytest.fixture
def lettering_font():
    families = set(QFontDatabase.families())
    family = next((name for name in (
        "DejaVu Sans", "Liberation Sans", "Arial", "Noto Sans")
        if name in families), None)
    if family is None:
        pytest.skip("An installed font with B/O/R outlines is required")
    return family


def _control(window, cls, name, *, visible=True, enabled=True):
    control = window.properties.findChild(cls, name)
    assert control is not None, f"Properties needs a stable {name} control"
    assert (not control.isHidden()) is visible, (
        f"{name} visibility does not match the selected output")
    assert control.isEnabled() is enabled, (
        f"{name} enabled state does not match the selected output")
    return control


def _choose(combo, value):
    index = combo.findData(value)
    assert index >= 0, f"{value!r} is not offered by {combo.objectName()}"
    combo.setCurrentIndex(index)
    QApplication.processEvents()


def _output_controls(window):
    return (
        _control(window, QComboBox, "text_output"),
        window.properties.findChild(QCheckBox, "text_group_output"),
        window.properties.findChild(QDoubleSpinBox, "text_solid_depth"),
        window.properties.findChild(QPushButton, "text_convert"),
    )


def _forbid_modal_text_ui(monkeypatch):
    monkeypatch.setattr(
        QDialog,
        "exec",
        lambda _dialog: pytest.fail("Choosing model text output opened a modal"),
    )


def _source_text(family):
    plane = CPlane(origin=(4., 11., 7.), normal=(0., -1., 0.),
                   xdir=(1., 0., 0.))
    source = g.apply_matrix(
        TextShape("BOR", 10., family, origin=(0., 0., 0.)),
        plane.basis_matrix(),
    )
    assert len(source.to_curves()) == 7, (
        "The installed B/O/R font must provide two B counters plus O and R")
    return source


def _ink_area(source):
    regions = g.planar_regions(source.to_curves())
    assert len(regions) == 3, "B, O and R should form three regions with holes"
    return sum(g.surface_area(region) for region in regions)


def _assert_grouped(objects):
    group_ids = {obj.group_id for obj in objects}
    assert len(group_ids) == 1 and None not in group_ids, (
        "The separate letter contours must be grouped by default")


def _assert_output_geometry(objects, output, source, depth=2.5):
    expected_bbox = g.bbox(g.make_compound(source.to_curves()))
    ink_area = _ink_area(source)

    if output == "curves":
        assert len(objects) == 7
        assert all(obj.kind == "curve" and g.is_closed_curve(obj.shape)
                   and g.is_valid(obj.shape) for obj in objects)
        _assert_grouped(objects)
        actual = [obj.shape for obj in objects]
        np.testing.assert_allclose(
            g.bbox(g.make_compound(actual)), expected_bbox, atol=1e-5)
        assert sum(g.curve_length(curve) for curve in actual) == pytest.approx(
            sum(g.curve_length(curve) for curve in source.to_curves()),
            rel=1e-6)
        return

    if output == "surface":
        assert len(objects) == 3
        assert all(obj.kind == "surface" and g.is_valid(obj.shape)
                   for obj in objects)
        _assert_grouped(objects)
        assert sum(g.surface_area(obj.shape) for obj in objects) == pytest.approx(
            ink_area, rel=1e-6), "Planar letter surfaces must retain B/O/R holes"
        lo, hi = g.bbox(g.make_compound([obj.shape for obj in objects]))
        assert lo[1] == pytest.approx(11., abs=1e-6)
        assert hi[1] == pytest.approx(11., abs=1e-6)
        return

    assert output == "solid"
    assert len(objects) == 3
    assert all(obj.kind == "solid" and g.is_valid(obj.shape)
               for obj in objects)
    assert sum(g.volume(obj.shape) for obj in objects) == pytest.approx(
        ink_area * depth, rel=1e-6), "Capped solids must retain B/O/R holes"
    lo, hi = g.bbox(g.make_compound([obj.shape for obj in objects]))
    assert lo[1] == pytest.approx(11. - depth, abs=1e-6)
    assert hi[1] == pytest.approx(11., abs=1e-6), (
        "Positive depth must extrude along the text-plane normal")


def test_properties_exposes_contextual_non_modal_output_controls(
        window, lettering_font, monkeypatch):
    _forbid_modal_text_ui(monkeypatch)
    obj = window.scene.add(_source_text(lettering_font), name="Lettering")
    window.selection.set([obj.id])
    QApplication.processEvents()

    output, group, depth, convert = _output_controls(window)
    assert {output.itemData(i) for i in range(output.count())} == {
        "editable", "curves", "surface", "solid"}
    assert output.currentData() == "editable"
    assert convert is not None and not convert.isHidden()
    assert not convert.isEnabled(), (
        "Editable is already the current form, so there is nothing to convert")
    _control(window, QCheckBox, "text_group_output",
             visible=False, enabled=False)
    _control(window, QDoubleSpinBox, "text_solid_depth",
             visible=False, enabled=False)

    for value in ("curves", "surface"):
        _choose(output, value)
        group = _control(window, QCheckBox, "text_group_output")
        assert group.isChecked(), "Curve and surface output should group by default"
        _control(window, QDoubleSpinBox, "text_solid_depth",
                 visible=False, enabled=False)
        assert convert.isEnabled()

    _choose(output, "solid")
    _control(window, QCheckBox, "text_group_output",
             visible=False, enabled=False)
    depth = _control(window, QDoubleSpinBox, "text_solid_depth")
    assert depth.value() > 0.
    assert convert.isEnabled()


@pytest.mark.parametrize("output", ["curves", "surface", "solid"])
def test_existing_text_converts_on_its_plane_with_one_undo_step(
        window, lettering_font, monkeypatch, output):
    _forbid_modal_text_ui(monkeypatch)
    source = _source_text(lettering_font)
    original_bytes = source.to_bytes()
    obj = window.scene.add(source, name="Lettering")
    window.selection.set([obj.id])
    QApplication.processEvents()

    output_box, _group, _depth, convert = _output_controls(window)
    _choose(output_box, output)
    depth = 2.5
    if output == "solid":
        depth_control = _control(
            window, QDoubleSpinBox, "text_solid_depth")
        depth_control.setValue(depth)
        QApplication.processEvents()

    before_undo = len(window.history._undo)
    QTest.mouseClick(convert, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    converted = window.scene.all()
    assert len(window.history._undo) == before_undo + 1
    assert all(not isinstance(item.shape, TextShape) for item in converted)
    _assert_output_geometry(converted, output, source, depth)

    window.history.undo()
    restored, = window.scene.all()
    assert isinstance(restored.shape, TextShape)
    assert restored.shape.to_bytes() == original_bytes

    window.history.redo()
    _assert_output_geometry(window.scene.all(), output, source, depth)


@pytest.mark.parametrize("output", ["curves", "surface", "solid"])
def test_direct_creation_can_choose_geometry_output_before_escape(
        window, lettering_font, monkeypatch, output):
    _forbid_modal_text_ui(monkeypatch)
    plane = CPlane(origin=(4., 11., 7.), normal=(0., -1., 0.),
                   xdir=(1., 0., 0.))
    window.viewport.cplane = plane
    window.processor.run("textobject")
    window.processor.provide(plane.origin)
    QApplication.processEvents()
    editor = window.viewport.findChild(QPlainTextEdit, "model_text_content")
    assert editor is not None and not editor.isHidden()
    editor.setPlainText("BOR")
    QApplication.processEvents()

    family = _control(window, QComboBox, "text_output")
    _choose(family, output)
    depth = 2.5
    if output == "solid":
        depth_control = _control(
            window, QDoubleSpinBox, "text_solid_depth")
        depth_control.setValue(depth)
        QApplication.processEvents()

    live_text, = window.scene.all()
    assert isinstance(live_text.shape, TextShape), (
        "Typing should remain editable until the inline session finishes")
    source = live_text.shape
    QTest.keyClick(editor, Qt.Key.Key_Escape)
    QApplication.processEvents()

    assert not window.processor.busy
    assert editor.isHidden()
    _assert_output_geometry(window.scene.all(), output, source, depth)
    assert len(window.history._undo) == 1
    window.history.undo()
    assert window.scene.all() == []
    window.history.redo()
    _assert_output_geometry(window.scene.all(), output, source, depth)
