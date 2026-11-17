"""A pane that has stopped moving swaps in finer meshes for what it is
zoomed in on, and drops them again once it zooms back out (#168).

The meshing itself is core/refine.py and tested there. This is the pane's
part: which objects it asks about, that the answer reaches the buffers it
draws from and the picking, and that a pane zoomed out or moved on lets go.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui.viewport import Viewport


class _AtOnce:
    """A worker pool that does the work as it is handed over."""

    def submit(self, fn, *args, **kw):
        fn(*args, **kw)


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def pane(app, monkeypatch):
    scene = Scene()
    vp = Viewport(scene, SelectionManager(scene))
    vp.resize(800, 600)
    monkeypatch.setattr(vp, "_worker_pool", lambda: _AtOnce())
    try:
        yield vp, scene
    finally:
        vp.deleteLater()
        QApplication.processEvents()


def _look(vp, target, half_height):
    """Parallel, along -X at `target`, `2 * half_height` units tall."""
    cam = vp.camera
    cam.projection = "parallel"
    cam.target = np.asarray(target, float)
    cam.distance = half_height / math.tan(math.radians(cam.fov) / 2)
    cam.azimuth = cam.elevation = 0.0


def _settle(vp):
    """What the pane does once the camera has stood still, after a frame
    has meshed what it shows."""
    for obj in vp.scene.drawable_objects():
        obj.mesh                                # noqa: B018
    vp._refine.plan()
    QApplication.processEvents()


def test_zoomed_in_the_pane_draws_a_finer_mesh(pane):
    vp, scene = pane
    ball = scene.add(g.make_sphere((0, 0, 0), 20.0), name="Ball")
    _look(vp, (20, 0, 0), 1.0)
    key = vp._gpu_sync_key()
    _settle(vp)
    shown = vp._refine.shown(ball)
    assert len(shown.triangles) > 4 * len(ball.mesh.triangles)
    assert vp._gpu_sync_key() != key            # the buffers are rebuilt


def test_the_scene_keeps_its_own_mesh(pane):
    vp, scene = pane
    ball = scene.add(g.make_sphere((0, 0, 0), 20.0), name="Ball")
    before = ball.mesh
    _look(vp, (20, 0, 0), 1.0)
    _settle(vp)
    assert ball.mesh is before                  # other panes, exports


def test_zoomed_back_out_the_pane_lets_go(pane):
    vp, scene = pane
    ball = scene.add(g.make_sphere((0, 0, 0), 20.0), name="Ball")
    _look(vp, (20, 0, 0), 1.0)
    _settle(vp)
    _look(vp, (0, 0, 0), 30.0)
    _settle(vp)
    assert vp._refine.shown(ball) is ball.mesh
    assert not vp._refine.meshes


def test_an_object_out_of_view_is_not_asked_about(pane, monkeypatch):
    vp, scene = pane
    scene.add(g.make_sphere((0, 0, 0), 20.0), name="Here")
    there = scene.add(g.make_sphere((0, 500, 0), 20.0), name="There")
    asked = []
    from serpentine3d.core import refine
    real = refine.plan
    monkeypatch.setattr(refine, "plan",
                        lambda shape, *a, **kw: asked.append(shape)
                        or real(shape, *a, **kw))
    _look(vp, (20, 0, 0), 1.0)
    _settle(vp)
    assert asked and there.shape not in asked


def test_an_edit_drops_the_finer_mesh_of_the_old_shape(pane):
    vp, scene = pane
    ball = scene.add(g.make_sphere((0, 0, 0), 20.0), name="Ball")
    _look(vp, (20, 0, 0), 1.0)
    _settle(vp)
    scene.replace_shape(ball.id, g.make_sphere((0, 0, 0), 19.0))
    edited = scene.get(ball.id)
    assert vp._refine.shown(edited) is edited.mesh


def test_a_click_reads_the_mesh_the_pane_draws(pane, monkeypatch):
    vp, scene = pane
    ball = scene.add(g.make_sphere((0, 0, 0), 20.0), name="Ball")
    _look(vp, (20, 0, 0), 1.0)
    _settle(vp)
    read = []
    real = vp._refine.shown
    monkeypatch.setattr(vp._refine, "shown",
                        lambda obj: read.append(obj.id) or real(obj))
    vp.pick_hits(400, 300)
    assert ball.id in read
