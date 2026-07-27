"""A coarse spatial index over one mesh's primitives, for picking.

Deciding what a click landed on means testing the cursor against geometry,
and that test is linear in the amount of geometry. Narrowing the drawing to
the objects near the cursor deals with a scene of many small objects. It
does nothing for the other shape a drawing takes: a scanned survey mesh
that is one object of three million triangles, where "the object near the
cursor" is the whole model.

So each big mesh gets its primitives sorted into a coarse grid, with a
bounding box kept per occupied cell. The pick then rejects cells the same
way it rejects objects — by projecting the box and missing the cursor — and
only tests the primitives in what survives.

The index is deliberately one level deep. A full BVH would query in
log(n) rather than in "n cells", but n cells is a few thousand boxes tested
in one array operation, and the build stays a sort instead of a recursion.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Below this a mesh is quicker to test outright than to sort, and the index
# would cost memory on every small object in the drawing to save nothing.
MIN_PRIMITIVES = 20_000

MAX_GRID = 64


def _grid_size(n: int) -> int:
    """Cells per axis for `n` primitives, balancing the two costs.

    Survey meshes are sheets rather than solids, so a grid of g per axis
    leaves about g**2 cells occupied, and a cursor-sized window covers a
    handful of them. Testing the survivors then costs about n / g**2, while
    the index itself costs eight corners per occupied cell to project — so
    a fine grid stops paying somewhere, and the sum is smallest around
    g**2 = sqrt(n / 2).
    """
    return int(np.clip(round((n / 2) ** 0.25), 1, MAX_GRID))


@dataclass(frozen=True)
class ChunkIndex:
    """Primitives grouped into grid cells, each with a bounding box.

    `order` is a permutation of the primitive indices laid out so that one
    chunk is one contiguous run; chunk c owns `order[starts[c]:starts[c+1]]`
    and is bounded by `mins[c]`, `maxs[c]`.
    """
    order: np.ndarray                 # (N,) int32
    starts: np.ndarray                # (C+1,) int64
    mins: np.ndarray                  # (C, 3) float64
    maxs: np.ndarray                  # (C, 3) float64

    @property
    def count(self) -> int:
        return len(self.mins)

    def gather(self, keep: np.ndarray) -> np.ndarray:
        """Primitive indices belonging to the chunks flagged in `keep`."""
        lo = self.starts[:-1][keep]
        hi = self.starts[1:][keep]
        counts = hi - lo
        total = int(counts.sum())
        if not total:
            return np.zeros(0, np.int64)
        # walk the kept runs as one arange that jumps at each run boundary,
        # rather than concatenating a list of slices per chunk
        steps = np.ones(total, np.int64)
        heads = np.concatenate([[0], np.cumsum(counts)[:-1]])
        steps[heads] = np.concatenate([lo[:1], lo[1:] - hi[:-1] + 1])
        return self.order[np.cumsum(steps)]


def build_index(corners: np.ndarray) -> ChunkIndex | None:
    """Index primitives given as (N, K, 3) corner points.

    K is 3 for triangles and 2 for edge segments; nothing here cares which.
    Returns None for a mesh small enough that the index would not pay for
    itself, which callers read as "test all of it".
    """
    n = len(corners)
    if n < MIN_PRIMITIVES:
        return None

    # kept in the mesh's own dtype: these are the two biggest arrays here,
    # and widening three million of them to double costs more than the sort
    lo = corners.min(axis=1)
    hi = corners.max(axis=1)
    origin = lo.min(axis=0).astype(np.float64)
    span = hi.max(axis=0).astype(np.float64) - origin
    # a sheet has an axis of no extent; give it one cell rather than a
    # division by zero
    span[span < 1e-12] = 1.0

    grid = _grid_size(n)
    centre = (lo + hi) * 0.5
    cell = np.clip(((centre - origin) / span * grid).astype(np.int64),
                   0, grid - 1)
    key = (cell[:, 0] * grid + cell[:, 1]) * grid + cell[:, 2]

    order = np.argsort(key, kind="stable")
    skey = key[order]
    run_start = np.flatnonzero(np.concatenate([[True], skey[1:] != skey[:-1]]))
    mins = np.minimum.reduceat(lo[order], run_start).astype(np.float64)
    maxs = np.maximum.reduceat(hi[order], run_start).astype(np.float64)
    starts = np.concatenate([run_start, [n]]).astype(np.int64)
    return ChunkIndex(order.astype(np.int32), starts, mins, maxs)
