"""Direct inline text and Properties edits survive session recovery."""

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QDialog

from serpentine3d.app import MainWindow
from serpentine3d.commands.base import PointReq
from serpentine3d.core import geometry as g
from serpentine3d.core.cplane import CPlane
from serpentine3d.core.journal import SessionJournal
from serpentine3d.core.replay import Replayer, load_events
from serpentine3d.core.text import TextShape
from tests.conftest import StubViewport
from tests import test_text_can_be_formatted_placed_and_edited as editor


typography = editor.typography


@pytest.fixture
def recording_window(tmp_path, monkeypatch):
    monkeypatch.setenv("SERP3D_JOURNAL_DIR", str(tmp_path / "journals"))
    w = MainWindow()
    w.resize(1200, 850)
    w.show()
    QApplication.processEvents()
    assert w.journal is not None
    yield w
    w.processor.cancel()
    w.viewport.end_inline_text()
    w.mark_saved()
    w.close()


def _recover(journal, monkeypatch):
    assert not journal.broken, (
        f"Using the text editor stopped session recording: {journal.failure!r}")
    journal.write_fingerprint()
    journal.close()

    def unexpected_dialog(_dialog):
        pytest.fail("A recovered command must use recorded typography, without a dialog")

    with monkeypatch.context() as patch:
        patch.setattr(QDialog, "exec", unexpected_dialog)
        replay = Replayer(load_events(journal.path))
        replay.run()
    assert replay.verify() == []
    assert not replay.proc.busy
    return replay.scene


def _new_sheet(proc):
    proc.run("layout New Typography A3 Landscape")
    assert not proc.busy
    sheet, = proc.ctx.scene.layouts
    return sheet


def _place_text(window, values, position, *, command="textobject", curves=False):
    if command == "textobject":
        if curves:
            window.processor.run(command)
            assert isinstance(window.processor.request, PointReq)
            window.processor.provide(position)
            QApplication.processEvents()
            editor._type_live(window, values["text"], "curves")
            editor._finish_inline(window)
            assert not window.processor.busy
            return
        editor._place_model(window, values, position=position)
        return
    window.processor.run(command)
    assert isinstance(window.processor.request, PointReq)
    window.processor.provide(position)
    QApplication.processEvents()
    editor._type_live(window, values["text"])
    editor._finish_inline(window)
    assert not window.processor.busy
    note, = window.viewport.layout_view.layout.notes
    window._edit_paper_text_in_viewport(window.viewport, note.id)
    QApplication.processEvents()
    editor._configure_live(window, values, in_properties=True)
    editor._finish_inline(window)


@pytest.mark.parametrize("curves", [False, True])
def test_editor_lettering_recovers_its_placement_and_contours(
        recording_window, monkeypatch, typography, curves):
    w = recording_window
    editor._forbid_modal(monkeypatch)
    values = dict(typography, text="BOR")
    w.viewport.cplane = CPlane(origin=(0., 8., 0.), normal=(0., -1., 0.),
                              xdir=(1., 0., 0.))
    _place_text(w, values, (25., 8., 40.), curves=curves)
    originals = w.scene.all()
    assert len(originals) == (7 if curves else 1)
    if curves:
        original_solids = g.extrude_profiles(
            [o.shape for o in originals], (0., -1., 0.), 3., cap=True)
        assert len(original_solids) == 3
        expected_volumes = sorted(g.volume(s) for s in original_solids)

    recovered = _recover(w.journal, monkeypatch)
    objects = recovered.all()
    assert len(objects) == len(originals)
    for before, after in zip(originals, objects):
        np.testing.assert_allclose(after.bbox(), before.bbox(), atol=1e-5)
    if curves:
        assert all(g.is_closed_curve(o.shape) for o in objects)
        group, = {o.group_id for o in objects}
        assert group, "The recovered outer letters and counters must remain grouped"
        assert set(recovered.expand_group_ids([objects[0].id])) == {o.id for o in objects}
        solids = g.extrude_profiles([o.shape for o in objects], (0., -1., 0.), 3., cap=True)
        assert len(solids) == 3, "B, O and R must extrude as three letters with holes"
        assert all(g.shape_kind(s) == "solid" and g.is_valid(s) for s in solids)
        assert sorted(g.volume(s) for s in solids) == pytest.approx(expected_volumes, rel=1e-6)
    else:
        assert isinstance(objects[0].shape, TextShape)
        editor._same_typography(objects[0].shape, values)
        np.testing.assert_allclose(objects[0].shape.origin, (25., 8., 40.))


def test_properties_edits_to_model_text_recover_as_editable_text(
        recording_window, monkeypatch, typography):
    w = recording_window
    editor._forbid_modal(monkeypatch)
    editor._place_model(w, typography)
    original, = w.scene.all()
    w.selection.set([original.id])
    changed = dict(typography, text="Revised title\nSouth wing", height=5., alignment="right")
    w._edit_model_text_in_viewport(w.viewport, original.id)
    QApplication.processEvents()
    editor._configure_live(w, changed, in_properties=True)
    editor._finish_inline(w)

    recovered = _recover(w.journal, monkeypatch)
    obj, = recovered.all()
    assert isinstance(obj.shape, TextShape)
    editor._same_typography(obj.shape, changed)
    np.testing.assert_allclose(obj.shape.origin, (25., 35., 0.))
    np.testing.assert_allclose(obj.bbox(), w.scene.all()[0].bbox(), atol=1e-5)


@pytest.mark.parametrize("edit_after_placement", [False, True])
def test_formatted_notes_recover_on_their_sheet(
        recording_window, monkeypatch, typography, edit_after_placement):
    w = recording_window
    editor._forbid_modal(monkeypatch)
    sheet = _new_sheet(w.processor)
    assert w.viewport.space == sheet.id
    _place_text(w, typography, (50., 70., 0.), command="text")
    note, = sheet.notes
    expected = typography
    if edit_after_placement:
        editor._pick_note(w, note)
        expected = dict(typography, text="Revised note\nSecond line", height=4., alignment="right")
        w._edit_paper_text_in_viewport(w.viewport, note.id)
        QApplication.processEvents()
        editor._configure_live(w, expected, in_properties=True)
        editor._finish_inline(w)

    recovered = _recover(w.journal, monkeypatch)
    recovered_sheet, = recovered.layouts
    assert recovered_sheet.name == sheet.name
    recovered_note, = recovered_sheet.notes
    editor._same_typography(recovered_note, expected)
    assert (recovered_note.x, recovered_note.y) == (50., 70.)
    assert not recovered.all(), "Paper text must remain on the sheet"


@pytest.mark.parametrize("command", ["textobject", "text"])
@pytest.mark.parametrize("stage", ["anchor", "inline"])
def test_cancelled_text_does_not_return_during_recovery(
        recording_window, monkeypatch, typography, command, stage):
    w = recording_window
    editor._forbid_modal(monkeypatch)
    # Keep a real preceding command, so even an entirely cancelled editor
    # session has a journal and a useful object that must survive recovery.
    w.processor.run("line 0,0,0 10,0,0")
    if command == "text":
        _new_sheet(w.processor)
    w.processor.run(command)
    assert isinstance(w.processor.request, PointReq)
    if stage == "anchor":
        w.processor.cancel()
    else:
        w.processor.provide((20., 30., 0.))
        QApplication.processEvents()
        editor._finish_inline(w)  # Empty inline text cancels the command.

    recovered = _recover(w.journal, monkeypatch)
    line, = recovered.all()
    assert g.curve_length(line.shape) == pytest.approx(10.)
    assert all(not sheet.notes and not sheet.objects for sheet in recovered.layouts)


def test_existing_scripted_text_sequences_remain_recoverable(env, tmp_path, monkeypatch):
    scene, _selection, history, ctx, proc = env
    journal = SessionJournal(str(tmp_path / "scripted.jsonl"))
    journal.attach(proc, scene, history)
    proc.run("textobject")
    for answer in ("BOR", "10,20,0", "7"):
        proc.provide_text(answer)
    assert not proc.busy
    original_bounds = [o.bbox() for o in scene.all()]
    assert len(original_bounds) == 7
    sheet = _new_sheet(proc)
    ctx.viewport = StubViewport(sheet.id)
    proc.run("text")
    for answer in ("50,70", "First line\\nSecond line", "4"):
        proc.provide_text(answer)
    assert not proc.busy
    assert sheet.notes[0].text == "First line\nSecond line"

    recovered = _recover(journal, monkeypatch)
    np.testing.assert_allclose([o.bbox() for o in recovered.all()], original_bounds, atol=1e-5)
    recovered_sheet, = recovered.layouts
    note, = recovered_sheet.notes
    assert (note.text, note.height, note.x, note.y) == ("First line\nSecond line", 4., 50., 70.)
