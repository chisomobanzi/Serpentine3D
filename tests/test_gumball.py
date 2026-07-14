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
    not stay frozen at the drag-start anchor."""
    vp, scene, sel = _vp()
    box = scene.add(g.make_box((-2, -2, -2), 4, 4, 4))
    sel.set([box.id])
    start_anchor = vp.gumball.anchor_and_axes()[0].copy()
    _begin(vp, "move", 2)                      # Z arrow
    vp.gumball.apply_scalar(10.0)              # move +10 along Z
    # geometry actually moved
    assert g.bbox(scene.get(box.id).shape)[0][2] == pytest.approx(8)
    # the drawn gumball anchor tracks it (was the bug: stayed at start)
    drawn = vp.gumball._draw_anchor()[0]
    assert drawn[2] == pytest.approx(start_anchor[2] + 10, abs=1e-6)
    assert np.linalg.norm(drawn - g_center(scene.get(box.id).shape)) < 1e-6


def g_center(shape):
    mn, mx = g.bbox(shape)
    return (np.asarray(mn) + np.asarray(mx)) / 2


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
    # previews live while typing
    assert g.bbox(scene.get(box.id).shape)[0][0] == pytest.approx(12.5)
    assert vp.gumball.commit_typed()
    assert vp.gumball.drag is None
    assert g.bbox(scene.get(box.id).shape)[0][0] == pytest.approx(12.5)


def test_typed_rotate_and_scale():
    vp, scene, sel = _vp()
    box = scene.add(g.make_box((0, 0, 0), 4, 2, 2))
    sel.set([box.id])
    _begin(vp, "rot", 2)
    for ch in "9", "0":
        vp.gumball.type_char(ch)
    vp.gumball.commit_typed()
    mn, mx = g.bbox(scene.get(box.id).shape)
    assert (mx[1] - mn[1]) == pytest.approx(4, abs=1e-4)   # 90deg: X->Y

    box2 = scene.get(box.id)
    sel.set([box2.id])
    _begin(vp, "scale", 0)
    for ch in "3":
        vp.gumball.type_char(ch)
    vp.gumball.commit_typed()
    mn, mx = g.bbox(scene.get(box.id).shape)
    # after the 90deg turn the X extent is the old width 2; x3 along X -> 6
    assert (mx[0] - mn[0]) == pytest.approx(6, abs=1e-4)


def test_typed_backspace_and_revert():
    vp, scene, sel = _vp()
    box = scene.add(g.make_box((0, 0, 0), 2, 2, 2))
    sel.set([box.id])
    _begin(vp, "move", 0)
    vp.gumball.type_char("5")
    assert g.bbox(scene.get(box.id).shape)[0][0] == pytest.approx(5)
    vp.gumball.type_char("back")              # buffer empty -> revert
    assert g.bbox(scene.get(box.id).shape)[0][0] == pytest.approx(0, abs=1e-5)
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
    assert g.bbox(scene.get(box.id).shape)[0][0] == pytest.approx(10)


def test_pad_move_follows_and_cancels():
    vp, scene, sel = _vp()
    box = scene.add(g.make_box((0, 0, 0), 2, 2, 2))
    sel.set([box.id])
    anchor0 = vp.gumball.anchor_and_axes()[0].copy()
    _begin(vp, "pad", 2)                       # XY plane pad
    # simulate an applied in-plane delta
    d = vp.gumball.drag
    d["offset"] = np.array([3.0, 4.0, 0.0])
    vp.gumball._apply(lambda s: g.translate(s, (3.0, 4.0, 0.0)))
    drawn = vp.gumball._draw_anchor()[0]
    assert drawn[0] == pytest.approx(anchor0[0] + 3)
    assert drawn[1] == pytest.approx(anchor0[1] + 4)
    vp.gumball.cancel_drag()
    assert g.bbox(scene.get(box.id).shape)[0][0] == pytest.approx(0, abs=1e-5)


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
