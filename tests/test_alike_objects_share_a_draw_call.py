"""Alike objects share a draw call, and nothing about them shows it.

Four thousand chamfered cubes took 210 ms a frame on an Intel laptop GPU, and
140 of that was Python asking for each object to be drawn. So neighbouring
objects that look the same go up as one mesh and are drawn in one call.

The danger in that is a batch that goes on drawing what used to be true, so
most of this is about what must not be merged, and about a batch noticing
when something has changed. Like test_viewport_perf these count GL calls. A
batched frame and an object-at-a-time frame were compared pixel by pixel on a
real GPU when this was written, which no test here can do.
"""

import numpy as np
import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.mesh import MeshShape
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.core.tessellate import merged, tessellate
from serpentine3d.ui import gpu_share
from serpentine3d.ui import viewport as vp_mod

class _GLRecorder:
    """Stands in for the OpenGL module and counts draws, like the one in
    test_viewport_perf."""

    def __init__(self):
        self.calls = {}
        self._consts = {}

    def __getattr__(self, name):
        if name.startswith("GL_"):
            return self._consts.setdefault(name, 0x2000 + len(self._consts))

        def fn(*a, **k):
            self.calls[name] = self.calls.get(name, 0) + 1
            return 0
        return fn

    @property
    def draws(self) -> int:
        return (self.calls.get("glDrawArrays", 0)
                + self.calls.get("glDrawElements", 0))


@pytest.fixture
def gl(monkeypatch):
    rec = _GLRecorder()
    monkeypatch.setattr(vp_mod, "GL", rec)
    gpu_share.reset()
    yield rec
    gpu_share.reset()


def _view(count=0, far=False):
    scene = Scene()
    x0 = 3_000_000.0 if far else 0.0
    for i in range(count):
        scene.add(g.make_box((x0 + i * 3.0, 0.0, 0.0), 1.0, 1.0, 1.0))
    view = vp_mod.Viewport(scene, SelectionManager(scene))
    view.resize(800, 600)
    view._mesh_prog, view._line_prog = 11, 12
    view._thick_prog, view._point_prog = 13, 14
    view._max_line_width = 1.0
    _sync(view)
    view.zoom_extents()
    return view


def _sync(view):
    for obj in view.scene.all():
        assert obj.mesh is not None     # meshed here, not on the workers
    view._sync_gpu()


def _items(view, mode="shaded", locked=(), light=False):
    return view._batched(view.scene.visible_objects(), set(locked), mode,
                         light)


def _batches(items):
    return [i for i in items if isinstance(i, vp_mod._Batch)]


def _uids(items):
    """The meshes in `items`, in the order they will be drawn."""
    out = []
    for item in items:
        out.extend(item.gpu._share_key[1] if isinstance(item, vp_mod._Batch)
                   else [item.mesh.uid])
    return out


def _matrices(view):
    w, h = view.width(), view.height()
    v = view.camera.view_matrix()
    return view.camera.proj_matrix(w, h) @ v, v


def _frame_draws(gl, view, **kw):
    gl.calls.clear()
    view._draw_objects(*_matrices(view), **kw)
    return gl.draws


# -- what it saves --

def test_a_thousand_alike_objects_are_a_few_draw_calls(gl):
    view = _view(400)
    assert _frame_draws(gl, view) < 400 * 2 / 8


def test_the_work_of_a_frame_stops_growing_with_the_objects(gl):
    small = _frame_draws(gl, _view(100))
    assert _frame_draws(gl, _view(400)) < small * 8


def test_a_batch_is_drawn_with_all_of_its_triangles(gl):
    view = _view(50)
    each = len(view.scene.all()[0].mesh.triangles)
    items = _items(view)
    held = sum(b.gpu.tri_count for b in _batches(items))
    loose = sum(view._gpu[o.id].tri_count for o in items
                if not isinstance(o, vp_mod._Batch))
    assert held + loose == 50 * each * 3


def test_one_upload_of_a_batch_serves_every_pane(gl):
    first = _view(0)
    second = vp_mod.Viewport(first.scene, first.selection)
    second._mesh_prog = 11
    for i in range(70):
        first.scene.add(g.make_box((i * 2.0, 0.0, 0.0), 1.0, 1.0, 1.0))
    _sync(first)
    _sync(second)
    _items(first)
    uploads = gpu_share.count()
    _items(second)
    assert gpu_share.count() == uploads


# -- what must stay as it was --

def test_the_draw_order_survives(gl):
    view = _view(120)
    in_order = [o.mesh.uid for o in view.scene.all()]
    view.scene.all()[60].color = (1.0, 0.0, 0.0)
    assert _uids(_items(view)) == in_order


def test_only_neighbours_are_merged(gl):
    """Moving red objects together would change which of two coincident
    faces wins, so red, green, red stays three."""
    view = _view(6)
    red, green = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)
    for i, o in enumerate(view.scene.all()):
        o.color = red if i < 2 or i > 3 else green
    looks = [b.look[0] for b in _batches(_items(view))]
    for one, two in zip(looks, looks[1:]):
        assert one is not two


def test_a_new_colour_shows_on_the_next_frame_unannounced(gl):
    view = _view(10)
    first = _batches(_items(view))[0].look
    for o in view.scene.all():
        o.color = (1.0, 0.0, 0.0)
    assert _batches(_items(view))[0].look != first


def test_a_layers_new_colour_shows_too(gl):
    view = _view(10)
    first = _batches(_items(view))[0].look
    view.scene.layers.set_color(view.scene.all()[0].layer_id,
                                (0.0, 0.0, 1.0))
    assert _batches(_items(view))[0].look != first


def test_a_locked_layer_is_greyed_as_a_batch(gl):
    view = _view(10)
    layer_id = view.scene.all()[0].layer_id
    assert (_batches(_items(view, locked=[layer_id]))[0].look
            != _batches(_items(view))[0].look)


@pytest.mark.parametrize("mark", ["selected", "material", "plane", "note"])
def test_something_special_about_an_object_keeps_it_out(gl, mark):
    view = _view(9)
    odd = view.scene.all()[4]
    if mark == "selected":
        view.selection.set([odd.id])
    elif mark == "material":
        odd.material = {"metallic": 1.0}
    elif mark == "plane":
        odd.clip_plane = {"enabled": False}
    else:
        odd.annotation = {"text": "hello"}
    assert any(i is odd for i in _items(view))


def test_a_picked_face_keeps_its_object_out(gl):
    view = _view(9)
    odd = view.scene.all()[4]
    view.selection.subobjects = [(odd.id, "face", 0)]
    assert any(i is odd for i in _items(view))


def test_letting_go_of_an_object_gives_the_same_batches_back(gl):
    view = _view(40)
    before = {id(b) for b in _batches(_items(view))}
    view.selection.set([view.scene.all()[20].id])
    _items(view)
    view.selection.set([])
    assert {id(b) for b in _batches(_items(view))} == before


def test_a_translucent_frame_is_drawn_an_object_at_a_time(gl):
    view = _view(40)
    view.scene.all()[0].material = {"opacity": 0.5}
    assert _frame_draws(gl, view) >= 40


@pytest.mark.parametrize("mode", ["ghosted", "rendered"])
def test_modes_with_an_order_or_materials_are_not_batched(gl, mode):
    view = _view(40)
    assert _frame_draws(gl, view, mode_override=mode) >= 40


def test_a_clipped_frame_is_not_batched(gl, monkeypatch):
    view = _view(40)
    plane = (0.0, 0.0, 1.0, 100.0)
    monkeypatch.setattr(view, "_clip_vectors", lambda: [plane])
    monkeypatch.setattr(view, "_draw_section_caps", lambda *a: None)
    assert _frame_draws(gl, view) >= 40


def test_far_objects_keep_their_own_anchor(gl):
    assert not _batches(_items(_view(9, far=True)))


def test_dashes_keep_their_own_buffers(gl):
    view = _view(9)
    assert all(vp_mod._GpuObject(o.mesh, dash_key="Dashed").plain is False
               for o in view.scene.all())


def test_a_mesh_too_big_to_be_worth_it_keeps_its_call(gl):
    grid = np.array([[x, y, 0.0] for x in range(40) for y in range(40)])
    tris = np.array([(a, a + 1, a + 40) for a in range(1500)
                     if (a + 1) % 40], np.uint32)
    big = tessellate(MeshShape(grid, tris))
    assert len(big.triangles) > vp_mod.BATCH_MAX_TRIANGLES / 2
    limit = vp_mod.BATCH_MAX_TRIANGLES
    assert vp_mod._GpuObject(big, dash_key="Continuous").plain is (
        len(big.triangles) <= limit)


def test_points_and_hatches_stay_out(gl):
    view = _view(0)
    dot = view.scene.add(g.make_point((0.0, 0.0, 0.0)))
    for i in range(4):
        view.scene.add(g.make_point((i + 1.0, 0.0, 0.0)))
    _sync(view)
    assert view._gpu[dot.id].plain is False
    assert not _batches(_items(view))


# -- what it costs to keep --

def test_one_deleted_object_rebuilds_one_batch(gl):
    """Why a run is cut by the mesh and not by counting: counting would move
    every batch after this one, and they would all go up again."""
    view = _view(300)
    before = {b.gpu._share_key[1] for b in _batches(_items(view))}
    view.scene.remove(view.scene.all()[150].id)
    _sync(view)
    after = {b.gpu._share_key[1] for b in _batches(_items(view))}
    assert len(after - before) <= 1


def test_batches_nobody_draws_are_given_back(gl):
    view = _view(70)
    _items(view)
    assert view._batches
    view.scene.all()[0].color = (1.0, 0.0, 0.0)
    for obj in view.scene.all():
        view.selection.set([obj.id])
    view.selection.set([o.id for o in view.scene.all()])
    for _ in range(vp_mod.BATCH_KEEP_DRAWS * 2 + 1):
        _items(view)
    assert not view._batches


def test_a_lost_context_lets_go_of_the_batches(gl):
    view = _view(70)
    _items(view)
    view._drop_gpu_cache()
    assert not view._batches
    assert gpu_share.count() == 0


# -- merging --

def test_merged_triangles_point_at_their_own_vertices():
    a = tessellate(g.make_box((0, 0, 0), 1, 1, 1))
    b = tessellate(g.make_box((5, 0, 0), 2, 2, 2))
    m = merged([a, b])
    assert len(m.local) == len(a.local) + len(b.local)
    assert m.triangles.dtype == np.uint32
    assert np.array_equal(m.local[m.triangles[:len(a.triangles)]],
                          a.local[a.triangles])
    assert np.array_equal(m.local[m.triangles[len(a.triangles):]],
                          b.local[b.triangles])
    assert len(m.local_edges) == len(a.local_edges) + len(b.local_edges)
    assert len(m.normals) == len(m.local) == len(m.curvature)


def test_merged_curves_have_no_faces():
    a = tessellate(g.make_line((0, 0, 0), (1, 0, 0)))
    m = merged([a, a])
    assert not m.has_faces
    assert len(m.local_edges) == 2 * len(a.local_edges)


def test_a_mesh_without_curvature_is_filled_in():
    a = tessellate(g.make_box((0, 0, 0), 1, 1, 1))
    a.curvature = np.zeros(0, np.float32)
    assert len(merged([a, a]).curvature) == 2 * len(a.local)


def test_merging_leaves_the_originals_alone():
    a = tessellate(g.make_box((0, 0, 0), 1, 1, 1))
    before = a.triangles.copy()
    merged([a, a])
    assert np.array_equal(a.triangles, before)