"""Every handle on a held face does something.

The 0.8.3 gumball hid the handles that could not change a plane: sliding
a flat face within itself, or scaling it, leaves the plane where it was,
so under the rule that neighbours extend to meet a *moved plane* they did
nothing. That rule is a solid modeller's; a person dragging a face expects
the other one, the mesh modeller's: the face's edges go with it and the
faces beside it lean to keep hold of them. Slide a box top sideways and
the box shears. Shrink it and the box tapers to a truncated pyramid.

So the in-plane arrows, the pads and the scale boxes come back, and they
do that. The arrow along the normal follows the same rule: the held face
moves rigidly and its neighbours adapt. A box cannot show the difference,
but a tapered solid can because re-trimming its sides would resize the cap.
"""

from __future__ import annotations

import numpy as np
import pytest

from serpentine3d.core import geometry as g


def _normals(shape):
    out = []
    for f in g.faces_of(shape):
        try:
            out.append(np.asarray(g.face_normal(f), float))
        except g.GeometryError:
            out.append(None)
    return out


def _face_where(shape, pred):
    for i, n in enumerate(_normals(shape)):
        if n is not None and pred(n):
            return i
    raise KeyError("no face matches")


def _slab():
    """A 20 x 10 x 10 box, and the index of its top."""
    box = g.make_box((0, 0, 0), 20, 10, 10)
    return box, _face_where(box, lambda n: n[2] > 0.9)


# --- moving a face along its normal -----------------------------------------

def test_moving_a_frustum_cap_along_its_normal_keeps_the_cap_rigid():
    box, top = _slab()
    frustum = g.scale_face(box, top, 0.5)
    faces = g.faces_of(frustum)
    top = _face_where(frustum, lambda n: n[2] > 0.999)
    bottom = _face_where(frustum, lambda n: n[2] < -0.999)
    lid_before, floor_before = faces[top], faces[bottom]
    lid_center = np.asarray(g.centroid(lid_before))
    lid_lo, lid_hi = g.bbox(lid_before)
    floor_center = np.asarray(g.centroid(floor_before))
    floor_lo, floor_hi = g.bbox(floor_before)

    out = g.offset_face(frustum, top, 3.0)

    assert g.shape_kind(out) == "solid"
    assert len(g.faces_of(out)) == len(faces)
    lid = g.faces_of(out)[_face_where(out, lambda n: n[2] > 0.999)]
    assert np.asarray(g.centroid(lid)) == pytest.approx(
        lid_center + (0, 0, 3), abs=1e-6)
    lid_after_lo, lid_after_hi = g.bbox(lid)
    assert np.asarray(lid_after_hi) - lid_after_lo == pytest.approx(
        np.asarray(lid_hi) - lid_lo, abs=1e-6)
    assert g.surface_area(lid) == pytest.approx(
        g.surface_area(lid_before), abs=1e-6)

    floor = g.faces_of(out)[_face_where(out, lambda n: n[2] < -0.999)]
    assert np.asarray(g.centroid(floor)) == pytest.approx(floor_center,
                                                          abs=1e-6)
    floor_after_lo, floor_after_hi = g.bbox(floor)
    assert np.asarray(floor_after_hi) - floor_after_lo == pytest.approx(
        np.asarray(floor_hi) - floor_lo, abs=1e-6)


# --- sliding a face in its own plane ----------------------------------------

def test_a_face_slid_in_its_plane_shears_the_box():
    box, top = _slab()

    out = g.slide_face(box, top, (3, 0, 0))

    assert g.volume(out) == pytest.approx(2000.0, abs=1e-3)
    assert len(g.faces_of(out)) == 6
    lid = g.faces_of(out)[_face_where(out, lambda n: n[2] > 0.999)]
    assert np.asarray(g.centroid(lid)) == pytest.approx((13, 5, 10), abs=1e-6)
    # the front leans to keep hold of the moved edge; the sides, which the
    # slide ran along, are untouched
    front = _normals(out)[_face_where(out, lambda n: n[0] > 0.5)]
    assert front == pytest.approx(np.array([10, 0, -3]) / np.hypot(10, 3),
                                  abs=1e-6)
    assert any(n is not None and abs(n[1] - 1) < 1e-9 for n in _normals(out))


def test_the_far_side_of_a_leaning_face_stays_put():
    box, top = _slab()

    out = g.slide_face(box, top, (3, 0, 0))

    floor = g.faces_of(out)[_face_where(out, lambda n: n[2] < -0.9)]
    lo, hi = g.bbox(floor)
    assert lo == pytest.approx((0, 0, 0), abs=1e-6)
    assert hi == pytest.approx((20, 10, 0), abs=1e-6)


def test_a_slide_along_the_normal_is_refused():
    """That is a move, and the move arrow's job. The slide would have to
    pretend the plane can hold a point off it."""
    box, top = _slab()

    with pytest.raises(g.GeometryError):
        g.slide_face(box, top, (0, 0, 3))


def test_a_slide_of_nothing_is_refused():
    box, top = _slab()

    with pytest.raises(g.GeometryError):
        g.slide_face(box, top, (0, 0, 0))


def test_a_slide_along_a_chamfer_leaves_the_chamfer_alone():
    """Only the faces the slide runs across have to lean."""
    box = g.make_box((0, 0, 0), 10, 10, 10)
    e = next(i for i, ed in enumerate(g.edges_of(box))
             if abs(g.centroid(ed)[0] - 10) < 1e-6
             and abs(g.centroid(ed)[2] - 10) < 1e-6)
    cham = g.fillet_edges(box, 3.0, edges=[g.edges_of(box)[e]], chamfer=True)
    top = _face_where(cham, lambda n: n[2] > 0.99)

    out = g.slide_face(cham, top, (0, 2, 0))

    assert len(g.faces_of(out)) == 7
    assert any(n is not None and abs(n[0] - n[2]) < 1e-6 and n[0] > 0.5
               for n in _normals(out)), "the 45 degree face is untouched"
    assert g.volume(out) == pytest.approx(955.0, abs=1e-3)


def test_a_face_beside_a_curved_face_cannot_slide():
    cyl = g.make_cylinder((0, 0, 0), 5, 10)
    top = _face_where(cyl, lambda n: n[2] > 0.9)

    with pytest.raises(g.GeometryError):
        g.slide_face(cyl, top, (1, 0, 0))


# --- scaling a face in its own plane ----------------------------------------

def test_a_face_scaled_in_its_plane_tapers_the_box():
    box, top = _slab()

    out = g.scale_face(box, top, 0.5)

    # a frustum: h/3 (A1 + A2 + sqrt(A1 A2))
    assert g.volume(out) == pytest.approx(10 / 3 * (200 + 50 + 100), abs=1e-3)
    assert len(g.faces_of(out)) == 6
    lid = g.faces_of(out)[_face_where(out, lambda n: n[2] > 0.999)]
    assert np.asarray(g.centroid(lid)) == pytest.approx((10, 5, 10), abs=1e-6)
    lo, hi = g.bbox(lid)
    assert (hi[0] - lo[0], hi[1] - lo[1]) == pytest.approx((10, 5), abs=1e-6)
    leaning = [n for n in _normals(out)
               if n is not None and 0.05 < abs(n[2]) < 0.95]
    assert len(leaning) == 4, "all four sides lean inward"


def test_a_face_scaled_along_one_edge_narrows_only_that_way():
    box, top = _slab()

    out = g.scale_face(box, top, 0.5, axis=(1, 0, 0))

    assert g.volume(out) == pytest.approx(10 * 15 * 10, abs=1e-3)
    normals = _normals(out)
    assert any(n is not None and abs(n[1] - 1) < 1e-9 for n in normals)
    assert any(n is not None and abs(n[1] + 1) < 1e-9 for n in normals)
    leaning = [n for n in normals if n is not None and 0.05 < abs(n[2]) < 0.95]
    assert len(leaning) == 2


def test_growing_a_face_flares_the_box():
    box, top = _slab()

    out = g.scale_face(box, top, 1.5)

    assert g.volume(out) > 2000.0
    lid = g.faces_of(out)[_face_where(out, lambda n: n[2] > 0.999)]
    lo, hi = g.bbox(lid)
    assert hi[0] - lo[0] == pytest.approx(30, abs=1e-6)


def test_scaling_a_face_to_nothing_is_refused():
    box, top = _slab()

    with pytest.raises(g.GeometryError):
        g.scale_face(box, top, 0.0)
    with pytest.raises(g.GeometryError):
        g.scale_face(box, top, -1.0)


def test_a_scale_that_changes_nothing_is_refused():
    box, top = _slab()

    with pytest.raises(g.GeometryError):
        g.scale_face(box, top, 1.0)
