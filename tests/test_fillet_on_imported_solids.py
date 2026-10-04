"""The visible Fillet tool must round STEP solids as well as curves."""

import math

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QToolButton

from serpentine3d.commands.base import PointReq
from serpentine3d.core import geometry as g
from serpentine3d.fileio import import_file
from serpentine3d.fileio.step import export_step
from serpentine3d.scripting import Document


def _step(tmp_path, shape):
    path = tmp_path / "Imported part.step"
    export_step([shape], str(path))
    return path


def test_toolbar_fillet_accepts_an_imported_step_solid(tmp_path):
    from serpentine3d.app import MainWindow

    window = MainWindow()
    try:
        path = _step(tmp_path, g.make_box((0, 0, 0), 20, 20, 20))
        import_file(window.scene, str(path))
        obj = window.scene.all()[0]
        button = next(b for b in window.findChildren(QToolButton)
                      if b.text() == "Fillet")
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        window.processor.click_object(obj.id)
        assert isinstance(window.processor.request, PointReq), (
            "Fillet rejected the solid instead of asking for its radius")
        window.processor.provide_text("1")
        assert not window.processor.busy
        rounded = window.scene.get(obj.id)
        assert rounded.kind == "solid" and g.is_valid(rounded.shape)
        assert g.volume(rounded.shape) < 8000 - 1
        window.history.undo()
        assert g.volume(window.scene.get(obj.id).shape) == pytest.approx(8000)
    finally:
        window._saved_revision = window.scene.revision
        window.close()


def test_fillet_uses_every_preselected_solid(tmp_path):
    path = _step(tmp_path, g.make_compound([
        g.make_box((0, 0, 0), 20, 20, 20),
        g.make_cylinder((40, 0, 0), 10, 20),
    ]))
    doc = Document(str(path))
    before = {o.id: g.volume(o.shape) for o in doc.objects()}
    doc.selection.set(list(before))
    messages = doc.run("fillet", ["1"])
    assert any("all edges of 2 object(s)" in m for m in messages)
    for oid, volume in before.items():
        result = doc.get(oid).shape
        assert g.is_valid(result) and g.volume(result) < volume


@pytest.mark.parametrize("command", ["fillet", "filletedge"])
def test_fillet_rounds_only_the_picked_step_edge(tmp_path, command):
    shape = g.boolean_union(g.make_box((0, 0, 0), 30, 30, 10),
                            g.make_box((10, 10, 10), 10, 10, 0.2))
    doc = Document(str(_step(tmp_path, shape)))
    obj = doc.objects()[0]
    volume = g.volume(obj.shape)
    doc.selection.toggle_subobject(obj.id, "edge", 0)
    messages = doc.run(command, ["No", "1"])
    result = doc.get(obj.id).shape
    assert "Filleted 1 edge(s)." in messages
    assert g.is_valid(result)
    assert g.volume(result) == pytest.approx(
        volume - (1 - math.pi / 4) * 10)
    assert not doc.selection.subobjects


def test_fillet_still_rounds_two_curves():
    doc = Document()
    doc.add(g.make_line((0, 0, 0), (10, 0, 0)), name="First")
    doc.add(g.make_line((10, 0, 0), (10, 10, 0)), name="Second")
    messages = doc.run("fillet", ["First", "Second", "10,0,0", "2"])
    assert any(m.startswith("Filleted into ") for m in messages)
    assert len(doc.objects()) == 1
    assert g.is_valid(doc.objects()[0].shape)
    assert g.curve_length(doc.objects()[0].shape) == pytest.approx(16 + math.pi)


@pytest.mark.parametrize("command", ["fillet", "filletedge"])
def test_whole_part_failure_explains_how_to_choose_edges(tmp_path, command):
    shape = g.boolean_union(g.make_box((0, 0, 0), 30, 30, 10),
                            g.make_box((10, 10, 10), 10, 10, 0.2))
    doc = Document(str(_step(tmp_path, shape)))
    obj = doc.objects()[0]
    volume = g.volume(obj.shape)
    doc.selection.set([obj.id])
    messages = doc.run(command, ["1"])
    assert "Ctrl+Shift" in messages[-1] and "specific edges" in messages[-1]
    assert not any("Command failed" in m for m in messages)
    assert g.volume(doc.get(obj.id).shape) == pytest.approx(volume)


def test_a_smooth_edge_has_a_geometry_error_instead_of_a_kernel_exception():
    shape = g.fillet_edges(g.make_box((0, 0, 0), 20, 20, 20), 1)
    with pytest.raises(g.GeometryError, match="No sharp edges"):
        g.fillet_edges(shape, 1)


def test_a_smooth_step_part_reports_the_problem_without_cancelling(tmp_path):
    shape = g.fillet_edges(g.make_box((0, 0, 0), 20, 20, 20), 1)
    doc = Document(str(_step(tmp_path, shape)))
    obj = doc.objects()[0]
    volume = g.volume(obj.shape)
    doc.selection.set([obj.id])
    messages = doc.run("fillet", ["1"])
    assert any("No sharp edges" in m for m in messages)
    assert not any("Command failed" in m or "cancelled" in m for m in messages)
    assert g.volume(doc.get(obj.id).shape) == pytest.approx(volume)


def test_partial_success_keeps_only_the_failed_parts_edges(tmp_path):
    path = _step(tmp_path, g.make_compound([
        g.make_box((0, 0, 0), 1, 1, 1),
        g.make_box((30, 0, 0), 20, 20, 20),
    ]))
    doc = Document(str(path))
    small, large = doc.objects()
    doc.selection.toggle_subobject(small.id, "edge", 0)
    doc.selection.toggle_subobject(large.id, "edge", 0)
    messages = doc.run("fillet", ["No", "2"])
    assert "Filleted 1 edge(s)." in messages
    assert g.volume(doc.get(small.id).shape) == pytest.approx(1)
    assert g.volume(doc.get(large.id).shape) < 8000
    assert doc.selection.subobjects == [(small.id, "edge", 0)]


@pytest.mark.parametrize("command", ["fillet", "filletedge"])
def test_a_failed_picked_edge_stays_selected_for_a_smaller_radius(tmp_path,
                                                               command):
    doc = Document(str(_step(tmp_path, g.make_box((0, 0, 0), 20, 20, 20))))
    obj = doc.objects()[0]
    doc.selection.toggle_subobject(obj.id, "edge", 0)
    messages = doc.run(command, ["No", "999"])
    assert not any("Command failed" in m for m in messages)
    assert g.volume(doc.get(obj.id).shape) == pytest.approx(8000)
    assert doc.selection.subobjects == [(obj.id, "edge", 0)]
    assert "Filleted 1 edge(s)." in doc.run(command, ["No", "1"])
