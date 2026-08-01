"""Sorting translucent objects back to front, once per frame instead of
once per object.

A single object with opacity below 1 puts the whole scene through a
back-to-front sort every frame, so the cave file paid 6583 Python calls a
frame — each building two arrays and taking a norm — to order objects that
had not moved. Profiling put it at about a fifth of a full redraw, in every
viewport.

The distance is now one vectorised subtraction per frame, and the centres
behind it are cached against the mesh they came from, so they survive both
the camera moving and the scene changing around them.

The order itself must not change, which is what the differential test is
for: the old per-object key function is kept here and the two are compared
on awkward input.
"""

import numpy as np
import pytest

from serpentine3d.ui.viewport import _back_to_front


def old_order(centres, valid, eye):
    """How this was sorted when the key was computed per object."""
    def depth(i):
        if not valid[i]:
            return 0.0
        return -float(np.linalg.norm(centres[i] - eye))

    return sorted(range(len(centres)), key=depth)


def test_farthest_is_drawn_first():
    """Back to front: what is furthest away is laid down first, so nearer
    translucent things composite over it."""
    centres = np.array([[1.0, 0, 0], [9.0, 0, 0], [5.0, 0, 0]])
    valid = np.array([True, True, True])
    order = _back_to_front(centres, valid, np.zeros(3))
    assert list(order) == [1, 2, 0]


def test_unknown_bounds_sort_last():
    """An object still being meshed has no bounds and used to score zero,
    which put it nearest. Keep that: changing it would reorder drawings that
    look right today."""
    centres = np.array([[1.0, 0, 0], [0.0, 0, 0], [9.0, 0, 0]])
    valid = np.array([True, False, True])
    order = _back_to_front(centres, valid, np.zeros(3))
    assert list(order) == [2, 0, 1]


def test_equal_distances_keep_their_incoming_order():
    """The list arrives sorted by draw_order, and the depth sort was stable,
    so objects the same distance away kept it. An unstable sort would shuffle
    coincident faces from frame to frame and make them flicker."""
    centres = np.array([[3.0, 0, 0]] * 5)
    valid = np.array([True] * 5)
    order = _back_to_front(centres, valid, np.zeros(3))
    assert list(order) == [0, 1, 2, 3, 4]


def test_no_objects_is_not_an_error():
    order = _back_to_front(np.zeros((0, 3)), np.zeros(0, bool), np.zeros(3))
    assert list(order) == []


def test_nothing_has_bounds_yet():
    """A scene opened but not yet meshed: every key is zero, every object
    keeps its place."""
    centres = np.zeros((3, 3))
    order = _back_to_front(centres, np.zeros(3, bool), np.ones(3))
    assert list(order) == [0, 1, 2]


# --- the centres behind the distances --------------------------------------

class FakeMesh:
    def __init__(self, uid, lo, hi, calls):
        self.uid = uid
        self._b = (np.array(lo, float), np.array(hi, float))
        self._calls = calls

    def bounds(self):
        self._calls.append(self.uid)
        return self._b


class FakeObject:
    def __init__(self, mesh=None):
        self.mesh = mesh
        self.mesh_ready = mesh is not None


@pytest.fixture
def vp(_qapp):
    from serpentine3d.core.scene import Scene
    from serpentine3d.core.selection import SelectionManager
    from serpentine3d.ui.viewport import Viewport

    scene = Scene()
    return Viewport(scene, SelectionManager(scene))


def test_a_centre_is_the_middle_of_the_bounds(vp):
    calls = []
    obj = FakeObject(FakeMesh("m1", [0, 0, 0], [2, 4, 6], calls))
    centres, valid = vp._centres_for([obj])
    assert list(centres[0]) == [1, 2, 3]
    assert list(valid) == [True]


def test_an_unmeshed_object_has_no_centre(vp):
    centres, valid = vp._centres_for([FakeObject(None)])
    assert list(valid) == [False]
    assert centres.shape == (1, 3), "still needs a row, or the rows misalign"


def test_a_centre_is_worked_out_once_per_mesh(vp):
    """The camera moves every frame; the geometry does not. Recomputing the
    centres on each orbit step is the cost this cache exists to remove."""
    calls = []
    objs = [FakeObject(FakeMesh(f"m{i}", [0, 0, 0], [i, i, i], calls))
            for i in range(3)]
    for _ in range(5):
        vp._centres_for(objs)
    assert sorted(calls) == ["m0", "m1", "m2"]


def test_a_remeshed_object_is_not_stale(vp):
    """A new mesh is a new uid, so the old centre cannot be handed out for
    it — geometry that moved would otherwise sort at where it used to be."""
    calls = []
    obj = FakeObject(FakeMesh("m1", [0, 0, 0], [2, 2, 2], calls))
    assert list(vp._centres_for([obj])[0][0]) == [1, 1, 1]
    obj.mesh = FakeMesh("m2", [10, 10, 10], [12, 12, 12], calls)
    assert list(vp._centres_for([obj])[0][0]) == [11, 11, 11]


def test_centres_of_meshes_that_have_gone_are_dropped(vp):
    """Every remesh mints a new uid, so a cache that only grows is a slow
    leak. Reconciling the scene is when meshes are replaced, so it is also
    when the centres of the ones that went are let go."""
    vp._centre_cache["stale-mesh"] = np.zeros(3)
    vp.scene.notify()                       # something changed; walk again
    vp._sync_gpu()                          # an empty scene: nothing is live
    assert vp._centre_cache == {}


@pytest.mark.parametrize("seed", range(8))
def test_it_orders_exactly_as_the_per_object_key_did(seed):
    rng = np.random.default_rng(seed)
    n = 40
    centres = rng.normal(scale=50, size=(n, 3))
    # Duplicate rows and an eye sitting on top of one of them: ties and a
    # zero distance are where a sort's stability and sign show up.
    centres[5] = centres[6] = centres[7]
    valid = rng.random(n) > 0.25
    eye = centres[7].copy() if seed % 2 else rng.normal(scale=50, size=3)

    assert list(_back_to_front(centres, valid, eye)) \
        == old_order(centres, valid, eye)
