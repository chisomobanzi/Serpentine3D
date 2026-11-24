"""The arrow on a held face moves it, and the faces beside it follow (#176).

The Gumball's arrows move a held face the mesh modeller's way: the face
goes where it is dragged and each face beside it leans to keep hold of it.
The extrusion square is the other thing: new walls under the face, the
faces beside it left where they were.

On a solid the faces beside lean by the kernel's draft, which needs a
closed solid. On a surface, and on a solid whose top is two faces side by
side, the draft refused and the arrow fell back to the push, so it built
walls just as the square did. Now the corners move and every face that
shares one is rebuilt through where its corners went: flat if it can be,
and on a surface a twisted four-sided patch if it cannot, as Blender
would leave it; refused rather than extruded when it is neither. A
solid's faces all stay flat, and what it refused before it still does.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from PySide6.QtCore import Qt

from serpentine3d.core import geometry as g
from tests.test_a_face_pushed_on_a_surface_is_kept import (
    D, _close, _face, _flat_three)
from tests.test_a_flat_edge_surface_is_pushed_like_a_flat_face import (
    _edge_triangle, _is_plane)
from tests.test_a_flat_edge_surface_is_pushed_like_a_flat_face import (
    _flat_three as _edge_three)
from tests.test_a_held_face_or_edge_gets_a_whole_gumball import _holding

NONE = Qt.KeyboardModifier.NoModifier


def _moved(shape, index, distance):
    """The Gumball's arrow along a held face's normal."""
    from serpentine3d.ui.gumball import Gumball
    return Gumball._face_moved(shape, index, distance, True, False)


def _corners(shape):
    """Every corner of `shape`, once."""
    from OCP.BRep import BRep_Tool
    from OCP.TopExp import TopExp_Explorer
    from serpentine3d.core import occ
    out = []
    exp = TopExp_Explorer(shape, occ.VERTEX)
    while exp.More():
        p = BRep_Tool.Pnt_s(occ.to_vertex(exp.Current()))
        p = (p.X(), p.Y(), p.Z())
        if not any(_close(p, q) for q in out):
            out.append(p)
        exp.Next()
    return out


def _check_followed(before, after, part, delta):
    """`part`'s corners went by `delta`, every other corner stayed, and
    the faces are the same faces, still joined."""
    held = _corners(part)
    want = [tuple(p[k] + delta[k] for k in range(3))
            if any(_close(p, h) for h in held) else p
            for p in _corners(before)]
    got = _corners(after)
    assert len(got) == len(want)
    for p in want:
        assert any(_close(p, q, 1e-5) for q in got), p
    assert len(g.faces_of(after)) == len(g.faces_of(before))
    assert g.shape_kind(after) == g.shape_kind(before)
    assert len(g.joined_pieces(after)) == 1
    assert g.is_valid(after)


def _out(shape, index, distance):
    n = g.face_point_normal(g.faces_of(shape)[index])[1]
    return tuple(v * distance for v in n)


def _panel():
    """Four squares in one plane, two by two, joined."""
    return g.join_surfaces([
        _face((x, y, 0), (x + 10, y, 0), (x + 10, y + 10, 0), (x, y + 10, 0))
        for x in (0, 10) for y in (0, 10)])


def _split_box():
    """A 10 box whose top is two faces side by side, and the right one."""
    box = g.join_surfaces([
        _face((0, 0, 0), (0, 10, 0), (10, 10, 0), (10, 0, 0)),
        _face((0, 0, 0), (10, 0, 0), (10, 0, 10), (5, 0, 10), (0, 0, 10)),
        _face((10, 0, 0), (10, 10, 0), (10, 10, 10), (10, 0, 10)),
        _face((10, 10, 0), (0, 10, 0), (0, 10, 10), (5, 10, 10),
              (10, 10, 10)),
        _face((0, 10, 0), (0, 0, 0), (0, 0, 10), (0, 10, 10)),
        _face((0, 0, 10), (5, 0, 10), (5, 10, 10), (0, 10, 10)),
        _face((5, 0, 10), (10, 0, 10), (10, 10, 10), (5, 10, 10)),
    ])
    right = next(i for i, f in enumerate(g.faces_of(box))
                 if _close(g.centroid(f), (7.5, 5, 10)))
    return box, right


# --- the arrow along the normal ---------------------------------------------

@pytest.mark.parametrize("distance", [-D, D])
@pytest.mark.parametrize("index", [0, 1, 2])
def test_the_arrow_moves_a_face_of_a_flat_surface_and_the_rest_follow(
        index, distance):
    shape = _flat_three()
    after = _moved(shape, index, distance)
    _check_followed(shape, after, g.faces_of(shape)[index],
                    _out(shape, index, distance))


@pytest.mark.parametrize("distance", [-D, D])
@pytest.mark.parametrize("index", [0, 1, 2])
def test_the_arrow_moves_a_flat_edge_surface_face_and_the_rest_follow(
        index, distance):
    shape = _edge_three()
    after = _moved(shape, index, distance)
    _check_followed(shape, after, g.faces_of(shape)[index],
                    _out(shape, index, distance))


def test_a_square_lifted_out_of_a_panel_twists_the_one_at_its_corner():
    shape = _panel()
    held = next(i for i, f in enumerate(g.faces_of(shape))
                if _close(g.centroid(f), (5, 5, 0)))

    after = _moved(shape, held, D)

    _check_followed(shape, after, g.faces_of(shape)[held],
                    _out(shape, held, D))
    # the two beside it lean and stay flat; the one that only shares a
    # corner cannot, and is a twisted patch through its four corners
    assert sorted(_is_plane(f) for f in g.faces_of(after)) \
        == [False, True, True, True]


def test_a_face_beside_a_twisted_one_moves_again_and_the_twist_follows():
    shape = _panel()
    faces = g.faces_of(shape)
    first = next(i for i, f in enumerate(faces)
                 if _close(g.centroid(f), (5, 5, 0)))
    lifted = _moved(shape, first, D)
    twisted = next(i for i, f in enumerate(g.faces_of(lifted))
                   if not _is_plane(f))
    # the square across the twisted one from the one first lifted
    again = next(i for i, f in enumerate(g.faces_of(lifted))
                 if _close(g.centroid(f), (5, 15, D / 2), 1e-6)
                 or _close(g.centroid(f), (15, 5, D / 2), 1e-6))
    assert again != twisted

    after = _moved(lifted, again, D)

    _check_followed(lifted, after, g.faces_of(lifted)[again],
                    _out(lifted, again, D))


def test_a_solid_whose_top_is_two_faces_lifts_one_and_the_other_leans():
    box, right = _split_box()
    assert g.shape_kind(box) == "solid"

    after = _moved(box, right, D)

    _check_followed(box, after, g.faces_of(box)[right], (0, 0, D))
    # 50 D lifted under the right half, and a wedge of 25 D under the left
    # half, which now leans up to meet it: not the 50 D of a block on top
    assert math.isclose(g.volume(after), 1000 + 75 * D, rel_tol=1e-6)


def test_where_the_faces_beside_cannot_follow_the_arrow_builds_no_walls():
    # five corners, three staying and two going: no plane holds them,
    # and no four-sided patch either
    shape = g.join_surfaces([
        _face((0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)),
        _face((10, 0, 0), (20, -5, 0), (30, 5, 0), (20, 15, 0), (10, 10, 0)),
    ])
    with pytest.raises(g.GeometryError):
        _moved(shape, 0, D)


# --- within the face's plane, edges, and parts held together ----------------

@pytest.mark.parametrize("index", [0, 1, 2])
def test_a_face_of_a_flat_surface_slides_and_the_rest_follow(index):
    shape = _flat_three()
    delta = (2.0, 0.0, 1.0)                   # within y = 0
    _check_followed(shape, g.slide_face(shape, index, delta),
                    g.faces_of(shape)[index], delta)


def test_an_edge_of_a_flat_surface_moves_and_the_faces_on_it_follow():
    shape = _flat_three()
    shared = next(i for i in range(len(g.edges_of(shape)))
                  if sorted(g.edge_faces(shape, i)) == [0, 1])
    delta = (0.0, D, 0.0)                     # out of the plane

    after = g.move_edge(shape, shared, delta)

    _check_followed(shape, after, g.edges_of(shape)[shared], delta)


def test_two_faces_of_a_panel_move_together_and_the_rest_follow():
    shape = _panel()
    faces = g.faces_of(shape)
    held = [i for i, f in enumerate(faces)
            if _close(g.centroid(f), (5, 5, 0))
            or _close(g.centroid(f), (15, 15, 0))]
    delta = (0.0, 0.0, D)

    after = g.move_parts(shape, held, [], delta)

    _check_followed(shape, after,
                    g.make_compound([faces[i] for i in held]), delta)


# --- by hand, on the Gumball ------------------------------------------------

def _ground_three():
    """Three Edge Surface triangles lying on the ground, joined: the test
    camera looks along -Y, so it can take hold of an arrow out of them."""
    return g.join_surfaces([
        _edge_triangle((0, 0, 0), (0, 30, 0), (60, 30, 0)),
        _edge_triangle((0, 0, 0), (60, 30, 0), (100, 30, 0)),
        _edge_triangle((0, 0, 0), (100, 30, 0), (100, 0, 0)),
    ])


def test_dragging_the_arrow_out_of_a_held_face_takes_the_rest_with_it():
    shape = _ground_three()
    gb, vp, obj = _holding(shape, "face", 0)
    normal = np.asarray(g.face_point_normal(g.faces_of(shape)[0])[1])
    _, axes = gb.anchor_and_axes()
    toward = float(np.sign(np.dot(axes[2], normal)))

    assert gb.begin_drag(("move", 2), 10.0, 10.0, NONE)
    gb.apply_scalar(-D * toward)
    gb.end_drag()

    _check_followed(shape, vp.scene.get(obj.id).shape,
                    g.faces_of(shape)[0], tuple(normal * -D))


def test_dragging_an_arrow_along_a_held_face_slides_it_and_the_rest_follow():
    shape = _ground_three()
    gb, vp, obj = _holding(shape, "face", 1)
    _, axes = gb.anchor_and_axes()
    # an arrow in the ground, and not the one the camera looks along
    i = next(i for i in (0, 1) if abs(float(axes[i][2])) < 1e-6
             and abs(float(axes[i][1])) < 0.9)

    assert gb.begin_drag(("move", i), 10.0, 10.0, NONE)
    gb.apply_scalar(4.0)
    gb.end_drag()

    _check_followed(shape, vp.scene.get(obj.id).shape,
                    g.faces_of(shape)[1], tuple(np.asarray(axes[i]) * 4.0))
