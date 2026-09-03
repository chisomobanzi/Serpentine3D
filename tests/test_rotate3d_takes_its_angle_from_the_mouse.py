"""`rotate3d` lets you drag the angle instead of only typing it.

Asked for by a user: rotate3d would be much more usable if it used the
mouse to set the angle, the way plain `rotate` already does. Plain
`rotate` asks for a reference direction and then for where that direction
should end up, previewing the turn as you go; rotate3d stopped at the axis
and demanded a number, which means knowing the answer before you start.

The one thing rotate3d cannot copy from `rotate` is the angle formula.
`rotate` turns about the construction plane normal and its reference
points are picked on that plane, so they are already square to the axis.
rotate3d's axis is any two points in space, so the picks have to be
projected onto the plane square to it first, or a reference point that
happens to lie well along the axis reports almost no angle at all.
"""

from __future__ import annotations

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
    ctx = CommandContext(scene, selection, History(scene))
    echoes: list[str] = []
    ctx.add_echo_listener(echoes.append)
    return scene, selection, ctx, CommandProcessor(ctx), echoes


def _start(proc, obj, axis_a="0,0,0", axis_b="10,0,0"):
    """Run rotate3d up to the point where it wants the angle."""
    proc.run("rotate3d")
    proc.click_object(obj.id)
    proc.finish_selection()
    proc.provide_text(axis_a)
    proc.provide_text(axis_b)


# --- dragging the angle ----------------------------------------------------

def test_two_reference_points_turn_the_object(env):
    """The whole request: point at where the object is, point at where it
    should end up, and it goes there. No angle worked out on paper."""
    scene, _sel, _ctx, proc, _ = env
    tip = scene.add(g.make_point((0, 5, 0)))
    _start(proc, tip)

    proc.provide_text("0,5,0")               # reference: straight out on +Y
    proc.provide_text("0,0,5")               # send it round to +Z

    assert not proc.busy
    assert g.point_coords(scene.get(tip.id).shape) == pytest.approx(
        (0, 0, 5), abs=1e-6)


def test_the_angle_is_measured_square_to_the_picked_axis(env):
    """The bit that cannot be lifted from `rotate`.

    Both reference points here sit ten units along the axis and one unit
    off it, so their full vectors are nearly parallel and the raw angle
    between them is under a degree. Square to the axis they are a clean
    quarter turn apart, and that is the turn the user is pointing at.
    """
    scene, _sel, _ctx, proc, _ = env
    tip = scene.add(g.make_point((0, 5, 0)))
    _start(proc, tip)

    proc.provide_text("10,1,0")
    proc.provide_text("10,0,1")

    assert g.point_coords(scene.get(tip.id).shape) == pytest.approx(
        (0, 0, 5), abs=1e-6), (
        "the part of each pick running along the axis was not taken out")


def test_the_turn_goes_the_way_the_picks_do(env):
    """Reversing the two reference points turns the other way, or the
    drag would feel like it had a mind of its own."""
    scene, _sel, _ctx, proc, _ = env
    tip = scene.add(g.make_point((0, 5, 0)))
    _start(proc, tip)

    proc.provide_text("0,0,5")
    proc.provide_text("0,5,0")

    assert g.point_coords(scene.get(tip.id).shape) == pytest.approx(
        (0, 0, -5), abs=1e-6)


def test_the_second_reference_point_previews_the_turn(env):
    """A drag you cannot see is just a number you cannot type."""
    scene, _sel, _ctx, proc, _ = env
    obj = scene.add(g.make_box((0, 1, -1), 2, 2, 2))
    _start(proc, obj)
    proc.provide_text("0,5,0")

    ghost = proc.preview_for((0.0, 0.0, 5.0))

    assert ghost is not None, "no ghost while dragging the angle round"
    lo, hi = g.bbox(ghost)
    assert hi[1] == pytest.approx(1.0, abs=1e-6), (
        "a quarter turn about X should lay the box down in Z")


# --- typing it still works -------------------------------------------------

def test_typing_an_angle_still_works(env):
    """It was the only way in before, and for a known angle it is still
    the quickest. The reference prompt takes a bare number instead."""
    scene, _sel, _ctx, proc, _ = env
    tip = scene.add(g.make_point((5, 3, 0)))
    _start(proc, tip)

    proc.provide_text("90")

    assert not proc.busy
    assert g.point_coords(scene.get(tip.id).shape) == pytest.approx(
        (5, 0, 3), abs=1e-6)


def test_copy_still_leaves_the_original_behind(env):
    scene, _sel, _ctx, proc, _ = env
    scene.add(g.make_point((0, 5, 0)))
    tip = [o for o in scene.all()][0]
    _start(proc, tip)

    proc.provide_text("Copy=Yes")
    proc.provide_text("0,5,0")
    proc.provide_text("0,0,5")

    assert len(scene.all()) == 2


# --- picks that cannot mean anything ---------------------------------------

def test_a_reference_point_on_the_axis_is_refused(env):
    """It has no direction square to the axis, so there is nothing for the
    second pick to be measured against. Saying so beats turning by zero."""
    scene, _sel, _ctx, proc, echoes = env
    tip = scene.add(g.make_point((0, 5, 0)))
    _start(proc, tip)

    proc.provide_text("4,0,0")               # sitting on the axis itself

    assert not proc.busy
    assert any("axis" in e.lower() for e in echoes), echoes
    assert g.point_coords(scene.get(tip.id).shape) == pytest.approx(
        (0, 5, 0), abs=1e-6), "nothing should have moved"


def test_a_zero_length_axis_is_still_refused(env):
    scene, _sel, _ctx, proc, echoes = env
    tip = scene.add(g.make_point((0, 5, 0)))
    proc.run("rotate3d")
    proc.click_object(tip.id)
    proc.finish_selection()
    proc.provide_text("0,0,0")

    proc.provide_text("0,0,0")

    assert not proc.busy
    assert any("axis" in e.lower() for e in echoes), echoes
