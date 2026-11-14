"""Positioning an array has to keep up with the mouse.

A 5 x 5 array of a filleted plate with holes took ten seconds a mouse move in
the quad layout. The copies were built and tessellated from nothing, once for
each of the four panes, to show triangles the original already had. The app
is fast again the moment the command ends, because the real copies are only
built once; only the ghost was being rebuilt.

So the ghost is the original's mesh at each offset, and these check it is
still the array you would get, as well as that it no longer costs anything.
"""

from __future__ import annotations

import numpy as np
import pytest

from serpentine3d.app import MainWindow
from serpentine3d.core import geometry as g
from serpentine3d.core import tessellate as tess
from serpentine3d.core.mesh import MeshShape
from serpentine3d.ui import viewport as vp_mod

BOX = (10.0, 6.0, 4.0)


@pytest.fixture
def window():
    w = MainWindow()
    w.resize(1200, 800)
    w.set_view_layout("quad")
    yield w
    w.processor.cancel()


def _array(w, objs, nx, ny):
    """`array` waiting for its X spacing, with `objs` selected."""
    w.selection.set([o.id for o in objs])
    w.processor.run("array")
    w.processor.provide_text(str(nx))
    w.processor.provide_text(str(ny))
    return w.processor.request


def _along(req, spacing):
    """Where the cursor is for a request's spacing to come out as `spacing`."""
    centre, direction = req.axis_lock
    return tuple(np.asarray(centre) + spacing * np.asarray(direction))


def _hover(w, point):
    w._ghost_timer = None           # the 30Hz cap, not what is being tested
    w._on_mouse_world(point)


def _box_at(w, x=0.0, y=0.0, z=0.0):
    return w.scene.add(g.make_box((x, y, z), *BOX))


def _corners(dm):
    """Every copy's lowest corner, from the triangles as they would be drawn."""
    tris = dm.vertices[dm.triangles.ravel()].reshape(-1, 12 * 3, 3)
    return sorted(tuple(np.round(t.min(axis=0), 3).tolist()) for t in tris)


# -- what it shows --

def test_the_x_prompt_shows_the_row_at_the_spacing_under_the_cursor(window):
    o = _box_at(window)
    req = _array(window, [o], 3, 2)
    _hover(window, _along(req, 25.0))
    assert _corners(window.viewport._ghost) == [
        (25.0, 0.0, 0.0), (50.0, 0.0, 0.0)]


def test_the_y_prompt_shows_every_copy(window):
    o = _box_at(window)
    req = _array(window, [o], 3, 2)
    window.processor.provide(_along(req, 25.0))
    req = window.processor.request
    _hover(window, _along(req, 12.0))
    assert _corners(window.viewport._ghost) == [
        (0.0, 12.0, 0.0), (25.0, 0.0, 0.0), (25.0, 12.0, 0.0),
        (50.0, 0.0, 0.0), (50.0, 12.0, 0.0)]


def test_a_spacing_behind_the_centre_goes_the_other_way(window):
    o = _box_at(window)
    req = _array(window, [o], 2, 1)
    _hover(window, _along(req, -30.0))
    assert _corners(window.viewport._ghost) == [(-30.0, 0.0, 0.0)]


def test_the_ghost_is_where_the_copies_land(window):
    """The whole point of a preview: compared with the objects it promised."""
    o = _box_at(window, 3.0, 4.0, 5.0)
    req = _array(window, [o], 5, 5)
    window.processor.provide(_along(req, 20.0))
    req = window.processor.request
    point = _along(req, 15.0)
    _hover(window, point)
    ghost = window.viewport._ghost
    window.processor.provide(point)
    assert not window.processor.busy
    copies = [c for c in window.scene.all() if c.id != o.id]
    assert len(copies) == 24
    assert _corners(ghost) == sorted(
        tuple(np.round(g.bbox(c.shape)[0], 3).tolist()) for c in copies)


def test_every_selected_object_is_in_the_ghost(window):
    objs = [_box_at(window), _box_at(window, 0.0, 0.0, 20.0)]
    req = _array(window, objs, 2, 1)
    _hover(window, _along(req, 40.0))
    assert _corners(window.viewport._ghost) == [
        (40.0, 0.0, 0.0), (40.0, 0.0, 20.0)]


def test_curves_and_points_are_ghosted_too(window):
    objs = [window.scene.add(g.make_line((0, 0, 0), (10, 0, 0))),
            window.scene.add(g.make_point((5.0, 3.0, 0.0)))]
    req = _array(window, objs, 3, 1)
    _hover(window, _along(req, 30.0))
    ghost = window.viewport._ghost
    assert ghost.edge_segments[:, :, 0].max() == pytest.approx(70.0)
    assert sorted(ghost.points[:, 0].tolist()) == pytest.approx([35.0, 65.0])


def test_an_imported_mesh_is_ghosted_as_well(window):
    mesh = MeshShape(np.array([[0, 0, 0], [8, 0, 0], [0, 8, 0]], float),
                     np.array([[0, 1, 2]], np.uint32))
    o = window.scene.add(mesh)
    req = _array(window, [o], 2, 1)
    _hover(window, _along(req, 20.0))
    tris, _segs = window.viewport._ghost_geometry()
    assert len(tris) == 3
    assert tris[:, 0].min() == pytest.approx(20.0)


def test_a_spacing_of_nothing_has_nothing_new_to_show(window):
    o = _box_at(window)
    req = _array(window, [o], 3, 3)
    _hover(window, _along(req, 0.0))
    assert window.viewport._ghost is None


def test_far_from_home_the_ghost_keeps_its_precision(window):
    """The mesh is float32 offsets; the copies have to go through the world."""
    o = _box_at(window, 2_000_000.0, -3_000_000.0, 0.0)
    req = _array(window, [o], 2, 1)
    _hover(window, _along(req, 0.125 + 30.0))
    assert o.mesh.far
    ghost = window.viewport._ghost
    assert ghost.far
    tris, _segs = window.viewport._ghost_geometry()
    assert tris[:, 0].min() == pytest.approx(2_000_030.125, abs=1e-6)


# -- what it costs --

def test_no_part_of_positioning_an_array_tessellates(window, monkeypatch):
    objs = [_box_at(window), _box_at(window, 0.0, 0.0, 20.0)]
    for o in objs:
        assert len(o.mesh.triangles)        # already on screen

    def boom(*_args, **_kw):
        raise AssertionError("the ghost is being rebuilt, not moved")

    monkeypatch.setattr(tess, "tessellate", boom)
    monkeypatch.setattr(g, "translate", boom)
    req = _array(window, objs, 5, 5)
    for spacing in (20.0, 21.0):
        _hover(window, _along(req, spacing))
        assert window.viewport._ghost is not None
    window.processor.provide(_along(req, 21.0))
    req = window.processor.request
    for spacing in (15.0, 16.0):
        _hover(window, _along(req, spacing))
        assert len(window.viewport._ghost.triangles) == (
            len(objs[0].mesh.triangles) * 2 * 24)
    monkeypatch.undo()


def test_every_pane_shows_the_one_ghost(window):
    o = _box_at(window)
    req = _array(window, [o], 5, 5)
    _hover(window, _along(req, 20.0))
    panes = window.all_viewports()
    assert len(panes) == 4
    assert all(p._ghost is panes[0]._ghost is not None for p in panes)


# -- the same saving for every other preview --

def _count_tessellate(monkeypatch):
    calls = []
    real = tess.tessellate

    def counted(shape, *args, **kw):
        calls.append(shape)
        return real(shape, *args, **kw)

    monkeypatch.setattr(tess, "tessellate", counted)
    return calls


def test_one_shape_is_tessellated_once_however_many_panes_show_it(
        window, monkeypatch):
    calls = _count_tessellate(monkeypatch)
    shape = g.make_box((0, 0, 0), 1, 2, 3)
    panes = window.all_viewports()
    for vp in panes:
        vp.set_ghost(shape)
    assert len(calls) == 1
    assert all(p._ghost is panes[0]._ghost is not None for p in panes)


def test_the_next_shape_is_not_shown_the_last_ones_mesh(window, monkeypatch):
    calls = _count_tessellate(monkeypatch)
    vp = window.viewport
    vp.set_ghost(g.make_box((0, 0, 0), 1, 1, 1))
    vp.set_ghost(g.make_box((50, 0, 0), 1, 1, 1))
    assert len(calls) == 2
    assert vp._ghost.bounds()[0][0] == pytest.approx(50.0)


def test_a_finished_ghost_is_not_kept_alive(window):
    vp = window.viewport
    vp.set_ghost(g.make_box((0, 0, 0), 1, 1, 1))
    assert vp_mod._ghost_memo[0] is not None
    vp.set_ghost(None)
    assert vp_mod._ghost_memo == (None, None)


# -- the arrays themselves --

def test_copies_keep_their_triangles_apart():
    dm = tess.tessellate(g.make_box((0, 0, 0), 1, 1, 1))
    made = tess.copies_of([dm, dm], [(5.0, 0.0, 0.0), (0.0, 5.0, 0.0)])
    n, m = len(dm.vertices), len(dm.triangles)
    assert len(made.vertices) == n * 4
    assert len(made.triangles) == m * 4
    assert made.triangles.dtype == dm.triangles.dtype
    assert made.triangles.max() == n * 4 - 1
    # each copy's triangles index its own vertices, in the original's order
    for k, shift in enumerate(((5, 0, 0), (0, 5, 0), (5, 0, 0), (0, 5, 0))):
        got = made.vertices[made.triangles[k * m:(k + 1) * m]]
        assert got == pytest.approx(dm.vertices[dm.triangles] + shift)


def test_nowhere_to_put_a_copy_is_no_mesh():
    dm = tess.tessellate(g.make_box((0, 0, 0), 1, 1, 1))
    assert tess.copies_of([dm], []) is None


def test_the_original_mesh_is_left_as_it_was():
    dm = tess.tessellate(g.make_box((0, 0, 0), 1, 1, 1))
    before = dm.local.copy(), dm.triangles.copy()
    tess.copies_of([dm], [(7.0, 0.0, 0.0)])
    assert np.array_equal(dm.local, before[0])
    assert np.array_equal(dm.triangles, before[1])

# -- a ghost too heavy to draw --

def _grid(n):
    """A wavy sheet of 2(n-1)^2 triangles, an imported mesh standing in
    for a scan."""
    xs, ys = np.meshgrid(np.arange(n, dtype=float), np.arange(n, dtype=float))
    verts = np.column_stack([xs.ravel(), ys.ravel(), np.sin(xs.ravel() / 3)])
    a = np.arange(n - 1)
    i, j = np.meshgrid(a, a)
    k = (j * n + i).ravel()
    tris = np.concatenate([np.column_stack([k, k + 1, k + n]),
                           np.column_stack([k + 1, k + n + 1, k + n])])
    return MeshShape(verts, tris.astype(np.uint32))


def test_copies_past_the_budget_are_their_boxes():
    """A scan of millions of triangles 24 times over is gigabytes, built on
    every move of the mouse. What does not fit is drawn as the box each copy
    fills, the heaviest first, so a light part beside it keeps its faces."""
    light = tess.tessellate(g.make_box((0, 0, 0), 1, 1, 1))
    heavy = tess.tessellate(_grid(20))
    offsets = [(50.0, 0.0, 0.0), (100.0, 0.0, 0.0)]
    weight = len(light.triangles) + len(light.local_edges)
    made = tess.copies_of([heavy, light], offsets, budget=weight * 2)
    assert len(made.triangles) == len(light.triangles) * 2
    boxes = made.edge_segments[len(light.local_edges) * 2:]
    assert len(boxes) == 12 * 2
    lo, hi = heavy.bounds()
    assert boxes.reshape(-1, 3).min(axis=0) == pytest.approx(lo + (50, 0, 0))
    assert boxes.reshape(-1, 3).max(axis=0) == pytest.approx(hi + (100, 0, 0))


def test_within_the_budget_nothing_is_boxed():
    heavy = tess.tessellate(_grid(20))
    made = tess.copies_of([heavy], [(50.0, 0.0, 0.0)])
    assert len(made.triangles) == len(heavy.triangles)
    assert len(made.edge_segments) == len(heavy.local_edges)


def test_an_array_too_heavy_to_ghost_shows_where_each_copy_lands(
        window, monkeypatch):
    o = window.scene.add(_grid(30))
    monkeypatch.setattr(tess, "GHOST_BUDGET", 1000)
    req = _array(window, [o], 3, 1)
    _hover(window, _along(req, 50.0))
    tris, segs = window.viewport._ghost_geometry()
    assert tris is None
    assert len(segs) == 12 * 2 * 2
    lo, hi = o.mesh.bounds()
    assert segs.min(axis=0) == pytest.approx(lo + (50, 0, 0))
    assert segs.max(axis=0) == pytest.approx(hi + (100, 0, 0))
    window.processor.provide(_along(req, 50.0))
    assert not window.processor.busy
    copies = [c for c in window.scene.all() if c.id != o.id]
    assert len(copies) == 2            # the array itself is not cut down


def test_a_ghost_is_turned_into_corners_once_however_often_it_is_painted(
        window):
    """Four panes, each painting whenever anything moves: the ghost only
    changes when the mouse does."""
    o = _box_at(window)
    req = _array(window, [o], 5, 5)
    _hover(window, _along(req, 20.0))
    panes = window.all_viewports()
    tris, segs = panes[0]._ghost_geometry()
    for p in panes:
        for _ in range(3):
            again = p._ghost_geometry()
            assert again[0] is tris and again[1] is segs


def test_the_next_mouse_position_gets_corners_of_its_own(window):
    o = _box_at(window)
    req = _array(window, [o], 2, 1)
    _hover(window, _along(req, 20.0))
    before, _segs = window.viewport._ghost_geometry()
    _hover(window, _along(req, 30.0))
    after, _segs = window.viewport._ghost_geometry()
    assert after[:, 0].min() == pytest.approx(before[:, 0].min() + 10.0)


def test_corners_are_let_go_with_the_ghost(window):
    o = _box_at(window)
    req = _array(window, [o], 2, 1)
    _hover(window, _along(req, 20.0))
    window.viewport._ghost_geometry()
    window.viewport.set_ghost(None)
    assert vp_mod._corners_memo == (None, None)
