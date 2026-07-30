"""Which edges a shape has, without losing one to a recycled address.

`edges_of` walked the explorer and de-duplicated on `hash(e.TShape())`. But
`TShape()` hands back a fresh Python wrapper every call, and its hash is that
wrapper's own address — so the key said nothing about the edge. Two things
followed. A shell's shared edges were never actually de-duplicated (a box came
back with 24 edges, one per face visit). And when the freed address of one
wrapper was handed out again for the next, two different edges collided and one
of them silently went missing: a rectangle that drew with three sides, a box
that printed without its top edge.

The edge itself hashes the way OCC hashes shapes — same underlying shape and
placement, either orientation — which is exactly the identity being asked for.
"""

from __future__ import annotations

from serpentine3d.core import geometry as g
from serpentine3d.core.tessellate import tessellate


def test_a_box_has_twelve_edges_not_one_per_face_visit():
    box = g.make_box((0.0, 0.0, 0.0), 10.0, 5.0, 3.0)
    assert len(g.edges_of(box)) == 12


def test_every_edge_the_explorer_finds_comes_back_exactly_once():
    box = g.make_box((0.0, 0.0, 0.0), 10.0, 5.0, 3.0)
    edges = g.edges_of(box)
    for a in edges:
        assert sum(1 for b in edges if a.IsSame(b)) == 1


def test_no_edge_goes_missing_between_runs():
    """The flake, as it showed up: a rectangle drawn with three sides. It
    depends on what the allocator hands out, so it takes repetition to see."""
    rect = g.make_rectangle((0.0, 0.0, 0.0), (10.0, 5.0, 0.0))
    assert {len(g.edges_of(rect)) for _ in range(50)} == {4}
    assert {len(tessellate(rect).edge_segments) for _ in range(50)} == {4}


def test_free_points_in_a_compound_all_survive():
    """Same key, same trap: a dropped vertex is a point object that stops
    being drawn."""
    pts = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 5.0, 0.0),
           (0.0, 5.0, 0.0), (5.0, 2.5, 1.0)]
    comp = g.make_compound([g.make_point(p) for p in pts])
    assert {len(tessellate(comp).points) for _ in range(50)} == {len(pts)}
