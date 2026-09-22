"""Held faces and edges of a solid move together, as one change.

Found through the band (issue #30): a band round a box holds every face
and edge, a window round its top holds the top face and the four edges
round it, and `move` on either did something wrong. The parts were moved
one after another, and moving one part tilts the faces beside it, which
carries the next held part some of the way before it is moved its full
distance again. Four rim edges moved up 5 made a box 20 high, not 15;
six faces moved up 5 made a box half the size, 15 units off.

The right question is not "where does each part go, in turn" but "which
corners move". Every corner of a held face or edge moves by the delta. A
face all of whose corners move is carried whole; a face none of whose
corners move stays; a face in between leans to the one plane through its
moved and unmoved corners, and if no such plane exists the move is
refused rather than the face bent. That reproduces what moving a single
face or edge already did, and makes any set of parts mean one thing.
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


def _box():
    return g.make_box((0, 0, 0), 10, 10, 10)


def _face_where(shape, normal):
    for i, f in enumerate(g.faces_of(shape)):
        n = g.face_normal(f)
        if sum(a * b for a, b in zip(n, normal)) > 0.9:
            return i
    raise AssertionError(f"no face facing {normal}")


def _edges_where(shape, test):
    return [i for i, e in enumerate(g.edges_of(shape)) if test(g.centroid(e))]


def _top_rim(shape):
    return _edges_where(shape, lambda c: c[2] == 10 and 5 in (c[0], c[1]))


def _size(shape):
    lo, hi = g.bbox(shape)
    return tuple(round(hi[i] - lo[i], 6) for i in range(3))


# --- edges ------------------------------------------------------------------

def test_the_four_rim_edges_of_the_top_move_the_top(box=None):
    box = _box()

    out = g.move_parts(box, [], _top_rim(box), (0, 0, 5))

    assert _size(out) == (10, 10, 15), "not 20: the top went up once"
    assert g.volume(out) == pytest.approx(1500)
    assert g.is_valid(out)


def test_two_opposite_rim_edges_lift_the_top_flat():
    box = _box()
    rim = [i for i in _top_rim(box) if g.centroid(g.edges_of(box)[i])[1] == 5]

    out = g.move_parts(box, [], rim, (0, 0, 5))

    assert _size(out) == (10, 10, 15)
    assert g.volume(out) == pytest.approx(1500)


def test_one_edge_still_moves_the_way_it_did():
    """The single case is unchanged: the two faces beside it lean."""
    box = _box()
    (edge,) = [i for i in _top_rim(box)
               if g.centroid(g.edges_of(box)[i])[0] == 0]

    out = g.move_parts(box, [], [edge], (0, 0, 5))
    same = g.move_edge(box, edge, (0, 0, 5))

    assert g.volume(out) == pytest.approx(g.volume(same))
    assert _size(out) == _size(same)


def test_an_edge_moved_along_itself_is_nothing():
    box = _box()
    (upright,) = _edges_where(box, lambda c: c[:2] == (0, 0))[:1] or [None]

    with pytest.raises(g.GeometryError):
        g.move_parts(box, [], [upright], (0, 0, 5))


# --- faces ------------------------------------------------------------------

def test_every_face_held_is_the_solid_carried_whole():
    box = _box()

    out = g.move_parts(box, list(range(6)), [], (0, 0, 5))

    assert g.bbox(out)[0][2] == pytest.approx(5)
    assert _size(out) == (10, 10, 10)
    assert g.volume(out) == pytest.approx(1000)


def test_the_four_sides_held_carry_the_box_too():
    """The top and bottom have every corner moved, so they go along."""
    box = _box()
    sides = [i for i in range(6) if abs(g.face_normal(g.faces_of(box)[i])[2]) < 0.1]

    out = g.move_parts(box, sides, [], (0, 0, 5))

    assert g.bbox(out)[0][2] == pytest.approx(5)
    assert _size(out) == (10, 10, 10)


def test_one_face_moved_square_to_itself_is_a_push():
    box = _box()

    out = g.move_parts(box, [_face_where(box, (0, 0, 1))], [], (0, 0, 5))

    assert _size(out) == (10, 10, 15)
    assert g.volume(out) == pytest.approx(1500)


def test_one_face_moved_in_its_own_plane_is_a_slide():
    box = _box()

    out = g.move_parts(box, [_face_where(box, (0, 0, 1))], [], (3, 0, 0))

    assert g.volume(out) == pytest.approx(1000), "a shear keeps the volume"
    assert g.bbox(out)[1][0] == pytest.approx(13)
    assert len(g.faces_of(out)) == 6


def test_one_face_moved_slantwise_is_a_push_and_a_slide_with_no_kink():
    """Moving a face up and across at once used to slide it, then push
    the slid outline straight up, leaving a kink in each leaning side."""
    box = _box()
    top = _face_where(box, (0, 0, 1))

    out = g.move_parts(box, [top], [], (3, 0, 5))

    assert g.is_valid(out)
    assert len(g.faces_of(out)) == 6, "a kinked side is two faces"
    assert g.volume(out) == pytest.approx(1500)
    new_top = g.faces_of(out)[_face_where(out, (0, 0, 1))]
    assert g.centroid(new_top) == pytest.approx((8, 5, 15))


# --- faces and edges together, which is what a band holds ------------------

def test_a_face_and_the_edges_round_it_move_once():
    box = _box()
    top = _face_where(box, (0, 0, 1))

    out = g.move_parts(box, [top], _top_rim(box), (0, 0, 5))

    assert _size(out) == (10, 10, 15)


def test_everything_held_is_the_solid_carried_whole():
    box = _box()

    out = g.move_parts(box, list(range(6)), list(range(12)), (0, 0, 5))

    assert g.bbox(out)[0][2] == pytest.approx(5)
    assert _size(out) == (10, 10, 10)


def test_two_faces_that_would_bend_a_third_are_refused():
    """Top and front moved sideways: the left side would need one plane
    to hold the top's moved edge and another to hold the front's."""
    box = _box()
    top = _face_where(box, (0, 0, 1))
    front = _face_where(box, (0, -1, 0))

    with pytest.raises(g.GeometryError, match="bend"):
        g.move_parts(box, [top, front], [], (3, 0, 0))


def test_nothing_moved_is_said_so():
    with pytest.raises(g.GeometryError):
        g.move_parts(_box(), [], [], (0, 0, 5))
    with pytest.raises(g.GeometryError):
        g.move_parts(_box(), [5], [], (0, 0, 0))


# --- the commands -----------------------------------------------------------

@pytest.fixture
def env():
    scene = Scene()
    selection = SelectionManager(scene)
    ctx = CommandContext(scene, selection, History(scene))
    said: list[str] = []
    ctx.add_echo_listener(said.append)
    return scene, selection, CommandProcessor(ctx), said


def _move(proc, delta):
    proc.run("move")
    proc.provide((0.0, 0.0, 0.0))
    proc.provide(tuple(float(v) for v in delta))


def test_move_carries_a_band_full_of_parts_as_one(env):
    scene, sel, proc, said = env
    box = scene.add(_box(), name="Box")
    for i in range(6):
        sel.toggle_subobject(box.id, "face", i)
    for i in range(12):
        sel.toggle_subobject(box.id, "edge", i)

    _move(proc, (0, 0, 5))

    shape = scene.get(box.id).shape
    assert g.bbox(shape)[0][2] == pytest.approx(5)
    assert _size(shape) == (10, 10, 10)
    assert not any("zero" in m for m in said), said


def test_move_carries_the_rim_edges_once(env):
    scene, sel, proc, said = env
    box = scene.add(_box(), name="Box")
    for i in _top_rim(box.shape):
        sel.toggle_subobject(box.id, "edge", i)

    _move(proc, (0, 0, 5))

    assert _size(scene.get(box.id).shape) == (10, 10, 15)
    assert any("4 solid edge" in m for m in said), said


def test_move_says_what_it_moved_in_one_breath(env):
    scene, sel, proc, said = env
    box = scene.add(_box(), name="Box")
    sel.toggle_subobject(box.id, "face", _face_where(box.shape, (0, 0, 1)))
    for i in _top_rim(box.shape):
        sel.toggle_subobject(box.id, "edge", i)

    _move(proc, (0, 0, 5))

    assert _size(scene.get(box.id).shape) == (10, 10, 15)
    assert any("1 face" in m and "4 solid edge" in m for m in said), said


def test_a_refused_set_stays_held_and_untouched(env):
    scene, sel, proc, said = env
    box = scene.add(_box(), name="Box")
    sel.toggle_subobject(box.id, "face", _face_where(box.shape, (0, 0, 1)))
    sel.toggle_subobject(box.id, "face", _face_where(box.shape, (0, -1, 0)))

    _move(proc, (3, 0, 0))

    assert g.volume(scene.get(box.id).shape) == pytest.approx(1000)
    assert _size(scene.get(box.id).shape) == (10, 10, 10)
    assert len(sel.subobjects) == 2
    assert any("bend" in m for m in said), said


def test_rotating_two_faces_of_one_solid_is_refused_not_botched(env):
    """Turning faces one after another double counts the same way; until
    a set can be turned as one, say so and leave the solid alone."""
    scene, sel, proc, said = env
    box = scene.add(_box(), name="Box")
    before = g.volume(box.shape)
    sel.toggle_subobject(box.id, "face", 0)
    sel.toggle_subobject(box.id, "face", 2)

    proc.run("rotate")
    proc.provide((5.0, 5.0, 5.0))
    proc.provide(10.0)

    assert g.volume(scene.get(box.id).shape) == pytest.approx(before)
    assert any("one face at a time" in m for m in said), said
    assert len(sel.subobjects) == 2


def test_every_face_held_turns_as_the_whole_object(env):
    """A band round the whole solid holds all of it, so any transform
    means the object."""
    scene, sel, proc, said = env
    box = scene.add(_box(), name="Box")
    for i in range(6):
        sel.toggle_subobject(box.id, "face", i)

    proc.run("rotate")
    proc.provide((0.0, 0.0, 0.0))
    proc.provide(90.0)

    lo, hi = g.bbox(scene.get(box.id).shape)
    assert lo[0] == pytest.approx(-10, abs=1e-6)
    assert hi[1] == pytest.approx(10, abs=1e-6)
    assert math.isclose(g.volume(scene.get(box.id).shape), 1000)
    assert any("Box" in m or "object" in m for m in said), said
