"""Geometry 300,000 units from the origin holds still while you orbit.

The GPU works in float32, whose grid at 100,000 units is 8mm wide. With
vertices uploaded absolute and one MVP cast to float32, the world-to-eye
subtraction happens in float32 and loses almost every digit, and the
rounding changes as the camera moves, so a survey that far out swims.
The fix is to upload each mesh relative to an anchor near it and fold
the anchor back into the matrix in float64, where the subtraction is
exact, casting only the small remainder.

GL cannot run under offscreen pytest, so these tests drive the pure
helpers and pin the wiring with getsource, the way the section tests do.
"""

from __future__ import annotations

import inspect

import numpy as np

from serpentine3d.core.tessellate import DisplayMesh
from serpentine3d.ui import viewport as vp
from serpentine3d.utils.math3d import look_at, perspective


FAR = np.array([300000.0, 200000.0, 0.0])


def _far_mesh(size=5.0):
    """A little box of triangles a long way from the origin."""
    mesh = DisplayMesh()
    corners = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
                        [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]],
                       float) * size + FAR
    mesh.vertices = corners
    mesh.normals = np.zeros_like(corners)
    mesh.triangles = np.array([[0, 1, 2], [0, 2, 3]], np.uint32)
    return mesh


# -- the anchor itself ----------------------------------------------------

def test_a_far_mesh_gets_an_anchor_at_its_middle():
    a = vp.mesh_anchor(_far_mesh())
    assert a is not None
    assert np.allclose(a, FAR + 2.5)


def test_a_mesh_near_the_origin_gets_none_and_the_old_path():
    mesh = _far_mesh()
    mesh.vertices = mesh.vertices - FAR
    assert vp.mesh_anchor(mesh) is None


def test_a_bare_curve_far_out_is_anchored_too():
    """Curves have no faces; their segments still need the treatment."""
    mesh = DisplayMesh()
    seg = np.array([[[0, 0, 0], [10, 0, 0]]], float) + FAR
    mesh.edge_segments = seg
    assert vp.mesh_anchor(mesh) is not None


def test_an_empty_mesh_has_nothing_to_anchor():
    assert vp.mesh_anchor(DisplayMesh()) is None


# -- rebasing the vertex data ---------------------------------------------

def test_rebased_points_are_small_and_land_back_where_they_were():
    mesh = _far_mesh()
    a = vp.mesh_anchor(mesh)
    rel = vp.rebased(mesh.vertices, a)
    assert rel.dtype == np.float32
    assert np.abs(rel).max() < 10.0
    assert np.abs(rel.astype(np.float64) + a - mesh.vertices).max() < 1e-4


def test_rebased_with_no_anchor_is_just_float32():
    pts = np.array([[1.0, 2.0, 3.0]])
    out = vp.rebased(pts, None)
    assert out.dtype == np.float32
    assert np.allclose(out, pts)


# -- folding the anchor back into the matrix ------------------------------

def test_the_anchored_matrix_projects_relative_points_to_the_same_place():
    view = look_at(FAR + (30, 40, 20), FAR, (0, 0, 1))
    mvp = perspective(45.0, 1.5, 0.1, 1000.0) @ view
    a = FAR + 2.5
    v = FAR + (1.0, 2.0, 3.0)
    truth = mvp @ np.append(v, 1.0)
    folded = vp.anchored(mvp, a).astype(np.float64) \
        @ np.append(v - a, 1.0)
    assert np.abs(folded - truth).max() < 1e-3


def test_anchored_with_no_anchor_is_the_plain_float32_cast():
    m = np.arange(16, dtype=float).reshape(4, 4)
    out = vp.anchored(m, None)
    assert out.dtype == np.float32
    assert np.allclose(out, m)


def test_a_clip_plane_still_cuts_through_the_same_world_point():
    """The shader dots uClips with the rebased pos, so the offset moves."""
    n = np.array([0.0, 0.0, -1.0])
    o = FAR + (0.0, 0.0, 2.0)                # plane 2 up, keeping below
    clip = np.array([*n, float(np.dot(-n, o))], np.float32)
    a = FAR
    (oc,) = vp.anchored_clips([clip], a)
    below = FAR + (1.0, 1.0, 1.0)
    above = FAR + (1.0, 1.0, 3.0)
    assert np.dot(oc, np.append(below - a, 1.0)) > 0
    assert np.dot(oc, np.append(above - a, 1.0)) < 0


def test_clips_with_no_anchor_pass_through_untouched():
    clip = np.array([0.0, 0.0, 1.0, 5.0], np.float32)
    assert vp.anchored_clips([clip], None)[0] is clip


# -- the swim itself ------------------------------------------------------

def _screen(m, v4, w=1600.0, h=1000.0):
    """Pixel position, in whatever precision the inputs bring."""
    p = np.asarray(m) @ np.asarray(v4)
    return np.array([p[0] / p[3] * w / 2, p[1] / p[3] * h / 2])


def test_the_old_float32_path_visibly_swims_and_the_anchored_one_holds():
    """The regression test for the bug itself, in numbers.

    Orbit a camera around a vertex 360,000 units out and watch where it
    lands on screen, against the float64 truth. The error of the old
    path changes frame to frame, which is motion the eye sees on
    geometry that is standing still. The anchored path's error stays
    under a thousandth of a pixel.
    """
    v = FAR + (2.0, 3.0, 1.0)
    a = FAR + 2.5
    proj = perspective(45.0, 1.6, 0.1, 10000.0)
    old_err, new_err = [], []
    for i in range(24):
        az = i * 0.002
        eye = FAR + 40.0 * np.array([np.cos(az), np.sin(az), 0.5])
        mvp = proj @ look_at(eye, FAR, (0, 0, 1))
        truth = _screen(mvp, np.append(v, 1.0))
        old = _screen(mvp.astype(np.float32),
                      np.append(v, 1.0).astype(np.float32))
        new = _screen(vp.anchored(mvp, a),
                      np.append(vp.rebased(v[None], a)[0],
                                np.float32(1.0)))
        old_err.append(old - truth)
        new_err.append(new - truth)
    old_swim = max(np.abs(np.diff(old_err, axis=0)).max(axis=1))
    new_swim = max(np.abs(np.diff(new_err, axis=0)).max(axis=1))
    assert old_swim > 0.05, \
        "the old path does not jitter here, so this test guards nothing"
    assert new_swim < 1e-3, f"anchored path still swims {new_swim:.4f} px"


# -- the wiring, pinned where GL cannot run under pytest ------------------

def test_the_buffers_upload_relative_to_the_anchor():
    src = inspect.getsource(vp._MeshBuffers.__init__)
    assert "mesh_anchor" in src and "rebased" in src


def test_the_draw_loop_folds_each_objects_anchor_into_its_matrices():
    src = inspect.getsource(vp.Viewport._draw_objects)
    assert "anchored(" in src and "anchored_clips(" in src


def test_the_ground_shadow_squashes_in_float64_per_anchor():
    src = inspect.getsource(vp.Viewport._draw_ground_shadow)
    assert "anchored(" in src


def test_point_markers_and_highlights_ride_the_same_anchor():
    assert "rebased(" in inspect.getsource(vp.Viewport._draw_point_markers)


def test_every_caller_hands_draw_objects_the_float64_matrix():
    """The fold has to happen before the cast; a caller that casts first
    throws the digits away on the doorstep."""
    from serpentine3d.ui.layout_view import LayoutView
    for fn, marker in [
        (vp.Viewport._paint_frame, "_draw_objects(mvp64"),
        (vp.Viewport._paint_technical, "_draw_objects(mvp64"),
        (vp.Viewport.render_model_image, "_draw_objects(mvp64"),
        (vp.Viewport.render_detail_image, "_draw_objects(mvp64"),
        (LayoutView._paint_detail_3d, "_draw_objects(mvp64"),
    ]:
        assert marker in inspect.getsource(fn), fn.__qualname__
