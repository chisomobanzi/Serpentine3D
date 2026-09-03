"""The held-face gumball, second pass: every handle it shows does something.

The in-plane arrows and pads slide the face and the box shears; the scale
boxes taper it; the rings tilt it; the arrow along the normal moves it and
its box extrudes it. Nothing on it is inert, and nothing that would be
inert is drawn. The edge gumball is untouched.
"""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import Qt

from serpentine3d.core import geometry as g
from tests.test_a_held_face_or_edge_gets_a_whole_gumball import (
    _edge_at, _face_where, _holding, _normals)

NONE = Qt.KeyboardModifier.NoModifier
EVERY = {("move", 0), ("move", 1), ("move", 2),
         ("pad", 0), ("pad", 1), ("pad", 2),
         ("rot", 0), ("rot", 1),
         ("scale", 0), ("scale", 1), ("ext", 2)}


def _slab_gumball():
    """A gumball on the top of a 20 x 10 x 10 box, plus which in-plane axis
    runs along X (the fake camera looks along -Y, so that is the one whose
    line a press can be measured on)."""
    box = g.make_box((0, 0, 0), 20, 10, 10)
    gb, vp, obj = _holding(box, "face", _face_where(box, lambda n: n[2] > 0.9))
    _, axes = gb.anchor_and_axes()
    along_x = next(i for i in (0, 1) if abs(axes[i][0]) > 0.9)
    return gb, vp, obj, along_x


def test_a_held_flat_face_offers_every_handle_that_does_something():
    gb, _, _, _ = _slab_gumball()

    assert gb.handles() == EVERY


def test_a_curved_face_still_only_offsets():
    cyl = g.make_cylinder((0, 0, 0), 5, 10)
    wall = next(i for i, n in enumerate(_normals(cyl)) if n is None)
    gb, _, _ = _holding(cyl, "face", wall)

    assert gb.handles() == {("move", 2)}


def test_the_edge_gumball_is_untouched():
    box = g.make_box((0, 0, 0), 10, 10, 10)
    gb, _, _ = _holding(box, "edge", _edge_at(box, x=10, z=10))

    assert gb.handles() == {("move", 0), ("move", 1), ("move", 2), ("ext", 2)}


def test_the_side_arrow_slides_the_face():
    gb, vp, obj, i = _slab_gumball()

    assert gb.begin_drag(("move", i), 15.0, 10.0, NONE)
    label = gb.apply_scalar(3.0)

    out = vp.scene.get(obj.id).shape
    assert "slide" in label
    assert g.volume(out) == pytest.approx(2000.0, abs=1e-3)
    lid = g.faces_of(out)[_face_where(out, lambda n: n[2] > 0.999)]
    assert np.asarray(g.centroid(lid)) == pytest.approx((13, 5, 10), abs=1e-6)


def test_a_slide_back_to_zero_is_the_box():
    gb, vp, obj, i = _slab_gumball()
    gb.begin_drag(("move", i), 15.0, 10.0, NONE)
    gb.apply_scalar(3.0)

    gb.apply_scalar(0.0)

    assert len(g.faces_of(vp.scene.get(obj.id).shape)) == 6
    assert all(n is None or abs(abs(n).max() - 1) < 1e-9
               for n in _normals(vp.scene.get(obj.id).shape))


def test_the_scale_box_tapers_the_face_along_its_axis():
    gb, vp, obj, i = _slab_gumball()

    assert gb.begin_drag(("scale", i), 15.0, 10.0, NONE)
    label = gb.apply_scalar(0.5)

    assert "scale face" in label
    assert g.volume(vp.scene.get(obj.id).shape) == pytest.approx(1500.0,
                                                                  abs=1e-3)


def test_shift_tapers_the_face_every_way():
    gb, vp, obj, i = _slab_gumball()
    gb.begin_drag(("scale", i), 15.0, 10.0, NONE)

    gb.apply_scalar(0.5, uniform=True)

    assert g.volume(vp.scene.get(obj.id).shape) == pytest.approx(
        10 / 3 * (200 + 50 + 100), abs=1e-3)


def test_the_pad_slides_the_face_and_can_lift_it_at_once():
    """A pad drag is a vector. Its part along the normal moves the face
    (the old walls stretch), its part in the plane slides it (they
    lean), and the two are done in that order."""
    gb, vp, obj, i = _slab_gumball()
    _, axes = gb.anchor_and_axes()
    flat = next(j for j in (0, 1) if abs(axes[j][1]) > 0.9)   # the y=5 plane

    assert gb.begin_drag(("pad", flat), 10.0, 10.0, NONE)
    gb.drag_to(13.0, 10.0, NONE)
    assert g.volume(vp.scene.get(obj.id).shape) == pytest.approx(2000.0,
                                                                  abs=1e-3)

    label = gb.drag_to(13.0, 12.0, NONE)

    out = vp.scene.get(obj.id).shape
    assert "slide" in label
    assert g.volume(out) == pytest.approx(2400.0, abs=1e-3)
    lid = g.faces_of(out)[_face_where(out, lambda n: n[2] > 0.999)]
    assert np.asarray(g.centroid(lid)) == pytest.approx((13, 5, 12), abs=1e-6)


def test_the_gumball_stays_on_the_slid_face():
    gb, vp, obj, i = _slab_gumball()
    gb.begin_drag(("move", i), 15.0, 10.0, NONE)
    gb.apply_scalar(3.0)

    gb.end_drag()

    tgt = gb._pushpull_target()
    assert tgt is not None
    _, fidx, centroid, _, _ = tgt
    assert centroid == pytest.approx((13, 5, 10), abs=1e-6)
    assert (obj.id, "face", fidx) in vp.selection.subobjects


def test_the_gumball_stays_on_the_tapered_face():
    gb, vp, obj, i = _slab_gumball()
    gb.begin_drag(("scale", i), 15.0, 10.0, NONE)
    gb.apply_scalar(0.5, uniform=True)

    gb.end_drag()

    tgt = gb._pushpull_target()
    assert tgt is not None and tgt[3][2][2] == pytest.approx(1.0, abs=1e-6)
    lo, hi = g.bbox(g.faces_of(vp.scene.get(obj.id).shape)[tgt[1]])
    assert hi[0] - lo[0] == pytest.approx(10.0, abs=1e-6)


def test_ctrl_only_grows_along_the_normal():
    """Ctrl on a side arrow is still a slide: there is nothing for the
    face to grow sideways into."""
    gb, vp, obj, i = _slab_gumball()

    assert gb.begin_drag(("move", i), 15.0, 10.0,
                         Qt.KeyboardModifier.ControlModifier)
    gb.apply_scalar(3.0)

    assert g.volume(vp.scene.get(obj.id).shape) == pytest.approx(2000.0,
                                                                  abs=1e-3)
