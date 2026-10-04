"""SetPt candidates travel through the real window, input, and axis chips.

Command geometry and drawing are covered separately. These tests check the
geometry each pane receives when the user changes the current candidate.
"""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from serpentine3d.commands.base import PointReq, SelectReq
from serpentine3d.core import geometry as g


TARGET = (40.0, 50.0, 12.0)


@pytest.fixture
def window():
    from serpentine3d.app import MainWindow

    w = MainWindow()
    w.resize(1200, 800)
    w.set_view_layout("quad")
    try:
        yield w
    finally:
        if w.processor.busy:
            w.processor.cancel()
        w.mark_saved()
        w.close()


def _start(w):
    point = w.scene.add(g.make_point((1.0, 2.0, 3.0)))
    line = w.scene.add(g.make_line((5.0, 6.0, 7.0), (9.0, 10.0, 11.0)))
    objects = [point, line]
    originals = [obj.shape for obj in objects]
    w.selection.set([obj.id for obj in objects])
    w.command_line.run_command("setpt")
    assert isinstance(w.processor.request, PointReq)
    assert len(w.all_viewports()) == 4
    return objects, originals


def _cursor(w, target=TARGET, pane=0):
    # A normal later cursor event is beyond the application's 30 Hz cap.
    QTest.qWait(35)
    w.all_viewports()[pane].mouseWorldMoved.emit(target)


def _type(w, text):
    w.command_line.input.selectAll()
    QTest.keyClicks(w.command_line.input, text)


def _candidate(w, input_kind):
    if input_kind == "cursor":
        _cursor(w, pane=2)
    else:
        _type(w, "40,50,12")


def _axis(w, name):
    chip = next(chip for chip in w.command_line._chips
                if chip.text().split("=", 1)[0] == name)
    chip.click()


def _assert_result_in_every_pane(w, point, line):
    for pane in w.all_viewports():
        mesh = pane._ghost
        assert mesh is not None, \
            f"{pane._view_name} lost the current SetPt result"
        assert mesh.points == pytest.approx(np.asarray([point]), abs=1e-5)
        segments = mesh.edge_segments.reshape(-1, 3)
        assert len(segments), "the selected curve must remain in the ghost"
        assert segments.min(axis=0) == pytest.approx(
            np.asarray(line).min(axis=0), abs=1e-5)
        assert segments.max(axis=0) == pytest.approx(
            np.asarray(line).max(axis=0), abs=1e-5)


def _assert_default_result(w, z=12.0):
    _assert_result_in_every_pane(w, (1.0, 2.0, z),
                               ((5.0, 6.0, z), (9.0, 10.0, z)))


def _assert_clear(w):
    assert all(pane._ghost is None for pane in w.all_viewports()), \
        "no pane may retain an ownerless SetPt ghost"


def _assert_originals(w, objects, originals):
    assert len(w.scene.all()) == len(objects)
    for obj, original in zip(objects, originals):
        assert w.scene.get(obj.id).shape.IsSame(original), \
            "previewing or cancelling must not edit the originals"


@pytest.mark.parametrize("pane", range(4),
                         ids=("perspective", "top", "front", "right"))
def test_mouse_world_from_any_pane_updates_the_result_in_all_panes(window, pane):
    objects, originals = _start(window)
    _cursor(window, pane=pane)
    _assert_default_result(window)
    _cursor(window, (80.0, 90.0, 24.0), pane=pane)
    _assert_default_result(window, z=24.0)
    _assert_originals(window, objects, originals)


def test_typing_coordinates_updates_the_result_in_all_panes(window):
    objects, originals = _start(window)
    _type(window, "40,50,12")
    _assert_default_result(window)
    _type(window, "80,90,24")
    _assert_default_result(window, z=24.0)
    _assert_originals(window, objects, originals)


@pytest.mark.parametrize("input_kind", ("cursor", "typed"))
def test_axis_chips_immediately_recompute_the_current_candidate(window, input_kind):
    objects, originals = _start(window)
    request = window.processor.request
    _candidate(window, input_kind)
    _assert_default_result(window)

    _axis(window, "X")
    _assert_result_in_every_pane(window, (40.0, 2.0, 12.0),
                               ((40.0, 6.0, 12.0), (40.0, 10.0, 12.0)))
    _axis(window, "Z")
    _assert_result_in_every_pane(window, (40.0, 2.0, 3.0),
                               ((40.0, 6.0, 7.0), (40.0, 10.0, 11.0)))
    assert window.processor.request is request
    _assert_originals(window, objects, originals)


@pytest.mark.parametrize("input_kind", ("cursor", "typed"))
def test_all_axes_off_clears_and_reenabling_restores_without_new_input(window, input_kind):
    objects, originals = _start(window)
    _candidate(window, input_kind)
    _assert_default_result(window)

    _axis(window, "Z")
    _assert_clear(window)
    _axis(window, "Z")
    _assert_default_result(window)
    _assert_originals(window, objects, originals)


def test_invalid_typed_coordinates_do_not_restore_an_older_candidate(window):
    objects, originals = _start(window)
    _cursor(window, (80.0, 90.0, 24.0), pane=1)
    _type(window, "40,50,12")
    _assert_default_result(window)
    _type(window, "40,50,invalid")
    _assert_clear(window)

    _axis(window, "X")
    _assert_clear(window)
    _axis(window, "Z")
    _assert_clear(window)
    _axis(window, "Z")
    _assert_clear(window)
    _assert_originals(window, objects, originals)


@pytest.mark.parametrize("input_kind", ("cursor", "typed"))
def test_confirmation_applies_the_displayed_result_and_clears_every_pane(window, input_kind):
    objects, _originals = _start(window)
    _candidate(window, input_kind)
    _assert_default_result(window)
    ghost = window.all_viewports()[2]._ghost
    shown_point = ghost.points.copy()
    shown_line = ghost.edge_segments.reshape(-1, 3).copy()

    if input_kind == "cursor":
        window.all_viewports()[2].pointPicked.emit(TARGET)
    else:
        QTest.keyClick(window.command_line.input, Qt.Key.Key_Return)

    assert not window.processor.busy
    _assert_clear(window)
    assert np.asarray([g.point_coords(window.scene.get(objects[0].id).shape)]) \
        == pytest.approx(shown_point, abs=1e-5)
    assert np.asarray(g.bbox(window.scene.get(objects[1].id).shape)) \
        == pytest.approx(np.asarray([shown_line.min(axis=0),
                                     shown_line.max(axis=0)]), abs=1e-5)


@pytest.mark.parametrize("input_kind", ("cursor", "typed"))
def test_escape_clears_every_pane_and_preserves_originals(window, input_kind):
    objects, originals = _start(window)
    _candidate(window, input_kind)
    _assert_default_result(window)

    QTest.keyClick(window.command_line.input, Qt.Key.Key_Escape)

    assert not window.processor.busy
    _assert_clear(window)
    _assert_originals(window, objects, originals)


@pytest.mark.parametrize("input_kind", ("cursor", "typed"))
@pytest.mark.parametrize("next_command", ("line", "setpt"))
def test_starting_another_request_does_not_inherit_the_old_candidate(
        window, input_kind, next_command):
    objects, originals = _start(window)
    old_request = window.processor.request
    _candidate(window, input_kind)
    _assert_default_result(window)

    # This is the window route used by command actions, even while busy.
    window.run_command(next_command)

    assert window.processor.request is not old_request
    _assert_clear(window)
    if next_command == "setpt":
        # Replacing a command cancels its selection, so make the next pick
        # through the normal pane signals and finish the selection prompt.
        assert isinstance(window.processor.request, SelectReq)
        for obj in objects:
            window.all_viewports()[1].objectClicked.emit(
                obj.id, Qt.KeyboardModifier.NoModifier)
        window.command_line.input.selectAll()
        QTest.keyClick(window.command_line.input, Qt.Key.Key_Backspace)
        QTest.keyClick(window.command_line.input, Qt.Key.Key_Return)
        assert isinstance(window.processor.request, PointReq)
        _assert_clear(window)
        _axis(window, "X")
        _assert_clear(window)
        _cursor(window, (80.0, 90.0, 24.0), pane=3)
        _assert_result_in_every_pane(window, (80.0, 2.0, 24.0),
                                   ((80.0, 6.0, 24.0), (80.0, 10.0, 24.0)))
    else:
        assert isinstance(window.processor.request, PointReq)
    _assert_originals(window, objects, originals)
