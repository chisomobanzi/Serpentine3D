"""A flat face made by Edge Surface is pushed like any flat face (#176).

Edge Surface makes a triangle as a freeform patch with one side shrunk to
a point. Flat as it lies, it counted as curved: the Gumball offered it
only the offset arrow, and the offset refuses a face that closes to a
point, where the kernel faults (#160). Three such triangles joined into
one would not move at all, where the same three made by Planar Surface
would.

A face is now flat by where it lies, not by the surface it was made on:
before a flat freeform face is pushed, pulled or held, it is rebuilt as
a plane over the same edges, and from then on it is moved like one. A
face that really is curved is left to the offset, and still refused
where that would fault.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from PySide6.QtCore import Qt

from serpentine3d.core import geometry as g
from tests.test_a_face_pushed_on_a_surface_is_kept import (
    D, _check_carried, _close)
from tests.test_a_held_face_or_edge_gets_a_whole_gumball import _holding

NONE = Qt.KeyboardModifier.NoModifier


def _edge_triangle(a, b, c):
    return g.edge_surface([g.make_line(a, b), g.make_line(b, c),
                           g.make_line(c, a)])


def _flat_three():
    """The report's three triangles, made by Edge Surface and joined."""
    return g.join_surfaces([
        _edge_triangle((0, 0, 0), (0, 0, 30), (60, 0, 30)),
        _edge_triangle((0, 0, 0), (60, 0, 30), (100, 0, 30)),
        _edge_triangle((0, 0, 0), (100, 0, 30), (100, 0, 0)),
    ])


def _curved_triangle():
    """An Edge Surface triangle with one bowed side: not flat anywhere."""
    bow = g.make_interp_curve([(0, 0, 0), (30, 0, 10), (60, 0, 0)])
    return g.edge_surface([bow, g.make_line((60, 0, 0), (30, 40, 0)),
                           g.make_line((30, 40, 0), (0, 0, 0))])


def _is_plane(face):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_SurfaceType
    return (BRepAdaptor_Surface(face).GetType()
            == GeomAbs_SurfaceType.GeomAbs_Plane)


def test_a_flat_edge_surface_face_is_a_plane_over_the_same_edges():
    face = g.faces_of(_edge_triangle((0, 0, 0), (60, 0, 30), (100, 0, 30)))[0]
    assert not _is_plane(face)

    plane = g.as_plane(face)

    assert _is_plane(plane)
    assert _close(g.face_normal(plane), g.face_point_normal(face)[1])
    assert _close(g.centroid(plane), g.centroid(face))
    assert g.surface_area(plane) == pytest.approx(g.surface_area(face))


def test_a_curved_face_is_not_a_plane():
    with pytest.raises(g.GeometryError):
        g.as_plane(g.faces_of(_curved_triangle())[0])


def test_flat_faces_become_planes_in_their_places():
    shape = _flat_three()

    out = g.flat_faces_as_planes(shape)

    assert g.shape_kind(out) == "surface"
    assert len(g.joined_pieces(out)) == 1
    before, after = g.faces_of(shape), g.faces_of(out)
    assert len(after) == len(before)
    for was, now in zip(before, after):
        assert _is_plane(now)
        assert _close(g.centroid(now), g.centroid(was))
        assert _close(g.face_normal(now), g.face_point_normal(was)[1])


def test_a_shape_with_no_flat_freeform_face_comes_back_as_it_was():
    box = g.make_box((0, 0, 0), 10, 10, 10)
    assert g.flat_faces_as_planes(box) is box
    curved = _curved_triangle()
    assert g.flat_faces_as_planes(curved) is curved


@pytest.mark.parametrize("distance", [-D, D])
@pytest.mark.parametrize("index", [0, 1, 2])
def test_a_face_of_flat_edge_surfaces_is_carried_on_walls(index, distance):
    shape = _flat_three()
    _check_carried(shape, g.push_pull(shape, index, distance), index, distance)


@pytest.mark.parametrize("distance", [-D, D])
def test_the_gumballs_extrusion_square_carries_a_flat_edge_surface_face(
        distance):
    from serpentine3d.ui.gumball import Gumball
    shape = _flat_three()
    after = Gumball._face_moved(shape, 0, distance, True, True)
    _check_carried(shape, after, 0, distance)


def test_a_held_flat_edge_surface_face_gets_a_flat_faces_gumball():
    gb, _, _ = _holding(_flat_three(), "face", 0)

    target = gb._pushpull_target()

    assert target is not None and target[4]          # held as flat
    assert ("ext", 2) in gb.handles()


def test_dragging_the_square_on_a_held_flat_edge_surface_face_keeps_it():
    # Lying on the ground, where the test camera's sideways look can take
    # hold of the square out of them. The arrow: see
    # test_a_moved_face_takes_its_neighbours_with_it
    shape = g.join_surfaces([
        _edge_triangle((0, 0, 0), (0, 30, 0), (60, 30, 0)),
        _edge_triangle((0, 0, 0), (60, 30, 0), (100, 30, 0)),
        _edge_triangle((0, 0, 0), (100, 30, 0), (100, 0, 0)),
    ])
    gb, vp, obj = _holding(shape, "face", 0)
    normal = np.asarray(g.face_point_normal(g.faces_of(shape)[0])[1])
    _, axes = gb.anchor_and_axes()
    toward = float(np.sign(np.dot(axes[2], normal)))

    assert gb.begin_drag(("ext", 2), 10.0, 10.0, NONE)
    gb.apply_scalar(-D * toward)
    gb.end_drag()

    _check_carried(shape, vp.scene.get(obj.id).shape, 0, -D)


def test_a_solid_of_flat_edge_surfaces_is_pushed_by_its_volume():
    a, b, c, d = (0, 0, 0), (10, 0, 0), (0, 10, 0), (0, 0, 10)
    solid = g.join_surfaces([_edge_triangle(a, c, b), _edge_triangle(a, b, d),
                             _edge_triangle(a, d, c), _edge_triangle(b, c, d)])
    assert g.shape_kind(solid) == "solid"
    floor = next(i for i, f in enumerate(g.faces_of(solid))
                 if abs(g.centroid(f)[2]) < 1e-9)
    area = g.surface_area(g.faces_of(solid)[floor])
    volume = g.volume(solid)

    pulled = g.push_pull(solid, floor, D)

    assert math.isclose(g.volume(pulled), volume + area * D, rel_tol=1e-6)


def test_a_curved_edge_surface_is_still_refused():
    curved = _curved_triangle()
    with pytest.raises(g.GeometryError):
        g.push_pull(curved, 0, D)
    with pytest.raises(g.GeometryError):
        g.offset_face(curved, 0, D)
