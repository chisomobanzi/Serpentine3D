"""Point picks that show you where you are going.

tests/test_command_interaction.py is the structural rule — no pick after a
command's first may leave the screen dead. These are the behavioural half for
the picks that are not distances: that the ghost actually tracks the cursor,
and that it shows the thing the pick is about to decide.
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
    return scene, selection, history, ctx, CommandProcessor(ctx)


def test_orient3pt_shows_where_the_objects_land(env):
    """The first target point decides where the objects go, so it should
    show them going there — the turn comes with the next two picks."""
    scene, sel, _hist, _ctx, proc = env
    obj = scene.add(g.make_box((0, 0, 0), 2, 2, 2))
    sel.set([obj.id])
    proc.run("orient3pt")
    for p in ((0, 0, 0), (1, 0, 0), (0, 1, 0)):
        proc.provide(tuple(float(c) for c in p))
    assert "first target" in proc.request.prompt.lower()
    ghost = proc.preview_for((10, 0, 0))
    assert ghost is not None, "no ghost while placing the first target point"
    lo, hi = g.bbox(ghost)
    assert lo[0] == pytest.approx(10, abs=1e-6), (
        "the ghost should sit where the cursor is")
    assert hi[0] - lo[0] == pytest.approx(2, abs=1e-6)


def test_orient3pt_still_completes(env):
    scene, sel, _hist, _ctx, proc = env
    obj = scene.add(g.make_box((0, 0, 0), 2, 2, 2))
    sel.set([obj.id])
    proc.run("orient3pt")
    for p in ((0, 0, 0), (1, 0, 0), (0, 1, 0),
              (10, 0, 0), (11, 0, 0), (10, 1, 0)):
        proc.provide(tuple(float(c) for c in p))
    assert not proc.busy
    lo, _hi = g.bbox(scene.get(obj.id).shape)
    assert lo[0] == pytest.approx(10, abs=1e-6)
