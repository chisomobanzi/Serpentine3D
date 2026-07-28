"""The lines a mesh is drawn with: its boundary and its creases.

Opening a 522 MB survey file sat at 98% for six and a half minutes on a
single object. It was this: an edge loop written in Python, three iterations
per triangle, each one calling into numpy. A survey mesh has millions.
"""

import time

import numpy as np
import pytest

from serpentine3d.core.mesh import MeshShape


def _segments(mesh, angle_deg=30.0):
    """feature_edges as a set of rounded endpoint pairs, order-insensitive."""
    out = set()
    for a, b in mesh.feature_edges(angle_deg):
        pair = (tuple(np.round(a, 6)), tuple(np.round(b, 6)))
        out.add(tuple(sorted(pair)))
    return out


def test_a_lone_triangle_is_all_boundary():
    mesh = MeshShape(np.array([[0., 0, 0], [1, 0, 0], [0, 1, 0]]),
                     np.array([[0, 1, 2]], np.uint32))
    assert len(_segments(mesh)) == 3


def test_an_empty_mesh_has_no_edges():
    empty = MeshShape(np.zeros((0, 3)), np.zeros((0, 3), np.uint32))
    assert empty.feature_edges().shape == (0, 2, 3)


def test_a_flat_pair_keeps_its_outline_but_not_its_seam():
    """Two coplanar triangles are one quad as far as the eye is concerned;
    drawing the diagonal would put a line across a flat face."""
    mesh = MeshShape(np.array([[0., 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]]),
                     np.array([[0, 1, 2], [0, 2, 3]], np.uint32))
    segments = _segments(mesh)
    assert len(segments) == 4, segments
    diagonal = tuple(sorted(((0., 0., 0.), (1., 1., 0.))))
    assert diagonal not in segments


def test_a_folded_pair_keeps_the_fold():
    """The same two triangles bent to a right angle: now the seam is a crease
    and has to be drawn, or the fold disappears."""
    mesh = MeshShape(np.array([[0., 0, 0], [1, 0, 0], [1, 1, 0], [0, 0, 1]]),
                     np.array([[0, 1, 2], [0, 3, 1]], np.uint32))
    segments = _segments(mesh)
    seam = tuple(sorted(((0., 0., 0.), (1., 0., 0.))))
    assert seam in segments, segments
    assert len(segments) == 5


def test_the_crease_angle_decides_what_counts_as_a_fold():
    """A shallow fold is smooth shading, not a line."""
    mesh = MeshShape(np.array([[0., 0, 0], [1, 0, 0], [1, 1, 0],
                               [0, -1, 0.05]]),
                     np.array([[0, 1, 2], [0, 3, 1]], np.uint32))
    seam = tuple(sorted(((0., 0., 0.), (1., 0., 0.))))
    assert seam not in _segments(mesh, angle_deg=30.0)
    assert seam in _segments(mesh, angle_deg=1.0)


def test_an_edge_shared_by_three_triangles_is_not_drawn():
    """Non-manifold junctions have no one fold angle to measure, so they are
    left alone rather than guessed at."""
    verts = np.array([[0., 0, 0], [1, 0, 0], [0, 1, 0], [0, -1, 0],
                      [0, 0, 1]])
    tris = np.array([[0, 1, 2], [0, 3, 1], [0, 1, 4]], np.uint32)
    seam = tuple(sorted(((0., 0., 0.), (1., 0., 0.))))
    assert seam not in _segments(MeshShape(verts, tris))


def test_a_survey_mesh_does_not_take_minutes():
    """The regression that started this: a per-edge Python loop. A grid of
    200k triangles stood in for the object that froze the import at 98%."""
    side = 317                                   # ~200k triangles
    xs, ys = np.meshgrid(np.arange(side), np.arange(side))
    verts = np.column_stack([xs.ravel(), ys.ravel(),
                             np.zeros(side * side)]).astype(float)
    idx = np.arange(side * side).reshape(side, side)
    a = idx[:-1, :-1].ravel()
    b = idx[:-1, 1:].ravel()
    c = idx[1:, 1:].ravel()
    d = idx[1:, :-1].ravel()
    tris = np.concatenate([np.column_stack([a, b, c]),
                           np.column_stack([a, c, d])]).astype(np.uint32)
    mesh = MeshShape(verts, tris)

    start = time.perf_counter()
    edges = mesh.feature_edges()
    elapsed = time.perf_counter() - start

    # A flat grid: every edge on the outside, none within.
    assert len(edges) == 4 * (side - 1)
    assert elapsed < 4.0, f"{len(tris)} triangles took {elapsed:.1f}s"


def _unweld(mesh):
    """The mesh as Rhino stores it: every face owning its own corners, so no
    two faces share a vertex index even where they touch."""
    verts = mesh.vertices[mesh.triangles.ravel()]
    tris = np.arange(len(verts), dtype=np.uint32).reshape(-1, 3)
    return MeshShape(verts, tris)


def test_faces_that_touch_are_neighbours_even_with_their_own_vertices():
    """A .3dm mesh arrives with four unshared corners per quad. Matching
    edges by vertex index then finds nothing shared, so every triangle edge
    looks like a boundary: one cave object produced 6.6 million of them,
    which is both a wireframe over a solid surface and a frozen import."""
    welded = MeshShape(np.array([[0., 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]]),
                       np.array([[0, 1, 2], [0, 2, 3]], np.uint32))
    assert _segments(_unweld(welded)) == _segments(welded)


def test_an_unwelded_fold_is_still_a_fold():
    welded = MeshShape(np.array([[0., 0, 0], [1, 0, 0], [1, 1, 0], [0, 0, 1]]),
                       np.array([[0, 1, 2], [0, 3, 1]], np.uint32))
    assert _segments(_unweld(welded)) == _segments(welded)


def test_an_unwelded_survey_mesh_draws_its_outline_not_every_triangle():
    """Finding which corners coincide is now the whole cost of the function,
    so it has to be a sort and not a search. A million-vertex mesh here; the
    cave has six and a half of them, and two objects made of them."""
    side = 400                                   # ~1M unwelded vertices
    xs, ys = np.meshgrid(np.arange(side), np.arange(side))
    verts = np.column_stack([xs.ravel(), ys.ravel(),
                             np.zeros(side * side)]).astype(float)
    idx = np.arange(side * side).reshape(side, side)
    a = idx[:-1, :-1].ravel()
    b = idx[:-1, 1:].ravel()
    c = idx[1:, 1:].ravel()
    d = idx[1:, :-1].ravel()
    tris = np.concatenate([np.column_stack([a, b, c]),
                           np.column_stack([a, c, d])]).astype(np.uint32)
    mesh = _unweld(MeshShape(verts, tris))

    start = time.perf_counter()
    edges = mesh.feature_edges()
    elapsed = time.perf_counter() - start

    assert len(edges) == 4 * (side - 1), len(edges)
    # Loose on purpose: this guards against matching corners by searching
    # rather than by sorting, which took nine seconds here, not against the
    # tenths a loaded machine adds.
    assert elapsed < 4.0, f"{len(tris)} unwelded triangles took {elapsed:.1f}s"


def test_a_triangle_pinched_to_a_line_draws_no_zero_length_edge():
    """Welding can bring a triangle's own corners together. A segment from a
    point to itself is nothing to draw."""
    mesh = MeshShape(np.array([[0., 0, 0], [1, 0, 0], [1, 0, 0]]),
                     np.array([[0, 1, 2]], np.uint32))
    for a, b in mesh.feature_edges():
        assert not np.array_equal(a, b), "a segment going nowhere"


def test_the_answer_does_not_depend_on_how_the_edges_were_grouped():
    """A shuffled mesh describes the same surface and must draw the same."""
    rng = np.random.default_rng(0)
    verts = np.array([[0., 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
                      [0, 0, 1], [1, 0, 1]])
    tris = np.array([[0, 1, 2], [0, 2, 3], [0, 4, 1], [1, 4, 5]], np.uint32)
    plain = _segments(MeshShape(verts, tris))
    order = rng.permutation(len(tris))
    assert _segments(MeshShape(verts, tris[order])) == plain
