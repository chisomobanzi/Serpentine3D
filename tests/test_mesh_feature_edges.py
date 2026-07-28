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
    assert elapsed < 2.0, f"{len(tris)} triangles took {elapsed:.1f}s"


def test_the_answer_does_not_depend_on_how_the_edges_were_grouped():
    """A shuffled mesh describes the same surface and must draw the same."""
    rng = np.random.default_rng(0)
    verts = np.array([[0., 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
                      [0, 0, 1], [1, 0, 1]])
    tris = np.array([[0, 1, 2], [0, 2, 3], [0, 4, 1], [1, 4, 5]], np.uint32)
    plain = _segments(MeshShape(verts, tris))
    order = rng.permutation(len(tris))
    assert _segments(MeshShape(verts, tris[order])) == plain
