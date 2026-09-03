"""A held face or edge gets the gumball it deserves.

Asked for by a user: Ctrl+Shift-click a face and the gumball shrank to one
arrow, which was fine for a moment and then not, because everything else a
gumball does (tilt it, grow it) meant leaving the face and typing. So a
held planar face now gets the arrow, two rings and the filled box, and a
held edge keeps its fillet arrow and gains an arrow along each face it
sits between, which moves the edge the way Rhino's MoveEdge does.

Two ideas a plain solid modeller keeps apart, and this gumball keeps apart
too: *moving* a face lets the faces beside it stretch to meet it (a chamfer
stays a chamfer), *extruding* a face adds new walls. The arrow does the
first, the box on the arrow does the second.
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

CTRL = Qt.KeyboardModifier.ControlModifier
NONE = Qt.KeyboardModifier.NoModifier


# --- fixtures -------------------------------------------------------------

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


def _edge_at(shape, x=None, y=None, z=None):
    """Index of the edge whose midpoint sits at the given coordinates."""
    for i, e in enumerate(g.edges_of(shape)):
        c = g.centroid(e)
        if all(want is None or abs(have - want) < 1e-6
               for have, want in zip(c, (x, y, z))):
            return i
    raise KeyError("no edge there")


def _chamfered_box():
    """A 10-box with its top-front edge (x=10, z=10) chamfered 3."""
    box = g.make_box((0, 0, 0), 10, 10, 10)
    e = _edge_at(box, x=10, z=10)
    return g.fillet_edges(box, 3.0, edges=[g.edges_of(box)[e]], chamfer=True)


class _Cam:
    """Looking along -Y, so a +Z or +X handle is never end-on to the ray."""

    def ray_through(self, px, py, w, h):
        return np.array([px, 100.0, py]), np.array([0.0, -1.0, 0.0])

    def project(self, pts, w, h):
        pts = np.asarray(pts, float)
        out = np.zeros((len(pts), 3))
        out[:, 0] = pts[:, 0]
        out[:, 1] = pts[:, 2]
        out[:, 2] = 1.0
        return out

    def right_up(self):
        return np.array([1.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0])


class _Cfg:
    def get(self, *a, default=None, **k):
        return default if default is not None else True


class _VP:
    def __init__(self, scene, sel):
        self.scene = scene
        self.selection = sel
        self.config = _Cfg()
        self.space = "model"
        self.point_mode = False
        self.cplane = CPlane((0, 0, 0), (0, 0, 1))
        self.camera = _Cam()
        self.grid_snap = False
        self.grid_snap_step = 0.0
        self.checkpoints = []

    def width(self):
        return 800

    def height(self):
        return 600

    def _detail_eye(self):
        return None

    def _eye(self):
        return self.camera

    def window_checkpoint(self, label):
        self.checkpoints.append(label)

    def window_discard_checkpoint(self):
        self.checkpoints.pop()


def _ring_facing_the_view(gb):
    """Which ring the fake camera can turn: the one whose axis runs along
    the view ray, so its plane faces you. On a cube the long-edge rule has
    no preference and either axis may come first."""
    _, (t1, _, _) = gb.anchor_and_axes()
    return 0 if abs(t1[1]) > 0.9 else 1


def _holding(shape, kind, index):
    """A gumball standing on one held sub-object of `shape`."""
    scene = Scene()
    obj = scene.add(shape)
    sel = SelectionManager(scene)
    sel.toggle_subobject(obj.id, kind, index)
    vp = _VP(scene, sel)
    return Gumball(vp), vp, obj


# --- tilting a face (geometry) ---------------------------------------------

def test_a_tilted_face_takes_its_neighbours_with_it():
    box = g.make_box((0, 0, 0), 10, 10, 10)
    top = _face_where(box, lambda n: n[2] > 0.9)

    out = g.tilt_face(box, top, (5, 5, 10), (1, 0, 0), 10)

    tilted = [n for n in _normals(out) if n is not None and n[2] > 0.9]
    assert len(tilted) == 1
    assert abs(tilted[0][2]) == pytest.approx(np.cos(np.radians(10)), abs=1e-3)
    assert len(g.faces_of(out)) == 6
    # about its own centre, so what comes up one side goes down the other
    assert g.volume(out) == pytest.approx(1000.0, abs=1e-3)


def test_tilting_about_a_far_edge_lifts_the_near_one():
    """The hinge is wherever you say: rotate the top about its back edge
    and the front face grows to meet it."""
    box = g.make_box((0, 0, 0), 10, 10, 10)
    top = _face_where(box, lambda n: n[2] > 0.9)

    out = g.tilt_face(box, top, (0, 5, 10), (0, 1, 0), -20)

    front = g.faces_of(out)[_face_where(out, lambda n: n[0] > 0.9)]
    lift = 10 * np.tan(np.radians(20))
    assert g.bbox(front)[1][2] == pytest.approx(10 + lift, abs=1e-3)


def test_a_tilt_beside_a_chamfer_keeps_the_chamfer():
    cham = _chamfered_box()
    top = _face_where(cham, lambda n: n[2] > 0.99)

    out = g.tilt_face(cham, top, tuple(g.centroid(g.faces_of(cham)[top])),
                      (0, 1, 0), 10)

    assert len(g.faces_of(out)) == 7
    assert any(n is not None and abs(n[0] - n[2]) < 1e-3 and n[0] > 0.5
               for n in _normals(out)), "the 45 degree face is still there"


def test_a_curved_face_cannot_be_tilted():
    cyl = g.make_cylinder((0, 0, 0), 5, 10)
    wall = next(i for i, n in enumerate(_normals(cyl)) if n is None)

    with pytest.raises(g.GeometryError):
        g.tilt_face(cyl, wall, (5, 0, 5), (0, 0, 1), 10)


def test_turning_a_face_about_its_own_normal_is_refused():
    """A plane spun about its normal is the same plane. Better to say so
    than to hand back the solid untouched and let the drag look broken."""
    box = g.make_box((0, 0, 0), 10, 10, 10)
    top = _face_where(box, lambda n: n[2] > 0.9)

    with pytest.raises(g.GeometryError):
        g.tilt_face(box, top, (5, 5, 10), (0, 0, 1), 10)


# --- moving an edge (geometry) ---------------------------------------------

def test_an_edge_sits_between_two_faces():
    box = g.make_box((0, 0, 0), 10, 10, 10)
    e = _edge_at(box, x=10, z=10)

    faces = g.edge_faces(box, e)

    normals = sorted(tuple(np.round(_normals(box)[i], 6)) for i in faces)
    assert normals == [(0.0, 0.0, 1.0), (1.0, 0.0, 0.0)]


def test_a_moved_edge_tilts_only_the_face_it_leaves():
    """Lift the top-front edge straight up: the top tilts about its back
    edge, the front just gets taller."""
    box = g.make_box((0, 0, 0), 10, 10, 10)
    e = _edge_at(box, x=10, z=10)

    out = g.move_edge(box, e, (0, 0, 3))

    assert g.volume(out) == pytest.approx(1000 + 0.5 * 10 * 3 * 10, abs=1e-3)
    front = g.faces_of(out)[_face_where(out, lambda n: n[0] > 0.999)]
    assert g.bbox(front)[1][2] == pytest.approx(13.0, abs=1e-6)
    top = _normals(out)[_face_where(out, lambda n: n[2] > 0.9)]
    assert top[0] == pytest.approx(-3 / np.hypot(10, 3), abs=1e-6)


def test_a_moved_edge_lands_where_it_was_sent():
    """Sideways and up at once: both faces tilt, and they still meet on
    the line you asked for."""
    box = g.make_box((0, 0, 0), 10, 10, 10)
    e = _edge_at(box, x=10, z=10)

    out = g.move_edge(box, e, (2, 0, 3))

    _edge_at(out, x=12, y=5, z=13)          # raises if it is not there
    assert len(g.faces_of(out)) == 6
    assert _face_where(out, lambda n: 0 < n[0] < 0.999 and n[2] < 0)
    assert _face_where(out, lambda n: n[0] < 0 and n[2] > 0.9)


def test_moving_an_edge_along_itself_changes_nothing():
    box = g.make_box((0, 0, 0), 10, 10, 10)
    e = _edge_at(box, x=10, z=10)

    with pytest.raises(g.GeometryError):
        g.move_edge(box, e, (0, 4, 0))


def test_a_curved_edge_cannot_be_moved():
    cyl = g.make_cylinder((0, 0, 0), 5, 10)
    rim = next(i for i, ed in enumerate(g.edges_of(cyl))
               if abs(g.centroid(ed)[2] - 10) < 1e-6)

    with pytest.raises(g.GeometryError):
        g.move_edge(cyl, rim, (0, 0, 3))


# --- what a held face offers ------------------------------------------------

def test_a_held_flat_face_offers_move_tilt_and_extrude():
    box = g.make_box((0, 0, 0), 10, 10, 10)
    gb, _, _ = _holding(box, "face", _face_where(box, lambda n: n[2] > 0.9))

    assert gb.handles() == {("move", 2), ("rot", 0), ("rot", 1), ("ext", 2)}


def test_a_held_curved_face_only_offsets():
    cyl = g.make_cylinder((0, 0, 0), 5, 10)
    wall = next(i for i, n in enumerate(_normals(cyl)) if n is None)
    gb, _, _ = _holding(cyl, "face", wall)

    assert gb.handles() == {("move", 2)}


def test_the_rings_sit_square_to_the_longest_edge():
    """A ring about an arbitrary in-plane direction tilts a box top into
    something no one asked for. Along its long edge it tilts the lid."""
    slab = g.make_box((0, 0, 0), 20, 10, 5)
    gb, _, _ = _holding(slab, "face", _face_where(slab, lambda n: n[2] > 0.9))

    _, (t1, t2, n) = gb.anchor_and_axes()

    assert abs(t1[0]) == pytest.approx(1.0, abs=1e-6)
    assert abs(t2[1]) == pytest.approx(1.0, abs=1e-6)
    assert n[2] == pytest.approx(1.0, abs=1e-6)


def test_the_arrow_moves_the_face_and_the_chamfer_follows():
    cham = _chamfered_box()
    gb, vp, obj = _holding(cham, "face",
                           _face_where(cham, lambda n: n[2] > 0.99))

    assert gb.begin_drag(("move", 2), 5.0, 10.0, NONE)
    gb.apply_scalar(4.0)

    out = vp.scene.get(obj.id).shape
    assert len(g.faces_of(out)) == 7, "no new walls: the chamfer stretched"
    assert g.volume(out) == pytest.approx(1155.0, abs=1e-3)


def test_the_box_extrudes_the_face_instead():
    cham = _chamfered_box()
    gb, vp, obj = _holding(cham, "face",
                           _face_where(cham, lambda n: n[2] > 0.99))

    assert gb.begin_drag(("ext", 2), 5.0, 10.0, NONE)
    gb.apply_scalar(4.0)

    out = vp.scene.get(obj.id).shape
    assert len(g.faces_of(out)) == 11, "new walls stand on the old outline"
    assert g.volume(out) == pytest.approx(1235.0, abs=1e-3)


def test_ctrl_and_the_arrow_extrude_too():
    """The same shortcut the rest of the gumball has, for a hand that
    already knows it from Rhino."""
    cham = _chamfered_box()
    gb, vp, obj = _holding(cham, "face",
                           _face_where(cham, lambda n: n[2] > 0.99))

    assert gb.begin_drag(("move", 2), 5.0, 10.0, CTRL)
    gb.apply_scalar(4.0)

    assert len(g.faces_of(vp.scene.get(obj.id).shape)) == 11


def test_carving_with_the_arrow_still_works():
    box = g.make_box((0, 0, 0), 10, 10, 10)
    gb, vp, obj = _holding(box, "face", _face_where(box, lambda n: n[2] > 0.9))

    gb.begin_drag(("move", 2), 5.0, 10.0, NONE)
    gb.apply_scalar(-3.0)

    out = vp.scene.get(obj.id).shape
    assert g.volume(out) == pytest.approx(700.0, abs=1e-3)


def test_a_ring_tilts_the_face():
    box = g.make_box((0, 0, 0), 10, 10, 10)
    top = _face_where(box, lambda n: n[2] > 0.9)
    gb, vp, obj = _holding(box, "face", top)

    assert gb.begin_drag(("rot", _ring_facing_the_view(gb)), 9.0, 13.0, NONE)
    label = gb.apply_scalar(10.0)

    out = vp.scene.get(obj.id).shape
    assert "tilt" in label
    assert g.volume(out) == pytest.approx(1000.0, abs=1e-3)
    n = _normals(out)[_face_where(out, lambda n: n[2] > 0.9)]
    assert n[2] == pytest.approx(np.cos(np.radians(10)), abs=1e-3)


def test_a_tilt_back_to_zero_is_the_face_you_started_with():
    box = g.make_box((0, 0, 0), 10, 10, 10)
    gb, vp, obj = _holding(box, "face", _face_where(box, lambda n: n[2] > 0.9))
    assert gb.begin_drag(("rot", _ring_facing_the_view(gb)), 9.0, 13.0, NONE)
    gb.apply_scalar(25.0)
    tilted = _normals(vp.scene.get(obj.id).shape)
    assert not any(x is not None and x[2] > 0.999999 for x in tilted)

    gb.apply_scalar(0.0)

    n = _normals(vp.scene.get(obj.id).shape)
    assert any(x is not None and x[2] > 0.999999 for x in n)


def test_the_gumball_stays_on_the_face_it_tilted():
    """The tilt rebuilds the solid and the face index goes stale, so after
    the drag the held face has to be found again or a second drag would
    tilt some other face."""
    box = g.make_box((0, 0, 0), 10, 10, 10)
    gb, vp, obj = _holding(box, "face", _face_where(box, lambda n: n[2] > 0.9))
    assert gb.begin_drag(("rot", _ring_facing_the_view(gb)), 9.0, 13.0, NONE)
    gb.apply_scalar(15.0)

    gb.end_drag()

    tgt = gb._pushpull_target()
    assert tgt is not None
    _, fidx, _, (_, _, n), _ = tgt
    assert n[2] == pytest.approx(np.cos(np.radians(15)), abs=1e-3)
    assert (obj.id, "face", fidx) in vp.selection.subobjects


def test_a_tilt_too_far_keeps_the_last_good_face():
    box = g.make_box((0, 0, 0), 10, 10, 10)
    gb, vp, obj = _holding(box, "face", _face_where(box, lambda n: n[2] > 0.9))
    assert gb.begin_drag(("rot", _ring_facing_the_view(gb)), 9.0, 13.0, NONE)
    gb.apply_scalar(10.0)
    good = g.volume(vp.scene.get(obj.id).shape)
    assert good == pytest.approx(1000.0, abs=1e-3)

    gb.apply_scalar(89.9)                  # the plane cuts the box in half

    out = vp.scene.get(obj.id).shape
    assert g.volume(out) == pytest.approx(good, abs=1e-3)


# --- what a held edge offers ------------------------------------------------

def test_a_held_edge_offers_a_move_along_each_face():
    box = g.make_box((0, 0, 0), 10, 10, 10)
    gb, _, _ = _holding(box, "edge", _edge_at(box, x=10, z=10))

    assert gb.handles() == {("move", 0), ("move", 1), ("move", 2), ("ext", 2)}
    _, (a, b, out) = gb.anchor_and_axes()
    got = sorted(tuple(np.round(v, 6)) for v in (a, b))
    assert got == [(0.0, 0.0, 1.0), (1.0, 0.0, 0.0)]


def test_several_edges_still_only_fillet():
    box = g.make_box((0, 0, 0), 10, 10, 10)
    gb, vp, obj = _holding(box, "edge", _edge_at(box, x=10, z=10))
    vp.selection.toggle_subobject(obj.id, "edge", _edge_at(box, x=0, z=10))

    assert gb.handles() == {("move", 2), ("ext", 2)}


def test_a_round_edge_still_only_fillets():
    cyl = g.make_cylinder((0, 0, 0), 5, 10)
    rim = next(i for i, ed in enumerate(g.edges_of(cyl))
               if abs(g.centroid(ed)[2] - 10) < 1e-6)
    gb, _, _ = _holding(cyl, "edge", rim)

    assert gb.handles() == {("move", 2), ("ext", 2)}


def test_dragging_an_edge_along_a_face_moves_it():
    box = g.make_box((0, 0, 0), 10, 10, 10)
    gb, vp, obj = _holding(box, "edge", _edge_at(box, x=10, z=10))
    _, (a, _, _) = gb.anchor_and_axes()
    up = 0 if a[2] > 0.9 else 1            # whichever arrow points +Z

    assert gb.begin_drag(("move", up), 10.0, 10.0, NONE)
    label = gb.apply_scalar(3.0)

    assert "edge" in label
    out = vp.scene.get(obj.id).shape
    assert g.volume(out) == pytest.approx(1150.0, abs=1e-3)


def test_the_gumball_stays_on_the_edge_it_moved():
    box = g.make_box((0, 0, 0), 10, 10, 10)
    gb, vp, obj = _holding(box, "edge", _edge_at(box, x=10, z=10))
    _, (a, _, _) = gb.anchor_and_axes()
    up = 0 if a[2] > 0.9 else 1
    gb.begin_drag(("move", up), 10.0, 10.0, NONE)
    gb.apply_scalar(3.0)

    gb.end_drag()

    held = [e for e in vp.selection.subobjects if e[1] == "edge"]
    assert len(held) == 1
    edge = g.edges_of(vp.scene.get(obj.id).shape)[held[0][2]]
    assert np.asarray(g.centroid(edge)) == pytest.approx((10, 5, 13), abs=1e-6)


def test_the_fillet_arrow_is_untouched():
    box = g.make_box((0, 0, 0), 10, 10, 10)
    gb, vp, obj = _holding(box, "edge", _edge_at(box, x=10, z=10))

    assert gb.begin_drag(("move", 2), 10.0, 10.0, NONE)
    assert gb.drag["fillet"] == (obj.id, [_edge_at(box, x=10, z=10)])
    gb.apply_scalar(2.0)

    assert g.volume(vp.scene.get(obj.id).shape) < 1000.0
