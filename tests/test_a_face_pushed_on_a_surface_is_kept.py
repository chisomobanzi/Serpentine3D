"""Push a face of a surface and the face is still there (#176).

Push/pull was written for solids: pulling a face out unions a prism onto
the solid, pushing it in carves the prism away. A surface has no inside,
so the carve took the face itself, which lies on the prism's boundary, and
left a shell one face short that still passed the kernel's checks. The
union simply failed. Three flat surfaces joined into one, then a face held
and dragged back on the Gumball, lost that face.

On a surface the face is carried out on new walls instead, either way:
the face moves, walls join it to its old outline, and every other face is
left as it was.
"""

from __future__ import annotations

import math

import pytest

from serpentine3d.core import geometry as g

D = 2.0


def _face(*pts):
    return g.planar_face(g.make_polyline([tuple(map(float, p)) for p in pts],
                                         closed=True))


def _flat_three():
    """Three triangles in one plane, joined: the shape in the report."""
    return g.join_surfaces([
        _face((0, 0, 0), (0, 0, 30), (60, 0, 30)),
        _face((0, 0, 0), (60, 0, 30), (100, 0, 30)),
        _face((0, 0, 0), (100, 0, 30), (100, 0, 0)),
    ])


def _close(a, b, tol=1e-6):
    return all(abs(x - y) < tol for x, y in zip(a, b))


def _looks(face):
    """Where a face is, which way it faces and how big it is."""
    return g.centroid(face), g.face_normal(face), g.surface_area(face)


def _has(shape, centre, normal, area):
    return any(_close(c, centre) and _close(n, normal) and
               abs(a - area) < 1e-6 for c, n, a in map(_looks, g.faces_of(shape)))


def _check_carried(before, after, index, distance):
    faces = g.faces_of(before)
    centre, normal, area = _looks(faces[index])
    moved = tuple(c + distance * n for c, n in zip(centre, normal))
    assert _has(after, moved, normal, area), "the face did not arrive"
    for i, face in enumerate(faces):
        if i != index:
            assert _has(after, *_looks(face)), f"face {i} was lost or turned"
    edges = len(g.edges_of(faces[index]))
    assert len(g.faces_of(after)) == len(faces) + edges
    assert g.shape_kind(after) == "surface"
    assert len(g.joined_pieces(after)) == 1


@pytest.mark.parametrize("distance", [-D, D])
@pytest.mark.parametrize("index", [0, 1, 2])
def test_a_face_of_a_flat_surface_is_carried_on_walls(index, distance):
    shape = _flat_three()
    _check_carried(shape, g.push_pull(shape, index, distance), index, distance)


@pytest.mark.parametrize("distance", [-D, D])
def test_a_lone_face_is_carried_on_walls(distance):
    shape = _face((0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0))
    _check_carried(shape, g.push_pull(shape, 0, distance), 0, distance)


def test_the_floor_of_an_open_box_is_carried_out_on_walls():
    shape = g.join_surfaces([
        _face((0, 0, 0), (0, 10, 0), (10, 10, 0), (10, 0, 0)),
        _face((0, 0, 0), (10, 0, 0), (10, 0, 10), (0, 0, 10)),
        _face((10, 0, 0), (10, 10, 0), (10, 10, 10), (10, 0, 10)),
        _face((10, 10, 0), (0, 10, 0), (0, 10, 10), (10, 10, 10)),
        _face((0, 10, 0), (0, 0, 0), (0, 0, 10), (0, 10, 10)),
    ])
    floor = next(i for i, f in enumerate(g.faces_of(shape))
                 if abs(g.centroid(f)[2]) < 1e-9)
    # Down, away from the box, whichever way the joined floor faces.
    distance = -D * g.face_normal(g.faces_of(shape)[floor])[2]
    _check_carried(shape, g.push_pull(shape, floor, distance), floor,
                   distance)


@pytest.mark.parametrize("grow", [False, True])
@pytest.mark.parametrize("distance", [-D, D])
def test_the_gumball_keeps_the_face_it_drags(distance, grow):
    from serpentine3d.ui.gumball import Gumball
    shape = _flat_three()
    after = Gumball._face_moved(shape, 0, distance, True, grow)
    _check_carried(shape, after, 0, distance)


def test_a_solid_is_still_pushed_and_pulled_by_its_volume():
    box = g.make_box((0, 0, 0), 10, 10, 10)
    top = next(i for i, f in enumerate(g.faces_of(box))
               if abs(g.centroid(f)[2] - 10) < 1e-9)
    assert math.isclose(g.volume(g.push_pull(box, top, -D)), 800, rel_tol=1e-6)
    assert math.isclose(g.volume(g.push_pull(box, top, D)), 1200, rel_tol=1e-6)
