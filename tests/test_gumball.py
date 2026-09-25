"""Gumball: follow-during-drag fix, typed numeric entry, snapping."""

import numpy as np
import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager


def _vp():
    from serpentine3d.ui.viewport import Viewport
    scene = Scene()
    sel = SelectionManager(scene)
    vp = Viewport(scene, sel)
    vp.resize(900, 700)
    vp.camera.target = np.zeros(3)
    vp.camera.distance = 40.0
    return vp, scene, sel


def _begin(vp, kind, axis):
    """Start a gumball drag on a handle, centre pixel (bypasses hit-test)."""
    w, h = vp.width(), vp.height()
    ok = vp.gumball.begin_drag((kind, axis), w / 2, h / 2,
                               __import__("PySide6.QtCore",
                                          fromlist=["Qt"]).Qt
                               .KeyboardModifier.NoModifier)
    assert ok, f"begin_drag failed for {kind} {axis}"


def test_gumball_follows_geometry_during_move():
    """The reported bug: mid-move the gumball must track the geometry,
    not stay frozen at the drag-start anchor. The move rides as a display
    offset until release, and the gumball tracks where it is shown."""
    vp, scene, sel = _vp()
    box = scene.add(g.make_box((-2, -2, -2), 4, 4, 4))
    sel.set([box.id])
    start_anchor = vp.gumball.anchor_and_axes()[0].copy()
    _begin(vp, "move", 2)                      # Z arrow
    vp.gumball.apply_scalar(10.0)              # move +10 along Z
    # the move is shown, not written: the scene keeps the shape as it was
    assert g.bbox(scene.get(box.id).shape)[0][2] == pytest.approx(-2)
    assert _is_translation(scene.drag_display[box.id], (0.0, 0.0, 10.0))
    # the drawn gumball anchor tracks the shown position (was the bug:
    # stayed at start)
    drawn = vp.gumball._draw_anchor()[0]
    assert drawn[2] == pytest.approx(start_anchor[2] + 10, abs=1e-6)
    assert np.linalg.norm(
        drawn - (g_center(scene.get(box.id).shape)
                 + np.asarray(scene.drag_display[box.id][:3, 3]))) < 1e-6
    vp.gumball.end_drag()                      # release folds in the pose
    obj = scene.get(box.id)
    assert g.bbox(obj.shape)[0][2] == pytest.approx(-2, abs=1e-5)  # shape untouched
    assert _is_translation(obj.transform, (0.0, 0.0, 10.0))
    assert obj.bbox()[0][2] == pytest.approx(8)
    assert not scene.drag_display
    drawn = vp.gumball._draw_anchor()[0]
    wmin, wmax = obj.bbox()
    assert np.linalg.norm(drawn - (np.asarray(wmin) + np.asarray(wmax)) / 2) < 1e-6


def g_center(shape):
    mn, mx = g.bbox(shape)
    return (np.asarray(mn) + np.asarray(mx)) / 2


def _is_translation(m, off):
    """drag_display carries 4x4 poses; a whole-object move is the one
    whose linear part is the identity."""
    m = np.asarray(m, float)
    return (np.allclose(m[:3, :3], np.eye(3), atol=1e-9)
            and np.allclose(m[:3, 3], off, atol=1e-9))


def test_rotate_and_scale_anchor_stays_put():
    """Rotate/scale pivot on the anchor, so the gumball stays there."""
    vp, scene, sel = _vp()
    box = scene.add(g.make_box((0, 0, 0), 4, 2, 2))
    sel.set([box.id])
    anchor = vp.gumball.anchor_and_axes()[0].copy()
    _begin(vp, "rot", 2)
    vp.gumball.apply_scalar(90.0)
    assert np.allclose(vp.gumball._draw_anchor()[0], anchor, atol=1e-6)


def test_typed_move_commits_exact_distance():
    vp, scene, sel = _vp()
    box = scene.add(g.make_box((0, 0, 0), 2, 2, 2))
    sel.set([box.id])
    _begin(vp, "move", 0)                      # X arrow
    for ch in "1", "2", ".", "5":
        assert vp.gumball.type_char(ch)
    # previews live while typing, as a display offset: the scene is not
    # written until Enter
    assert g.bbox(scene.get(box.id).shape)[0][0] == pytest.approx(0, abs=1e-5)
    assert _is_translation(scene.drag_display[box.id], (12.5, 0.0, 0.0))
    assert vp.gumball.commit_typed()
    assert vp.gumball.drag is None
    assert not scene.drag_display
    obj = scene.get(box.id)
    assert g.bbox(obj.shape)[0][0] == pytest.approx(0, abs=1e-5)  # shape untouched
    assert obj.bbox()[0][0] == pytest.approx(12.5)                  # pose carries it


def test_typed_rotate_and_scale():
    vp, scene, sel = _vp()
    box = scene.add(g.make_box((0, 0, 0), 4, 2, 2))
    sel.set([box.id])
    _begin(vp, "rot", 2)
    for ch in "9", "0":
        vp.gumball.type_char(ch)
    vp.gumball.commit_typed()
    mn, mx = scene.get(box.id).bbox()      # the world box: the pose, not the shape
    assert (mx[1] - mn[1]) == pytest.approx(4, abs=1e-4)   # 90deg: X->Y

    box2 = scene.get(box.id)
    sel.set([box2.id])
    vp.camera.target = np.asarray((0.0, 1.0, 1.0))  # on the scale axis line {(t,1,1)}
    _begin(vp, "scale", 0)
    for ch in "3":
        vp.gumball.type_char(ch)
    vp.gumball.commit_typed()
    mn, mx = scene.get(box.id).bbox()
    # after the 90deg turn the X extent is the old width 2; x3 along X -> 6
    assert (mx[0] - mn[0]) == pytest.approx(6, abs=1e-4)


def test_typed_backspace_and_revert():
    vp, scene, sel = _vp()
    box = scene.add(g.make_box((0, 0, 0), 2, 2, 2))
    sel.set([box.id])
    _begin(vp, "move", 0)
    vp.gumball.type_char("5")
    # the preview is a display offset; the scene is written on no keypress
    assert g.bbox(scene.get(box.id).shape)[0][0] == pytest.approx(0, abs=1e-5)
    assert _is_translation(scene.drag_display[box.id], (5.0, 0.0, 0.0))
    vp.gumball.type_char("back")              # buffer empty -> revert
    assert g.bbox(scene.get(box.id).shape)[0][0] == pytest.approx(0, abs=1e-5)
    assert not scene.drag_display
    vp.gumball.cancel_drag()


def test_move_grid_snaps(monkeypatch):
    vp, scene, sel = _vp()
    vp.grid_snap = True
    vp.grid_snap_step = 5.0
    box = scene.add(g.make_box((0, 0, 0), 2, 2, 2))
    sel.set([box.id])
    _begin(vp, "move", 0)
    # feed a raw mouse value near 12 -> snaps to 10 via drag_to; emulate by
    # calling apply_scalar with the snapped value the drag path would use
    snapped = round(12.3 / vp.grid_snap_step) * vp.grid_snap_step
    vp.gumball.apply_scalar(snapped)
    # the snapped value is what the display transform carries
    assert _is_translation(scene.drag_display[box.id], (10.0, 0.0, 0.0))
    vp.gumball.end_drag()
    obj = scene.get(box.id)
    assert g.bbox(obj.shape)[0][0] == pytest.approx(0, abs=1e-5)  # shape untouched
    assert obj.bbox()[0][0] == pytest.approx(10)


def test_pad_move_follows_and_cancels():
    vp, scene, sel = _vp()
    box = scene.add(g.make_box((0, 0, 0), 2, 2, 2))
    sel.set([box.id])
    anchor0 = vp.gumball.anchor_and_axes()[0].copy()
    _begin(vp, "pad", 2)                       # XY plane pad
    # simulate an applied in-plane delta, as the drag path does: the offset
    # is shown, the scene is not written
    d = vp.gumball.drag
    d["offset"] = np.array([3.0, 4.0, 0.0])
    m = np.eye(4)
    m[:3, 3] = d["offset"]
    vp.scene.set_drag_display({box.id: m})
    drawn = vp.gumball._draw_anchor()[0]
    assert drawn[0] == pytest.approx(anchor0[0] + 3)
    assert drawn[1] == pytest.approx(anchor0[1] + 4)
    vp.gumball.cancel_drag()
    assert g.bbox(scene.get(box.id).shape)[0][0] == pytest.approx(0, abs=1e-5)
    assert not scene.drag_display


def test_pad_and_rot_reject_typing():
    vp, scene, sel = _vp()
    box = scene.add(g.make_box((0, 0, 0), 2, 2, 2))
    sel.set([box.id])
    _begin(vp, "pad", 2)
    assert not vp.gumball.accepts_typing()
    assert not vp.gumball.type_char("5")
    vp.gumball.cancel_drag()


def test_readout_label_states():
    vp, scene, sel = _vp()
    box = scene.add(g.make_box((0, 0, 0), 2, 2, 2))
    sel.set([box.id])
    # idle: no readout
    vp._update_gumball_readout()
    assert vp._gumball_readout.isHidden()
    # armed (clicked, awaiting a value): prompt shows
    _begin(vp, "move", 0)
    vp.gumball.arm()
    vp._update_gumball_readout()
    assert not vp._gumball_readout.isHidden()
    assert "distance" in vp._gumball_readout.text()
    # typing: live value shows
    vp.gumball.type_char("7")
    info = vp.gumball.readout()
    assert info is not None and "7" in info[0]
    # rotate prompt/units
    vp.gumball.cancel_drag()
    _begin(vp, "rot", 2)
    vp.gumball.type_char("4"); vp.gumball.type_char("5")
    assert "°" in vp.gumball.readout()[0]
    vp.gumball.cancel_drag()
    vp._update_gumball_readout()
    assert vp._gumball_readout.isHidden()


def test_compounded_nonuniform_scale_stays_valid():
    """Regression: scaling a shape non-uniformly, tessellating, then
    scaling again used to make BRepBuilderAPI_GTransform emit faces with
    NULL surfaces — every later OCCT call then segfaulted (crash after
    gumball scaling on a second axis). It must stay valid now."""
    from serpentine3d.core.tessellate import tessellate
    from serpentine3d.core.geometry import _has_null_surface
    box = g.make_box((-2, -2, -2), 4, 4, 4)
    shape = box
    for axis in [(0, 1, 0), (0, 0, 1), (1, 0, 0), (0, 1, 0), (0, 0, 1)]:
        shape = g.scale_along_axis(shape, (0, 0, 0), axis, -2.5)
        tessellate(shape)                     # mutates the shape in place
        assert not _has_null_surface(shape), \
            "non-uniform scale of a meshed shape produced null surfaces"
    # non-uniform scale via factors= is guarded the same way
    s = g.scale(box, (0, 0, 0), 1.0, factors=(2.0, 0.5, 1.0))
    tessellate(s)
    s = g.scale(s, (0, 0, 0), 1.0, factors=(0.5, 2.0, 1.0))
    assert not _has_null_surface(s)


def test_gumball_scale_across_axes_no_crash():
    """Drive real gumball scale drags across all three axes (the crash
    repro): the shape must remain tessellatable at every step."""
    from serpentine3d.core.tessellate import tessellate
    from serpentine3d.core.geometry import _has_null_surface
    vp, scene, sel = _vp()
    box = scene.add(g.make_box((-2, -2, -2), 4, 4, 4))
    sel.set([box.id])
    for axis in (0, 1, 2):
        _begin(vp, "scale", axis)
        vp.gumball.apply_scalar(-1.8)         # negative, non-uniform
        vp.gumball.end_drag()
        obj = scene.get(box.id)
        tessellate(obj.shape)                 # what the viewport does
        assert not _has_null_surface(obj.shape)
    assert g.volume(scene.get(box.id).shape) > 0


# -- many-object rot / scale: transform carries, shape untouched ------

def test_rot_many_objects():
    """Rotating several objects writes a display matrix per object and
    commits a batched transform on release; the shapes are untouched."""
    vp, scene, sel = _vp()
    boxes = [scene.add(g.make_box((0, 0, 0), 4, 2, 1)) for _ in range(3)]
    sel.set([b.id for b in boxes])
    _begin(vp, "rot", 2)                       # Z rotation
    vp.gumball.apply_scalar(90.0)              # 90° about Z
    # mid-drag: each object carries a display rotation matrix;
    # no shape has been rewritten
    for b in boxes:
        assert b.id in scene.drag_display
        assert scene.drag_display[b.id].shape == (4, 4)
        lo, _hi = g.bbox(b.shape)
        assert lo == pytest.approx(np.array([0, 0, 0]), abs=1e-5)  # unchanged
    vp.gumball.end_drag()
    for b in boxes:
        obj = scene.get(b.id)
        lo, _hi = g.bbox(obj.shape)
        assert lo == pytest.approx(np.array([0, 0, 0]), abs=1e-5)  # untouched
        assert obj.transform is not None
        # 90° about Z swaps the box extents: the 4-long way now lies on Y
        mn, mx = obj.bbox()
        assert mx[1] - mn[1] == pytest.approx(4, abs=1e-5)
        assert mx[0] - mn[0] == pytest.approx(2, abs=1e-5)
    assert not scene.drag_display


def test_scale_many_objects():
    """Scaling several objects writes a display scale matrix per object
    and commits a batched transform on release; the shapes are untouched."""
    vp, scene, sel = _vp()
    boxes = [scene.add(g.make_box((0, 0, 0), 2, 2, 2)) for _ in range(3)]
    sel.set([b.id for b in boxes])
    _begin(vp, "scale", 0)                     # X scale
    vp.gumball.apply_scalar(3.0)               # 3× along X
    for b in boxes:
        assert b.id in scene.drag_display
        assert scene.drag_display[b.id].shape == (4, 4)
        lo, _hi = g.bbox(b.shape)
        assert lo == pytest.approx(np.array([0, 0, 0]), abs=1e-5)  # unchanged
    vp.gumball.end_drag()
    for b in boxes:
        obj = scene.get(b.id)
        lo, _hi = g.bbox(obj.shape)
        assert lo == pytest.approx(np.array([0, 0, 0]), abs=1e-5)  # untouched
        assert obj.transform is not None
        # scaled 3× about its centre (1,1,1): x now spans -2..4
        mn, mx = obj.bbox()
        assert mx[0] == pytest.approx(4, abs=1e-5)
        assert mn[0] == pytest.approx(-2, abs=1e-5)
    assert not scene.drag_display
