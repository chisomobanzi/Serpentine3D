"""Geometry nobody can see should not be meshed or uploaded (GitHub #5).

The viewport draws `visible_objects()` but reconciled its GPU buffers over
`all()`, so every object in the file got a display mesh built and vertex
buffers filled whether or not its layer was switched on. A reporter opened
a 510 MB file with roughly 65,000 objects and three layers ticked: about
93% of that work was for geometry that was never going to be drawn.

Layer visibility has to be part of what decides a resync, not just what
decides a draw. `LayerTable.set_visible` replaces the layer without telling
the scene, exactly as `set_linetype` does, so `scene.revision` does not
move — and a sync that skips hidden objects and then never runs again would
leave them unuploaded, and so invisible, when the layer came back on.
"""

import inspect

import numpy as np
import pytest

from serpentine3d.core.mesh import MeshShape
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager


def _qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _viewport(scene):
    _qapp()
    from serpentine3d.ui.viewport import Viewport
    return Viewport(scene, SelectionManager(scene))


def _tri() -> MeshShape:
    return MeshShape(
        vertices=np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0],
                           [0.0, 1.0, 0.0]]),
        triangles=np.array([[0, 1, 2]]))


@pytest.fixture
def scene():
    return Scene()


# -- what gets buffers --

def test_an_object_on_a_hidden_layer_is_not_a_candidate(scene):
    off = scene.layers.create("off")
    obj = scene.add(_tri(), layer_id=off.id)
    scene.layers.set_visible(off.id, False)
    vp = _viewport(scene)

    assert obj not in vp._gpu_candidates()


def test_a_hidden_object_is_not_a_candidate(scene):
    obj = scene.add(_tri())
    scene.update(obj.id, visible=False)
    vp = _viewport(scene)

    assert vp._gpu_candidates() == []


def test_what_is_on_screen_still_gets_buffers(scene):
    """The saving is only worth having if it costs nothing visible."""
    obj = scene.add(_tri())
    vp = _viewport(scene)

    assert [o.id for o in vp._gpu_candidates()] == [obj.id]


def test_candidates_are_exactly_what_the_draw_loop_walks(scene):
    """Upload less than is drawn and objects go missing; upload more and
    this whole change buys nothing."""
    on = scene.add(_tri())
    off = scene.layers.create("off")
    scene.add(_tri(), layer_id=off.id)
    scene.layers.set_visible(off.id, False)
    vp = _viewport(scene)

    assert ([o.id for o in vp._gpu_candidates()]
            == [o.id for o in scene.visible_objects()] == [on.id])


# -- and the resync that has to follow a layer coming back --

def test_hiding_a_layer_moves_the_sync_key(scene):
    off = scene.layers.create("off")
    scene.add(_tri(), layer_id=off.id)
    vp = _viewport(scene)
    before = vp._gpu_sync_key()

    scene.layers.set_visible(off.id, False)

    assert vp._gpu_sync_key() != before


def test_showing_a_layer_again_moves_the_sync_key(scene):
    """The one that bites: buffers were released on the way out, so a key
    that did not move on the way back in would leave the layer blank."""
    off = scene.layers.create("off")
    scene.add(_tri(), layer_id=off.id)
    scene.layers.set_visible(off.id, False)
    vp = _viewport(scene)
    hidden_key = vp._gpu_sync_key()

    scene.layers.set_visible(off.id, True)

    assert vp._gpu_sync_key() != hidden_key


def test_hiding_an_object_moves_the_sync_key(scene):
    obj = scene.add(_tri())
    vp = _viewport(scene)
    before = vp._gpu_sync_key()

    scene.update(obj.id, visible=False)

    assert vp._gpu_sync_key() != before


def test_an_untouched_scene_keeps_its_key(scene):
    """A key that moved every frame would rebuild every buffer every frame."""
    scene.add(_tri())
    vp = _viewport(scene)

    assert vp._gpu_sync_key() == vp._gpu_sync_key()


# -- the loop itself, which cannot be run here: _GpuObject calls GL --

def test_the_sync_walks_candidates_rather_than_the_whole_scene():
    from serpentine3d.ui.viewport import Viewport

    src = inspect.getsource(Viewport._sync_gpu)
    assert "_gpu_candidates()" in src
    assert "self.scene.all()" not in src


def test_the_sync_keys_off_the_shared_helper():
    from serpentine3d.ui.viewport import Viewport

    assert "_gpu_sync_key()" in inspect.getsource(Viewport._sync_gpu)
