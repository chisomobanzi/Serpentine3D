"""Points on belongs to the drawing, and a held point is a thing you can move.

Two complaints, one cause each. Points on was kept per pane, so turning them
on in the Top view left the Right view drawing a plain white line: no markers
to click, and the gumball there refuses to stand on a point the pane is not
showing, so a corner picked in one view was picked nowhere else. And the
transform commands only ever asked which objects to work on, so `move` with
three corners held either moved the whole curve or asked you to pick it.

A control point you are holding is what the command is for. It moves by the
same rule the objects move by, and it is still held when the command is over,
because the next thing you do is usually move it again.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

import serpentine3d.commands  # registers all commands  # noqa: F401
from serpentine3d.commands.base import CommandContext, CommandProcessor
from serpentine3d.core import geometry as g
from serpentine3d.core.history import History
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui.viewport import Viewport

CORNERS = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 10.0, 0.0),
           (20.0, 10.0, 0.0)]


def _points(scene, obj):
    return np.asarray(g.get_control_points(scene.get(obj.id).shape), float)


def _near(a, b, tol=1e-6):
    return np.allclose(np.asarray(a, float), np.asarray(b, float), atol=tol)


# -- the same points, in every pane ------------------------------------------

@pytest.fixture
def panes():
    """Two panes onto one drawing, as the four-pane layout is."""
    QApplication.instance() or QApplication([])
    scene = Scene()
    sel = SelectionManager(scene)
    top, right = Viewport(scene, sel), Viewport(scene, sel)
    for v, name in ((top, "top"), (right, "right")):
        v.resize(400, 300)
        v.set_view(name)
    obj = scene.add(g.make_polyline(CORNERS))
    ctx = CommandContext(scene, sel, History(scene), viewport=top)
    return scene, sel, obj, top, right, CommandProcessor(ctx)


def test_points_on_in_one_pane_turns_them_on_in_every_pane(panes):
    scene, sel, obj, top, right, proc = panes
    sel.set([obj.id])
    proc.run("pointson")
    assert obj.id in top.cv_enabled
    assert obj.id in right.cv_enabled, "the other pane still draws a bare line"


def test_points_off_turns_them_off_everywhere(panes):
    scene, sel, obj, top, right, proc = panes
    sel.set([obj.id])
    proc.run("pointson")
    proc.run("pointsoff")
    assert not top.cv_enabled
    assert not right.cv_enabled


def test_a_point_held_in_one_pane_is_held_in_the_other(panes):
    """No markers meant no gumball: the anchor is a point nobody can see."""
    scene, sel, obj, top, right, proc = panes
    sel.set([obj.id])
    proc.run("pointson")
    sel.set_subobjects([(obj.id, "cv", 2)])
    assert top.gumball.active()
    assert right.gumball.active(), "no gumball on the corner in the other pane"
    for pane in (top, right):
        anchor, _axes = pane.gumball.anchor_and_axes()
        assert _near(anchor, CORNERS[2])


def test_another_drawing_keeps_its_own_points_to_itself(panes):
    """Shared across the panes of one document, not across documents."""
    _scene, _sel, obj, top, _right, _proc = panes
    other = Scene()
    elsewhere = Viewport(other, SelectionManager(other))
    top.cv_enabled.add(obj.id)
    assert not elsewhere.cv_enabled


# -- a held point is something a command can move ----------------------------

@pytest.fixture
def env():
    scene = Scene()
    sel = SelectionManager(scene)
    ctx = CommandContext(scene, sel, History(scene))
    return scene, sel, ctx, CommandProcessor(ctx)


def _hold(scene, sel, indices):
    """A polyline with those corners held, and nothing else selected.

    Nothing else, because taking hold of a point lets go of the curve it
    belongs to: a gumball on both would move the corner twice.
    """
    obj = scene.add(g.make_polyline(CORNERS))
    sel.set_subobjects([(obj.id, "cv", i) for i in indices])
    return obj


def test_move_moves_the_points_it_is_holding(env):
    scene, sel, ctx, proc = env
    obj = _hold(scene, sel, [1, 2])
    proc.run("move")
    proc.provide_text("0,0,0")
    proc.provide_text("0,0,5")
    assert not proc.busy
    pts = _points(scene, obj)
    assert _near(pts[1], (10.0, 0.0, 5.0))
    assert _near(pts[2], (10.0, 10.0, 5.0))
    assert _near(pts[0], CORNERS[0]), "it moved a corner it was not holding"
    assert _near(pts[3], CORNERS[3])


def test_move_never_asks_which_objects_when_it_holds_points(env):
    """Asking would throw them away: a select prompt clears the selection."""
    scene, sel, ctx, proc = env
    _hold(scene, sel, [0])
    proc.run("move")
    assert proc.request is not None
    assert "point" in proc.request.prompt.lower()


def test_the_points_are_still_held_when_the_move_is_over(env):
    """You almost always move a corner again, and to a place you pick next."""
    scene, sel, ctx, proc = env
    obj = _hold(scene, sel, [1])
    proc.run("move")
    proc.provide_text("0,0,0")
    proc.provide_text("1,0,0")
    assert sel.subobjects_of(obj.id, "cv") == [1]


def test_rotate_turns_the_points_it_is_holding(env):
    scene, sel, ctx, proc = env
    obj = _hold(scene, sel, [1])
    proc.run("rotate")
    proc.provide_text("0,0,0")       # centre
    proc.provide_text("90")          # degrees, about the cplane normal
    assert not proc.busy
    pts = _points(scene, obj)
    assert _near(pts[1], (0.0, 10.0, 0.0))
    assert _near(pts[2], CORNERS[2])


def test_scale_pulls_the_points_it_is_holding(env):
    scene, sel, ctx, proc = env
    obj = _hold(scene, sel, [3])
    proc.run("scale")
    proc.provide_text("0,0,0")       # base point
    proc.provide_text("2")           # factor
    assert not proc.busy
    pts = _points(scene, obj)
    assert _near(pts[3], (40.0, 20.0, 0.0))
    assert _near(pts[0], CORNERS[0])


def test_scale_by_one_axis_pulls_the_points_it_is_holding(env):
    scene, sel, ctx, proc = env
    obj = _hold(scene, sel, [3])
    proc.run("scalenu")
    proc.provide_text("0,0,0")       # base point
    proc.provide_text("3")           # X
    proc.provide_text("1")           # Y
    proc.provide_text("1")           # Z
    assert not proc.busy
    pts = _points(scene, obj)
    assert _near(pts[3], (60.0, 10.0, 0.0))


def test_mirror_flips_the_points_it_is_holding(env):
    scene, sel, ctx, proc = env
    obj = _hold(scene, sel, [1])
    proc.run("mirror")
    proc.provide_text("0,0,0")
    proc.provide_text("0,10,0")      # mirror line up the Y axis
    assert not proc.busy
    pts = _points(scene, obj)
    assert _near(pts[1], (-10.0, 0.0, 0.0))
    assert _near(pts[3], CORNERS[3])


def test_a_surface_moves_the_points_it_is_holding(env):
    """Not only curves: a control point on a surface is one too."""
    scene, sel, ctx, proc = env
    srf = g.loft([g.make_circle((0, 0, 0), 4), g.make_circle((0, 0, 8), 2)])
    obj = scene.add(list(g.faces_of(srf))[0])
    was = np.asarray(g.surface_control_points(obj.shape)[0], float)
    sel.set_subobjects([(obj.id, "cv", 0)])
    proc.run("move")
    proc.provide_text("0,0,0")
    proc.provide_text("0,0,4")
    assert not proc.busy
    now = np.asarray(g.surface_control_points(scene.get(obj.id).shape)[0],
                     float)
    assert _near(now[0], was[0] + np.array([0.0, 0.0, 4.0]))
    assert _near(now[-1], was[-1])


def test_move_still_moves_whole_objects_when_no_points_are_held(env):
    scene, sel, ctx, proc = env
    obj = scene.add(g.make_polyline(CORNERS))
    sel.set([obj.id])
    proc.run("move")
    proc.provide_text("0,0,0")
    proc.provide_text("0,0,7")
    assert not proc.busy
    assert _near(_points(scene, obj)[0], (0.0, 0.0, 7.0))


def test_a_point_transform_is_the_same_rule_the_objects_get():
    """The points go through the very transform the shapes go through."""
    pts = [(1.0, 0.0, 0.0), (0.0, 2.0, 0.0)]
    out = g.transform_points(
        pts, lambda s: g.rotate(s, (0, 0, 0), (0, 0, 1), 90.0))
    assert _near(out[0], (0.0, 1.0, 0.0), tol=1e-9)
    assert _near(out[1], (-2.0, 0.0, 0.0), tol=1e-9)
    out = g.transform_points(pts, lambda s: g.scale(s, (0, 0, 0), 3.0))
    assert _near(out[0], (3.0, 0.0, 0.0), tol=1e-9)
    assert math.isfinite(out[1][1])
