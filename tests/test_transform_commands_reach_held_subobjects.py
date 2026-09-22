"""Move, rotate and scale act on what you are holding (#29).

Reported: sub-objects can only be transformed with the gumball, not with
the ordinary transform commands. They could not. The commands asked
`held_control_points`, which keeps only control points, so a held edge,
face or curve segment was invisible. The command then put up its select
prompt, and a select prompt clears the selection to take its answer, so
the thing you were holding was thrown away and the whole object moved
instead. That is worse than doing nothing.

What each kind can be asked to do is decided by the geometry that exists
for it, not by the command:

    curve segment   move, rotate, scale   (any point map)
    solid face      move, rotate, scale   (slide/push, tilt, scale_face)
    solid edge      move only             (move_edge)

An edge that cannot be turned says so and stays held, rather than turning
the solid it belongs to.
"""

from __future__ import annotations

import math

import pytest

import serpentine3d.commands  # registers the commands  # noqa: F401
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
    said: list[str] = []
    ctx.add_echo_listener(said.append)
    return scene, selection, CommandProcessor(ctx), said


def _box(scene):
    return scene.add(g.make_box((0, 0, 0), 10, 10, 10), name="Box")


def _rect(scene):
    return scene.add(g.make_polyline(
        [(0, 0, 0), (10, 0, 0), (10, 6, 0), (0, 6, 0)], closed=True),
        name="Rect")


def _edge_at(shape, mid):
    for i, e in enumerate(g.edges_of(shape)):
        if math.dist(g.centroid(e), mid) < 1e-6:
            return i
    raise AssertionError(f"no edge with midpoint {mid}")


def _top_face(shape):
    for i, f in enumerate(g.faces_of(shape)):
        if g.face_normal(f)[2] > 0.9:
            return i
    raise AssertionError("no upward face")


# --- the reported bug ------------------------------------------------------

def test_holding_a_subobject_means_the_command_has_nothing_to_ask(env):
    scene, sel, proc, _said = env
    box = _box(scene)
    sel.toggle_subobject(box.id, "edge", 0)

    proc.run("move")

    prompt = getattr(proc.request, "prompt", "")
    assert "Select objects" not in prompt, (
        "the select prompt is what threw the held edge away")
    assert "Point to move from" in prompt


def test_the_whole_object_is_not_moved_instead(env):
    scene, sel, proc, _said = env
    box = _box(scene)
    sel.toggle_subobject(box.id, "edge", 0)

    proc.run("move")
    proc.provide((0.0, 0.0, 0.0))
    proc.provide((0.0, 0.0, 5.0))

    lo, _hi = g.bbox(scene.get(box.id).shape)
    assert lo[2] == pytest.approx(0.0, abs=1e-6), (
        "the box itself must stay where it is; only the held edge moves")


# --- move ------------------------------------------------------------------

def test_move_carries_a_held_curve_segment(env):
    scene, sel, proc, _said = env
    rect = _rect(scene)
    sel.toggle_subobject(rect.id, "edge", _edge_at(rect.shape, (5, 0, 0)))

    proc.run("move")
    proc.provide((0.0, 0.0, 0.0))
    proc.provide((0.0, -2.0, 0.0))

    shape = scene.get(rect.id).shape
    lo, hi = g.bbox(shape)
    assert lo == pytest.approx((0, -2, 0), abs=1e-6)
    assert hi == pytest.approx((10, 6, 0), abs=1e-6)
    assert g.is_closed_curve(shape), "the rectangle stays in one piece"


def test_move_carries_a_held_solid_edge(env):
    scene, sel, proc, _said = env
    box = _box(scene)
    before = g.volume(box.shape)
    sel.toggle_subobject(box.id, "edge", 0)

    proc.run("move")
    proc.provide((0.0, 0.0, 0.0))
    proc.provide((2.0, 3.0, 0.0))

    after = g.volume(scene.get(box.id).shape)
    assert after != pytest.approx(before), "the edge moved, so the solid changed"
    assert g.is_valid(scene.get(box.id).shape)


def test_move_carries_a_held_solid_face(env):
    scene, sel, proc, _said = env
    box = _box(scene)
    sel.toggle_subobject(box.id, "face", _top_face(box.shape))

    proc.run("move")
    proc.provide((0.0, 0.0, 0.0))
    proc.provide((0.0, 0.0, 5.0))

    shape = scene.get(box.id).shape
    assert g.volume(shape) == pytest.approx(1500.0, rel=1e-3), (
        "pushing the top face up by 5 makes a 10 by 10 by 15 box")
    assert g.bbox(shape)[1][2] == pytest.approx(15.0, abs=1e-3)


# --- rotate ----------------------------------------------------------------

def test_rotate_turns_a_held_curve_segment(env):
    scene, sel, proc, _said = env
    rect = _rect(scene)
    sel.toggle_subobject(rect.id, "edge", _edge_at(rect.shape, (5, 0, 0)))

    proc.run("rotate")
    proc.provide((5.0, 0.0, 0.0))        # centre
    proc.provide(90.0)                   # angle

    ends = {tuple(round(v, 6) for v in p)
            for e in g.edges_of(scene.get(rect.id).shape)
            for p in g.curve_endpoints(e)}
    assert {(5.0, -5.0, 0.0), (5.0, 5.0, 0.0)} <= ends, (
        "the held side swung about its own middle")
    assert {(0.0, 6.0, 0.0), (10.0, 6.0, 0.0)} <= ends, (
        "the far side stayed put")


def _side_face(shape):
    """A face standing upright, which the vertical axis can actually turn."""
    for i, f in enumerate(g.faces_of(shape)):
        if abs(g.face_normal(f)[2]) < 0.1:
            return i
    raise AssertionError("no upright face")


def test_rotate_tilts_a_held_solid_face(env):
    scene, sel, proc, _said = env
    box = _box(scene)
    before = g.volume(box.shape)
    sel.toggle_subobject(box.id, "face", _side_face(box.shape))

    proc.run("rotate")                    # about the CPlane normal, so Z
    proc.provide((5.0, 5.0, 5.0))
    proc.provide(10.0)

    shape = scene.get(box.id).shape
    assert g.is_valid(shape)
    assert g.volume(shape) != pytest.approx(before), "the face leaned over"


def test_a_face_square_to_the_axis_says_turning_it_would_do_nothing(env):
    """Turning a plane about its own normal leaves the same plane. Saying
    "Rotated 1 face" there would be a lie."""
    scene, sel, proc, said = env
    box = _box(scene)
    before = g.volume(box.shape)
    sel.toggle_subobject(box.id, "face", _top_face(box.shape))

    proc.run("rotate")
    proc.provide((5.0, 5.0, 10.0))
    proc.provide(10.0)

    assert g.volume(scene.get(box.id).shape) == pytest.approx(before)
    assert any("square to the axis" in m for m in said), said
    assert sel.subobjects, "nothing was touched, so it is still held"


# --- scale -----------------------------------------------------------------

def test_scale_resizes_a_held_curve_segment(env):
    scene, sel, proc, _said = env
    rect = _rect(scene)
    sel.toggle_subobject(rect.id, "edge", _edge_at(rect.shape, (5, 0, 0)))

    proc.run("scale")
    proc.provide((5.0, 0.0, 0.0))
    proc.provide(0.5)

    ends = {tuple(round(v, 6) for v in p)
            for e in g.edges_of(scene.get(rect.id).shape)
            for p in g.curve_endpoints(e)}
    assert {(2.5, 0.0, 0.0), (7.5, 0.0, 0.0)} <= ends, (
        "the held side halved about its middle")


def test_scale_resizes_a_held_solid_face(env):
    scene, sel, proc, _said = env
    box = _box(scene)
    before = g.volume(box.shape)
    sel.toggle_subobject(box.id, "face", _top_face(box.shape))

    proc.run("scale")
    proc.provide((5.0, 5.0, 10.0))
    proc.provide(0.5)

    shape = scene.get(box.id).shape
    assert g.is_valid(shape)
    assert g.volume(shape) < before, "a smaller top makes a smaller solid"


# --- what cannot be done says so -------------------------------------------

def test_an_edge_cannot_be_turned_and_says_so(env):
    scene, sel, proc, said = env
    box = _box(scene)
    before = g.volume(box.shape)
    sel.toggle_subobject(box.id, "edge", 0)

    proc.run("rotate")
    proc.provide((5.0, 5.0, 5.0))
    proc.provide(45.0)

    assert g.volume(scene.get(box.id).shape) == pytest.approx(before), (
        "refusing must not fall back to turning the whole solid")
    assert any("edge" in m.lower() for m in said), said
    assert sel.subobjects, "the edge stays held, so you can try something else"


# --- nothing that worked before stops working ------------------------------

def test_a_held_control_point_still_moves(env):
    scene, sel, proc, said = env
    line = scene.add(g.make_line((0, 0, 0), (10, 0, 0)), name="Line")
    sel.toggle_subobject(line.id, "cv", 0)

    proc.run("move")
    proc.provide((0.0, 0.0, 0.0))
    proc.provide((0.0, 4.0, 0.0))

    lo, _hi = g.bbox(scene.get(line.id).shape)
    assert lo[1] == pytest.approx(0.0, abs=1e-6)
    assert any("control point" in m for m in said), said


def test_with_nothing_held_it_still_asks_and_moves_whole_objects(env):
    scene, sel, proc, _said = env
    box = _box(scene)

    proc.run("move")
    assert "Select objects to move" in getattr(proc.request, "prompt", "")
    proc.click_object(box.id)
    proc.finish_selection()
    proc.provide((0.0, 0.0, 0.0))
    proc.provide((0.0, 0.0, 5.0))

    assert g.bbox(scene.get(box.id).shape)[0][2] == pytest.approx(5.0, abs=1e-6)
