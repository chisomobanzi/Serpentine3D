"""Object alignment follows the natural frame of one whole framed object.

The pivot remains the selection's bounding-box centre. Geometry without
a unique frame, or a selection of several objects, uses the CPlane.
These tests exercise the same axes the viewport draws without painting GL.
"""

from __future__ import annotations

import numpy as np
import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.cplane import CPlane
from serpentine3d.core.hatch import HatchShape
from serpentine3d.core.mesh import MeshShape
from serpentine3d.core.picture import PictureShape
from serpentine3d.core.pointcloud import PointCloudShape
from serpentine3d.core.text import TextShape
from tests.test_a_held_face_or_edge_gets_a_whole_gumball import _face_where
from tests.test_the_gumball_can_be_aligned import TILTED, _whole


def _cp_axes(cp):
    return np.asarray((cp.xdir, cp.ydir, cp.normal), float)


def _assert_axes(gb, expected):
    _, axes = gb.anchor_and_axes()
    axes = np.asarray(axes, float)
    assert axes == pytest.approx(np.asarray(expected, float), abs=1e-6)
    assert axes @ axes.T == pytest.approx(np.eye(3), abs=1e-6)
    assert np.cross(axes[0], axes[1]) == pytest.approx(axes[2], abs=1e-6)


def _rectangle_on(cp):
    return g.make_polyline([cp.to_world(u, v) for u, v in
                            ((0, 0), (17, 0), (17, 4), (0, 4))], closed=True)


def _rotated_text():
    return g.rotate(TextShape("Rhino", 3, origin=(9, -4, 0)),
                    (0, 0, 0), (0, 0, 1), 30)


def _rotated_hatch():
    region = g.planar_face(g.make_rectangle((0, 0, 0), (12, 4, 0)))
    # The pattern angle is independent of the object's placement frame.
    return g.rotate(HatchShape(region, angle=67, spacing=2, xdir=(1, 0, 0)),
                    (0, 0, 0), (0, 0, 1), 30)


def _picture():
    return PictureShape(dict(origin=(7, -5, 11), u=(6, 8, 0),
                             v=(-8, 6, 0)))


@pytest.mark.parametrize("kind", ["line", "collinear-polyline"])
@pytest.mark.parametrize("end", [(6, 8, 0), (6, 8, 10)],
                         ids=["in-cplane", "spatial"])
def test_straight_curves_have_x_along_the_line_and_z_towards_the_cplane(kind, end):
    midpoint = tuple(np.asarray(end, float) / 2)
    shape = (g.make_line((0, 0, 0), end) if kind == "line"
             else g.make_polyline([(0, 0, 0), midpoint, end]))
    gb, vp, _ = _whole(shape)

    _, axes = gb.anchor_and_axes()

    x, y, z = np.asarray(axes, float)
    direction = np.asarray(end, float) / np.linalg.norm(end)
    assert abs(np.dot(x, direction)) == pytest.approx(1, abs=1e-6)
    normal = np.asarray(vp.cplane.normal, float)
    toward_plane = normal - np.dot(normal, direction) * direction
    toward_plane /= np.linalg.norm(toward_plane)
    assert z == pytest.approx(toward_plane, abs=1e-6)
    assert y == pytest.approx(np.cross(z, x), abs=1e-6)
    assert np.asarray(axes) @ np.asarray(axes).T == pytest.approx(np.eye(3), abs=1e-6)


@pytest.mark.parametrize("kind", ["circle", "arc", "polyline", "spline"])
def test_nonstraight_planar_curves_use_their_plane_and_project_cplane_x(kind):
    plane = CPlane(normal=(0, -1, -1), xdir=(1, 0, 0))
    points = [plane.to_world(u, v) for u, v in ((0, 0), (4, 3), (9, 1), (11, 6))]
    if kind == "circle":
        shape = g.make_circle((0, 0, 0), 5, normal=tuple(plane.normal))
    elif kind == "arc":
        shape = g.make_arc_3pt(*points[:3])
    elif kind == "polyline":
        shape = g.make_polyline(points)
    else:
        shape = g.make_interp_curve(points)
    cp = CPlane(normal=(0, 0, 1), xdir=(0, 1, 0))
    gb, _, _ = _whole(shape, cp)
    # The plane normal is chosen in the CPlane's hemisphere, independently
    # of the curve's traversal direction or the original circle normal.
    expected = ((0, 1 / np.sqrt(2), -1 / np.sqrt(2)),
                (-1, 0, 0), (0, 1 / np.sqrt(2), 1 / np.sqrt(2)))

    _assert_axes(gb, expected)


def test_a_rectangle_drawn_on_the_cplane_keeps_its_exact_axes():
    cp = CPlane(origin=(8, -3, 5), normal=(1, 2, 3), xdir=(2, -1, 0))
    gb, _, _ = _whole(_rectangle_on(cp), cp)

    _assert_axes(gb, _cp_axes(cp))


def test_a_curve_plane_uses_cplane_y_when_cplane_x_is_normal_to_it():
    gb, vp, _ = _whole(g.make_circle((0, 0, 0), 5, normal=(1, 0, 0)))

    _, axes = gb.anchor_and_axes()

    x, y, z = np.asarray(axes, float)
    assert x == pytest.approx(vp.cplane.ydir, abs=1e-6)
    assert abs(z[0]) == pytest.approx(1, abs=1e-6)
    assert np.cross(x, y) == pytest.approx(z, abs=1e-6)
    assert np.asarray(axes) @ np.asarray(axes).T == pytest.approx(np.eye(3), abs=1e-6)


def test_one_whole_planar_face_uses_its_own_normal():
    face = g.planar_face(g.make_rectangle((0, 0, 0), (12, 4, 0)))
    face = g.rotate(face, (0, 0, 0), (1, 0, 0), 30)
    gb, _, _ = _whole(face)

    _assert_axes(gb, ((1, 0, 0), (0, np.sqrt(3) / 2, .5),
                      (0, -.5, np.sqrt(3) / 2)))


@pytest.mark.parametrize("factory", [_rotated_text, _rotated_hatch],
                         ids=["text", "hatch"])
def test_rotated_annotation_objects_follow_their_placement_axes(factory):
    gb, _, _ = _whole(factory(), TILTED)

    _assert_axes(gb, ((np.sqrt(3) / 2, .5, 0),
                      (-.5, np.sqrt(3) / 2, 0), (0, 0, 1)))


@pytest.mark.parametrize("u,v,expected", [
    ((6, 8, 0), (-8, 6, 0), ((.6, .8, 0), (-.8, .6, 0), (0, 0, 1))),
    ((6, 8, 0), (8, -6, 0), ((.6, .8, 0), (.8, -.6, 0), (0, 0, -1))),
    ((0, 6, 8), (5, 3, 4), ((0, .6, .8), (1, 0, 0), (0, .8, -.6))),
], ids=["rotated", "mirrored", "skewed-upright"])
def test_pictures_follow_their_own_plane_with_a_right_handed_orthonormal_frame(
        u, v, expected):
    picture = PictureShape(dict(origin=(7, -5, 11), u=u, v=v))
    gb, _, _ = _whole(picture, TILTED)

    _assert_axes(gb, expected)


def _polysurface():
    box = g.make_box((0, 0, 0), 10, 10, 10)
    faces = g.faces_of(box)
    return g.join_surfaces([faces[_face_where(box, lambda n: n[0] > .9)],
                            faces[_face_where(box, lambda n: n[2] > .9)]])


def _freeform_surface():
    profile = g.make_circle((0, 0, 0), 5)
    top = g.make_circle((0, 0, 8), 2)
    top = g.rotate(top, (0, 0, 8), (1, 0, 0), 20)
    return g.loft([profile, top])


@pytest.mark.parametrize("factory", [
    lambda: g.rotate(g.make_box((0, 0, 0), 10, 6, 4),
                     (0, 0, 0), (0, 0, 1), 30),
    _polysurface,
    _freeform_surface,
    lambda: MeshShape([[0, 0, 0], [6, 8, 0], [-8, 6, 0]], [[0, 1, 2]]),
    lambda: PointCloudShape([[0, 0, 0], [6, 8, 0], [-8, 6, 0]]),
    lambda: g.make_point((2, 3, 4)),
    lambda: g.make_compound([g.make_line((0, 0, 0), (6, 8, 0)),
                             g.make_line((0, 0, 0), (0, 0, 9))]),
    lambda: g.make_polyline([(0, 0, 0), (5, 0, 0), (5, 5, 0), (3, 5, 4)]),
], ids=["solid", "polysurface", "freeform-surface", "mesh", "point-cloud",
        "point", "compound", "nonplanar-curve"])
def test_objects_without_a_natural_frame_fall_back_to_the_cplane(factory):
    gb, _, _ = _whole(factory(), TILTED)

    _assert_axes(gb, _cp_axes(TILTED))


def test_multiple_whole_objects_use_the_cplane_even_when_each_has_a_frame():
    gb, vp, first = _whole(g.make_line((0, 0, 0), (6, 8, 0)), TILTED)
    second = vp.scene.add(_picture())
    vp.selection.set([first.id, second.id])

    _assert_axes(gb, _cp_axes(TILTED))


@pytest.mark.parametrize("factory", [
    lambda: g.make_line((2, 3, 4), (8, 11, 4)),
    lambda: g.make_polyline([(0, 0, 0), (9, 0, 0), (2, 3, 0)]),
    lambda: g.planar_face(g.make_rectangle((0, 0, 0), (12, 4, 0))),
    _rotated_text, _rotated_hatch, _picture,
], ids=["line", "curve", "face", "text", "hatch", "picture"])
def test_alignment_changes_preserve_the_bounding_box_centre(factory):
    gb, _, obj = _whole(factory(), TILTED)
    lo, hi = obj.bbox()
    expected = (np.asarray(lo) + np.asarray(hi)) / 2

    for alignment in ("object", "cplane", "world", "view"):
        gb.set_align(alignment)
        anchor, _ = gb.anchor_and_axes()
        assert anchor == pytest.approx(expected, abs=1e-6)


@pytest.mark.parametrize("alignment", ["world", "cplane", "view"])
def test_an_explicit_alignment_overrides_the_objects_own_axes(alignment):
    gb, vp, _ = _whole(_rotated_text(), TILTED)
    gb.set_align(alignment)
    if alignment == "world":
        expected = np.eye(3)
    elif alignment == "cplane":
        expected = _cp_axes(TILTED)
    else:
        right, up = vp._eye().right_up()
        expected = (right, up, np.cross(right, up))

    _assert_axes(gb, expected)


def test_object_axes_update_when_the_scene_replaces_geometry():
    gb, vp, obj = _whole(g.make_line((0, 0, 0), (6, 8, 0)))
    _, before = gb.anchor_and_axes()
    old_revision = vp.scene.revision
    vp.scene.replace_shape(obj.id, g.make_line((4, 2, 0), (4, 12, 0)))

    anchor, after = gb.anchor_and_axes()

    assert vp.scene.revision > old_revision
    assert abs(after[0][1]) == pytest.approx(1, abs=1e-6)
    assert not np.allclose(before, after)
    assert anchor == pytest.approx((4, 7, 0), abs=1e-6)


def test_object_axes_follow_selection_changes_without_a_scene_revision():
    gb, vp, first = _whole(g.make_line((0, 0, 0), (6, 8, 0)))
    second = vp.scene.add(g.make_line((4, 2, 0), (4, 12, 0)))
    _, before = gb.anchor_and_axes()
    revision = vp.scene.revision
    vp.selection.set([second.id])

    anchor, after = gb.anchor_and_axes()

    assert vp.scene.revision == revision
    assert abs(after[0][1]) == pytest.approx(1, abs=1e-6)
    assert not np.allclose(before, after)
    assert anchor == pytest.approx((4, 7, 0), abs=1e-6)
    vp.selection.set([first.id])
    _assert_axes(gb, before)


def test_planar_curve_axes_follow_cplane_changes_without_geometry_edits():
    gb, vp, _ = _whole(g.make_circle((0, 0, 0), 5))
    anchor, _ = gb.anchor_and_axes()
    revision = vp.scene.revision
    vp.cplane = CPlane(normal=(0, 0, -1), xdir=(0, 1, 0))

    _assert_axes(gb, _cp_axes(vp.cplane))
    assert vp.scene.revision == revision
    assert gb.anchor_and_axes()[0] == pytest.approx(anchor, abs=1e-6)


def test_straight_curve_perpendicular_axes_follow_cplane_changes():
    gb, vp, _ = _whole(g.make_line((0, 0, 0), (6, 8, 0)))
    anchor, before = gb.anchor_and_axes()
    revision = vp.scene.revision
    vp.cplane = CPlane(normal=(0, 1, 0), xdir=(1, 0, 0))

    after_anchor, after = gb.anchor_and_axes()

    assert abs(np.dot(after[0], (.6, .8, 0))) == pytest.approx(1, abs=1e-6)
    assert after[2] == pytest.approx((-.8, .6, 0), abs=1e-6)
    assert not np.allclose(before, after)
    assert vp.scene.revision == revision
    assert after_anchor == pytest.approx(anchor, abs=1e-6)
