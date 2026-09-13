"""Trim deletes: each click on a piece takes it away at once (issue #23).

In 0.10.0 the pieces only went after a further Enter, and Escape (or Enter
on nothing) at that step left the object merely split, which read as
"Trim does not trim". Rhino removes the clicked part immediately and the
command carries on until Enter; what was trimmed stays trimmed.
"""

import pytest

import serpentine3d.commands  # registers all commands  # noqa: F401
from serpentine3d.commands.base import CommandContext, CommandProcessor
from serpentine3d.core import geometry as g
from serpentine3d.core.history import History
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager


@pytest.fixture
def env():
    scene = Scene()
    selection = SelectionManager(scene)
    history = History(scene)
    ctx = CommandContext(scene, selection, history)
    proc = CommandProcessor(ctx)
    return scene, ctx, proc


def _three_pieces(scene, proc):
    line = scene.add(g.make_line((0, 0, 0), (30, 0, 0)), name="Target")
    c1 = scene.add(g.make_line((10, -5, 0), (10, 5, 0)), name="Cutter")
    c2 = scene.add(g.make_line((20, -5, 0), (20, 5, 0)), name="Cutter")
    proc.run("trim")
    proc.click_object(c1.id)
    proc.click_object(c2.id)
    proc.finish_selection()
    proc.click_object(line.id)
    pieces = [o for o in scene.all() if o.id not in (c1.id, c2.id)]
    assert len(pieces) == 3
    return line, (c1, c2), pieces


def _model(scene, cutters):
    ids = {c.id for c in cutters}
    return [o for o in scene.all() if o.id not in ids]


def test_a_clicked_piece_goes_at_once_and_the_command_carries_on(env):
    scene, _ctx, proc = env
    _line, cutters, pieces = _three_pieces(scene, proc)
    proc.click_object(pieces[0].id)
    assert scene.get(pieces[0].id) is None, "clicking a piece removes it now"
    assert proc.busy, "Trim keeps going until Enter, like Rhino"
    proc.click_object(pieces[2].id)
    assert scene.get(pieces[2].id) is None
    proc.finish_selection()
    assert not proc.busy
    remaining = _model(scene, cutters)
    assert [o.id for o in remaining] == [pieces[1].id]
    assert g.curve_length(remaining[0].shape) == pytest.approx(10)


def test_escape_keeps_what_was_already_trimmed(env):
    scene, _ctx, proc = env
    _line, cutters, pieces = _three_pieces(scene, proc)
    proc.click_object(pieces[0].id)
    proc.cancel()
    assert not proc.busy
    assert {o.id for o in _model(scene, cutters)} == {
        pieces[1].id, pieces[2].id}


def test_trimming_nothing_leaves_the_object_whole(env):
    scene, _ctx, proc = env
    line, cutters, _pieces = _three_pieces(scene, proc)
    proc.finish_selection()          # Enter without clicking a piece
    assert not proc.busy
    remaining = _model(scene, cutters)
    assert len(remaining) == 1, "no piece chosen, so nothing is split"
    assert g.curve_length(remaining[0].shape) == pytest.approx(30)
    assert remaining[0].name == line.name
    assert remaining[0].layer_id == line.layer_id


def test_one_undo_step_puts_the_whole_object_back(env):
    scene, ctx, proc = env
    line, cutters, pieces = _three_pieces(scene, proc)
    proc.click_object(pieces[0].id)
    proc.finish_selection()
    ctx.history.undo()
    remaining = _model(scene, cutters)
    assert len(remaining) == 1
    assert g.curve_length(remaining[0].shape) == pytest.approx(30)
