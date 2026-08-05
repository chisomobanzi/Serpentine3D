"""What a boolean made is what you are holding when it finishes.

Every command let go of the selection when it was done, which is right for
most of them: you picked the objects to tell the command which ones, and once
it has acted the pick has been spent. A boolean is not like that. It consumes
the objects you picked and puts a different one in their place, and letting go
then leaves you holding nothing at all — the gumball was sitting on the solid
you were working on, and after a split it simply went away rather than moving
to the pieces that replaced it.
"""

from __future__ import annotations

import numpy as np
import pytest

from serpentine3d.commands.base import CommandContext, CommandProcessor
from serpentine3d.core import geometry as g
from serpentine3d.core.history import History
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager


@pytest.fixture
def env():
    scene = Scene()
    sel = SelectionManager(scene)
    ctx = CommandContext(scene, sel, History(scene))
    return scene, sel, CommandProcessor(ctx)


def _box(scene, corner=(0.0, 0.0, 0.0), d=10.0, name=None):
    return scene.add(g.make_box(corner, d, d, d), name=name)


def _slab(scene):
    """A plane through the middle of a 10-cube, wide enough to cut it."""
    return scene.add(g.extrude(g.make_line((5.0, -5.0, -5.0),
                                           (5.0, 15.0, -5.0)),
                               (0.0, 0.0, 1.0), 25.0))


def _solids(scene):
    return [o for o in scene.all() if o.kind == "solid"]


# -- split --

def test_a_split_leaves_its_pieces_selected(env):
    scene, sel, proc = env
    box = _box(scene)
    cutter = _slab(scene)
    sel.set([box.id])
    proc.run("booleansplit")            # the box is the pre-selection
    proc.click_object(cutter.id)
    proc.finish_selection()
    pieces = _solids(scene)
    assert len(pieces) == 2
    assert sorted(sel.ids) == sorted(o.id for o in pieces)


def test_the_split_object_is_not_still_selected(env):
    """It is gone from the scene, and a selection cannot outlive it."""
    scene, sel, proc = env
    box = _box(scene)
    cutter = _slab(scene)
    sel.set([box.id])
    proc.run("booleansplit")
    proc.click_object(cutter.id)
    proc.finish_selection()
    assert box.id not in sel.ids
    assert not sel.is_selected(box.id)


def test_a_split_that_cuts_nothing_leaves_nothing_selected(env):
    scene, sel, proc = env
    box = _box(scene)
    away = scene.add(g.extrude(g.make_line((90.0, -5.0, -5.0),
                                           (90.0, 15.0, -5.0)),
                               (0.0, 0.0, 1.0), 25.0))
    sel.set([box.id])
    proc.run("booleansplit")
    proc.click_object(away.id)
    proc.finish_selection()
    assert sel.ids == []


# -- the other three --

def test_a_union_leaves_the_result_selected(env):
    scene, sel, proc = env
    a = _box(scene)
    b = _box(scene, (5.0, 5.0, 5.0))
    sel.set([a.id, b.id])
    proc.run("booleanunion")
    proc.finish_selection()
    assert sel.ids == [o.id for o in _solids(scene)]
    assert len(sel.ids) == 1


def test_a_difference_leaves_what_it_cut_into_selected(env):
    scene, sel, proc = env
    keep = _box(scene)
    cut = _box(scene, (5.0, 5.0, 5.0))
    sel.set([keep.id])
    proc.run("booleandifference")
    proc.click_object(cut.id)
    proc.finish_selection()
    assert sel.ids == [keep.id]
    assert scene.get(cut.id) is None


def test_an_intersection_leaves_the_result_selected(env):
    scene, sel, proc = env
    a = _box(scene)
    b = _box(scene, (5.0, 5.0, 5.0))
    sel.set([a.id, b.id])
    proc.run("booleanintersection")
    proc.finish_selection()
    assert len(sel.ids) == 1
    assert sel.ids == [o.id for o in _solids(scene)]


# -- and the gumball that follows it --

def test_the_gumball_moves_onto_the_pieces_a_split_made(env):
    """The whole point of holding on to the result."""
    from PySide6.QtWidgets import QApplication

    from serpentine3d.ui.viewport import Viewport
    QApplication.instance() or QApplication([])
    scene, sel, proc = env
    vp = Viewport(scene, sel)
    vp.resize(800, 600)
    box = _box(scene)
    cutter = _slab(scene)
    sel.set([box.id])
    before, _axes = vp.gumball.anchor_and_axes()
    proc.run("booleansplit")
    proc.click_object(cutter.id)
    proc.finish_selection()
    assert vp.gumball.active(), "the gumball let go of everything"
    after, _axes = vp.gumball.anchor_and_axes()
    # both halves together are the box that was there, so the anchor stays
    assert np.allclose(after, before, atol=1e-4)
    # and holding one half puts it on that half
    half = min(_solids(scene), key=lambda o: o.bbox()[1][0])
    sel.set([half.id])
    one, _axes = vp.gumball.anchor_and_axes()
    assert one[0] == pytest.approx(2.5, abs=1e-4)


# -- without changing what every other command does --

def test_an_ordinary_command_still_lets_go_when_it_is_done(env):
    """Picking objects to tell a command which ones is a pick it spends."""
    scene, sel, proc = env
    box = _box(scene)
    sel.set([box.id])
    proc.run("move")
    proc.provide_text("0,0,0")
    proc.provide_text("1,0,0")
    assert sel.ids == []


def test_a_cancelled_boolean_claims_nothing(env):
    """Escaped halfway, it made nothing, so there is nothing to hand back."""
    scene, sel, proc = env
    box = _box(scene)
    _slab(scene)
    sel.set([box.id])
    proc.run("booleansplit")
    proc.cancel()
    assert sel.ids == []
    assert len(_solids(scene)) == 1, "the box was not cut"
