"""The gumball can be aligned to the world, the CPlane or the object.

A small tag on a leader off the gumball opens a menu with the three.
Whole objects follow the CPlane unless told otherwise, as they always
have; a held face or edge follows itself. "Object" for a whole object
means the CPlane, because a solid has no frame of its own to offer.

Under world or CPlane axes a held face still does everything it did in
its own frame: an arrow along a leaning axis lifts the face by the part
of the drag along its normal and slides it by the rest, a ring tilts it
about the axis laid into its plane, a scale box tapers it along that
same line, and the box that extrudes only appears on an axis that runs
straight out of the face. The colours say which axis is which in every
frame: red is X, green is Y and blue is Z.
"""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import Qt

from serpentine3d.core import geometry as g
from serpentine3d.core.cplane import CPlane
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui.gumball import Gumball
from tests.test_a_held_face_or_edge_gets_a_whole_gumball import (
    _VP, _edge_at, _face_where, _holding)

NONE = Qt.KeyboardModifier.NoModifier
TILTED = CPlane((0, 0, 0), normal=(0, 1, 0), xdir=(1, 0, 0))   # y is up


def _whole(shape, cplane=None):
    scene = Scene()
    obj = scene.add(shape)
    sel = SelectionManager(scene)
    sel.set([obj.id])
    vp = _VP(scene, sel)
    if cplane is not None:
        vp.cplane = cplane
    return Gumball(vp), vp, obj


def _axes(gb):
    _, axes = gb.anchor_and_axes()
    return [tuple(np.round(a, 6)) for a in axes]


# --- what the axes follow ---------------------------------------------------

def test_a_whole_object_follows_the_cplane_by_default():
    gb, _, _ = _whole(g.make_box((0, 0, 0), 10, 10, 10), TILTED)

    assert gb.align == "object"
    assert _axes(gb) == [(1, 0, 0), (0, 0, -1), (0, 1, 0)]


def test_a_whole_object_can_take_world_axes():
    gb, _, _ = _whole(g.make_box((0, 0, 0), 10, 10, 10), TILTED)

    gb.set_align("world")

    assert _axes(gb) == [(1, 0, 0), (0, 1, 0), (0, 0, 1)]


def test_a_held_face_keeps_its_own_frame_by_default():
    box = g.make_box((0, 0, 0), 20, 10, 10)
    gb, vp, _ = _holding(box, "face", _face_where(box, lambda n: n[2] > 0.9))
    vp.cplane = TILTED

    assert _axes(gb)[2] == (0, 0, 1)


def test_a_held_face_can_take_the_cplane():
    box = g.make_box((0, 0, 0), 20, 10, 10)
    gb, vp, _ = _holding(box, "face", _face_where(box, lambda n: n[2] > 0.9))
    vp.cplane = TILTED

    gb.set_align("cplane")

    assert _axes(gb) == [(1, 0, 0), (0, 0, -1), (0, 1, 0)]


def test_a_held_edge_always_keeps_its_own_frame():
    """The arrows on an edge run along the faces it sits between; there is
    no world version of that worth having."""
    box = g.make_box((0, 0, 0), 10, 10, 10)
    gb, _, _ = _holding(box, "edge", _edge_at(box, x=10, z=10))

    gb.set_align("world")

    assert sorted(_axes(gb)[:2]) == [(0, 0, 1), (1, 0, 0)]


def test_a_held_face_uses_xyz_colours_in_every_alignment():
    box = g.make_box((0, 0, 0), 20, 10, 10)
    gb, _, _ = _holding(box, "face", _face_where(box, lambda n: n[2] > 0.9))
    from serpentine3d.ui.gumball import AXIS_COLORS

    for alignment in ("object", "world", "cplane"):
        gb.set_align(alignment)
        assert gb._axis_colours() == AXIS_COLORS


# --- a held face under foreign axes ------------------------------------------

def test_a_box_top_under_world_axes_offers_the_same_handles():
    box = g.make_box((0, 0, 0), 20, 10, 10)
    gb, _, _ = _holding(box, "face", _face_where(box, lambda n: n[2] > 0.9))

    gb.set_align("world")

    assert gb.handles() == {
        ("move", 0), ("move", 1), ("move", 2),
        ("pad", 0), ("pad", 1), ("pad", 2),
        ("rot", 0), ("rot", 1), ("scale", 0), ("scale", 1), ("ext", 2)}
    assert gb._two_way_axes() == {2}


def test_a_leaning_face_under_world_axes_has_no_axis_to_extrude_along():
    box = g.make_box((0, 0, 0), 20, 10, 10)
    top = _face_where(box, lambda n: n[2] > 0.9)
    wedge = g.tilt_face(box, top, (10, 5, 10), (0, 1, 0), 30)
    gb, _, _ = _holding(wedge, "face",
                        _face_where(wedge, lambda n: 0.5 < n[2] < 0.95))

    gb.set_align("world")

    on = gb.handles()
    assert not any(k == "ext" for k, _ in on)
    assert gb._two_way_axes() == set()
    assert {("rot", 0), ("rot", 1), ("rot", 2)} <= on
    assert {("scale", 0), ("scale", 1), ("scale", 2)} <= on


def test_a_world_arrow_that_leans_lifts_and_slides():
    """Dragging a leaning face 3 along world X moves that rigid face by 3;
    its neighbours rebuild to meet the translated boundary."""
    box = g.make_box((0, 0, 0), 20, 10, 10)
    top = _face_where(box, lambda n: n[2] > 0.9)
    wedge = g.tilt_face(box, top, (10, 5, 10), (0, 1, 0), 30)
    lid_index = _face_where(wedge, lambda n: 0.5 < n[2] < 0.95)
    lid_before = g.faces_of(wedge)[lid_index]
    before_x = np.asarray(g.centroid(lid_before))[0]
    before_area = g.surface_area(lid_before)
    gb, vp, obj = _holding(wedge, "face", lid_index)
    gb.set_align("world")
    before = g.volume(wedge)

    assert gb.begin_drag(("move", 0), 15.0, 10.0, NONE)
    label = gb.apply_scalar(3.0)

    out = vp.scene.get(obj.id).shape
    assert "face" in label
    assert g.volume(out) != pytest.approx(before, abs=1.0)
    lid = g.faces_of(out)[_face_where(out, lambda n: 0.5 < n[2] < 0.95)]
    assert np.asarray(g.centroid(lid))[0] == pytest.approx(before_x + 3.0,
                                                           abs=1e-3)
    assert g.surface_area(lid) == pytest.approx(before_area, abs=1e-6)


def test_a_world_ring_tilts_about_the_axis_laid_into_the_face():
    box = g.make_box((0, 0, 0), 20, 10, 10)
    lid_index = _face_where(box, lambda n: n[2] > 0.9)
    lid_area = g.surface_area(g.faces_of(box)[lid_index])
    gb, vp, obj = _holding(box, "face", lid_index)
    gb.set_align("world")
    _, axes = gb.anchor_and_axes()
    ring = next(i for i in (0, 1) if abs(axes[i][1]) > 0.9)   # about Y

    assert gb.begin_drag(("rot", ring), 14.0, 13.0, NONE)
    gb.apply_scalar(20.0)

    out = vp.scene.get(obj.id).shape
    lid = g.faces_of(out)[_face_where(out, lambda n: 0.9 < n[2] < 0.95)]
    assert g.surface_area(lid) == pytest.approx(lid_area, abs=1e-6)
    assert g.volume(out) != pytest.approx(2000.0, abs=1.0)


# --- the tag and the menu ---------------------------------------------------

def test_the_tag_is_a_handle_that_opens_the_menu():
    gb, vp, _ = _whole(g.make_box((0, 0, 0), 10, 10, 10))
    px, py = gb._project([gb.tag_position()])[0][:2]

    assert gb.hit_test(px, py) == ("menu", 0)
    assert gb.begin_drag(("menu", 0), px, py, NONE) is True
    assert gb.drag is None


def test_the_menu_offers_the_three_and_knows_which_is_on():
    gb, _, _ = _whole(g.make_box((0, 0, 0), 10, 10, 10))

    rows = gb.menu_rows()

    assert [r[1] for r in rows] == ["object", "cplane", "world"]
    assert [r[2] for r in rows] == [True, False, False]     # object is on
    assert rows[0][3] is False, "nothing held: object is not on offer"
    gb.set_align("world")
    assert [r[2] for r in gb.menu_rows()] == [False, False, True]


def test_object_is_on_offer_when_a_face_is_held():
    box = g.make_box((0, 0, 0), 20, 10, 10)
    gb, _, _ = _holding(box, "face", _face_where(box, lambda n: n[2] > 0.9))

    assert gb.menu_rows()[0][3] is True


def test_the_choice_is_remembered(tmp_path):
    from serpentine3d.utils.config import Config
    scene = Scene()
    obj = scene.add(g.make_box((0, 0, 0), 10, 10, 10))
    sel = SelectionManager(scene)
    sel.set([obj.id])
    vp = _VP(scene, sel)
    vp.config = Config(str(tmp_path / "config.json"))
    Gumball(vp).set_align("world")

    assert Gumball(vp).align == "world"
    saved = Config(str(tmp_path / "config.json")).get("gumball", "align")
    assert saved == "world"


def test_a_nonsense_alignment_is_refused():
    gb, _, _ = _whole(g.make_box((0, 0, 0), 10, 10, 10))

    with pytest.raises(ValueError):
        gb.set_align("sideways")
