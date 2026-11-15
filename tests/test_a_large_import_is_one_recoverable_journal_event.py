"""A big drawing is one import, even while its progress pumps the event loop.

The journal must retain the file operation, rather than serialising every
imported shape as an idle edit. Recovery then needs to map the recreated
objects so subsequent hand edits, selections and undo still mean the same work.
"""

import json
import os
import time

import pytest

from serpentine3d import fileio
from serpentine3d.commands.base import CommandContext, CommandProcessor
from serpentine3d.core import geometry as g
from serpentine3d.core.history import History
from serpentine3d.core.journal import SessionJournal
from serpentine3d.core.replay import Replayer, load_events
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager


ezdxf = pytest.importorskip("ezdxf")


def _drawing(tmp_path, n=3):
    doc = ezdxf.new("R2010", units=ezdxf.units.MM)
    for i in range(n):
        doc.modelspace().add_line((i * 10, 0), (i * 10, 5))
    path = tmp_path / "lines.dxf"
    doc.saveas(path)
    return str(path)


def _bounds(scene):
    return sorted(tuple(round(v, 6) for point in obj.bbox() for v in point)
                  for obj in scene.all())


@pytest.fixture
def rig(tmp_path):
    scene = Scene()
    selection = SelectionManager(scene)
    history = History(scene)
    proc = CommandProcessor(CommandContext(scene, selection, history))
    journal = SessionJournal(str(tmp_path / "session.jsonl"))
    journal.attach(proc, scene, history)
    yield scene, selection, history, proc, journal
    journal.close()


@pytest.fixture
def window(tmp_path, monkeypatch):
    from serpentine3d.app import MainWindow
    # MainWindow journal names have second resolution. Keep fast test windows
    # in separate directories rather than appending to the preceding session.
    monkeypatch.setenv("SERP3D_JOURNAL_DIR", str(tmp_path / "journals"))
    win = MainWindow()
    yield win
    win.mark_saved()
    win.close()


def test_dxf_progress_moves_inside_a_large_drawing(tmp_path):
    seen = []
    scene = Scene()
    n = fileio.import_file(scene, _drawing(tmp_path, 1200),
                           progress=lambda f, m: seen.append((f, m)) or True)
    assert n == len(scene.all()) == 1200
    fractions = [f for f, _message in seen]
    assert len([f for f in fractions if 0.0 < f < 1.0]) >= 5, \
        "the bar must advance while the drawing is read, not only at its ends"
    assert fractions == sorted(fractions)
    assert fractions[0] == 0.0 and fractions[-1] == 1.0
    assert all(0.0 <= f <= 1.0 and message for f, message in seen)


def test_cancelling_inside_a_dxf_keeps_the_existing_scene(tmp_path):
    scene = Scene()
    existing = scene.add(g.make_line((-20, 0, 0), (-10, 0, 0)), name="keep")
    before = _bounds(scene)
    layers = [(layer.id, layer.name) for layer in scene.layers.all()]
    seen = []

    def progress(fraction, message):
        seen.append(fraction)
        return fraction < 0.4

    with pytest.raises(fileio.Cancelled):
        fileio.import_file(scene, _drawing(tmp_path, 1200), progress=progress)

    assert existing.id in scene.objects and _bounds(scene) == before
    assert [(layer.id, layer.name) for layer in scene.layers.all()] == layers
    assert any(0.0 < fraction < 1.0 for fraction in seen)


def test_cancel_on_dxf_completion_keeps_the_finished_import(tmp_path):
    scene = Scene()
    assert fileio.import_file(scene, _drawing(tmp_path),
                              progress=lambda f, m: f < 1.0) == 3
    assert len(scene.all()) == 3


def test_the_app_records_one_compact_import_despite_quiet_period_flushes(
        tmp_path, window, monkeypatch):
    from PySide6.QtWidgets import QApplication

    window.processor.run("line -20,0,0 -10,0,0")
    before = set(window.scene.objects)
    real_process = QApplication.processEvents
    flushes = []

    def pump_and_flush(*args, **kwargs):
        real_process(*args, **kwargs)
        flushes.append(len(window.scene.all()))
        window.journal.flush()             # the UI's quiet-period timer

    monkeypatch.setattr(QApplication, "processEvents", pump_and_flush)
    path = _drawing(tmp_path, 80)
    window._import_path(path)              # the shared menu/drop action
    window.journal.flush()
    events = load_events(window.journal.path)
    imports = [event for event in events if event["ev"] == "import"]

    assert flushes, "the app did not pump its progress event loop"
    assert len(imports) == 1, "one file import must be one named journal event"
    assert imports[0]["path"] == path
    assert set(imports[0]["made"]) == set(window.scene.objects) - before
    assert len(imports[0]["made"]) == 80
    assert not [event for event in events if event["ev"] == "edit"], \
        "an import must not leak a BREP delta from a progress flush"
    assert os.path.getsize(window.journal.path) < 80 * 200 + 2000, \
        "journal size should scale with object identities, not BREP payloads"
    assert not window.journal.broken


def test_the_apps_dxf_cancel_is_atomic_and_later_work_still_records(
        tmp_path, window, monkeypatch):
    from PySide6.QtWidgets import QProgressDialog

    window.processor.run("line -20,0,0 -10,0,0")
    before = _bounds(window.scene)
    real_set_value = QProgressDialog.setValue
    cancelled_at = []

    def cancel_partway(dialog, value):
        real_set_value(dialog, value)
        if 20 <= value < 100:
            cancelled_at.append(value)
            dialog.cancel()

    monkeypatch.setattr(QProgressDialog, "setValue", cancel_partway)
    # Exercise the app's cancellation wiring without relying on the fixture
    # taking longer than the progress dialog's repaint throttle interval.
    monkeypatch.setattr(fileio, "throttled", lambda callback: callback)
    window._import_path(_drawing(tmp_path, 1200))
    assert cancelled_at, "Cancel was never offered while the DXF was read"
    assert _bounds(window.scene) == before
    window.processor.run("line -30,0,0 -25,0,0")
    window.journal.write_fingerprint()
    window.journal.flush()
    events = load_events(window.journal.path)
    assert not [event for event in events if event["ev"] == "import"]
    replay = Replayer(events)
    replay.run()
    assert replay.verify() == []
    assert _bounds(replay.scene) == _bounds(window.scene)
    assert not window.journal.broken


@pytest.mark.parametrize("failure", [fileio.Cancelled, ValueError])
def test_a_failed_app_import_does_not_suppress_the_next_command(
        tmp_path, window, monkeypatch, failure):
    from PySide6.QtWidgets import QMessageBox

    def fail(*args, **kwargs):
        raise failure("the read stopped")

    monkeypatch.setattr(fileio, "import_file", fail)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)
    window._import_path(str(tmp_path / "unreadable.dxf"))
    window.processor.run("line 0,0,0 5,0,0")
    window.journal.write_fingerprint()
    window.journal.flush()
    events = load_events(window.journal.path)
    assert not [event for event in events if event["ev"] == "import"]
    replay = Replayer(events)
    replay.run()
    assert replay.verify() == []
    assert _bounds(replay.scene) == _bounds(window.scene)
    assert not window.journal.broken


def test_nested_journal_pauses_wait_for_the_outer_operation(rig):
    scene, selection, history, proc, journal = rig
    with journal.pause():
        scene.add(g.make_line((0, 0, 0), (5, 0, 0)))
        with journal.pause():
            journal.flush()
        journal.flush()
        assert not [event for event in load_events(journal.path)
                    if event["ev"] == "edit"]
    journal.flush()
    assert len([event for event in load_events(journal.path)
                if event["ev"] == "edit"]) == 1


def test_a_journal_pause_that_raises_still_records_later_work(rig):
    scene, selection, history, proc, journal = rig
    with pytest.raises(ValueError, match="stopped"):
        with journal.pause():
            raise ValueError("stopped")
    proc.run("line 0,0,0 5,0,0")
    history.checkpoint("hand move")
    obj = scene.all()[0]
    scene.replace_shape(obj.id, g.translate(obj.shape, (20, 0, 0)))
    journal.flush()
    journal.write_fingerprint()
    replay = Replayer(load_events(journal.path))
    replay.run()
    assert replay.verify() == []
    assert _bounds(replay.scene) == _bounds(scene)


def _with_compact_import(events, path, ids):
    """Use real later command events with the compact import wire format.

    The baseline recorder emits a checkpoint and a shape delta for import.
    Replace only those two records to test recovery independently of the new
    recorder, so a BREP fallback cannot accidentally make recovery pass.
    """
    start = next(i for i, event in enumerate(events)
                 if event["ev"] == "ckpt" and event["label"] == "import")
    assert events[start + 1]["ev"] == "edit"
    assert {made[0] for made in events[start + 1]["made"]} == set(ids)
    return (events[:start] + [{"ev": "import", "path": path, "made": ids}]
            + events[start + 2:])


def test_recovery_reimports_then_follows_hand_edits_and_deletion_by_identity(
        tmp_path, rig):
    scene, selection, history, proc, journal = rig
    proc.run("line -20,0,0 -10,0,0")
    before = set(scene.objects)
    path = _drawing(tmp_path)
    history.checkpoint("import")
    fileio.import_file(scene, path)
    journal.flush()
    imported = [obj for obj in scene.all() if obj.id not in before]
    history.checkpoint("hand move")
    scene.replace_shape(imported[0].id,
                        g.translate(imported[0].shape, (100, 0, 0)))
    journal.flush()
    selection.set([imported[1].id])
    assert proc.run("delete")
    journal.write_fingerprint()
    events = _with_compact_import(load_events(journal.path), path,
                                 [obj.id for obj in imported])

    replay = Replayer(events)
    replay.run()
    assert replay.verify() == []
    assert _bounds(replay.scene) == _bounds(scene)
    assert len(replay.scene.all()) == 3
    assert set(replay.scene.objects).isdisjoint(scene.objects), \
        "the comparison must exercise genuinely regenerated identities"


def test_a_recovered_import_is_one_undo_step_and_redo_restores_it(
        tmp_path, rig):
    scene, selection, history, proc, journal = rig
    proc.run("line -20,0,0 -10,0,0")
    before = set(scene.objects)
    path = _drawing(tmp_path)
    history.checkpoint("import")
    fileio.import_file(scene, path)
    journal.flush()
    ids = [obj.id for obj in scene.all() if obj.id not in before]
    assert proc.run("undo")
    assert len(scene.all()) == 1
    journal.write_fingerprint()
    assert proc.run("redo")
    assert len(scene.all()) == 4
    journal.write_fingerprint()
    events = _with_compact_import(load_events(journal.path), path, ids)

    replay = Replayer(events)
    replay.run()
    assert replay.verify() == []
    assert _bounds(replay.scene) == _bounds(scene)


def test_a_session_containing_only_an_import_is_kept_as_real_work(tmp_path):
    path = tmp_path / "20260101-000001-1.jsonl"
    events = [{"ev": "session", "ver": 1, "app": "0.13.0"},
              {"ev": "import", "path": _drawing(tmp_path), "made": ["a"]}]
    path.write_text("".join(json.dumps(event) + "\n" for event in events),
                    encoding="utf-8")
    old = time.time() - 3 * 86400
    os.utime(path, (old, old))
    journal = SessionJournal.maybe(str(tmp_path))
    try:
        assert path.exists(), "a completed import is work, not an old stub"
    finally:
        journal.close()
