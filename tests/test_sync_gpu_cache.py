"""Walking the whole scene once per frame, per viewport.

_sync_gpu reconciles the GPU cache against the scene: which objects need
buffers, which have gone, which changed linetype. It ran on every paint, so
on the cave file that is 7064 objects of Python bookkeeping a frame — and
four times over in the quad layout, which is most of why a full redraw there
cost 4.6x a single view rather than the 4x the extra pixels explain.

Nothing about that walk changes between frames unless the scene does. So it
is skipped unless something it depends on moved, and the tests below are
about what "moved" has to mean. Two of those are traps: layer linetypes are
edited without notifying the scene, and background tessellation finishes
without notifying it either.

The walk is counted rather than inspected — asserting on scene.all() calls
needs no GL context, which an offscreen test has no way to make.
"""

import pytest

from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui.viewport import Viewport


@pytest.fixture
def counted(_qapp):
    """A viewport whose scene walk is counted and always empty.

    Empty because a non-empty walk builds GPU buffers, and there is no
    context to build them in; the reconciling is what is under test, not
    what it uploads.
    """
    scene = Scene()
    vp = Viewport(scene, SelectionManager(scene))
    walks = []

    def all_objects():
        walks.append(1)
        return []

    scene.all = all_objects
    return vp, scene, walks


def test_an_unchanged_scene_is_not_walked_again(counted):
    vp, _scene, walks = counted
    vp._sync_gpu()
    vp._sync_gpu()
    vp._sync_gpu()
    assert len(walks) == 1, "re-reconciled a scene that had not changed"


def test_a_changed_scene_is_walked_again(counted):
    vp, scene, walks = counted
    vp._sync_gpu()
    scene.notify()
    vp._sync_gpu()
    assert len(walks) == 2


def test_a_layer_linetype_change_is_walked_again(counted):
    """set_linetype edits the layer without notifying the scene, so the
    revision does not move — but every object on that layer needs its dashes
    rebuilt. Keyed on the revision alone, the dashes would not appear until
    something else happened to change."""
    vp, scene, walks = counted
    vp._sync_gpu()
    scene.layers.set_linetype(scene.layers.all()[0].id, "Dashed")
    vp._sync_gpu()
    assert len(walks) == 2


def test_finished_tessellation_is_walked_again(counted):
    """A big mesh is built on a worker and the object becomes drawable with
    no change to the scene at all. Miss that and the object stays a bounding
    box until the user moves something else."""
    vp, _scene, walks = counted
    vp._sync_gpu()
    vp._on_tess_done()
    vp._sync_gpu()
    assert len(walks) == 2


def test_a_lost_context_walks_again(counted):
    """initializeGL runs again after a dock or undock and throws the cache
    away. The scene has not changed, but every object needs new arrays — so
    the reconcile has to happen regardless of the key."""
    vp, _scene, walks = counted
    vp._sync_gpu()
    vp._drop_gpu_cache()
    vp._sync_gpu()
    assert len(walks) == 2
