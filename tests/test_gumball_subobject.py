"""Sub-object gumball: a single selected planar face turns the gumball into
a normal-aligned push/pull handle that moves the face and rebuilds the solid.

The interactive drag (mouse math) needs a live GL viewport, so here we drive
the geometry-facing logic directly with a minimal fake viewport."""

import numpy as np
import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.cplane import CPlane
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui.gumball import Gumball


class _Cam:
    """Just enough camera for begin_drag/_size_world: an orthographic-ish
    ray straight down -Z and a trivial projection."""
    def ray_through(self, px, py, w, h):
        # look along -Y so a +Z face-normal handle isn't parallel to the ray
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

    def window_checkpoint(self, label):
        self._checkpoints.append(label)


def _box_scene():
    scene = Scene()
    obj = scene.add(g.make_box((0, 0, 0), 10, 10, 10))
    sel = SelectionManager(scene)
    # find the top face index (normal +z) in faces_of order — matches picking
    faces = g.faces_of(obj.shape)
    top = next(i for i, f in enumerate(faces) if g.face_normal(f)[2] > 0.9)
    return scene, sel, obj, top


def test_planar_face_activates_pushpull():
    scene, sel, obj, top = _box_scene()
    gb = Gumball(_VP(scene, sel))
    assert gb.active() is False              # nothing selected yet
    sel.toggle_subobject(obj.id, "face", top)
    assert gb.active() is True
    assert gb._face_mode() is True
    tgt = gb._pushpull_target()
    assert tgt is not None
    oid, fidx, centroid, (t1, t2, n), planar = tgt
    assert (oid, fidx) == (obj.id, top)
    assert planar is True
    assert n[2] == pytest.approx(1.0, abs=1e-6)     # face normal is +z
    assert centroid[2] == pytest.approx(10.0, abs=1e-6)
    # axes are an orthonormal right-handed basis with normal last
    assert np.dot(t1, n) == pytest.approx(0, abs=1e-9)
    assert np.dot(t1, t2) == pytest.approx(0, abs=1e-9)


def _is_nonplanar(face):
    try:
        g.face_normal(face)
        return False
    except g.GeometryError:
        return True


def _cyl_scene():
    scene = Scene()
    cyl = scene.add(g.make_cylinder((0, 0, 0), 5, 10))   # vol ~785.4
    sel = SelectionManager(scene)
    faces = g.faces_of(cyl.shape)
    side = next(i for i, f in enumerate(faces) if _is_nonplanar(f))
    return scene, sel, cyl, side


def test_curved_face_gets_offset_handle():
    scene, sel, cyl, side = _cyl_scene()
    sel.toggle_subobject(cyl.id, "face", side)
    gb = Gumball(_VP(scene, sel))
    assert gb.active() is True
    assert gb._face_mode() is True
    tgt = gb._pushpull_target()
    assert tgt is not None
    oid, fidx, centroid, (t1, t2, axis), planar = tgt
    assert (oid, fidx) == (cyl.id, side)
    assert planar is False                    # curved -> offset, not push/pull
    # the handle points radially outward (away from the axis at mid-height)
    assert axis[2] == pytest.approx(0.0, abs=1e-6)
    assert np.hypot(axis[0], axis[1]) == pytest.approx(1.0, abs=1e-6)


def test_offset_grows_cylinder_radius_via_gumball():
    scene, sel, cyl, side = _cyl_scene()
    sel.toggle_subobject(cyl.id, "face", side)
    gb = Gumball(_VP(scene, sel))
    assert gb.begin_drag(("move", 2), 5.0, 5.0, 0) is True
    assert gb.drag["pp"] == (cyl.id, side)
    assert gb.drag["pp_planar"] is False

    gb.apply_scalar(2.0)                       # r 5 -> 7
    assert g.volume(scene.get(cyl.id).shape) == pytest.approx(
        np.pi * 49 * 10, abs=1)
    gb.apply_scalar(-2.0)                      # r 5 -> 3, from original
    assert g.volume(scene.get(cyl.id).shape) == pytest.approx(
        np.pi * 9 * 10, abs=1)

    gb.end_drag()
    # the offset keeps the face index stable, so the handle stays put
    assert (cyl.id, "face", side) in sel.subobjects
    assert gb._pushpull_target() is not None


def test_pushpull_extrudes_and_carves_via_gumball():
    scene, sel, obj, top = _box_scene()
    sel.toggle_subobject(obj.id, "face", top)
    gb = Gumball(_VP(scene, sel))

    # begin a drag on the normal handle, then apply distances the way a
    # mouse drag / typed value would
    assert gb.begin_drag(("move", 2), 5.0, 5.0, 0) is True
    assert gb.drag["pp"] == (obj.id, top)

    gb.apply_scalar(5.0)                      # pull out 5
    assert g.volume(scene.get(obj.id).shape) == pytest.approx(1500.0, abs=1)

    gb.apply_scalar(-3.0)                     # each apply works from originals
    assert g.volume(scene.get(obj.id).shape) == pytest.approx(700.0, abs=1)

    gb.end_drag()
    assert gb.drag is None

    # push_pull rebuilt the solid (face indices shift); the selection must
    # re-point at the moved face so the gumball stays on it for the next pull
    tgt = gb._pushpull_target()
    assert tgt is not None, "gumball should stay on the moved face"
    _, fidx, centroid, (_, _, n), _ = tgt
    assert n[2] == pytest.approx(1.0, abs=1e-6)     # still the top (+z) face
    assert centroid[2] == pytest.approx(7.0, abs=0.1)   # carved down to z=7
    assert (obj.id, "face", fidx) in sel.subobjects


def test_pushpull_rejects_wrong_handle():
    scene, sel, obj, top = _box_scene()
    sel.toggle_subobject(obj.id, "face", top)
    gb = Gumball(_VP(scene, sel))
    # in face mode only the normal move handle is valid
    assert gb.begin_drag(("rot", 1), 5.0, 5.0, 0) is False
    assert gb.drag is None


# --------------------------------------------------------------- edge fillet

def test_edge_selection_activates_fillet():
    scene, sel, obj, _ = _box_scene()
    gb = Gumball(_VP(scene, sel))
    sel.toggle_subobject(obj.id, "edge", 0)
    assert gb.active() is True
    assert gb._fillet_mode() is True
    tgt = gb._fillet_target()
    assert tgt is not None
    oid, idxs, anchor, (t1, t2, out) = tgt
    assert oid == obj.id and idxs == [0]
    assert np.linalg.norm(out) == pytest.approx(1.0, abs=1e-6)
    # the handle points away from the solid centre
    solid_c = np.asarray(g.centroid(obj.shape), float)
    assert np.dot(out, anchor - solid_c) > 0


def test_fillet_via_gumball_reverts_at_zero():
    scene, sel, obj, _ = _box_scene()
    gb = Gumball(_VP(scene, sel))
    sel.toggle_subobject(obj.id, "edge", 0)
    assert gb.begin_drag(("move", 2), 5.0, 5.0, 0) is True
    assert gb.drag["fillet"] == (obj.id, [0])

    gb.apply_scalar(2.0)                       # a fillet shaves a little
    v = g.volume(scene.get(obj.id).shape)
    assert 980.0 < v < 1000.0

    gb.apply_scalar(0.0)                       # radius 0 -> original solid back
    assert g.volume(scene.get(obj.id).shape) == pytest.approx(1000.0, abs=1)


def test_fillet_multi_edge_then_selection_cleared():
    scene, sel, obj, _ = _box_scene()
    gb = Gumball(_VP(scene, sel))
    for i in (0, 2, 4):
        sel.toggle_subobject(obj.id, "edge", i)
    tgt = gb._fillet_target()
    assert tgt is not None and sorted(tgt[1]) == [0, 2, 4]

    assert gb.begin_drag(("move", 2), 5.0, 5.0, 0) is True
    gb.apply_scalar(1.5)
    assert g.volume(scene.get(obj.id).shape) < 1000.0

    gb.end_drag()
    # a committed fillet consumes the edges -> they leave the selection
    for i in (0, 2, 4):
        assert (obj.id, "edge", i) not in sel.subobjects


def test_face_push_pull_beats_edge_fillet_when_both_selected():
    scene, sel, obj, top = _box_scene()
    gb = Gumball(_VP(scene, sel))
    sel.toggle_subobject(obj.id, "edge", 0)
    sel.toggle_subobject(obj.id, "face", top)
    assert gb._face_mode() is True
    assert gb._fillet_mode() is False         # push/pull takes priority


def test_oversized_fillet_keeps_last_good_shape():
    scene, sel, obj, _ = _box_scene()
    gb = Gumball(_VP(scene, sel))
    sel.toggle_subobject(obj.id, "edge", 0)
    gb.begin_drag(("move", 2), 5.0, 5.0, 0)
    gb.apply_scalar(2.0)
    good = g.volume(scene.get(obj.id).shape)
    gb.apply_scalar(999.0)                     # too big: fillet_edges raises
    # swallowed — the scene keeps the last valid shape, no crash
    assert g.volume(scene.get(obj.id).shape) == pytest.approx(good, abs=1)


# ------------------------------------------------------------- multi-face

def _box_top_bottom():
    scene, sel, obj, top = _box_scene()
    faces = g.faces_of(obj.shape)
    bot = next(i for i, f in enumerate(faces) if g.face_normal(f)[2] < -0.9)
    return scene, sel, obj, top, bot


def test_two_faces_activate_multiface():
    scene, sel, obj, top, bot = _box_top_bottom()
    gb = Gumball(_VP(scene, sel))
    sel.toggle_subobject(obj.id, "face", top)
    sel.toggle_subobject(obj.id, "face", bot)
    assert gb.active() is True
    assert gb._face_mode() is True
    assert gb._pushpull_target() is None       # 1-face handle doesn't fire
    mf = gb._multiface_target()
    assert mf is not None
    oid, idxs, anchor, basis = mf
    assert oid == obj.id and set(idxs) == {top, bot}


def test_single_face_is_pushpull_not_multiface():
    scene, sel, obj, top = _box_scene()
    gb = Gumball(_VP(scene, sel))
    sel.toggle_subobject(obj.id, "face", top)
    assert gb._pushpull_target() is not None
    assert gb._multiface_target() is None


def test_multiface_offsets_all_faces_via_gumball():
    scene, sel, obj, top, bot = _box_top_bottom()
    gb = Gumball(_VP(scene, sel))
    sel.toggle_subobject(obj.id, "face", top)
    sel.toggle_subobject(obj.id, "face", bot)
    assert gb.begin_drag(("move", 2), 5.0, 5.0, 0) is True
    assert set(gb.drag["multiface"][1]) == {top, bot}

    gb.apply_scalar(5.0)                        # both grow 5 -> height 20
    assert g.volume(scene.get(obj.id).shape) == pytest.approx(2000.0, abs=1)
    gb.apply_scalar(0.0)                        # revert to original
    assert g.volume(scene.get(obj.id).shape) == pytest.approx(1000.0, abs=1)

    gb.end_drag()
    # offsets keep face indices stable, so the faces stay selected for reuse
    assert gb._multiface_target() is not None


def test_chamfer_when_alt_held():
    from PySide6.QtCore import Qt
    scene, sel, obj, _ = _box_scene()
    orig = obj.shape
    gb = Gumball(_VP(scene, sel))
    sel.toggle_subobject(obj.id, "edge", 0)
    # Alt at grab -> chamfer instead of fillet
    assert gb.begin_drag(("move", 2), 5.0, 5.0,
                         Qt.KeyboardModifier.AltModifier) is True
    assert gb.drag["chamfer"] is True
    gb.apply_scalar(2.0)
    cham = g.volume(scene.get(obj.id).shape)
    assert cham < 1000.0
    # a chamfer removes a different amount than a fillet of the same size
    fil = g.volume(g.fillet_edges(orig, 2.0, edges=[g.edges_of(orig)[0]]))
    assert abs(cham - fil) > 1.0
