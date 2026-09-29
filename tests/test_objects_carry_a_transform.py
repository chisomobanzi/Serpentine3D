"""Objects sit where a 4x4 says; moving them moves the matrix, not the B-rep.

Scene.set_transforms is what a committed gumball drag writes: the shapes
stay exactly as the file made them and the matrices move, so releasing a
drag costs a matrix per object, not a re-transform, a re-mesh and a B-rep
dump in the journal. Scene.bake is where a matrix becomes geometry, for
the operations that change the shape itself.
"""
import numpy as np

from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene


def _translation(x, y, z):
    m = np.eye(4)
    m[:3, 3] = (x, y, z)
    return m


def _rot_z(deg):
    a = np.radians(deg)
    m = np.eye(4)
    m[0, 0], m[0, 1] = np.cos(a), -np.sin(a)
    m[1, 0], m[1, 1] = np.sin(a), np.cos(a)
    return m


def test_set_transforms_moves_the_matrix_not_the_shape():
    scene = Scene()
    obj = scene.add(g.make_box((0, 0, 0), 4, 2, 1))
    local_box = obj.bbox()
    scene.set_transforms({obj.id: _translation(3, 4, 5)})
    new = scene.get(obj.id)
    assert new.transform is not None
    # The B-rep is the very same object in memory: nothing was copied.
    assert new._shape is obj._shape
    # And the world box is the local box shifted, not re-measured.
    assert new.bbox() == (tuple(np.add(local_box[0], (3, 4, 5))),
                          tuple(np.add(local_box[1], (3, 4, 5))))


def test_set_transforms_notifies_once_for_many_and_never_for_a_noop():
    scene = Scene()
    objs = [scene.add(g.make_box((i * 10, 0, 0), 1, 1, 1)) for i in range(20)]
    calls = []
    scene.add_listener(lambda: calls.append(1), ("objects",))
    m = _translation(1, 0, 0)
    scene.set_transforms({o.id: m for o in objs})
    assert len(calls) == 1
    scene.set_transforms({o.id: m for o in objs})      # same matrix again
    assert len(calls) == 1


def test_none_clears_a_transform_and_restores_the_local_box():
    scene = Scene()
    obj = scene.add(g.make_box((0, 0, 0), 4, 2, 1))
    local_box = obj.bbox()
    scene.set_transforms({obj.id: _translation(3, 4, 5)})
    scene.set_transforms({obj.id: None})
    new = scene.get(obj.id)
    assert new.transform is None
    assert new.bbox() == local_box


def test_bbox_of_a_rotated_object_is_the_world_box():
    scene = Scene()
    obj = scene.add(g.make_box((0, 0, 0), 4, 2, 1))
    scene.set_transforms({obj.id: _rot_z(90)})
    mn, mx = scene.get(obj.id).bbox()
    # (x, y) -> (-y, x): the local x 0..4, y 0..2 becomes x -2..0, y 0..4.
    assert np.allclose(mn, (-2, 0, 0), atol=1e-6)
    assert np.allclose(mx, (0, 4, 1), atol=1e-6)


def test_bake_folds_the_transform_into_the_shape():
    scene = Scene()
    obj = scene.add(g.make_box((0, 0, 0), 4, 2, 1))
    old_mesh = obj.mesh            # warm it, so the bake has one to carry
    scene.set_transforms({obj.id: _translation(3, 4, 5)})
    world_box = scene.get(obj.id).bbox()   # the world box, before it is folded in
    scene.bake(obj.id)
    new = scene.get(obj.id)
    assert new.transform is None
    assert new._shape is not obj._shape
    # Re-measured by the kernel after the fold, so compare with tolerance:
    # the exact corner shift and the B-rep's own bounds differ at 1e-9.
    assert np.allclose(new.bbox()[0], world_box[0], atol=1e-6)
    assert np.allclose(new.bbox()[1], world_box[1], atol=1e-6)
    # A pure translation keeps the tessellation: moved vertices, same
    # triangles.
    assert new._mesh is not None
    assert np.allclose(new._mesh.vertices, old_mesh.vertices + (3, 4, 5),
                       atol=1e-4)
    assert new._mesh.triangles is old_mesh.triangles


def test_bake_of_an_untransformed_object_is_a_noop():
    scene = Scene()
    obj = scene.add(g.make_box((0, 0, 0), 4, 2, 1))
    out = scene.bake(obj.id)
    assert out is obj
    assert scene.get(obj.id)._shape is obj._shape


def test_clone_carries_the_transform_so_undo_costs_no_geometry():
    scene = Scene()
    obj = scene.add(g.make_box((0, 0, 0), 4, 2, 1))
    m = _rot_z(45) @ _translation(1, 2, 3)
    scene.set_transforms({obj.id: m})
    clone = scene.get(obj.id).clone()
    assert np.array_equal(clone.transform, m)
    assert clone._shape is obj._shape


def test_pick_finds_an_object_where_its_transform_put_it():
    """The pick runs in world: a transformed object is hit where the
    matrix put it, not where the shape was made."""
    from serpentine3d.core.selection import SelectionManager
    from serpentine3d.ui.viewport import Viewport

    scene = Scene()
    view = Viewport(scene, SelectionManager(scene))
    view.resize(800, 600)
    view.set_view("top")
    box = scene.add(g.make_box((-1, -1, -1), 2, 2, 2))
    scene.set_transforms({box.id: _translation(30, 20, 0)})
    centre = view.width() / 2, view.height() / 2
    # the shape was made at the origin; the matrix stands it at
    # (30, 20, 0). A pick aimed at the origin finds nothing.
    assert view.pick_objects(*centre) == []
    # and one aimed at the new place finds it.
    view.camera.target = np.asarray((30.0, 20.0, 0.0))
    assert view.pick_objects(*centre) == [box.id]


def test_committing_a_drag_does_not_void_the_box_cache():
    """The release-hang regression. The box cache holds the LOCAL box keyed
    on the shape's identity, so a pose change moves the answer without
    re-measuring the shape. If set_transforms voided the cache, the first
    painted frame after a committed drag would walk every shape's B-rep
    again — 200 solids cost a measured ~1.4 s on one frame (bench:
    cache kept ~1 ms vs ~1447 ms voided) — which on a big file was the
    30-40 s freeze after a mouse release."""
    scene = Scene()
    obj = scene.add(g.make_box((0, 0, 0), 4, 2, 1))
    obj.bbox()                       # warm: the one kernel walk
    cached = scene.get(obj.id)._bounds
    assert cached is not None and cached[0] is obj.shape
    local_lo = np.asarray(cached[1][0], float)

    scene.set_transforms({obj.id: _translation(3, 4, 5)})
    new = scene.get(obj.id)
    # the same cache tuple rides on the new object: not voided, not rebuilt
    assert new._bounds is cached
    assert new._bounds[0] is new.shape
    # and the world answer is the local box shifted, not re-measured
    wlo, _whi = new.bbox()
    assert np.allclose(np.asarray(wlo, float), local_lo + (3, 4, 5))

    # a second committed drag (rotation) still costs no re-measure
    scene.set_transforms({new.id: _rot_z(90) @ new.transform})
    twice = scene.get(new.id)
    assert twice._bounds is cached
    assert twice._bounds[0] is twice.shape
    # the world box is the eight local corners mapped by the full pose
    m = _rot_z(90) @ new.transform
    lo, hi = cached[1]
    corners = np.array([[a, b, c] for a in (lo[0], hi[0])
                           for b in (lo[1], hi[1])
                           for c in (lo[2], hi[2])])
    world = corners @ m[:3, :3].T + m[:3, 3]
    wlo2, whi2 = twice.bbox()
    assert np.allclose(np.asarray(wlo2, float), world.min(axis=0), atol=1e-9)
    assert np.allclose(np.asarray(whi2, float), world.max(axis=0), atol=1e-9)
