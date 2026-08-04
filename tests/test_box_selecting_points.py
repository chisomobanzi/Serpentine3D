"""A dragged box picks up point objects.

Clicking a point selected it, dragging a box around it did not. A point
carries its geometry in `mesh.points` — it has no edges to cross and no
triangle vertices to fall inside — and the box pick only ever looked at
those two, so it skipped every point in the drawing. Anything built out of
points went with it: a divided curve's marks, an imported survey, the
output of `point` itself, none of them could be picked in a crowd.
"""

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager


@pytest.fixture
def view():
    QApplication.instance() or QApplication([])
    from serpentine3d.ui.viewport import Viewport
    scene = Scene()
    vp = Viewport(scene, SelectionManager(scene))
    vp.resize(800, 600)
    return vp


def _at(view, obj):
    """Where an object's own geometry lands on screen."""
    pts = obj.mesh.points if len(obj.mesh.points) else \
        obj.mesh.edge_segments.reshape(-1, 3)
    scr = view.camera.project(np.asarray(pts, float),
                              view.width(), view.height())
    return float(scr[:, 0].mean()), float(scr[:, 1].mean())


def _box_round(view, obj, pad=40.0, crossing=True):
    """A box drawn around one object, with room to spare."""
    x, y = _at(view, obj)
    return view._box_pick(x - pad, y - pad, x + pad, y + pad, crossing)


def test_a_box_dragged_round_a_point_selects_it(view):
    pt = view.scene.add(g.make_point((2.0, 1.0, 0.0)))
    assert _box_round(view, pt, crossing=True) == [pt.id]


def test_a_window_box_round_a_point_selects_it_too(view):
    """A window box asks whether the whole object is inside. All of a
    point is wherever the point is."""
    pt = view.scene.add(g.make_point((2.0, 1.0, 0.0)))
    assert _box_round(view, pt, crossing=False) == [pt.id]


def test_a_box_that_misses_the_point_leaves_it_alone(view):
    """Otherwise the fix is "select everything", which is not a fix."""
    pt = view.scene.add(g.make_point((2.0, 1.0, 0.0)))
    x, y = _at(view, pt)
    assert view._box_pick(x + 100, y + 100, x + 200, y + 200,
                          crossing=True) == []
    assert view._box_pick(x + 100, y + 100, x + 200, y + 200,
                          crossing=False) == []


def test_a_box_over_several_points_takes_them_all(view):
    pts = [view.scene.add(g.make_point((x, 0.0, 0.0)))
           for x in (-1.0, 0.0, 1.0)]
    picked = view._box_pick(0.0, 0.0, 800.0, 600.0, crossing=True)
    assert sorted(picked) == sorted(p.id for p in pts)


def test_a_curve_is_still_picked_the_way_it_was(view):
    """The path points were missing from is the one curves use."""
    crv = view.scene.add(g.make_line((-2.0, 0.0, 0.0), (2.0, 0.0, 0.0)))
    assert _box_round(view, crv, pad=200.0, crossing=True) == [crv.id]


# -- and by name, the way every other kind can be --

def test_selpt_selects_the_points_and_leaves_the_rest():
    """Curves, surfaces and solids each have a command that rounds them
    all up. Points had none, so the only way to gather them was to hunt
    them down one at a time."""
    import serpentine3d.commands                             # noqa: F401
    from serpentine3d.commands.base import (CommandContext,
                                            CommandProcessor)
    from serpentine3d.core.history import History
    scene = Scene()
    ctx = CommandContext(scene, SelectionManager(scene), History(scene))
    said = []
    ctx.add_echo_listener(said.append)
    pts = [scene.add(g.make_point((x, 0.0, 0.0))) for x in (0.0, 1.0)]
    scene.add(g.make_line((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)))
    scene.add(g.make_box((0, 0, 0), 1, 1, 1))
    CommandProcessor(ctx).run("selpt")
    assert sorted(ctx.selection.ids) == sorted(p.id for p in pts), said
    assert "2 point(s)" in said[-1]
