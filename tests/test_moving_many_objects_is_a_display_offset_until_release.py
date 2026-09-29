"""A gumball move of many objects must not touch the scene until release.

The old way wrote every selected object into the scene on every mouse move:
replace_shape reset each object's mesh, and the mesh property then
tessellated the shape again, synchronously, on the drawing thread. A few
hundred objects therefore re-meshed a few hundred times per mouse move, and
the window froze for minutes while the queue of queued moves drained,
landing the objects wherever the queue had reached by release time.

Now the move rides as a display transform (Scene.drag_display: an id to a
4x4 matrix) the viewports draw each frame, and end_drag writes the scene
once — as a transform on each object (Scene.set_transforms). The geometry,
the meshes and the GPU buffers are never touched by a move: Rhino's way,
where two objects and fifty thousand cost the same.
"""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import Qt

from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.core.tessellate import DisplayMesh, tessellate

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


def _centre(obj) -> float:
    """The shape's own (local) centre along X."""
    mn, mx = g.bbox(obj.shape)
    return (mn[0] + mx[0]) / 2


def _wcentre(obj) -> float:
    """The centre where the object is shown: the pose in it."""
    mn, mx = obj.bbox()
    return (mn[0] + mx[0]) / 2


def _is_translation(m, off):
    return (np.allclose(m[:3, :3], np.eye(3))
            and np.allclose(m[:3, 3], off))


def test_moving_many_objects_does_not_touch_the_scene_until_release():
    vp, scene, sel = _vp()
    boxes = _boxes(scene)
    for b in boxes:                       # warm the meshes: the commit must
        _ = scene.get(b.id).mesh          # carry them across, not re-mesh
    _aim_at_row(vp)
    sel.set([b.id for b in boxes])
    _begin(vp, ("move", 0))               # the X arrow
    counter = _Counter(scene)
    revision = scene.revision
    uids = {b.id: scene.get(b.id).mesh.uid for b in boxes}

    vp.gumball.apply_scalar(10.0)         # one mouse move of the drag
    assert counter.calls == 0, (
        f"a drag of {MANY} objects woke the listeners before release; "
        "the move is a display transform, not a scene change")
    assert scene.revision == revision
    for b in boxes:
        assert _is_translation(scene.drag_display[b.id], (10.0, 0.0, 0.0))
    # the shapes stayed where they were; the display is all the truth
    for i, b in enumerate(boxes):
        assert _centre(scene.get(b.id)) == pytest.approx(i * 20.0 + 5.0), (
            "the shape stays where it was while the display shows it moved")

    vp.gumball.apply_scalar(20.0)         # a second move, still display
    assert counter.calls == 0
    assert scene.revision == revision
    for b in boxes:
        assert scene.get(b.id).mesh.uid == uids[b.id], (
            "no re-meshing while the drag rides as a display offset")

    vp.gumball.end_drag()                 # the one and only write
    assert counter.calls == 1, (
        f"the whole drag is one change and one notification, "
        f"got {counter.calls}")
    for i, b in enumerate(boxes):
        obj = scene.get(b.id)
        assert _centre(obj) == pytest.approx(i * 20.0 + 5.0), (
            "the release writes a transform, not the geometry")
        assert _is_translation(obj.transform, (20.0, 0.0, 0.0))
        assert _wcentre(obj) == pytest.approx(i * 20.0 + 25.0), (
            "...and the object is shown where the drag left it")
    assert not scene.drag_display


def test_commit_sets_a_transform_without_touching_the_geometry():
    vp, scene, sel = _vp()
    boxes = _boxes(scene)
    old_meshes = {b.id: scene.get(b.id).mesh for b in boxes}   # tessellates
    old_shapes = {b.id: scene.get(b.id)._shape for b in boxes}
    _aim_at_row(vp)
    sel.set([b.id for b in boxes])
    _begin(vp, ("move", 0))
    counter = _Counter(scene)
    vp.gumball.apply_scalar(7.0)
    vp.gumball.end_drag()
    assert counter.calls == 1
    for b in boxes:
        obj = scene.get(b.id)
        assert obj._shape is old_shapes[b.id], (
            "no BREP rewrite: the shape the object has is the one it had")
        assert obj.mesh is old_meshes[b.id], (
            "no re-meshing or re-upload: the mesh shown is the mesh kept")
        assert _is_translation(obj.transform, (7.0, 0.0, 0.0)), (
            "the move lives in the object's transform")
        assert _wcentre(obj) == pytest.approx(_centre(obj) + 7.0)


def test_cancelled_move_leaves_the_scene_alone():
    vp, scene, sel = _vp()
    boxes = _boxes(scene)
    old_meshes = {b.id: scene.get(b.id).mesh for b in boxes}
    _aim_at_row(vp)
    sel.set([b.id for b in boxes])
    _begin(vp, ("move", 0))
    counter = _Counter(scene)
    revision = scene.revision
    vp.gumball.apply_scalar(10.0)
    assert counter.calls == 0 and scene.revision == revision
    vp.gumball.cancel_drag()
    assert counter.calls == 0, (
        "a cancelled move wrote the scene back; it was never written")
    assert scene.revision == revision
    assert not scene.drag_display
    for i, b in enumerate(boxes):
        assert _centre(scene.get(b.id)) == pytest.approx(i * 20.0 + 5.0)
        assert scene.get(b.id).mesh is old_meshes[b.id], (
            "no re-meshing: the cancel cost the scene nothing")


def test_typed_value_commits_the_offset_once():
    vp, scene, sel = _vp()
    boxes = _boxes(scene)
    _aim_at_row(vp)
    sel.set([b.id for b in boxes])
    _begin(vp, ("move", 0))
    counter = _Counter(scene)
    gb = vp.gumball
    gb.type_char("5")                     # preview: display only
    assert counter.calls == 0
    for b in boxes:
        assert _is_translation(scene.drag_display[b.id], (5.0, 0.0, 0.0))
    gb.type_char("back")
    gb.type_char("back")                   # nothing left: back where they are
    assert counter.calls == 0
    assert not scene.drag_display
    assert np.allclose(gb.drag["offset"], 0.0)
    gb.type_char("5")
    assert gb.commit_typed()
    assert counter.calls == 1, (
        "typing a value commits once at Enter, not per keystroke")
    for i, b in enumerate(boxes):
        assert _wcentre(scene.get(b.id)) == pytest.approx(i * 20.0 + 10.0)
    assert not scene.drag_display


def test_translated_mesh_shares_indexes_and_moves_positions():
    shape = g.make_box((30.0, 20.0, 10.0), 8.0, 6.0, 4.0)
    mesh = tessellate(shape)
    off = np.array((3.0, -2.0, 1.0))
    moved = mesh.translated(off)
    assert moved.uid != mesh.uid
    assert moved.triangles is mesh.triangles
    assert moved.normals is mesh.normals
    assert moved.edge_of_segment is mesh.edge_of_segment
    assert moved.face_of_triangle is mesh.face_of_triangle
    assert np.allclose(moved.vertices, mesh.vertices + off, atol=1e-4)
    assert np.allclose(moved.edge_segments, mesh.edge_segments + off,
                       atol=1e-4)
    lo, hi = mesh.bounds()
    nlo, nhi = moved.bounds()
    assert np.allclose(nlo, lo + off, atol=1e-4)
    assert np.allclose(nhi, hi + off, atol=1e-4)
    # the lazy spatial indexes rebuild from the moved positions, no error
    moved.triangle_index()
    moved.segment_index()


def test_translated_empty_mesh_stays_empty():
    m = DisplayMesh()
    t = m.translated((1.0, 2.0, 3.0))
    assert t.uid != m.uid
    assert len(t.vertices) == 0 and len(t.triangles) == 0
    assert t.bounds() is None
