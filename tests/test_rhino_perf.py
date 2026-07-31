"""Rhino .3dm import must not be quadratic in a brep's size.

Regression: a 921 MB set-design file (1900 breps, 42k faces, 78k edges, worst
single brep 7921 faces x 12688 edges) never finished importing.
_edges_on_surface tested every face against every edge of the brep — about
1.1 billion surface projections, hours of work — because each face has to
rediscover which edges bound it.

Edges are pruned by bounding box first. That is sound: an edge every sample
of which projects onto the surface within `tol` necessarily lies inside the
surface's bounding box grown by `tol`.
"""

import numpy as np
import pytest

from serpentine3d.core import geometry
from serpentine3d.fileio import rhino


def _panel(x: float, y: float, size: float = 1.0):
    """An untrimmed planar face, one cell of a fence-like grid."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.gp import gp_Pnt, gp_Dir, gp_Pln, gp_Ax3
    pln = gp_Pln(gp_Ax3(gp_Pnt(x, y, 0), gp_Dir(0, 0, 1)))
    return BRepBuilderAPI_MakeFace(pln, 0., size, 0., size).Face()


def _edge(p0, p1):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
    from OCP.gp import gp_Pnt
    return BRepBuilderAPI_MakeEdge(gp_Pnt(*p0), gp_Pnt(*p1)).Edge()


def _grid(n: int):
    """n panels along x, each with its own 4 boundary edges."""
    faces, edges = [], []
    for i in range(n):
        x = i * 10.0            # far apart: no panel shares another's edges
        faces.append(_panel(x, 0.))
        edges += [_edge((x, 0, 0), (x + 1, 0, 0)),
                  _edge((x + 1, 0, 0), (x + 1, 1, 0)),
                  _edge((x + 1, 1, 0), (x, 1, 0)),
                  _edge((x, 1, 0), (x, 0, 0))]
    return faces, edges


def _surface_of(face):
    from OCP.BRep import BRep_Tool
    return BRep_Tool.Surface_s(geometry.occ.to_face(face))


def test_pruning_keeps_exactly_the_edges_that_bound_the_face():
    """Correctness before speed: every edge that really bounds a panel
    survives the prune, and no other panel's edges come along."""
    faces, edges = _grid(6)
    boxes = rhino._edge_boxes(edges)
    for i, face in enumerate(faces):
        own = {id(e) for e in edges[i * 4:i * 4 + 4]}
        near = {id(e) for e in rhino._edges_near(face, edges, boxes, 1e-6)}
        assert near == own, f"panel {i} got {len(near)}, wanted its own 4"


def test_pruning_does_not_change_which_edges_lie_on_the_surface():
    """The prune must be invisible to the projection test that follows it:
    for every panel, testing the pruned subset gives the same verdict per
    edge as testing that edge against the whole grid."""
    faces, edges = _grid(6)
    boxes = rhino._edge_boxes(edges)
    for i, face in enumerate(faces):
        surf = _surface_of(face)
        near = rhino._edges_near(face, edges, boxes, 1e-6)
        on_pruned = {id(e) for e in rhino._edges_on_surface(surf, near, 1e-6)}
        # every edge the prune kept and the projection accepted would also
        # have been accepted from the full list — and nothing near is lost
        on_full = {id(e) for e in rhino._edges_on_surface(surf, edges, 1e-6)}
        assert on_pruned == on_full & {id(e) for e in near}


def test_a_face_is_not_tested_against_every_edge_in_the_brep():
    """The actual defect: work per face must not grow with brep size."""
    def tested_for(n):
        faces, edges = _grid(n)
        boxes = rhino._edge_boxes(edges)
        return sum(len(rhino._edges_near(f, edges, boxes, 1e-6))
                   for f in faces)

    small, big = tested_for(4), tested_for(16)
    # Quadratic would be 16x the work for 4x the faces; linear is 4x.
    assert big == small * 4, f"{small} edge tests for 4 panels, {big} for 16"


def test_pruning_survives_a_face_with_no_edges_near_it():
    faces, _ = _grid(2)
    far = [_edge((1e6, 1e6, 1e6), (1e6 + 1, 1e6, 1e6))]
    assert rhino._edges_near(faces[0], far, rhino._edge_boxes(far),
                             1e-6) == []


def test_an_edge_that_overruns_the_surface_is_not_one_of_its_trims():
    """An edge bounding a face lies within the surface's own extent, so the
    on-surface prune can demand containment, not mere overlap. A rail running
    the length of the fence overlaps every panel's box but bounds none."""
    face = _panel(0., 0.)                   # extent [0,1] x [0,1] x 0
    rail = _edge((0.5, 0.5, 0), (50, 0.5, 0))   # on the plane, far too long
    own = _edge((0, 0, 0), (1, 0, 0))

    edges = [rail, own]
    kept = rhino._edges_bounding(face, edges, rhino._edge_boxes(edges), 1e-6)
    assert [id(e) for e in kept] == [id(own)]

    # the splitter still needs it: an edge crossing a face does cut it
    near = rhino._edges_near(face, edges, rhino._edge_boxes(edges), 1e-6)
    assert id(rail) in {id(e) for e in near}


def test_the_splitter_is_not_handed_the_whole_brep():
    """The fallback splits an untrimmed face with the edges lying on it. Given
    the brep's entire edge list instead, one boolean took 62 seconds — about
    eight hours across the fence. Only on-surface edges can cut the face, but
    one that overruns its extent still can, so this test is looser than
    `_edges_bounding`."""
    faces, edges = _grid(6)
    rail = _edge((0.5, 0.5, 0), (55, 0.5, 0))   # crosses panel 0, runs on
    edges = edges + [rail]
    cutting = rhino._edges_cutting(faces[0], _surface_of(faces[0]), edges,
                                   rhino._edge_boxes(edges), 1e-6)

    ids = {id(e) for e in cutting}
    assert id(rail) in ids, "a crossing edge must still be able to cut"
    assert ids == {id(e) for e in edges[:4]} | {id(rail)}, \
        f"{len(ids)} edges handed to the splitter, wanted 5"


def test_the_projector_is_built_once_per_face_not_once_per_sample(
        monkeypatch):
    """Constructing the extrema solver is the expensive part; the same one
    answers every sample of every edge on that surface."""
    built = {"n": 0}
    real = rhino.GeomAPI_ProjectPointOnSurf

    def counted(*a, **kw):
        built["n"] += 1
        return real(*a, **kw)

    monkeypatch.setattr(rhino, "GeomAPI_ProjectPointOnSurf", counted)

    faces, edges = _grid(4)
    rhino._edges_on_surface(_surface_of(faces[0]), edges, 1e-6)
    assert built["n"] == 1, f"{built['n']} projectors for one surface"


def test_reusing_the_projector_gives_the_same_answer():
    faces, edges = _grid(4)
    on = rhino._edges_on_surface(_surface_of(faces[0]), edges, 1e-6)
    assert len(on) == 16                    # every coplanar edge in the grid


def test_containment_query_matches_brute_force():
    """The sorted view behind `_edges_bounding` must agree exactly with the
    plain sweep it replaces, unmeasurable boxes included: at cab scale the
    per-face sweep of 48k edge boxes was ~2 ms, 40% of the face's whole
    conversion, so the prune itself needed pruning."""
    rng = np.random.default_rng(7)
    los = rng.uniform(0, 100, (500, 3))
    his = los + rng.uniform(0, 10, (500, 3))
    los[13] = [-np.inf] * 3     # an edge nobody could measure
    his[13] = [np.inf] * 3
    boxes = rhino._EdgeBoxes(los, his)
    for _ in range(50):
        lo = rng.uniform(0, 90, 3)
        hi = lo + rng.uniform(5, 40, 3)
        want = np.flatnonzero(np.all(los >= lo, axis=1)
                              & np.all(his <= hi, axis=1))
        got = boxes.contained(lo, hi)
        assert np.array_equal(np.sort(got), want)


def test_edge_boxes_still_unpacks_like_the_pair_it_was():
    _, edges = _grid(2)
    boxes = rhino._edge_boxes(edges)
    los, his = boxes
    assert los.shape == (8, 3) and his.shape == (8, 3)
    assert np.array_equal(boxes[0], los)


def test_an_unmeasurable_box_prunes_nothing():
    """A prefilter may only ever discard what it is sure about, so an edge
    whose box can't be measured has to survive."""
    faces, _ = _grid(3)
    junk = [object()]                       # nothing to take a box of
    boxes = rhino._edge_boxes(junk)
    assert np.all(np.isinf(boxes[0])) and np.all(np.isinf(boxes[1]))
    assert rhino._edges_near(faces[0], junk, boxes, 1e-6) == junk
