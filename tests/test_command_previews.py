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


def test_a_control_point_curve_is_previewed_as_it_will_be_built(env):
    """The ghost takes the cursor as its next control point, so what you are
    looking at is the curve the next click makes."""
    _scene, _sel, _hist, _ctx, proc = env
    proc.run("curve")
    for p in ("0,0", "10,10", "20,-10"):
        proc.provide_text(p)
    ghost = proc.preview_for((30.0, 0.0, 0.0))
    assert ghost is not None, "no curve under the cursor while drawing one"
    poles = g.get_control_points(ghost)
    assert poles[-1] == pytest.approx((30, 0, 0), abs=1e-9)
    assert len(poles) == 4


def test_an_interpolated_curve_is_previewed_through_its_points(env):
    _scene, _sel, _hist, _ctx, proc = env
    proc.run("interpcrv")
    for p in ("0,0", "10,10", "20,-10"):
        proc.provide_text(p)
    ghost = proc.preview_for((30.0, 0.0, 0.0))
    assert ghost is not None
    for want in ((0, 0, 0), (10, 10, 0), (20, -10, 0), (30, 0, 0)):
        assert g.distance_point_to_shape(ghost, want) < 1e-6


def test_the_preview_is_the_curve_and_not_the_chain_of_picks(env):
    """The complaint this fixes: the straight chain between the picks was
    the only thing on screen, and it is the one shape the curve is not."""
    _scene, _sel, _hist, _ctx, proc = env
    proc.run("interpcrv")
    for p in ("0,0", "10,10", "20,-10"):
        proc.provide_text(p)
    ghost = proc.preview_for((30.0, 0.0, 0.0))
    midpoint_of_a_straight_leg = (5.0, 5.0, 0.0)
    assert g.distance_point_to_shape(ghost, midpoint_of_a_straight_leg) > 0.1


def test_the_first_pick_of_a_curve_has_nothing_to_preview_yet(env):
    """One point and a cursor is a line, and drawing one would say the
    command makes lines. Two is the first honest preview."""
    _scene, _sel, _hist, _ctx, proc = env
    proc.run("curve")
    assert proc.preview_for((10.0, 0.0, 0.0)) is None


def test_a_curve_preview_survives_a_cursor_on_top_of_the_last_point(env):
    """Coincident points have no curve through them. The ghost goes quiet
    rather than the command falling over."""
    _scene, _sel, _hist, _ctx, proc = env
    proc.run("interpcrv")
    for p in ("0,0", "10,10"):
        proc.provide_text(p)
    proc.preview_for((10.0, 10.0, 0.0))     # must not raise
    assert proc.busy


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
