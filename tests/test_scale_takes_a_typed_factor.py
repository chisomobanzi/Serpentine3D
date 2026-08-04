"""A factor typed straight after the base point.

Every other scale asks "Scale factor, or first reference point" the moment
it has a base: one number and it is done. Scale1D asked for a reference
point first and would not take a number there, so clicking a base point
and typing 0.5 could not scale anything — the factor prompt was still two
picks away.

The number says how much. Which way it stretches is the one thing it does
not say, and the cursor has been saying that all along.
"""

import numpy as np
import pytest

import serpentine3d.commands  # registers commands  # noqa: F401
from serpentine3d.commands.base import CommandContext, CommandProcessor
from serpentine3d.core import geometry as g
from serpentine3d.core.cplane import CPlane
from serpentine3d.core.history import History
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager


class _Aiming:
    """A viewport that is only pointing somewhere, which is all this needs."""

    def __init__(self, direction=(1.0, 0.0, 0.0)):
        self._dir = direction

    def aim_direction(self):
        if self._dir is None:
            return None
        d = np.asarray(self._dir, float)
        return ((0.0, 0.0, 0.0), tuple(d / np.linalg.norm(d)))

    def locked_direction(self):
        return None

    def active_cplane(self):
        return CPlane()


def _scaling(command, factor, aim=(1.0, 0.0, 0.0)):
    """Select a 10 cube, click the base point, type the factor."""
    scene = Scene()
    ctx = CommandContext(scene, SelectionManager(scene), History(scene),
                         viewport=_Aiming(aim))
    said = []
    ctx.add_echo_listener(said.append)
    proc = CommandProcessor(ctx)
    box = scene.add(g.make_box((0, 0, 0), 10, 10, 10))
    proc.run(command)
    proc.click_object(box.id)
    proc.finish_selection()
    proc.provide_text("0,0,0")
    proc.provide_text(factor)
    return scene.get(box.id), proc, said


def _sides(obj):
    lo, hi = g.bbox(obj.shape)
    return tuple(round(h - lo_, 6) for lo_, h in zip(lo, hi))


def test_scale1d_stretches_along_the_aim_by_a_typed_factor():
    box, proc, said = _scaling("scale1d", "0.5")
    assert not proc.busy, f"still asking: {said}"
    assert _sides(box) == pytest.approx((5.0, 10.0, 10.0), abs=1e-5)


def test_scale1d_follows_the_cursor_to_the_other_axis():
    """Which axis it stretches is read off the cursor, so pointing up the
    y axis stretches y. Nothing else about the number changes."""
    box, _proc, said = _scaling("scale1d", "2", aim=(0.0, 1.0, 0.0))
    assert _sides(box) == pytest.approx((10.0, 20.0, 10.0), abs=1e-5), said


def test_scale1d_with_no_cursor_stretches_along_the_cplane():
    """Typed into a batch or over the bridge there is no cursor to ask."""
    box, _proc, said = _scaling("scale1d", "0.5", aim=None)
    assert _sides(box) == pytest.approx((5.0, 10.0, 10.0), abs=1e-5), said


def test_scale1d_still_takes_two_reference_points():
    """The axis from a pair of picks is the way it always worked, and the
    only way to stretch along something the cursor cannot point at."""
    scene = Scene()
    ctx = CommandContext(scene, SelectionManager(scene), History(scene),
                         viewport=_Aiming())
    proc = CommandProcessor(ctx)
    box = scene.add(g.make_box((0, 0, 0), 10, 10, 10))
    proc.run("scale1d")
    proc.click_object(box.id)
    proc.finish_selection()
    proc.provide_text("0,0,0")
    proc.provide_text("0,10,0")             # the axis, not a factor
    proc.provide_text("0,30,0")             # three times as far out
    assert _sides(scene.get(box.id)) == pytest.approx((10.0, 30.0, 10.0),
                                                     abs=1e-5)


def test_a_zero_factor_is_refused():
    _box, proc, said = _scaling("scale1d", "0")
    assert not proc.busy
    assert "zero" in said[-1].lower(), said[-1]


def test_plain_scale_was_already_right():
    """The report said "the scale commands", so this pins the one that was
    not broken: a factor typed after the base point has always worked."""
    box, proc, said = _scaling("scale", "0.5")
    assert not proc.busy, f"still asking: {said}"
    assert _sides(box) == pytest.approx((5.0, 5.0, 5.0), abs=1e-5)
