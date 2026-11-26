"""An isocurve can always reach the triangle it is drawn over (#168).

Faces are drawn pushed back a hair so the lines on them win the depth
test. That only works while a line is no further from the eye than the
triangle under it. Isocurves are sampled on the exact surface, so where
it dipped away from the eye each flat triangle stood in front of it, and
the line showed only near the triangles' corners, in dashes: a Sweep2
surface seen from above, in the reporter's 0.13.1 screenshot.

Cutting the lines from the triangles instead put them in the wrong place
across a face whose parameters run unevenly, zigzagging, and bent them
where the triangles bend. So each point stays on the surface, and
carries how far it is, along the triangle's normal, to the triangle's
plane: the pane draws it at whichever of the two is nearer the eye.
"""

from __future__ import annotations

import numpy as np

from serpentine3d.core import geometry as g
from serpentine3d.core.tessellate import merged, tessellate


def _trough():
    """The reporter's kind of surface: a Sweep2 whose profile dips, so
    from above part of it is a trough."""
    rail1 = g.make_interp_curve([(0, 0, 0), (16, 1, 3), (34, 0, 0)])
    rail2 = g.make_interp_curve([(2, 36, 4), (14, 34, 11), (26, 27, 6)])
    profile = g.make_interp_curve([(0, 0, 0), (-3, 18, -9), (2, 36, 4)])
    return g.sweep2(profile, rail1, rail2)


def _on_a_triangle(mesh, points, tol):
    """Whether each of `points` lies in the plane of a triangle of `mesh`
    that it is over, within `tol`."""
    v = np.asarray(mesh.vertices, float)
    a, b, c = (v[mesh.triangles[:, k]] for k in range(3))
    ab, ac = b - a, c - a
    n = np.cross(ab, ac)
    n /= np.linalg.norm(n, axis=1, keepdims=True)
    gram = np.stack([np.einsum("ij,ij->i", ab, ab),
                     np.einsum("ij,ij->i", ab, ac),
                     np.einsum("ij,ij->i", ac, ac)], axis=1)
    det = gram[:, 0] * gram[:, 2] - gram[:, 1] ** 2
    out = []
    for p in points:
        ap = p - a
        d1 = np.einsum("ij,ij->i", ap, ab)
        d2 = np.einsum("ij,ij->i", ap, ac)
        s = (gram[:, 2] * d1 - gram[:, 1] * d2) / det
        t = (gram[:, 0] * d2 - gram[:, 1] * d1) / det
        over = (s >= -0.05) & (t >= -0.05) & (s + t <= 1.05)
        height = np.abs(np.einsum("ij,ij->i", ap, n))
        out.append(bool((height[over] < tol).any()))
    return np.asarray(out)


def test_every_isocurve_point_carries_a_lift():
    mesh = tessellate(_trough())

    assert len(mesh.iso_segments)
    assert np.asarray(mesh.iso_lift).shape == np.asarray(
        mesh.iso_segments).shape


def test_lifted_each_point_lies_on_a_triangle_it_is_over():
    mesh = tessellate(_trough())
    isos = np.asarray(mesh.iso_segments, float).reshape(-1, 3)
    lifted = isos + np.asarray(mesh.iso_lift, float).reshape(-1, 3)

    # the trough strays up to about 0.11 from its triangles; float32
    # vertices on a 40 unit surface are good to a few millionths
    assert not _on_a_triangle(mesh, isos, 1e-4).all()
    assert _on_a_triangle(mesh, lifted, 1e-4).all()


def test_a_lift_runs_along_the_triangles_normal_so_the_line_keeps_its_place():
    """Seen square on to the triangle, a lift moves a point nowhere."""
    mesh = tessellate(_trough())
    isos = np.asarray(mesh.iso_segments, float).reshape(-1, 3)
    lift = np.asarray(mesh.iso_lift, float).reshape(-1, 3)
    v = np.asarray(mesh.vertices, float)
    a, b, c = (v[mesh.triangles[:, k]] for k in range(3))
    n = np.cross(b - a, c - a)
    n /= np.linalg.norm(n, axis=1, keepdims=True)
    reach = np.linalg.norm(lift, axis=1)

    assert reach.max() > 0.01
    for p, up, r in zip(isos + lift, lift, reach):
        if r < 1e-4:
            continue
        # among the triangles whose plane it now lies in, one it went
        # straight out to
        on = np.abs(np.einsum("ij,ij->i", p - a, n)) < 1e-4
        square = np.linalg.norm(np.cross(n[on], up / r), axis=1)
        assert square.min() < 1e-3


def test_a_cylinders_lifts_reach_its_flat_sides_from_the_curved_surface():
    radius = 40.0
    mesh = tessellate(g.make_cylinder((0.0, 0.0, 0.0), radius, 30.0))
    isos = np.asarray(mesh.iso_segments, float).reshape(-1, 3)
    lifted = isos + np.asarray(mesh.iso_lift, float).reshape(-1, 3)

    # on the surface, then in from it onto a flat side, never out past it
    assert np.allclose(np.linalg.norm(isos[:, :2], axis=1), radius,
                       atol=1e-4)
    reach = np.linalg.norm(lifted[:, :2], axis=1)
    assert reach.max() <= radius + 1e-4
    assert reach.min() < radius - 0.01
    assert _on_a_triangle(mesh, lifted, 1e-4).all()


def test_a_flat_shape_has_no_lifts_to_carry():
    mesh = tessellate(g.make_box((0.0, 0.0, 0.0), 10.0, 10.0, 10.0))
    assert len(mesh.iso_lift) == 0


def test_shapes_drawn_together_keep_their_lifts_in_step():
    near = tessellate(_trough())
    box = tessellate(g.make_box((50.0, 0.0, 0.0), 10.0, 10.0, 10.0))
    cylinder = tessellate(g.make_cylinder((0.0, 80.0, 0.0), 5.0, 9.0))

    together = merged([near, box, cylinder])

    assert np.array_equal(
        together.iso_lift,
        np.concatenate([near.iso_lift, cylinder.iso_lift]))
    assert len(together.iso_lift) == len(together.local_isos)


def _hidden(mesh, points, up):
    """Which of `points` the triangles cover, seen by an eye far along
    `up`, +z or -z: some triangle over the same spot is nearer the eye."""
    v = np.asarray(mesh.vertices, float)
    a, b, c = (v[mesh.triangles[:, k]] for k in range(3))
    e0, e1 = b[:, :2] - a[:, :2], c[:, :2] - a[:, :2]
    det = e0[:, 0] * e1[:, 1] - e0[:, 1] * e1[:, 0]
    keep = np.abs(det) > 1e-12
    a, b, c, e0, e1, det = a[keep], b[keep], c[keep], e0[keep], e1[keep], \
        det[keep]
    out = []
    for p in points:
        r = p[:2] - a[:, :2]
        s = (r[:, 0] * e1[:, 1] - r[:, 1] * e1[:, 0]) / det
        t = (e0[:, 0] * r[:, 1] - e0[:, 1] * r[:, 0]) / det
        over = (s >= 0) & (t >= 0) & (s + t <= 1)
        z = a[over, 2] + s[over] * (b[over, 2] - a[over, 2]) \
            + t[over] * (c[over, 2] - a[over, 2])
        # float32 vertices on a 40 unit surface: a few millionths is the
        # same height, and the face's push back covers it
        out.append(bool(len(z)) and bool(((z - p[2]) * up > 1e-5).any()))
    return np.asarray(out)


def test_seen_from_above_or_below_no_isocurve_point_sinks_under_its_face():
    """What the pane works out: each point drawn at whichever of the
    surface and its triangle is nearer the eye."""
    mesh = tessellate(_trough())
    isos = np.asarray(mesh.iso_segments, float).reshape(-1, 3)
    lift = np.asarray(mesh.iso_lift, float).reshape(-1, 3)

    for up in (1.0, -1.0):
        drawn = np.where((lift[:, 2] * up > 0)[:, None], isos + lift, isos)
        # on the surface alone, the trough hides some from either side
        assert _hidden(mesh, isos, up).any()
        assert not _hidden(mesh, drawn, up).any()
