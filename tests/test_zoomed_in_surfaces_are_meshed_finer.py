"""Zoomed in, the faces a pane is looking at are meshed again, finer (#168).

A surface is drawn from a mesh made once, at a fixed fraction of the object's
size, so far enough in its outline showed corners however finely the edge
beside it was drawn. Now a face whose mesh strays more than two pixels from
the surface is meshed again until it strays less than one, and only the faces
in view are: the rest keep the mesh they had.
"""
import math

import numpy as np
from OCP.BRep import BRep_Builder
from OCP.TopoDS import TopoDS_Compound

from serpentine3d.core import geometry as g
from serpentine3d.core import refine
from serpentine3d.core.tessellate import tessellate
from serpentine3d.ui.camera import Camera

W, H = 800, 600


def _camera(target, distance, projection="parallel", elevation=0.0):
    """Looking along -X at `target` from `distance` away, tilted down by
    `elevation` degrees."""
    cam = Camera()
    cam.projection = projection
    cam.target = np.asarray(target, float)
    cam.distance = float(distance)
    cam.azimuth = 0.0
    cam.elevation = math.radians(elevation)
    return cam


def _view(target, half_height, projection="parallel", elevation=0.0):
    """A view `2 * half_height` units tall, centred on `target`."""
    tan = math.tan(math.radians(Camera().fov) / 2)
    return refine.View.of(_camera(target, half_height / tan, projection,
                                  elevation), W, H)


def _sag(mesh, centre, radius, faces=None) -> float:
    """The furthest any triangle sinks inside a sphere, in units."""
    tris = mesh.triangles
    if faces is not None:
        tris = tris[np.isin(mesh.face_of_triangle, faces)]
    v = mesh.vertices[tris]
    pts = np.concatenate([v.mean(axis=1), (v[:, 0] + v[:, 1]) / 2,
                          (v[:, 1] + v[:, 2]) / 2, (v[:, 2] + v[:, 0]) / 2])
    return float((radius - np.linalg.norm(pts - centre, axis=1)).max())


def _compound(*shapes):
    out = TopoDS_Compound()
    b = BRep_Builder()
    b.MakeCompound(out)
    for s in shapes:
        b.Add(out, s)
    return out


def test_zoomed_in_a_sphere_strays_less_than_a_pixel():
    sphere = g.make_sphere((0, 0, 0), 20.0)
    base = tessellate(sphere)
    view = _view((20, 0, 0), 1.0)               # 2 units over 600 pixels
    pixel = 2.0 / H
    assert _sag(base, np.zeros(3), 20.0) > 10 * pixel

    levels = refine.plan(sphere, base, view)
    assert levels
    fine = refine.refined(sphere, base, levels)
    assert _sag(fine, np.zeros(3), 20.0) <= pixel


def test_zoomed_out_nothing_is_meshed_again():
    sphere = g.make_sphere((0, 0, 0), 20.0)
    base = tessellate(sphere)
    assert refine.plan(sphere, base, _view((0, 0, 0), 25.0)) == {}


def test_faces_out_of_view_keep_the_mesh_they_had():
    here = g.make_sphere((0, 0, 0), 20.0)
    there = g.make_sphere((0, 1000, 0), 20.0)
    both = _compound(here, there)
    base = tessellate(both)
    levels = refine.plan(both, base, _view((20, 0, 0), 1.0))
    assert set(levels) == {0}                   # the first sphere's face only

    fine = refine.refined(both, base, levels)
    kept = base.triangles[base.face_of_triangle == 1]
    now = fine.triangles[fine.face_of_triangle == 1]
    np.testing.assert_array_equal(fine.vertices[now], base.vertices[kept])
    assert (fine.face_of_triangle == 0).sum() > (base.face_of_triangle == 0).sum()


def test_the_finer_mesh_keeps_the_face_and_edge_numbers():
    cylinder = g.make_cylinder((0, 0, 0), 10.0, 30.0)
    base = tessellate(cylinder)
    view = _view((10, 0, 15), 0.5)
    fine = refine.refined(cylinder, base, refine.plan(cylinder, base, view))
    assert set(fine.face_of_triangle) == set(base.face_of_triangle)
    assert set(fine.edge_of_segment) == set(base.edge_of_segment)


def test_the_edges_round_a_finer_face_are_drawn_finer_too():
    # A circle this big is past what one degree a piece draws smooth: 0.04
    # units of sag, on a view where a pixel is 0.017.
    cylinder = g.make_cylinder((0, 0, 0), 1000.0, 3000.0)
    base = tessellate(cylinder)
    view = _view((1000, 0, 3000), 5.0, elevation=30.0)
    levels = refine.plan(cylinder, base, view)
    fine = refine.refined(cylinder, base, levels)
    assert len(fine.edge_segments) > len(base.edge_segments)
    assert set(fine.edge_of_segment) == set(base.edge_of_segment)


def test_a_finer_face_still_faces_the_same_way():
    cylinder = g.make_cylinder((0, 0, 0), 10.0, 30.0)
    base = tessellate(cylinder)
    view = _view((10, 0, 30), 1.0, elevation=30.0)  # the rim, from above
    levels = refine.plan(cylinder, base, view)
    assert len(levels) == 2                     # the side and the top

    def facing(mesh, face):
        v = mesh.vertices[mesh.triangles[mesh.face_of_triangle == face]]
        n = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
        return n.sum(axis=0)

    fine = refine.refined(cylinder, base, levels)
    for face in levels:
        before, after = facing(base, face), facing(fine, face)
        # the side's normals cancel round the circle; its winding still
        # agrees with each base triangle's, checked through the shading
        if np.linalg.norm(before) > 1e-6:
            assert np.dot(before, after) > 0
    tri = fine.triangles[fine.face_of_triangle == 0]
    v = fine.vertices[tri]
    winding = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
    shading = fine.normals[tri].mean(axis=1)
    assert (np.einsum("ij,ij->i", winding, shading) > 0).mean() > 0.99


def test_nearer_faces_are_meshed_finer_in_perspective():
    near = g.make_sphere((-10, 0, 0), 5.0)
    far = g.make_sphere((-300, 0, 0), 5.0)
    both = _compound(near, far)
    base = tessellate(both)
    # the camera sits at x = 10, looking down -X at both
    view = refine.View.of(_camera((0, 0, 0), 10.0, "perspective"), W, H)
    levels = refine.plan(both, base, view)
    assert levels.get(0, 0) > levels.get(1, 0)


def test_the_budget_holds_the_triangle_count_down():
    sphere = g.make_sphere((0, 0, 0), 20.0)
    base = tessellate(sphere)
    view = _view((20, 0, 0), 0.05)
    free = refine.plan(sphere, base, view)
    held = refine.plan(sphere, base, view, budget=len(base.triangles) * 8)
    assert held[0] < free[0]
    assert len(base.triangles) * 2 ** held[0] <= len(base.triangles) * 8


def test_a_face_meshed_once_is_not_meshed_again(monkeypatch):
    sphere = g.make_sphere((0, 0, 0), 20.0)
    base = tessellate(sphere)
    levels = refine.plan(sphere, base, _view((20, 0, 0), 1.0))
    first = refine.refined(sphere, base, levels)

    def no_meshing(*_args, **_kw):
        raise AssertionError("meshed the same face twice")
    monkeypatch.setattr(refine, "BRepMesh_IncrementalMesh", no_meshing)
    again = refine.refined(sphere, base, levels)
    np.testing.assert_array_equal(again.triangles, first.triangles)


def test_far_from_home_the_finer_mesh_is_as_exact():
    centre = np.array([5_000_000.0, 0.0, 0.0])
    sphere = g.translate(g.make_sphere((0, 0, 0), 20.0), tuple(centre))
    base = tessellate(sphere)
    assert base.far
    fine = refine.refined(sphere, base, refine.plan(
        sphere, base, _view(centre + (20, 0, 0), 1.0)))
    assert fine.far
    np.testing.assert_array_equal(fine.origin, base.origin)
    assert _sag(fine, centre, 20.0) <= 2.0 / H


def test_the_original_shape_is_not_remeshed():
    sphere = g.make_sphere((0, 0, 0), 20.0)
    base = tessellate(sphere)
    refine.refined(sphere, base, refine.plan(sphere, base,
                                             _view((20, 0, 0), 1.0)))
    again = tessellate(sphere)
    assert len(again.triangles) == len(base.triangles)


def test_zoom_extents_in_perspective_asks_for_nothing():
    # A box's nearest corner stands well in front of a round face, so
    # measured there a sphere seen whole looked three pixels out. It is
    # measured at the nearest point of its mesh instead.
    # Seen corner-on, filling about 60% of a pane 1000 pixels tall.
    sphere = g.make_sphere((0, 0, 0), 20.0)
    base = tessellate(sphere)
    cam = _camera((0, 0, 0), 83.0, "perspective", elevation=35.26)
    cam.azimuth = math.radians(45.0)
    assert refine.plan(sphere, base, refine.View.of(cam, 1600, 1000)) == {}


def test_a_flat_face_with_straight_edges_is_left_alone():
    # Nothing about its mesh can get any closer to it.
    box = g.make_box((0, 0, 0), 40, 30, 20)
    base = tessellate(box)
    assert refine.plan(box, base, _view((40, 15, 10), 0.01)) == {}


def test_a_small_round_is_left_alone_until_it_shows():
    # A fillet far smaller than its object is meshed finer than the
    # object's deflection already: the 20 degree limit on how far one
    # facet turns from the next decides it. So zooming in a little on the
    # object asks nothing of it, and zooming in on the round itself does.
    from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
    from serpentine3d.core import occ
    box = g.make_box((0, 0, 0), 400, 300, 200)
    mk = BRepFilletAPI_MakeFillet(box)
    edge = next(e for e in g.edges_of(box)
                if np.allclose(g.bbox(e)[0], (400, 0, 0), atol=1e-6)
                and np.allclose(g.bbox(e)[1], (400, 0, 200), atol=1e-6))
    mk.Add(2.0, occ.to_edge(edge))
    rounded = mk.Shape()
    base = tessellate(rounded)
    near_the_round = (399.4, 0.6, 100)
    assert refine.plan(rounded, base, _view(near_the_round, 60.0)) == {}
    assert refine.plan(rounded, base, _view(near_the_round, 0.5))


def test_right_up_close_one_face_asks_for_a_bounded_mesh():
    # A whole face is meshed at the level its nearest point needs, and with
    # the camera almost touching a sphere that was two million triangles:
    # minutes of meshing for the corner of it in view. The budget caps it.
    sphere = g.make_sphere((0, 0, 0), 20.0)
    base = tessellate(sphere)
    cam = _camera((0, 0, 20), 0.5, "perspective", elevation=60.0)
    levels = refine.plan(sphere, base, refine.View.of(cam, 1600, 1000))
    assert levels
    assert len(base.triangles) * 2 ** levels[0] <= 300_000


def _line_sag(segments, centre, radius) -> float:
    """The furthest any segment's middle sinks inside a sphere."""
    mids = segments.reshape(-1, 2, 3).mean(axis=1)
    return float((radius - np.linalg.norm(mids - centre, axis=1)).max())


def test_lines_on_a_finer_face_stay_in_front_of_it():
    # Faces are drawn pushed back a hair so the lines on them win the depth
    # test. That held while the mesh sagged far more than the lines did;
    # a finer face sagged as much as its edges and more than its
    # isocurves, so both broke up into dashes behind it.
    sphere = g.make_sphere((0, 0, 0), 20.0)
    base = tessellate(sphere)
    fine = refine.refined(sphere, base, refine.plan(
        sphere, base, _view((20, 0, 0), 1.0)))
    face = _sag(fine, np.zeros(3), 20.0)
    assert len(fine.iso_segments) and len(fine.edge_segments)
    assert _line_sag(fine.iso_segments, np.zeros(3), 20.0) < face / 2
    seam = fine.edge_segments[np.linalg.norm(
        fine.edge_segments[:, 1] - fine.edge_segments[:, 0], axis=1) > 0]
    assert _line_sag(seam, np.zeros(3), 20.0) < face / 2


def test_a_finer_faces_isocurves_reach_its_finer_triangles():
    # An isocurve point carries the way to the triangle under it, so the
    # pane can draw it in front of the face where the surface dips away
    # (#168). Meshed finer, the triangles under it are new ones.
    rail1 = g.make_interp_curve([(0, 0, 0), (16, 1, 3), (34, 0, 0)])
    rail2 = g.make_interp_curve([(2, 36, 4), (14, 34, 11), (26, 27, 6)])
    profile = g.make_interp_curve([(0, 0, 0), (-3, 18, -9), (2, 36, 4)])
    trough = g.sweep2(profile, rail1, rail2)
    base = tessellate(trough)
    levels = refine.plan(trough, base, _view((10, 18, 0), 2.0,
                                             elevation=89.0))
    assert levels

    fine = refine.refined(trough, base, levels)

    assert np.asarray(fine.iso_lift).shape == np.asarray(
        fine.iso_segments).shape
    lifted = (np.asarray(fine.iso_segments, float)
              + np.asarray(fine.iso_lift, float)).reshape(-1, 3)
    v = np.asarray(fine.vertices, float)
    a, b, c = (v[fine.triangles[:, k]] for k in range(3))
    n = np.cross(b - a, c - a)
    n /= np.linalg.norm(n, axis=1, keepdims=True)
    for p in lifted[::7]:
        assert np.abs(np.einsum("ij,ij->i", p - a, n)).min() < 1e-4
    # and the finer triangles sit nearer the surface, so the lifts shrink
    assert (np.linalg.norm(fine.iso_lift, axis=-1).max()
            < np.linalg.norm(base.iso_lift, axis=-1).max())
