"""Ctrl+Z in the middle of a polyline takes back one point, not the polyline.

It used to end the command and then undo whatever was drawn before it, so a
slip on the fifth point cost all five and the object behind them as well.
"""

import pytest

import serpentine3d.commands  # registers all commands  # noqa: F401
from serpentine3d.commands.base import CommandContext, CommandProcessor
from serpentine3d.core import geometry as g
from serpentine3d.core.history import History
from serpentine3d.core.journal import SessionJournal
from serpentine3d.core.replay import Replayer, load_events
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager


@pytest.fixture
def env():
    scene = Scene()
    selection = SelectionManager(scene)
    history = History(scene)
    ctx = CommandContext(scene, selection, history)
    return scene, ctx, CommandProcessor(ctx)


def _polyline_through(proc, *points):
    proc.run("polyline")
    for p in points:
        proc.provide_text(p)


def test_ctrl_z_takes_back_only_the_last_point(env):
    scene, _ctx, proc = env
    _polyline_through(proc, "0,0,0", "10,0,0", "10,10,0")
    proc.run("undo")
    assert proc.busy, "the polyline should still be going"
    assert proc.request.rubber_pts == [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0)]
    proc.provide_text("20,0,0")
    proc.provide_text("")
    made = scene.all()
    assert len(made) == 1
    assert g.curve_length(made[0].shape) == pytest.approx(20.0)


def test_each_press_takes_back_one_more(env):
    _scene, _ctx, proc = env
    _polyline_through(proc, "0,0,0", "10,0,0", "10,10,0")
    proc.run("undo")
    proc.run("undo")
    assert proc.request.rubber_pts == [(0.0, 0.0, 0.0)]
    assert proc.request.prompt == "Next point"


def test_the_first_point_can_be_taken_back_too(env):
    _scene, _ctx, proc = env
    _polyline_through(proc, "0,0,0")
    proc.run("undo")
    assert proc.busy
    assert proc.request.prompt == "Start of polyline"
    assert not proc.request.rubber_pts


def test_one_press_too_many_leaves_the_drawing_alone(env):
    """Ctrl+Z gets pressed repeatedly. Running out of points must not fall
    through to undoing the object that was drawn before the polyline."""
    scene, _ctx, proc = env
    proc.run("line 0,0,0 10,0,0")
    assert len(scene.all()) == 1
    _polyline_through(proc, "0,5,0")
    proc.run("undo")
    proc.run("undo")
    proc.run("undo")
    assert proc.busy
    assert len(scene.all()) == 1


def test_a_relative_point_measures_from_the_point_left_standing(env):
    scene, _ctx, proc = env
    _polyline_through(proc, "0,0,0", "10,0,0", "10,50,0")
    proc.run("undo")
    proc.provide_text("@5,0")
    proc.provide_text("")
    assert g.curve_length(scene.all()[0].shape) == pytest.approx(15.0)


def test_taking_back_the_first_point_restores_the_relative_base(env):
    _scene, ctx, proc = env
    proc.run("line 1,2,3 4,5,6")
    _polyline_through(proc, "0,0,0")
    proc.run("undo")
    assert ctx.last_point == (4.0, 5.0, 6.0)


def test_a_taken_back_point_is_no_longer_offered_as_a_snap(env):
    _scene, _ctx, proc = env
    _polyline_through(proc, "0,0,0", "10,0,0")
    proc.run("undo")
    assert proc.picked_points == [(0.0, 0.0, 0.0)]


def test_typing_undo_is_the_same_as_the_key(env):
    _scene, ctx, proc = env
    _polyline_through(proc, "0,0,0", "10,0,0", "10,50,0")
    proc.provide_text("u")
    assert proc.request.rubber_pts == [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0)]
    assert proc.picked_points == [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0)]
    assert ctx.last_point == (10.0, 0.0, 0.0)


def test_close_goes_by_the_points_that_are_left(env):
    _scene, _ctx, proc = env
    _polyline_through(proc, "0,0,0", "10,0,0", "10,10,0")
    assert "Close" in proc.keyword_chips()
    proc.run("undo")
    assert "Close" not in proc.keyword_chips()


def test_other_commands_still_end_on_undo(env):
    """Nothing but a run of points steps back: the ordinary undo stands."""
    scene, _ctx, proc = env
    proc.run("line 0,0,0 10,0,0")
    proc.run("circle")
    proc.provide_text("0,0,0")
    proc.run("undo")
    assert not proc.busy
    assert len(scene.all()) == 0


def test_undo_outside_a_command_is_untouched(env):
    scene, _ctx, proc = env
    _polyline_through(proc, "0,0,0", "10,0,0", "")
    assert len(scene.all()) == 1
    proc.run("undo")
    assert len(scene.all()) == 0


def test_a_taken_back_point_replays(tmp_path):
    scene = Scene()
    ctx = CommandContext(scene, SelectionManager(scene), History(scene))
    proc = CommandProcessor(ctx)
    journal = SessionJournal(str(tmp_path / "session.jsonl"))
    journal.attach(proc, scene, ctx.history)
    _polyline_through(proc, "0,0,0", "10,0,0", "10,50,0")
    proc.run("undo")
    proc.provide_text("20,0,0")
    proc.provide_text("")
    journal.close()
    r = Replayer(load_events(journal.path))
    r.run()
    assert len(r.scene.all()) == 1
    assert g.curve_length(r.scene.all()[0].shape) == pytest.approx(20.0)
