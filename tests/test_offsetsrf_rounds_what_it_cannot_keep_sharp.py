"""OffsetSrf keeps a solid's edges sharp (#139), and still offsets what it
can't keep sharp.

OpenCascade's sharp join can't carry a curved face and a flat one on until
they meet everywhere they do: an arc closed by a flat side, extruded, made
it give up, where the old rounded join offset it. Those come out rounded,
as they did, rather than not at all.
"""

import pytest

from serpentine3d.core import geometry as g


def _half_disc_prism():
    """An arc closed by one flat side, extruded 10."""
    return g.extrude(g.join_curves([
        g.make_arc_3pt((-10, 0, 0), (0, -10, 0), (10, 0, 0)),
        g.make_line((10, 0, 0), (-10, 0, 0))]), (0, 0, 1), 10, cap=True)


def _spline_prism():
    """A spline arching over a straight base, extruded 5."""
    return g.extrude(g.join_curves([
        g.make_interp_curve([(0, 0, 0), (5, 3, 0), (10, 0, 0)]),
        g.make_line((10, 0, 0), (0, 0, 0))]), (0, 0, 1), 5, cap=True)


@pytest.mark.parametrize("make", [_half_disc_prism, _spline_prism])
def test_a_curved_side_meeting_a_flat_one_still_offsets(make):
    solid = make()
    grown = g.offset_surface(solid, 1.0)
    assert g.shape_kind(grown) == "solid"
    assert g.is_valid(grown)
    assert g.volume(grown) > g.volume(solid)


def test_a_slot_keeps_its_flat_ends_sharp():
    """Lines and a tangent arc: the sharp join manages these, so the
    ends stay square, six faces, not rounded off into twenty."""
    slot = g.extrude(g.join_curves([
        g.make_line((0, 0, 0), (10, 0, 0)),
        g.make_arc_3pt((10, 0, 0), (12, 2, 0), (10, 4, 0)),
        g.make_line((10, 4, 0), (0, 4, 0)),
        g.make_line((0, 4, 0), (0, 0, 0))]), (0, 0, 1), 5, cap=True)
    assert len(g.faces_of(g.offset_surface(slot, 0.5))) == 6
