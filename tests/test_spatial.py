"""Coarse spatial index over a mesh's primitives.

Picking narrows the drawing to the objects near the cursor, but an object
can *be* the drawing: a scanned cave arrives as one mesh of three million
triangles, and testing every one of them against the ray is where a click
spends its seconds. This index gives the pick a way to skip most of a
single mesh, so the tests below are mostly about it never skipping too
much — a primitive missing from its own chunk's box is a click that
silently fails to select what is under it.
"""

import numpy as np
import pytest

from serpentine3d.core import spatial


def _mesh_corners(n: int, seed: int = 0) -> np.ndarray:
    """(n, 3, 3) triangles scattered over a shell, as a real scan would be."""
    rng = np.random.default_rng(seed)
    dirs = rng.normal(size=(n, 3))
    dirs /= np.linalg.norm(dirs, axis=1)[:, None]
    centres = dirs * 100.0
    return (centres[:, None, :]
            + rng.uniform(-0.5, 0.5, (n, 3, 3))).astype(np.float32)


def test_a_small_mesh_gets_no_index():
    """Below a threshold the whole mesh is cheaper to test than to sort."""
    assert spatial.build_index(_mesh_corners(200)) is None


def test_a_big_mesh_is_split_into_many_chunks():
    idx = spatial.build_index(_mesh_corners(60_000))
    assert idx is not None, "a 60k-triangle mesh was left unindexed"
    assert idx.count > 50, f"only {idx.count} chunks for 60k triangles"
    assert idx.count < 60_000, "one chunk per triangle is not an index"


def test_every_primitive_lands_in_exactly_one_chunk():
    n = 60_000
    idx = spatial.build_index(_mesh_corners(n))
    assert np.array_equal(np.sort(idx.order), np.arange(n))
    assert idx.starts[0] == 0 and idx.starts[-1] == n


def test_a_chunk_box_contains_every_primitive_in_it():
    """The dangerous half: a box that misses one of its own primitives
    rejects a chunk the cursor is actually over."""
    corners = _mesh_corners(60_000)
    idx = spatial.build_index(corners)
    for c in range(idx.count):
        members = idx.order[idx.starts[c]:idx.starts[c + 1]]
        pts = corners[members].reshape(-1, 3)
        assert (pts >= idx.mins[c] - 1e-6).all(), f"chunk {c} box too high"
        assert (pts <= idx.maxs[c] + 1e-6).all(), f"chunk {c} box too low"


def test_gathering_every_chunk_returns_every_primitive():
    n = 60_000
    idx = spatial.build_index(_mesh_corners(n))
    got = idx.gather(np.ones(idx.count, bool))
    assert np.array_equal(np.sort(got), np.arange(n))


def test_gathering_some_chunks_returns_exactly_their_primitives():
    idx = spatial.build_index(_mesh_corners(60_000))
    keep = np.zeros(idx.count, bool)
    keep[::7] = True
    want = np.concatenate([idx.order[idx.starts[c]:idx.starts[c + 1]]
                           for c in np.flatnonzero(keep)])
    assert np.array_equal(np.sort(idx.gather(keep)), np.sort(want))


def test_gathering_nothing_returns_nothing():
    idx = spatial.build_index(_mesh_corners(60_000))
    assert len(idx.gather(np.zeros(idx.count, bool))) == 0


def test_a_flat_mesh_still_indexes():
    """A survey mesh is often a sheet, with one axis of no extent at all —
    the cell size along it must not come out as a division by zero."""
    rng = np.random.default_rng(1)
    xy = rng.uniform(-50, 50, (60_000, 3, 2))
    corners = np.dstack([xy, np.zeros((60_000, 3, 1))]).astype(np.float32)
    idx = spatial.build_index(corners)
    assert idx is not None
    # a sheet occupies one cell layer, so it splits into the grid squared
    assert idx.count > 20, f"only {idx.count} chunks for a 60k-triangle sheet"
    assert np.isfinite(idx.mins).all() and np.isfinite(idx.maxs).all()


def test_segments_index_as_well_as_triangles():
    """Two corners per primitive, not three: the wireframe path uses this."""
    rng = np.random.default_rng(2)
    a = rng.uniform(-50, 50, (60_000, 1, 3))
    corners = np.concatenate([a, a + 0.4], axis=1).astype(np.float32)
    idx = spatial.build_index(corners)
    assert idx is not None and idx.count > 50
    assert np.array_equal(np.sort(idx.order), np.arange(60_000))


@pytest.mark.parametrize("n", [0, 1, 5])
def test_a_degenerate_mesh_does_not_raise(n):
    assert spatial.build_index(np.zeros((n, 3, 3), np.float32)) is None
