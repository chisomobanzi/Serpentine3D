"""Copies laid along a path can be turned to face along it.

`arraypath` used to translate and nothing else, so a row of chairs set out
along a curving path all faced the way the first one did, and a bolt arrayed
around a bent pipe stayed pointing at the ceiling. Rhino's two answers are
Freeform, where the copy turns with the curve in all three axes, and
Roadlike, where it yaws to follow the curve but stays upright, which is what
you want for anything standing on the ground.

The frames come from `sample_curve_frames`, and the two things worth testing
about it are that its tangents actually point along the curve and that its
up-vector does not spin: a circle sampled by a naive frame flips over at the
poles, and a hundred arrayed copies flip with it.
"""

import math

import numpy as np
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
    return scene, selection, CommandProcessor(ctx)


def _quarter_arc(radius=10.0):
    """A quarter circle in the XY plane, from (r,0,0) round to (0,r,0)."""
    mid = (radius * math.cos(math.pi / 4), radius * math.sin(math.pi / 4), 0)
    return g.make_arc_3pt((radius, 0, 0), mid, (0, radius, 0))


# --- the frames themselves -------------------------------------------------

def test_frames_carry_a_tangent_that_points_along_the_curve():
    """A straight line along +X: every tangent is +X, whatever else the
    frame does with the other two axes."""
    line = g.make_line((0, 0, 0), (10, 0, 0))
    frames = g.sample_curve_frames(line, 5)

    assert len(frames) == 5
    for origin, tangent, up in frames:
        assert np.allclose(tangent, (1, 0, 0), atol=1e-9)
        assert origin[1] == pytest.approx(0, abs=1e-9)
    assert frames[0][0][0] == pytest.approx(0, abs=1e-9)
    assert frames[-1][0][0] == pytest.approx(10, abs=1e-9)


def test_frames_are_orthonormal():
    frames = g.sample_curve_frames(_quarter_arc(), 6)
    for _, tangent, up in frames:
        assert np.linalg.norm(tangent) == pytest.approx(1, abs=1e-9)
        assert np.linalg.norm(up) == pytest.approx(1, abs=1e-9)
        assert float(np.dot(tangent, up)) == pytest.approx(0, abs=1e-9)


def test_the_frame_does_not_spin_along_the_curve():
    """The reason this is a rotation-minimising frame and not the textbook
    Frenet one: on a plane curve Frenet's normal is fine, but the moment the
    curve has an inflection or straightens out the normal flips end over end,
    and every copy standing on it flips too. Consecutive frames should differ
    by the smallest rotation that carries one tangent to the next, which
    means the up-vector never swings more than the tangent does."""
    frames = g.sample_curve_frames(_quarter_arc(), 24)
    for (_, t0, u0), (_, t1, u1) in zip(frames, frames[1:]):
        turned_tangent = math.acos(min(1.0, float(np.dot(t0, t1))))
        turned_up = math.acos(min(1.0, float(np.dot(u0, u1))))
        assert turned_up <= turned_tangent + 1e-6, "the frame rolled"


def test_a_helix_keeps_its_up_vector_off_the_tangent():
    """A curve that leaves the plane is where a fixed world up would fail:
    once the tangent points at the sky, "up" has to be something else."""
    pts = [(math.cos(t), math.sin(t), t) for t in np.linspace(0, 6.0, 40)]
    helix = g.make_interp_curve([tuple(map(float, p)) for p in pts])
    for _, tangent, up in g.sample_curve_frames(helix, 12):
        assert abs(float(np.dot(tangent, up))) < 1e-6


def test_frames_need_two_points():
    with pytest.raises(g.GeometryError):
        g.sample_curve_frames(g.make_line((0, 0, 0), (1, 0, 0)), 1)


# --- the command -----------------------------------------------------------

def _run_arraypath(proc, scene, orientation, count=4, base="10,0,0"):
    proc.run("arraypath")
    proc.click_object(scene.all()[0].id)              # the object to copy
    proc.finish_selection()
    proc.click_object(scene.all()[1].id)              # the path
    proc.finish_selection()
    proc.provide_text(str(count))
    proc.provide_text(orientation)
    proc.provide_text(base)                           # base point
    assert not proc.busy, "arraypath did not finish"


def _long_axis(shape):
    """Which way the box's longest side points, as a unit vector."""
    mn, mx = g.bbox(shape)
    span = np.array(mx) - np.array(mn)
    axis = np.zeros(3)
    axis[int(np.argmax(span))] = 1.0
    return axis


def test_none_leaves_every_copy_facing_the_way_it_started(env):
    """The old behaviour, kept: sometimes a row of identical posts is
    exactly what you want."""
    scene, sel, proc = env
    box = scene.add(g.make_box((10, 0, 0), 4, 1, 1))
    scene.add(_quarter_arc())

    _run_arraypath(proc, scene, "None")

    made = [o for o in scene.all() if o.id != box.id][1:]
    assert len(made) == 3
    for o in made:
        assert np.allclose(_long_axis(o.shape), (1, 0, 0))


def test_freeform_turns_each_copy_to_follow_the_curve(env):
    """The last copy sits at the far end of the quarter arc, where the
    tangent has turned 90 degrees, so the box that started long in X should
    be long in Y."""
    scene, sel, proc = env
    scene.add(g.make_box((10, 0, 0), 4, 1, 1))
    scene.add(_quarter_arc())

    _run_arraypath(proc, scene, "Freeform")

    last = scene.all()[-1]
    assert np.allclose(_long_axis(last.shape), (0, 1, 0)), \
        "the copy at the end of the arc did not turn with it"


def _humpback_arc():
    """An arc that climbs out of the ground plane and comes back down, like
    a bridge seen from the side. A straight ramp will not do: on a straight
    path the tangent never changes, so Freeform and Roadlike agree, and
    rightly."""
    return g.make_arc_3pt((0, 0, 0), (5, 0, 5), (10, 0, 0))


def test_roadlike_stays_upright_over_a_hump(env):
    """Roadlike keeps every copy's z pointing at the sky, which is what a
    lamp post, a chair or a fence picket wants."""
    scene, sel, proc = env
    scene.add(g.make_box((0, 0, 0), 4, 1, 1))
    scene.add(_humpback_arc())

    _run_arraypath(proc, scene, "Roadlike", count=5, base="0,0,0")

    for o in scene.all()[2:]:
        mn, mx = g.bbox(o.shape)
        assert (mx[2] - mn[2]) == pytest.approx(1, abs=1e-6), \
            "the copy tipped with the slope instead of standing up"


def test_freeform_does_tip_where_roadlike_would_not(env):
    """The other half of the previous test: the two options have to actually
    differ, or Roadlike is just Freeform with a nicer name."""
    scene, sel, proc = env
    scene.add(g.make_box((0, 0, 0), 4, 1, 1))
    scene.add(_humpback_arc())

    _run_arraypath(proc, scene, "Freeform", count=5, base="0,0,0")

    tallest = max(scene.all()[2:],
                  key=lambda o: g.bbox(o.shape)[1][2] - g.bbox(o.shape)[0][2])
    mn, mx = g.bbox(tallest.shape)
    assert (mx[2] - mn[2]) > 1.5, "nothing tipped, so Freeform did nothing"


def test_roadlike_still_swings_round_in_plan(env):
    """Upright is not the same as unturned: on a path that bends in plan the
    copies still have to face along it."""
    scene, sel, proc = env
    scene.add(g.make_box((10, 0, 0), 4, 1, 1))
    scene.add(_quarter_arc())

    _run_arraypath(proc, scene, "Roadlike")

    assert np.allclose(_long_axis(scene.all()[-1].shape), (0, 1, 0)), \
        "the copy at the end of the arc did not swing round with it"


def test_the_copies_still_land_on_the_path(env):
    """Turning them must not move them: each copy's base point stays at its
    sample on the curve, exactly as it did before orientation existed."""
    scene, sel, proc = env
    scene.add(g.make_box((10, 0, 0), 4, 1, 1))
    scene.add(_quarter_arc())

    _run_arraypath(proc, scene, "Freeform", count=5)

    samples = g.sample_curve(scene.all()[1].shape, 5)
    for target, o in zip(samples[1:], scene.all()[2:]):
        mn, mx = g.bbox(o.shape)
        # the base point was a corner of the box, so the copy's bbox has to
        # reach the sample it was placed at
        near = min(abs(np.array(mn) - np.array(target)).min(),
                   abs(np.array(mx) - np.array(target)).min())
        assert near < 1e-6 or _touches(mn, mx, target), \
            f"copy is not on the curve at {target}"


def _touches(mn, mx, p, tol=1e-6):
    return all(mn[i] - tol <= p[i] <= mx[i] + tol for i in range(3))


def test_orientation_defaults_to_freeform(env):
    """Rhino's default, and the one that is right for the case the command
    is usually reached for."""
    scene, sel, proc = env
    scene.add(g.make_box((10, 0, 0), 4, 1, 1))
    scene.add(_quarter_arc())

    proc.run("arraypath")
    proc.click_object(scene.all()[0].id)
    proc.finish_selection()
    proc.click_object(scene.all()[1].id)
    proc.finish_selection()
    proc.provide_text("4")
    req = proc.request
    assert req.options == ["Freeform", "Roadlike", "None"]
    assert req.default == "Freeform"
