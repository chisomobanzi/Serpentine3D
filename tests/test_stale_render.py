"""What is drawn must be the geometry the object actually has.

Reported: drag something with the gumball and now and then the drawing
decouples from it — the object is really where the gumball says, but it is
still painted where it was, until you nudge it again and it catches up.
Intermittent, and not reproducible on demand.

The buffers uploaded to the card were cached against `id(obj.mesh)`, which
is a memory address. Moving an object builds it a new display mesh and drops
the old one, and CPython hands the freed address straight back out: in a
tight loop a new mesh lands on the dead one's address 49 times out of 50. So
the check "is this the mesh I uploaded?" says yes about a mesh that no
longer exists, and the card keeps drawing the old position.

Intermittent because it depends on what else the allocator did in between;
self-correcting because the next move usually lands somewhere else. And it
shows up as a *split* — the sub-object highlight is built from the mesh on
the spot every frame, so the yellow sits at the new position while the
shaded faces behind it are still at the old one.
"""

import numpy as np

from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.core.tessellate import DisplayMesh
from serpentine3d.ui import viewport as vp_mod


def test_a_new_mesh_never_answers_to_a_dead_ones_name():
    """The bug in one line: an address is not an identity."""
    seen_reuse = False
    prev_addr, prev_key = None, None
    for _ in range(200):
        mesh = DisplayMesh()
        if prev_addr is not None and id(mesh) == prev_addr:
            seen_reuse = True
            assert mesh.uid != prev_key, (
                "a new mesh on a dead mesh's address reads as the same mesh")
        prev_addr, prev_key = id(mesh), mesh.uid
        del mesh
    assert seen_reuse, (
        "no address was ever recycled, so this proved nothing — check the "
        "test rather than trusting it")


def test_every_mesh_a_moved_object_gets_is_a_different_mesh():
    scene = Scene()
    obj = scene.add(g.make_box((0, 0, 0), 1, 1, 1))
    keys = {obj.mesh.uid}
    for _ in range(20):
        obj = scene.replace_shape(obj.id, g.translate(obj.shape, (0.1, 0, 0)))
        assert obj.mesh.uid not in keys, "a moved object reused a mesh key"
        keys.add(obj.mesh.uid)


def test_the_uploaded_buffers_are_keyed_on_the_mesh_not_its_address():
    """What the viewport remembers about what it uploaded has to outlive the
    mesh it uploaded, because the whole question is asked after that mesh is
    gone."""
    scene = Scene()
    sel = SelectionManager(scene)
    view = vp_mod.Viewport(scene, sel)
    obj = scene.add(g.make_box((0, 0, 0), 1, 1, 1))

    view._gpu[obj.id] = _StubGpu(obj.mesh)
    assert view._gpu[obj.id].mesh_key == obj.mesh.uid, (
        "the buffers are keyed on something that dies with the mesh")


def test_moving_an_object_reuploads_its_buffers(monkeypatch):
    """End to end, minus the card: move it and what is on screen changes."""
    scene = Scene()
    sel = SelectionManager(scene)
    view = vp_mod.Viewport(scene, sel)
    monkeypatch.setattr(vp_mod, "_GpuObject",
                        lambda mesh, dash=None, dash_key=None:
                        _StubGpu(mesh, dash_key))
    obj = scene.add(g.make_box((0, 0, 0), 1, 1, 1))

    view._sync_gpu()
    first = view._gpu[obj.id]
    view._sync_gpu()
    assert view._gpu[obj.id] is first, "rebuilt buffers for unchanged geometry"

    moved = scene.replace_shape(obj.id, g.translate(obj.shape, (5, 0, 0)))
    view._sync_gpu()
    rebuilt = view._gpu[obj.id]
    assert rebuilt is not first, "moved object kept its old buffers"
    assert rebuilt.mesh_key == moved.mesh.uid
    assert first.released, "the buffers it replaced were never freed"
    assert np.allclose(rebuilt.mesh.vertices[:, 0].max(),
                       moved.mesh.vertices[:, 0].max()), (
        "uploaded vertices are not the ones the object has")


def test_control_points_follow_the_geometry(monkeypatch):
    """The same key, the same trap: control points cached against a dead
    mesh's address would be drawn where the curve used to be."""
    scene = Scene()
    view = vp_mod.Viewport(scene, SelectionManager(scene))
    obj = scene.add(g.make_control_curve([(0, 0, 0), (1, 2, 0), (3, -1, 0),
                                          (4, 1, 0)]))

    before = view._cv_points(obj)
    assert before is not None, "fixture has no control points to stale"
    moved = scene.replace_shape(obj.id, g.translate(obj.shape, (10, 0, 0)))
    after = view._cv_points(moved)
    assert after is not None
    assert after[:, 0].min() >= before[:, 0].min() + 9.0, (
        "control points stayed where the object used to be")


class _StubGpu:
    """Stands in for the real buffers, which need a GL context."""

    def __init__(self, mesh, dash_key=None):
        self.mesh_key = mesh.uid
        self.mesh = mesh
        self.dash_key = dash_key
        self.tri_count = self.line_count = self.iso_count = 0
        self.released = False

    def release(self):
        self.released = True


class _InlinePool:
    """Runs the tessellation work where it was submitted, so a test can see
    the finished state without waiting on a thread."""

    def __init__(self, run=True):
        self.run, self.queued = run, []

    def submit(self, fn):
        self.queued.append(fn)
        if self.run:
            fn()


def _big(view, monkeypatch, run=True):
    """A viewport that treats everything as heavy enough to mesh in the
    background — that path is about big survey meshes, and the bug in it is
    nothing to do with size."""
    monkeypatch.setattr(type(view), "ASYNC_FACE_COUNT", 1)
    pool = _InlinePool(run)
    monkeypatch.setattr(view, "_worker_pool", lambda: pool)
    return pool


def test_the_placeholder_box_follows_the_object_it_stands_for(monkeypatch):
    """While something is still being meshed it is drawn as its bounding
    box. Move it and that box has to move: it is standing in for the object,
    not for where the object was when the work was queued."""
    scene = Scene()
    view = vp_mod.Viewport(scene, SelectionManager(scene))
    _big(view, monkeypatch, run=False)
    obj = scene.add(g.make_box((0, 0, 0), 1, 1, 1))

    assert view._schedule_tess(obj), "fixture is not exercising the slow path"
    before = view._tess_pending[obj.id][1]
    moved = scene.replace_shape(obj.id, g.translate(obj.shape, (100, 0, 0)))
    view._schedule_tess(moved)

    after = view._tess_pending[moved.id][1]
    assert after[:, 0].min() > before[:, 0].min() + 99, (
        "the placeholder stayed where the object used to be")


def test_editing_something_still_being_meshed_does_not_strand_it(monkeypatch):
    """The work in flight is for a shape that no longer exists. If that is
    taken as 'already being dealt with', nobody ever meshes what replaced it
    and the object stays a wireframe box for good."""
    scene = Scene()
    view = vp_mod.Viewport(scene, SelectionManager(scene))
    pool = _big(view, monkeypatch, run=False)
    obj = scene.add(g.make_box((0, 0, 0), 1, 1, 1))
    view._schedule_tess(obj)                    # queued, not run

    moved = scene.replace_shape(obj.id, g.translate(obj.shape, (100, 0, 0)))
    pool.run = True                             # the queue drains
    for fn in list(pool.queued):
        fn()
    pool.queued.clear()
    view._schedule_tess(moved)

    assert scene.get(obj.id).mesh_ready, (
        "left waiting on work for geometry that no longer exists")
