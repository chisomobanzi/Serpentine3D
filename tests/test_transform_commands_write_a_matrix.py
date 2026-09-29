"""Whole-object transform commands ride as a 4x4 pose, not a re-written
B-rep.

The same deal a gumball drag makes: move/rotate/scale/mirror/orient/array
of whole objects call Scene.set_transforms, so a hundred objects cost a
hundred matrices instead of a hundred re-transforms, re-meshes and B-rep
dumps. The shape a file made is the shape the object keeps.
"""

import numpy as np
import pytest

import serpentine3d.commands  # registers all commands  # noqa: F401
from serpentine3d.core import geometry as g


def _is_translation(m, off, tol=1e-9):
    return (m is not None
            and np.allclose(m[:3, :3], np.eye(3), atol=tol)
            and np.allclose(m[:3, 3], np.asarray(off, float), atol=tol))


def test_move_writes_a_transform(env):
    scene, sel, hist, ctx, proc = env
    obj = scene.add(g.make_box((0, 0, 0), 1, 1, 1))
    proc.run("move")
    proc.click_object(obj.id)
    proc.finish_selection()
    proc.provide_text("0,0,0")
    proc.provide_text("5,5,0")
    assert not proc.busy
    obj = scene.get(obj.id)
    # the shape the file made is the shape the object keeps
    mn, mx = g.bbox(obj.shape)
    assert mn == pytest.approx((0, 0, 0), abs=1e-6)
    assert mx == pytest.approx((1, 1, 1), abs=1e-6)
    # the pose carries the move
    assert _is_translation(obj.transform, (5.0, 5.0, 0.0))
    wmn, wmx = obj.bbox()
    assert wmn == pytest.approx((5, 5, 0), abs=1e-6)
    # undo takes the pose off without touching the shape
    proc.run("undo")
    obj = scene.get(obj.id)
    assert obj.transform is None
    mn, _ = g.bbox(obj.shape)
    assert mn == pytest.approx((0, 0, 0), abs=1e-6)


def test_copy_shares_the_local_shape_and_carries_a_pose(env):
    scene, sel, hist, ctx, proc = env
    obj = scene.add(g.make_box((0, 0, 0), 1, 1, 1))
    proc.run("copy")
    proc.click_object(obj.id)
    proc.finish_selection()
    proc.provide_text("0,0,0")
    proc.provide_text("5,0,0")
    proc.provide_text("")           # finish
    assert not proc.busy
    assert len(scene.all()) == 2
    orig = scene.get(obj.id)
    copy = [o for o in scene.all() if o.id != obj.id][0]
    # one tessellation, one B-rep: the copy shares the original's local
    # shape and stands where its pose puts it
    assert copy._shape is orig._shape
    assert orig.transform is None
    assert _is_translation(copy.transform, (5.0, 0.0, 0.0))
    cmn, _ = copy.bbox()
    assert cmn[0] == pytest.approx(5, abs=1e-6)


def test_rotate_writes_a_transform(env):
    scene, sel, hist, ctx, proc = env
    obj = scene.add(g.make_box((1, 0, 0), 1, 1, 1))
    proc.run("rotate")
    proc.click_object(obj.id)
    proc.finish_selection()
    proc.provide_text("0,0,0")
    proc.provide_text("90")
    assert not proc.busy
    obj = scene.get(obj.id)
    mn, mx = g.bbox(obj.shape)
    assert mn == pytest.approx((1, 0, 0), abs=1e-6)   # shape untouched
    assert mx == pytest.approx((2, 1, 1), abs=1e-6)
    m = obj.transform
    assert m is not None
    assert not _is_translation(m, (0, 0, 0))
    assert np.linalg.det(m[:3, :3]) == pytest.approx(1.0, abs=1e-9)
    # 90 degrees about the origin: the box's (2,1) corner lands on (−1,2)
    wmn, wmx = obj.bbox()
    assert wmx[1] == pytest.approx(2, abs=1e-6)
    assert wmn[0] == pytest.approx(-1, abs=1e-6)


def test_scale_writes_a_transform(env):
    scene, sel, hist, ctx, proc = env
    obj = scene.add(g.make_box((0, 0, 0), 1, 1, 1))
    proc.run("scale")
    proc.click_object(obj.id)
    proc.finish_selection()
    proc.provide_text("0,0,0")
    proc.provide_text("2")
    assert not proc.busy
    obj = scene.get(obj.id)
    assert g.volume(obj.shape) == pytest.approx(1, rel=1e-6)   # untouched
    m = obj.transform
    assert m is not None
    assert np.linalg.det(m[:3, :3]) == pytest.approx(8.0, rel=1e-6)
    assert g.volume(obj.world_geometry()) == pytest.approx(8, rel=1e-6)


def test_mirror_without_keep_writes_a_reflection(env):
    scene, sel, hist, ctx, proc = env
    obj = scene.add(g.make_box((1, 0, 0), 1, 1, 1))
    proc.run("mirror")
    proc.click_object(obj.id)
    proc.finish_selection()
    proc.provide_text("0,0,0")
    proc.provide_text("0,10,0")
    proc.provide_text("No")          # keep original: No
    assert not proc.busy
    assert len(scene.all()) == 1
    obj = scene.get(obj.id)
    mn, mx = g.bbox(obj.shape)
    assert mn == pytest.approx((1, 0, 0), abs=1e-6)   # untouched
    m = obj.transform
    assert m is not None
    assert np.linalg.det(m[:3, :3]) < 0               # a reflection, not a turn
    # the box stood at x 1..2; mirrored in the YZ plane it stands at −2..−1
    wmn, wmx = obj.bbox()
    assert wmx[0] == pytest.approx(-1, abs=1e-6)
    assert wmn[0] == pytest.approx(-2, abs=1e-6)


def test_orient_writes_a_similarity(env):
    scene, sel, hist, ctx, proc = env
    obj = scene.add(g.make_box((0, 0, 0), 4, 2, 1))
    proc.run("orient")
    proc.click_object(obj.id)
    proc.finish_selection()
    proc.provide_text("0,0,0")           # ref 1
    proc.provide_text("4,0,0")           # ref 2 (along +X)
    proc.provide_text("10,0,0")          # target 1
    proc.provide_text("10,4,0")          # target 2 (along +Y): 90deg turn
    assert not proc.busy
    obj = scene.get(obj.id)
    mn, mx = g.bbox(obj.shape)
    assert mn == pytest.approx((0, 0, 0), abs=1e-6)   # shape untouched
    assert g.volume(obj.shape) == pytest.approx(8, rel=1e-6)
    m = obj.transform
    assert m is not None
    # a similarity: it turns and moves, it does not stretch
    assert np.linalg.det(m[:3, :3]) == pytest.approx(1.0, abs=1e-9)
    # the +X extent of the box now runs along +Y, standing at x 8..10
    wmn, wmx = obj.bbox()
    assert wmn == pytest.approx((8, 0, 0), abs=1e-5)
    assert wmx == pytest.approx((10, 4, 1), abs=1e-5)


def test_polar_array_copies_share_the_shape_and_carry_poses(env):
    scene, sel, hist, ctx, proc = env
    obj = scene.add(g.make_box((0, 0, 0), 2, 2, 2))
    proc.run("arraypolar")
    proc.click_object(obj.id)
    proc.finish_selection()
    proc.provide_text("20,0,0")          # center
    proc.provide_text("4")               # number of items
    proc.provide_text("360")             # full circle: step 90
    assert not proc.busy
    assert len(scene.all()) == 4
    orig = scene.get(obj.id)
    assert orig.transform is None
    copies = [o for o in scene.all() if o.id != obj.id]
    for c in copies:
        assert c._shape is orig._shape   # one B-rep, four poses
        assert c.transform is not None
    # the copies stand where their poses put them, spread around the ring
    centres = [np.asarray(c.bbox()[0]) + np.asarray(c.bbox()[1])
               for c in copies]
    for i in range(len(centres)):
        for j in range(i + 1, len(centres)):
            assert np.linalg.norm(centres[i] - centres[j]) > 5.0
