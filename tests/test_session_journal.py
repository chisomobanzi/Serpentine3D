"""The journal: every session is a recipe that can be cooked again.

A model is the sequence of resolved inputs that made it. The command
history echoes that sequence; the journal *records* it — every value a
command actually received, the plane and aim it was resolved against,
every idle edit the gumball made, every undo — so that a session can be
re-executed headless and land on the same geometry. What Rhino cannot
retrofit, this file keeps honest: the recording is only real if the
replay comes back identical.
"""

import json
import math
import os
import time

import numpy as np

import pytest

import serpentine3d.commands  # registers all commands  # noqa: F401
from serpentine3d.commands.base import CommandContext, CommandProcessor
from serpentine3d.core import geometry as g
from serpentine3d.core.cplane import CPlane, PRESETS
from serpentine3d.core.history import History
from serpentine3d.core.journal import SessionJournal
from serpentine3d.core.replay import Replayer, load_events
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager


@pytest.fixture
def rig(tmp_path):
    """A recording setup: scene, processor and an attached journal."""
    scene = Scene()
    selection = SelectionManager(scene)
    history = History(scene)
    ctx = CommandContext(scene, selection, history)
    proc = CommandProcessor(ctx)
    journal = SessionJournal(str(tmp_path / "session.jsonl"))
    journal.attach(proc, scene, history)
    return scene, selection, history, ctx, proc, journal


def _events(journal):
    journal.close()
    if not os.path.exists(journal.path):
        return []          # a session with no work takes its file away
    return _events_open(journal)


def _events_open(journal):
    with open(journal.path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _replay(journal):
    journal.close()
    r = Replayer(load_events(journal.path))
    r.run()
    return r


# -- recording --

def test_a_command_writes_its_recipe(rig):
    scene, sel, hist, ctx, proc, journal = rig
    proc.run("box")
    proc.provide_text("0,0,0")
    proc.provide_text("10,8,0")
    proc.provide_text("5")
    ev = _events(journal)
    assert ev[0]["ev"] == "session"
    cmd = next(e for e in ev if e["ev"] == "cmd")
    assert cmd["name"] == "box"
    vals = [e for e in ev if e["ev"] == "val"]
    assert vals[0]["v"] == {"p": [0.0, 0.0, 0.0]}
    assert vals[1]["v"] == {"p": [10.0, 8.0, 0.0]}
    # the height was typed as "5", but what the command received — and
    # what replays — is the resolved point five up from the far corner
    assert vals[2]["v"] == {"p": [10.0, 8.0, 5.0]}
    fin = next(e for e in ev if e["ev"] == "fin")
    assert fin["ok"] is True
    assert len(fin["made"]) == 1
    assert fin["made"][0] in scene.objects


def test_a_click_and_typed_text_record_the_same_value(rig):
    scene, sel, hist, ctx, proc, journal = rig
    proc.run("line")
    proc.provide((1.0, 2.0, 3.0))              # a click, already resolved
    proc.provide_text("4,5,6")                 # typed
    ev = _events(journal)
    vals = [e["v"] for e in ev if e["ev"] == "val"]
    assert vals == [{"p": [1.0, 2.0, 3.0]}, {"p": [4.0, 5.0, 6.0]}]


def test_a_keyword_answer_is_recorded_as_itself(rig):
    scene, sel, hist, ctx, proc, journal = rig
    proc.run("arc center")
    proc.provide_text("0,0,0")
    proc.provide_text("10,0,0")
    proc.provide_text("90")
    ev = _events(journal)
    vals = [e["v"] for e in ev if e["ev"] == "val"]
    assert vals[0] == {"s": "Center"}
    assert vals[-1] == {"n": 90.0}


def test_an_unknown_command_writes_nothing(rig):
    scene, sel, hist, ctx, proc, journal = rig
    proc.run("no_such_thing")
    assert [e for e in _events(journal) if e["ev"] == "cmd"] == []


def test_a_selection_answer_records_object_ids(rig):
    scene, sel, hist, ctx, proc, journal = rig
    proc.run("box 0,0,0 10,10,0 10")
    box_id = scene.all()[0].id
    sel.set([box_id])
    proc.run("delete")                         # consumes the preselection
    assert len(scene.all()) == 0
    ev = _events(journal)
    picked = [e["v"] for e in ev if e["ev"] == "val" and "ids" in e["v"]]
    assert picked and picked[0]["ids"] == [box_id]


def test_the_journal_survives_a_command_that_dies(rig):
    scene, sel, hist, ctx, proc, journal = rig
    proc.run("line")
    proc.provide_text("0,0,0")
    proc.provide_text("0,0,0")                 # coincident: GeometryError
    ev = _events(journal)
    fin = next(e for e in ev if e["ev"] == "fin")
    assert fin["ok"] is False


# -- idle edits (the gumball's route) --

def test_an_idle_edit_rides_as_a_delta(rig):
    scene, sel, hist, ctx, proc, journal = rig
    proc.run("box 0,0,0 10,10,0 10")
    box = scene.all()[0]
    hist.checkpoint("gumball move")            # what a drag start does
    scene.replace_shape(box.id, g.translate(box.shape, (5.0, 0.0, 0.0)))
    journal.flush()
    ev = _events(journal)
    assert any(e["ev"] == "ckpt" and e["label"] == "gumball move"
               for e in ev)
    edit = next(e for e in ev if e["ev"] == "edit")
    assert [c[0] for c in edit["chg"]] == [box.id]


def test_a_deferred_shape_converting_is_not_an_edit(rig):
    """A deferred shape realising on first read swaps geometry without
    any user act, and must not bloat the journal. The discriminator is
    the shadow itself — it knows it held a promise — not the checkpoint,
    which a paused drag can have already spent."""
    from serpentine3d.core.deferred import DeferredShape
    scene, sel, hist, ctx, proc, journal = rig
    real = g.make_box((0.0, 0.0, 0.0), 4.0, 4.0, 4.0)
    scene.add(DeferredShape(lambda: [real], kind="solid"))
    journal.flush()                            # settle the addition
    n_before = len([e for e in _events_open(journal) if e["ev"] == "edit"])
    _ = scene.all()[0].shape                   # first read: realise
    assert scene.all()[0].shape_ready
    journal.flush()
    ev = _events(journal)
    assert len([e for e in ev if e["ev"] == "edit"]) == n_before


def test_a_drag_that_pauses_and_continues_loses_nothing(rig):
    """The quiet-period timer can flush in the middle of a held drag.
    The movement after the pause arrives with the drag's checkpoint
    already spent, and it is still an edit: swallowing it records the
    object wherever it was when the flush fired, which is exactly the
    kind of lie a replay check exists to catch."""
    scene, sel, hist, ctx, proc, journal = rig
    proc.run("box 0,0,0 10,10,0 10")
    box = scene.all()[0]
    hist.checkpoint("gumball move")
    scene.replace_shape(box.id, g.translate(box.shape, (100.0, 0.0, 0.0)))
    journal.flush()                            # the timer, mid-drag
    obj = scene.all()[0]
    scene.replace_shape(box.id, g.translate(obj.shape, (200.0, 0.0, 0.0)))
    journal.flush()                            # the drag has ended
    r = _replay(journal)
    mn, _mx = g.bbox(r.scene.all()[0].shape)
    assert mn[0] == pytest.approx(300.0, abs=1e-6)


def test_a_paused_alt_drag_copy_loses_nothing(rig):
    """The session that found the bug: an alt-drag copy is an object
    born mid-drag, and the movement after a pause must follow it."""
    scene, sel, hist, ctx, proc, journal = rig
    proc.run("box 0,0,0 10,10,0 10")
    box = scene.all()[0]
    hist.checkpoint("gumball move")
    copy = scene.add(g.translate(box.shape, (50.0, 0.0, 0.0)))
    journal.flush()                            # mid-drag: copy at 50
    scene.replace_shape(copy.id,
                        g.translate(box.shape, (300.0, 0.0, 0.0)))
    journal.flush()                            # released at 300
    r = _replay(journal)
    assert len(r.scene.all()) == 2
    xs = sorted(round(g.bbox(o.shape)[0][0], 6) for o in r.scene.all())
    assert xs == [0.0, 300.0]


def test_a_cancelled_drag_leaves_no_edit(rig):
    scene, sel, hist, ctx, proc, journal = rig
    proc.run("box 0,0,0 10,10,0 10")
    box = scene.all()[0]
    hist.checkpoint("gumball move")
    scene.replace_shape(box.id, g.translate(box.shape, (5.0, 0.0, 0.0)))
    scene.replace_shape(box.id, box.shape)     # drag went back to zero
    hist.discard_checkpoint()                  # what cancel_drag does
    journal.flush()
    ev = _events(journal)
    assert [e for e in ev if e["ev"] == "edit"] == []
    assert [e for e in ev if e["ev"] == "ckpt"] == []


# -- replay --

def _volumes(scene):
    return sorted(round(g.volume(o.shape), 4) for o in scene.all()
                  if o.kind == "solid")


def test_the_journal_replays_to_the_same_scene(rig):
    scene, sel, hist, ctx, proc, journal = rig
    proc.run("box 0,0,0 10,10,0 10")
    proc.run("sphere 2point 20,0,0 30,0,0")
    proc.run("circle 0,30,0 5")
    r = _replay(journal)
    assert len(r.scene.all()) == len(scene.all()) == 3
    assert _volumes(r.scene) == _volumes(scene)
    assert sorted(o.kind for o in r.scene.all()) == \
        sorted(o.kind for o in scene.all())


def test_a_selection_replays_by_new_identity(rig):
    """Replayed ids differ; the journal's id map has to carry the answer
    across, or the wrong object dies."""
    scene, sel, hist, ctx, proc, journal = rig
    proc.run("box 0,0,0 10,10,0 10")
    proc.run("box 20,0,0 30,10,0 10")
    keep_vol = round(g.volume(scene.all()[1].shape), 4)
    sel.set([scene.all()[0].id])
    proc.run("delete")
    r = _replay(journal)
    assert len(r.scene.all()) == 1
    assert round(g.volume(r.scene.all()[0].shape), 4) == keep_vol


def test_undo_and_redo_replay(rig):
    scene, sel, hist, ctx, proc, journal = rig
    proc.run("box 0,0,0 10,10,0 10")
    proc.run("box 20,0,0 30,10,0 10")
    proc.run("undo")
    r = _replay(journal)
    assert len(r.scene.all()) == len(scene.all()) == 1


def test_a_cancelled_command_replays_cancelled(rig):
    scene, sel, hist, ctx, proc, journal = rig
    proc.run("polyline")
    proc.provide_text("0,0,0")
    proc.provide_text("10,0,0")
    proc.cancel()
    proc.run("box 0,0,0 5,5,0 5")
    r = _replay(journal)
    assert len(r.scene.all()) == len(scene.all()) == 1
    assert r.scene.all()[0].kind == "solid"


def test_an_idle_edit_replays(rig):
    scene, sel, hist, ctx, proc, journal = rig
    proc.run("box 0,0,0 10,10,0 10")
    box = scene.all()[0]
    hist.checkpoint("gumball move")
    scene.replace_shape(box.id, g.translate(box.shape, (5.0, 0.0, 0.0)))
    journal.flush()
    r = _replay(journal)
    mn, mx = g.bbox(r.scene.all()[0].shape)
    assert mn[0] == pytest.approx(5.0, abs=1e-6)
    assert mx[0] == pytest.approx(15.0, abs=1e-6)


def test_an_idle_edit_that_makes_and_removes_objects_replays(rig):
    """A gumball extrude births geometry outside any command, and a panel
    delete takes it away the same route; both travel as delta entries."""
    scene, sel, hist, ctx, proc, journal = rig
    proc.run("box 0,0,0 10,10,0 10")
    box = scene.all()[0]
    hist.checkpoint("gumball extrude")
    made = scene.add(g.make_box((20.0, 0.0, 0.0), 5.0, 5.0, 5.0))
    journal.flush()
    hist.checkpoint("delete")
    scene.remove(box.id)
    journal.flush()
    r = _replay(journal)
    assert len(r.scene.all()) == 1
    assert round(g.volume(r.scene.all()[0].shape), 4) == \
        round(g.volume(made.shape), 4)


def test_an_undo_over_an_idle_edit_replays(rig):
    """The delta checkpoints during replay exactly as the drag did live,
    or the undo peels the wrong layer."""
    scene, sel, hist, ctx, proc, journal = rig
    proc.run("box 0,0,0 10,10,0 10")
    box = scene.all()[0]
    hist.checkpoint("gumball move")
    scene.replace_shape(box.id, g.translate(box.shape, (5.0, 0.0, 0.0)))
    journal.flush()
    proc.run("undo")                           # back to the unmoved box
    r = _replay(journal)
    mn, _mx = g.bbox(r.scene.all()[0].shape)
    assert mn[0] == pytest.approx(0.0, abs=1e-6)


def test_the_plane_travels_with_the_point(rig):
    """A box drawn on a Front plane must replay on a Front plane, even
    though the replay has no viewport to ask."""
    scene, sel, hist, ctx, proc, journal = rig

    class FrontPane:
        def active_cplane(self):
            return PRESETS["front"]()
    ctx.viewport = FrontPane()
    proc.run("box 0,0,0 10,0,10 5")            # corners spread on the plane
    mn_live, mx_live = g.bbox(scene.all()[0].shape)
    r = _replay(journal)
    mn, mx = g.bbox(r.scene.all()[0].shape)
    assert mn == pytest.approx(mn_live, abs=1e-6)
    assert mx == pytest.approx(mx_live, abs=1e-6)


def test_replay_skips_commands_that_write_files(rig, tmp_path):
    scene, sel, hist, ctx, proc, journal = rig
    proc.run("box 0,0,0 10,10,0 10")
    out = str(tmp_path / "out.serp")
    proc.run("save")
    proc.provide_text(out)
    assert os.path.exists(out)
    os.unlink(out)
    r = _replay(journal)
    assert len(r.scene.all()) == 1
    assert not os.path.exists(out)             # replay must not write it


def test_a_menu_open_replays_as_a_load(rig, tmp_path):
    scene, sel, hist, ctx, proc, journal = rig
    from serpentine3d import fileio
    donor = Scene()
    donor.add(g.make_box((0, 0, 0), 4.0, 4.0, 4.0))
    path = str(tmp_path / "donor.serp")
    fileio.export_file(donor, path)
    # what MainWindow._open_path does: checkpoint, import, then tell the
    # journal, so the import is one named event rather than a BREP dump
    hist.checkpoint("open")
    fileio.import_file(scene, path)
    journal.note_load(path)
    proc.run("box 20,0,0 30,10,0 10")
    r = _replay(journal)
    assert len(r.scene.all()) == len(scene.all()) == 2
    assert _volumes(r.scene) == _volumes(scene)


# -- verification --

def test_a_journal_with_no_fingerprint_says_so(rig):
    """A session that never saved has nothing to check against, and the
    check must say that rather than call the replay faithful on no
    evidence."""
    scene, sel, hist, ctx, proc, journal = rig
    proc.run("box 0,0,0 10,10,0 10")
    journal.close()
    r = Replayer(load_events(journal.path))
    r.run()
    assert r.fingerprints_checked == 0


def test_the_fingerprint_confirms_a_faithful_replay(rig):
    scene, sel, hist, ctx, proc, journal = rig
    proc.run("box 0,0,0 10,10,0 10")
    proc.run("sphere 20,0,0 5")
    journal.write_fingerprint()
    journal.close()
    r = Replayer(load_events(journal.path))
    r.run()
    assert r.verify() == []
    assert r.fingerprints_checked == 1


def test_the_fingerprint_catches_a_divergence(rig):
    scene, sel, hist, ctx, proc, journal = rig
    proc.run("box 0,0,0 10,10,0 10")
    journal.write_fingerprint()
    journal.close()
    events = load_events(journal.path)
    fp = next(e for e in events if e["ev"] == "fp")
    fp["objects"][0]["size"] = 999.0           # lie about the volume
    r = Replayer(events)
    r.run()
    assert r.verify() != []


# -- the overrides that make a headless replay honest --

def test_the_context_obeys_replay_overrides():
    scene = Scene()
    ctx = CommandContext(scene, SelectionManager(scene), History(scene))
    front = PRESETS["front"]()
    ctx.replay_cplane = front
    ctx.replay_aim = ((0.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    assert ctx.cplane is front
    assert ctx.aim_direction() == ((0.0, 0.0, 0.0), (0.0, 1.0, 0.0))


def test_the_window_keeps_a_journal_of_its_own(tmp_path, monkeypatch):
    """The whole loop through the real app: model, close, replay, match."""
    monkeypatch.setenv("SERP3D_JOURNAL_DIR", str(tmp_path))
    monkeypatch.setenv("SERP3D_CONFIG", str(tmp_path / "cfg.json"))
    from serpentine3d.app import MainWindow
    w = MainWindow()
    w.viewport.resize(640, 480)
    assert w.journal is not None
    w.processor.run("box 0,0,0 10,10,0 10")
    w.processor.run("sphere 30,0,0 5")
    live_vols = _volumes(w.scene)
    w.mark_saved()
    w.close()                                  # fingerprints and closes it
    files = [f for f in os.listdir(tmp_path) if f.endswith(".jsonl")]
    assert len(files) == 1
    r = Replayer(load_events(str(tmp_path / files[0])))
    r.run()
    assert r.verify() == []
    assert _volumes(r.scene) == live_vols


def test_a_window_in_a_test_never_writes_into_the_real_directories():
    """The suite keeps its own sessions somewhere it can throw away.

    Every MainWindow opens a journal, and a suite run builds dozens of
    them. Pointed at the real directory that buries the sessions a
    person actually modelled in under test noise, and every command a
    test runs is a recording of work nobody did.

    The autosave slot next door is the same shape of accident: a test
    process that dies leaves a lockfile with a dead pid, which is
    exactly what a crashed session looks like, so the next real launch
    offers to recover a scene out of somebody's test.
    """
    from serpentine3d.app import MainWindow
    from serpentine3d.core.journal import JOURNAL_DIR
    from serpentine3d.utils.autosave import AUTOSAVE_DIR

    def inside(directory, path):
        return os.path.realpath(path).startswith(
            os.path.realpath(directory) + os.sep)

    w = MainWindow()
    try:
        assert w.journal is not None            # still worth exercising
        assert not inside(JOURNAL_DIR, w.journal.path)
        assert not inside(AUTOSAVE_DIR, w.autosave.autosave_path)
    finally:
        w.mark_saved()
        w.close()


def test_journal_can_be_disabled_by_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SERP3D_NO_JOURNAL", "1")
    assert SessionJournal.maybe(str(tmp_path)) is None
    monkeypatch.delenv("SERP3D_NO_JOURNAL")
    j = SessionJournal.maybe(str(tmp_path))
    assert j is not None
    j.close()


# -- pruning: a recipe is not a cache entry --


def _write_journal(path, events, when=None):
    path.write_text("".join(json.dumps(e) + "\n" for e in events),
                    encoding="utf-8")
    if when is not None:
        os.utime(path, (when, when))
    return path


def _stub(path, when=None):
    """A session that opened, looked around, and closed again."""
    return _write_journal(path, [{"ev": "session", "ver": 1, "app": "0"}],
                          when)


def _worked(path, when=None, ev="cmd"):
    """A session with real work in it."""
    body = ({"ev": "cmd", "name": "box", "sel": []} if ev == "cmd"
            else {"ev": "edit", "made": [], "chg": [], "gone": []})
    return _write_journal(path, [{"ev": "session", "ver": 1, "app": "0"},
                                 body], when)


def test_a_session_with_work_is_never_evicted_to_make_room(tmp_path):
    """The bug that ate a week of Voyager sessions.

    Pruning to the newest N at startup treats a recipe like a cache
    entry, so a burst of short sessions silently deletes the ones
    somebody actually modelled in. Age is not a reason to throw work
    away; nothing anybody built is ever evicted for room.
    """
    old = time.time() - 90 * 86400
    for i in range(60):
        _worked(tmp_path / f"20260101-{i:06d}-1.jsonl", when=old)
    j = SessionJournal.maybe(str(tmp_path))
    try:
        kept = [f for f in os.listdir(tmp_path) if f.endswith(".jsonl")]
        assert len(kept) == 61          # the 60 recipes, plus this session
    finally:
        j.close()


def test_a_session_that_recorded_nothing_takes_itself_away(tmp_path):
    """Opening the app and closing it should not leave litter behind."""
    j = SessionJournal.maybe(str(tmp_path))
    path = j.path
    j.close()
    assert not os.path.exists(path)


def test_a_session_that_recorded_something_stays(tmp_path, monkeypatch):
    monkeypatch.setenv("SERP3D_JOURNAL_DIR", str(tmp_path))
    monkeypatch.setenv("SERP3D_CONFIG", str(tmp_path / "cfg.json"))
    from serpentine3d.app import MainWindow
    w = MainWindow()
    w.viewport.resize(640, 480)
    path = w.journal.path
    w.processor.run("box 0,0,0 10,10,0 10")
    w.mark_saved()
    w.close()
    assert os.path.exists(path)
    assert any(json.loads(ln)["ev"] == "cmd"
               for ln in open(path, encoding="utf-8") if ln.strip())


def test_an_abandoned_stub_is_swept_but_the_work_beside_it_is_not(tmp_path):
    """A crash leaves a stub behind; close() never got to remove it."""
    old = time.time() - 3 * 86400
    stub = _stub(tmp_path / "20260101-000001-1.jsonl", when=old)
    real = _worked(tmp_path / "20260101-000002-1.jsonl", when=old)
    j = SessionJournal.maybe(str(tmp_path))
    j.close()
    assert not stub.exists()
    assert real.exists()


def test_a_second_window_still_open_keeps_its_stub(tmp_path):
    """Another window's journal is a stub until its first command."""
    live = _stub(tmp_path / "20260101-000003-1.jsonl")     # mtime is now
    j = SessionJournal.maybe(str(tmp_path))
    j.close()
    assert live.exists()


def test_a_session_of_nothing_but_gumball_work_is_work(tmp_path):
    """An edit is a drag or a control point: no command, still a model."""
    old = time.time() - 3 * 86400
    p = _worked(tmp_path / "20260101-000004-1.jsonl", when=old, ev="edit")
    j = SessionJournal.maybe(str(tmp_path))
    j.close()
    assert p.exists()


# -- imported meshes --


def _tetra(scale=1.0):
    from serpentine3d.core.mesh import MeshShape
    verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]],
                     float) * scale
    tris = np.array([[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]], np.uint32)
    return MeshShape(verts, tris)


def test_an_imported_mesh_does_not_stop_every_command(rig):
    """One FBX in the drawing used to end the session.

    A mesh cannot be written as a BREP, so the idle flush raised on it,
    and the flush is the first thing a command does. The dirty flag
    survived the throw, so the next command raised too, and the next:
    delete, hide and move all silently did nothing for the rest of the
    session, on the whole drawing and not just the mesh.
    """
    scene, sel, hist, ctx, proc, journal = rig
    hist.checkpoint("import")
    scene.add(_tetra(), name="voyager")
    journal.flush()                            # what the quiet timer does
    proc.run("box 0,0,0 10,10,0 10")
    assert len(scene.all()) == 2
    sel.set([scene.all()[0].id])
    assert proc.run("delete") is True
    assert len(scene.all()) == 1


def test_a_mesh_moved_by_hand_replays_where_it_was_put(rig):
    scene, sel, hist, ctx, proc, journal = rig
    hist.checkpoint("import")
    obj = scene.add(_tetra(), name="voyager")
    journal.flush()
    hist.checkpoint("gumball")
    moved = obj.shape.translated((0.0, 0.0, 100.0))
    scene.replace_shape(obj.id, moved)
    journal.flush()
    r = _replay(journal)
    back = r.scene.all()[0]
    assert np.allclose(back.shape.vertices, moved.vertices)


def test_a_recorder_that_fails_does_not_take_the_command_with_it(rig,
                                                                monkeypatch):
    """Losing the recording is a smaller thing than losing the work."""
    scene, sel, hist, ctx, proc, journal = rig
    from serpentine3d.core import geometry as geo

    def boom(shape):
        raise RuntimeError("no")

    monkeypatch.setattr(geo, "shape_to_bytes", boom)
    hist.checkpoint("import")
    scene.add(_tetra(), name="voyager")
    journal.flush()
    assert proc.run("box 0,0,0 10,10,0 10") is True
    assert len(scene.all()) == 2
    assert journal.broken is True
