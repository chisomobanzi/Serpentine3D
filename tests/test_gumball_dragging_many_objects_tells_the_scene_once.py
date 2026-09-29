"""Drag a big selection with the gumball and the scene should tell its
listeners once, not once per object — and for a whole-object move, not at
all until release.

A whole-object drag used to rebuild every selected object on every mouse
move, and Scene.replace_shape told the listeners about every object it
replaced. The layers panel answers an "objects" wake-up by rebuilding its
tree over the whole scene, so one move of a few hundred objects rebuilt
that tree a few hundred times over: the viewport froze for minutes while
the queue of queued mouse moves drained, and the objects landed wherever
the queue had reached by the time the mouse was released.

A whole-object drag now rides as a display transform (Scene.drag_display)
the viewports draw each frame, and end_drag folds it into the objects'
poses — the shapes are never rewritten — see
test_moving_many_objects_is_a_display_offset_until_release. A drag that
rebuilds geometry (held points, segments) still writes on every step, and
each such step is one change, one notification, exactly as the bulk
commands do it (see
test_organising_many_objects_tells_the_viewport_once). Each test also
checks the geometry landed right: a scene that never notified at all
would pass the count and fail the user.
"""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import Qt

from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager

MANY = 30


def _vp():
    from serpentine3d.ui.viewport import Viewport
    scene = Scene()
    sel = SelectionManager(scene)
    vp = Viewport(scene, sel)
    vp.resize(900, 700)
    vp.camera.target = np.zeros(3)
    vp.camera.distance = 40.0
    return vp, scene, sel


def _boxes(scene, n=MANY):
    """A row of boxes along X, i*20 apart, each 10 wide: union centre at
    ((n-1)*10, 5, 5), which the camera is aimed at so the centre pixel's
    ray crosses the gumball's X axis."""
    boxes = [scene.add(g.make_box((i * 20.0, 0.0, 0.0), 10.0, 10.0, 10.0),
                       name=f"Box {i}")
             for i in range(n)]
    return boxes


def _aim_at_row(vp, n=MANY):
    vp.camera.target = np.asarray(((n - 1) * 10.0, 5.0, 5.0))


def _is_translation(m, off):
    """drag_display carries 4x4 poses; a whole-object move is the one
    whose linear part is the identity."""
    m = np.asarray(m, float)
    return (np.allclose(m[:3, :3], np.eye(3), atol=1e-9)
            and np.allclose(m[:3, 3], off, atol=1e-9))


class _Counter:
    """Stands in for the viewport and the layers panel: counts every
    "objects" wake-up."""

    def __init__(self, scene):
        self.calls = 0
        scene.add_listener(self, kinds=("objects",))

    def __call__(self):
        self.calls += 1

    def reset(self):
        self.calls = 0


def _begin(vp, handle, modifiers=Qt.KeyboardModifier.NoModifier):
    w, h = vp.width(), vp.height()
    ok = vp.gumball.begin_drag(handle, w / 2, h / 2, modifiers)
    assert ok, f"begin_drag failed for {handle}"


def test_moving_many_with_the_gumball_notifies_once():
    vp, scene, sel = _vp()
    boxes = _boxes(scene)
    _aim_at_row(vp)
    sel.set([b.id for b in boxes])
    _begin(vp, ("move", 0))                    # the X arrow
    counter = _Counter(scene)
    revision = scene.revision
    vp.gumball.apply_scalar(10.0)              # one mouse move of the drag
    # the scene still holds the shapes where they were: the move rides as
    # a display offset the viewports draw, not as a scene change
    assert counter.calls == 0, (
        f"one move of {MANY} objects woke the listeners {counter.calls} "
        "times before release; a whole-object move does not write the scene")
    assert scene.revision == revision
    for b in boxes:
        assert _is_translation(scene.drag_display[b.id], (10.0, 0.0, 0.0))
    vp.gumball.apply_scalar(20.0)              # a second move, still display
    assert counter.calls == 0 and scene.revision == revision
    vp.gumball.end_drag()                      # the one and only write
    # every box moved with the drag: the shape stayed where it was, the
    # pose carries the move
    for i, b in enumerate(boxes):
        obj = scene.get(b.id)
        mn, mx = obj.bbox()
        assert (mn[0] + mx[0]) / 2 == pytest.approx(i * 20.0 + 25.0)
        assert _is_translation(obj.transform, (20.0, 0.0, 0.0))
    assert counter.calls == 1, (
        "the whole drag is one change and one notification, not N")
    assert not scene.drag_display


def test_alt_drag_copying_many_notifies_once():
    vp, scene, sel = _vp()
    boxes = _boxes(scene)
    _aim_at_row(vp)
    sel.set([b.id for b in boxes])
    counter = _Counter(scene)
    _begin(vp, ("move", 0), Qt.KeyboardModifier.AltModifier)
    copies = vp.selection.objects()
    assert len(copies) == MANY and len(scene.all()) == 2 * MANY
    assert counter.calls == 1, (
        f"Alt+drag copied {MANY} objects and woke the listeners "
        f"{counter.calls} times; the copies are one change")
    counter.reset()
    vp.gumball.apply_scalar(5.0)               # drag the copies: display only
    assert counter.calls == 0, (
        "the copies ride as a display offset until release")
    for i, c in enumerate(copies):
        obj = scene.get(c.id)
        mn, mx = g.bbox(obj.shape)
        assert (mn[0] + mx[0]) / 2 == pytest.approx(i * 20.0 + 5.0)
        assert _is_translation(scene.drag_display[c.id], (5.0, 0.0, 0.0))
    vp.gumball.end_drag()
    for i, c in enumerate(copies):
        obj = scene.get(c.id)
        mn, mx = obj.bbox()                      # the pose carries the move
        assert (mn[0] + mx[0]) / 2 == pytest.approx(i * 20.0 + 10.0)
        assert _is_translation(obj.transform, (5.0, 0.0, 0.0))
    assert counter.calls == 1, (
        "the drag of the copies is one change and one notification")
    assert not scene.drag_display


def test_moving_many_held_points_notifies_once():
    vp, scene, sel = _vp()
    # all first control points at the origin, so the held-point anchor is
    # the camera target and the centre pixel's ray crosses the X axis
    curves = []
    for i in range(MANY):
        curve = scene.add(g.make_control_curve(
            [(0.0, 0.0, 0.0), (5.0 + i, 5.0, 0.0), (10.0 + 2 * i, 0.0, 0.0)],
            3), name=f"Cv {i}")
        scene.cv_enabled.add(curve.id)
        sel.toggle_subobject(curve.id, "cv", 0)   # hold the first point
        curves.append(curve)
    _begin(vp, ("move", 0))
    counter = _Counter(scene)
    vp.gumball.apply_scalar(10.0)
    for curve in curves:
        pts = g.get_control_points(scene.get(curve.id).shape)
        assert np.allclose(pts[0], (10.0, 0.0, 0.0)), (
            "the held point should have moved with the drag")
    assert counter.calls == 1, (
        f"one move of {MANY} held points woke the listeners "
        f"{counter.calls} times; one change, one notification")
    vp.gumball.end_drag()
