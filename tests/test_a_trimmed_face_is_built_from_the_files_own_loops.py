"""A .3dm face is trimmed by the loops the file already carries (#10).

rhino3dm does not hand out the 2D trim curves, so the importer used to
rebuild each face's boundary by guessing: take every edge whose box is near
the face, keep the ones that project onto its surface, and hope they join
into a closed wire. When they did not, it fell back to splitting the whole
untrimmed surface by every edge that crossed it and asking the render mesh
which pieces were real. That fallback costs seconds per face, which is why
six of the openNURBS sample files reportedly hung the import.

The file does say which edges bound each face. `BrepFace.Loops` gives the
trims in order, each naming an edge and whether the loop runs along it
backwards. A seam is the case that broke the guess: the loop walks the same
edge twice, once each way, so no set of distinct edges can close it.
"""

from __future__ import annotations

import math

import pytest

rhino3dm = pytest.importorskip("rhino3dm")

from serpentine3d.core import geometry as g
from serpentine3d.fileio import rhino as R


RADIUS = 5.0
HEIGHT = 10.0
# The surface arrives as a NURBS conversion of the cylinder, so its area
# integrates about 0.2% high. That is the same on every path through the
# importer; what these tests are looking for is a face ten times the size,
# which is what building the wrong side of the boundary gives.
ROUGHLY = 5e-3


def _cylinder_brep():
    """A capped cylinder: its side face's loop uses the seam edge twice."""
    circle = rhino3dm.Circle(rhino3dm.Point3d(0, 0, 0), RADIUS)
    brep = rhino3dm.Brep.CreateFromCylinder(
        rhino3dm.Cylinder(circle, HEIGHT), True, True)
    assert brep is not None and len(brep.Faces) == 3
    return brep


def _seam_face_index(brep):
    for fi in range(len(brep.Faces)):
        loop = brep.Faces[fi].OuterLoop
        seen = [loop.Trims[i].EdgeIndex for i in range(loop.TrimCount)]
        if len(seen) != len(set(seen)):
            return fi
    raise AssertionError("this brep was supposed to have a seam")


def _no_guessing(monkeypatch):
    """Fail if the importer falls back to splitting and classifying."""
    def refuse(*_a, **_k):
        raise AssertionError(
            "the file's own loops describe this face, so it must not be "
            "rebuilt by splitting the untrimmed surface")

    monkeypatch.setattr(R, "_split_face_by_edges", refuse)


def test_the_brep_really_does_walk_one_edge_twice():
    """Guard the fixture: without this the test below proves nothing."""
    brep = _cylinder_brep()
    loop = brep.Faces[_seam_face_index(brep)].OuterLoop
    trims = [(loop.Trims[i].EdgeIndex, loop.Trims[i].IsReversed)
             for i in range(loop.TrimCount)]
    repeated = [e for e, _r in trims
                if sum(1 for o, _ in trims if o == e) > 1]
    assert repeated, trims
    both_ways = {r for e, r in trims if e == repeated[0]}
    assert both_ways == {True, False}, (
        "the seam is walked once each way, which is the whole difficulty")


def test_a_seam_face_is_trimmed_from_its_loops(monkeypatch):
    _no_guessing(monkeypatch)
    brep = _cylinder_brep()
    fi = _seam_face_index(brep)

    shapes = R._face_shapes(brep, fi, *R._brep_edge_context(brep))

    assert len(shapes) == 1
    area = g.surface_area(shapes[0])
    assert area == pytest.approx(2 * math.pi * RADIUS * HEIGHT, rel=ROUGHLY), (
        "the side of the cylinder, not the complement of it")


def test_the_flat_faces_come_out_right_too(monkeypatch):
    _no_guessing(monkeypatch)
    brep = _cylinder_brep()
    seam = _seam_face_index(brep)
    context = R._brep_edge_context(brep)

    caps = [R._face_shapes(brep, fi, *context)
            for fi in range(len(brep.Faces)) if fi != seam]

    assert all(len(s) == 1 for s in caps)
    for cap in caps:
        assert g.surface_area(cap[0]) == pytest.approx(
            math.pi * RADIUS ** 2, rel=ROUGHLY)


def test_the_whole_cylinder_converts_to_a_closed_solid(monkeypatch):
    _no_guessing(monkeypatch)
    brep = _cylinder_brep()

    shapes = R.object_to_shapes(brep)

    assert len(shapes) == 1
    total = 2 * math.pi * RADIUS * HEIGHT + 2 * math.pi * RADIUS ** 2
    assert g.surface_area(shapes[0]) == pytest.approx(total, rel=ROUGHLY)
    # bounds carry the brep's own modelling tolerance on purpose, so they
    # sit a hundredth proud of the exact cylinder
    lo, hi = g.bbox(shapes[0])
    assert lo == pytest.approx((-RADIUS, -RADIUS, 0), abs=0.02)
    assert hi == pytest.approx((RADIUS, RADIUS, HEIGHT), abs=0.02)


def test_a_face_whose_loops_are_unusable_still_converts(monkeypatch):
    """The guessing path stays as the safety net. A face the loops cannot
    describe must still come back, by whatever route."""
    brep = _cylinder_brep()
    fi = _seam_face_index(brep)
    monkeypatch.setattr(R, "_face_from_loops", lambda *a, **k: None)

    shapes = R._face_shapes(brep, fi, *R._brep_edge_context(brep))

    assert shapes, "falling back is slow, but it must not lose the face"
