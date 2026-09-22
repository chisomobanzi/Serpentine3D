"""The gumball moves faces and edges held together (issue #30, follow-up).

A Ctrl+Shift band across a solid holds several faces and the edges
between them, which a click never did, and the gumball had nothing to
offer that: one face is a push/pull handle, two or more are an inflate
handle, edges are a fillet handle, and several faces with edges was none
of those, so no gumball at all.

Two or more faces held with edges on one solid now get a whole gumball
whose three arrows move them as one change, through geometry.move_parts,
so a band across a box drags what it caught up once. Rings and scale
boxes are not offered, since turning a set of parts as one is not
something the geometry can do yet. The click's own modes are untouched:
one face still pushes, whatever edges ride along with it; two faces on
their own still inflate; edges on their own still fillet.
"""

from __future__ import annotations

import numpy as np
import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.cplane import CPlane
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui.gumball import Gumball


class _Cam:
    def ray_through(self, px, py, w, h):
        return np.array([px, 100.0, py]), np.array([0.0, -1.0, 0.0])

    def project(self, pts, w, h):
        pts = np.asarray(pts, float)
        out = np.zeros((len(pts), 3))
        out[:, 0] = pts[:, 0]
        out[:, 1] = pts[:, 1]
        out[:, 2] = 1.0
        return out

    def right_up(self):
        return np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0])


class _Cfg:
    def get(self, *a, default=None, **k):
        return default if default is not None else True


class _VP:
    def __init__(self, scene, selection):
        self.scene = scene
        self.selection = selection
        self.config = _Cfg()
        self.space = "model"
        self.point_mode = False
        self.cplane = CPlane((0, 0, 0), (0, 0, 1))
        self.camera = _Cam()
        self.grid_snap = False
        self.grid_snap_step = 0.0
        self._checkpoints = []

    def width(self):
        return 800

    def height(self):
        return 600

    def _detail_eye(self):
        return None

    def _eye(self):
        return self.camera

    def window_checkpoint(self, label):
        self._checkpoints.append(label)


def _box_scene():
    scene = Scene()
    obj = scene.add(g.make_box((0, 0, 0), 10, 10, 10))
    return scene, SelectionManager(scene), obj


def _top(shape):
    return next(i for i, f in enumerate(g.faces_of(shape))
                if g.face_normal(f)[2] > 0.9)


def _sides(shape):
    return [i for i, f in enumerate(g.faces_of(shape))
            if abs(g.face_normal(f)[2]) < 0.1]


def _uprights(shape):
    return [i for i, e in enumerate(g.edges_of(shape))
            if g.centroid(e)[2] == 5]


def _top_rim(shape):
    return [i for i, e in enumerate(g.edges_of(shape))
            if g.centroid(e)[2] == 10 and 5 in g.centroid(e)[:2]]


def _size(shape):
    lo, hi = g.bbox(shape)
    return tuple(round(hi[i] - lo[i], 6) for i in range(3))


def _hold_a_band_across(sel, obj):
    """What a crossing band across the middle of a box holds: the four
    sides and the four upright edges between them."""
    for i in _sides(obj.shape):
        sel.toggle_subobject(obj.id, "face", i)
    for i in _uprights(obj.shape):
        sel.toggle_subobject(obj.id, "edge", i)


# --- several faces with edges get a gumball ---------------------------------

def test_faces_and_edges_held_together_stand_a_gumball():
    scene, sel, obj = _box_scene()
    gb = Gumball(_VP(scene, sel))
    _hold_a_band_across(sel, obj)

    assert gb.active() is True
    assert gb._parts_target() is not None
    assert gb._multiface_target() is None, "not the inflate handle"
    assert gb._fillet_target() is None, "not the fillet handle"


def test_it_offers_the_three_arrows_and_nothing_else():
    scene, sel, obj = _box_scene()
    gb = Gumball(_VP(scene, sel))
    _hold_a_band_across(sel, obj)

    assert gb.handles() == {("move", 0), ("move", 1), ("move", 2)}


def test_it_stands_on_the_parts_along_the_plane_axes():
    scene, sel, obj = _box_scene()
    gb = Gumball(_VP(scene, sel))
    _hold_a_band_across(sel, obj)

    anchor, axes = gb.anchor_and_axes()

    assert anchor == pytest.approx((5.0, 5.0, 5.0))
    assert axes[2] == pytest.approx((0, 0, 1))


# --- dragging moves them as one change --------------------------------------

def test_dragging_the_arrow_moves_the_parts_once():
    """Every corner of the box is on a held side, so the box moves; it
    used to be nothing at all, and moved in turn it would be garbage."""
    scene, sel, obj = _box_scene()
    gb = Gumball(_VP(scene, sel))
    _hold_a_band_across(sel, obj)

    assert gb.begin_drag(("move", 2), 5.0, 5.0, 0) is True
    assert gb.drag["parts"][0] == obj.id
    gb.apply_scalar(5.0)

    shape = scene.get(obj.id).shape
    assert _size(shape) == (10, 10, 10)
    assert g.bbox(shape)[0][2] == pytest.approx(5.0)


def test_the_drag_rebuilds_from_the_original_each_time():
    scene, sel, obj = _box_scene()
    gb = Gumball(_VP(scene, sel))
    _hold_a_band_across(sel, obj)
    gb.begin_drag(("move", 2), 5.0, 5.0, 0)

    gb.apply_scalar(3.0)
    gb.apply_scalar(5.0)

    assert g.bbox(scene.get(obj.id).shape)[0][2] == pytest.approx(5.0)


def test_a_band_round_the_whole_solid_drags_the_solid():
    scene, sel, obj = _box_scene()
    gb = Gumball(_VP(scene, sel))
    for i in range(6):
        sel.toggle_subobject(obj.id, "face", i)
    for i in range(12):
        sel.toggle_subobject(obj.id, "edge", i)

    gb.begin_drag(("move", 0), 5.0, 5.0, 0)
    gb.apply_scalar(7.0)

    shape = scene.get(obj.id).shape
    assert _size(shape) == (10, 10, 10)
    assert g.bbox(shape)[0][0] == pytest.approx(7.0)


def test_a_set_the_kernel_cannot_keep_flat_keeps_the_last_good_shape():
    """The top and the front moved sideways would bend the sides, so the
    kernel refuses; the drag keeps what was showing rather than dying."""
    scene, sel, obj = _box_scene()
    gb = Gumball(_VP(scene, sel))
    top = _top(obj.shape)
    front = next(i for i, f in enumerate(g.faces_of(obj.shape))
                 if g.face_normal(f)[1] < -0.9)
    sel.toggle_subobject(obj.id, "face", top)
    sel.toggle_subobject(obj.id, "face", front)
    sel.toggle_subobject(obj.id, "edge", _top_rim(obj.shape)[0])
    gb.begin_drag(("move", 0), 5.0, 5.0, 0)

    gb.apply_scalar(3.0)

    assert g.is_valid(scene.get(obj.id).shape)
    assert g.volume(scene.get(obj.id).shape) == pytest.approx(1000)


# --- after the drag, the parts are still held --------------------------------

def test_the_parts_are_found_again_where_the_drag_left_them():
    scene, sel, obj = _box_scene()
    gb = Gumball(_VP(scene, sel))
    _hold_a_band_across(sel, obj)
    gb.begin_drag(("move", 2), 5.0, 5.0, 0)
    gb.apply_scalar(5.0)

    gb.end_drag()

    shape = scene.get(obj.id).shape
    held_faces = [i for oid, k, i in sel.subobjects if k == "face"]
    held_edges = [i for oid, k, i in sel.subobjects if k == "edge"]
    assert len(held_faces) == 4 and len(held_edges) == 4
    assert all(abs(g.face_normal(g.faces_of(shape)[i])[2]) < 0.1
               for i in held_faces), "the four sides"
    assert all(g.centroid(g.edges_of(shape)[i])[2] == pytest.approx(10.0)
               for i in held_edges), "the uprights, now 5 higher"
    assert gb.drag is None
    assert gb._parts_target() is not None, "so a second drag carries on"


# --- the click's own modes are left alone -----------------------------------

def test_one_face_with_the_edges_round_it_is_still_the_push_pull_handle():
    """A window round a box's top holds the top and its rim; the face
    handle is the richer one and the rim rides along with the face."""
    scene, sel, obj = _box_scene()
    gb = Gumball(_VP(scene, sel))
    sel.toggle_subobject(obj.id, "face", _top(obj.shape))
    for i in _top_rim(obj.shape):
        sel.toggle_subobject(obj.id, "edge", i)

    assert gb._parts_target() is None
    assert gb._pushpull_target() is not None


def test_two_faces_alone_still_inflate():
    scene, sel, obj = _box_scene()
    gb = Gumball(_VP(scene, sel))
    sel.toggle_subobject(obj.id, "face", 0)
    sel.toggle_subobject(obj.id, "face", 1)

    assert gb._parts_target() is None
    assert gb._multiface_target() is not None


def test_edges_alone_still_fillet():
    scene, sel, obj = _box_scene()
    gb = Gumball(_VP(scene, sel))
    for i in _top_rim(obj.shape):
        sel.toggle_subobject(obj.id, "edge", i)

    assert gb._parts_target() is None
    assert gb._fillet_target() is not None


def test_parts_of_two_solids_at_once_are_not_offered():
    """One solid at a time, as every sub-object mode is."""
    scene, sel, obj = _box_scene()
    other = scene.add(g.make_box((20, 0, 0), 10, 10, 10))
    gb = Gumball(_VP(scene, sel))
    _hold_a_band_across(sel, obj)
    sel.toggle_subobject(other.id, "face", _top(other.shape))

    assert gb._parts_target() is None
