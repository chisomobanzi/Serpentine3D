"""The gumball and friends hold still out at survey coordinates too.

The mesh fix gave far geometry an anchor, but everything drawn over it,
the gumball, the control-point display, the rubber band, the ghost,
still went to the GPU as absolute float32 and trembled against the now
solid model. Overlays re-upload every frame, so they can all share one
anchor: where the camera is looking, which is where everything worth
overlaying is.

These tests catch what each overlay uploads (the GL module is a
recorder, the preview batch a bucket) and assert the numbers that reach
the GPU are camera-relative and small.
"""

from __future__ import annotations

import inspect

import numpy as np
import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui import viewport as vp_mod
from tests.test_viewport_perf import _GLRecorder

pytest.importorskip("PySide6")

FAR = np.array([500000.0, 300000.0, 0.0])
NEAR_ENOUGH = 1000.0        # uploads must stay within this of the anchor


class _Bucket:
    """Stands in for the preview _LineBatch and keeps what was uploaded."""

    def __init__(self):
        self.uploads = []
        self.vao = 1
        self.count = 0

    def update(self, pts):
        self.uploads.append(np.asarray(pts, float))
        self.count = len(pts)


@pytest.fixture
def view(monkeypatch):
    monkeypatch.setattr(vp_mod, "GL", _GLRecorder())
    scene = Scene()
    sel = SelectionManager(scene)
    v = vp_mod.Viewport(scene, sel)
    v.resize(1200, 800)
    v._mesh_prog, v._line_prog, v._thick_prog = 11, 12, 13
    v._max_line_width = 1.0
    v._preview = _Bucket()
    v.camera.target = FAR.copy()
    v.camera.distance = 40.0
    v._frame_anchor = vp_mod.view_anchor(v.camera.target)
    return v


def _worst(view) -> float:
    ups = view._preview.uploads
    assert ups, "nothing was uploaded"
    return max(float(np.abs(u).max()) for u in ups)


# -- the anchor rule ------------------------------------------------------

def test_the_anchor_is_the_far_target_and_nothing_near_home():
    assert vp_mod.view_anchor((2.0, 3.0, 4.0)) is None
    a = vp_mod.view_anchor(FAR)
    assert a is not None and np.allclose(a, FAR)


# -- the rubber band and picked-point markers -----------------------------

def test_the_rubber_band_goes_up_camera_relative(view):
    view.set_preview(np.array([[FAR, FAR + (5.0, 0.0, 0.0)]]),
                     markers=[FAR + (1.0, 1.0, 0.0)])
    view._draw_preview(np.eye(4, dtype=np.float32))
    assert _worst(view) < NEAR_ENOUGH, \
        f"rubber band uploaded absolute coordinates ({_worst(view):.0f})"


def test_near_home_the_rubber_band_is_untouched(view):
    view.camera.target = np.zeros(3)
    view._frame_anchor = vp_mod.view_anchor(view.camera.target)
    view.set_preview(np.array([[(0, 0, 0), (5.0, 0.0, 0.0)]]))
    view._draw_preview(np.eye(4, dtype=np.float32))
    up = view._preview.uploads[-1]
    assert np.allclose(up.max(axis=0), (5.0, 0.0, 0.0))


# -- the control-point display --------------------------------------------

def test_control_points_go_up_camera_relative(view):
    obj = view.scene.add(g.make_polyline(
        [tuple(FAR), tuple(FAR + (30.0, 20.0, 10.0))]))
    view.cv_enabled.add(obj.id)
    view.selection.toggle_subobject(obj.id, "cv", 1)   # one held, one not
    view._draw_control_points(np.eye(4, dtype=np.float32))
    assert _worst(view) < NEAR_ENOUGH, \
        f"CV display uploaded absolute coordinates ({_worst(view):.0f})"


# -- the ghost of a pending command ---------------------------------------

def test_the_ghost_goes_up_camera_relative(view):
    from serpentine3d.core.tessellate import DisplayMesh
    dm = DisplayMesh()
    dm.edge_segments = (np.array([[[0.0, 0, 0], [4.0, 0, 0]]]) + FAR)
    view._ghost = dm
    view._draw_ghost(np.eye(4, dtype=np.float32))
    assert _worst(view) < NEAR_ENOUGH, \
        f"ghost uploaded absolute coordinates ({_worst(view):.0f})"


# -- the gumball ----------------------------------------------------------

def test_the_gumball_goes_up_camera_relative(view):
    pts = np.array([FAR + (0.0, 0, 0), FAR + (3.0, 0, 0)])
    view.gumball._lines(np.eye(4, dtype=np.float32), pts,
                        (1.0, 0.0, 0.0, 1.0), 1.4)
    view.gumball._tris(np.eye(4, dtype=np.float32), pts,
                       (1.0, 0.0, 0.0, 1.0))
    assert _worst(view) < NEAR_ENOUGH, \
        f"gumball uploaded absolute coordinates ({_worst(view):.0f})"


# -- the grid on a far construction plane ---------------------------------

def test_a_far_cplanes_basis_keeps_its_origin_exact():
    """float32 rounds 500,000.01 to the nearest 1/32; the basis matrix
    must carry the plane's origin in float64 for the grid fold."""
    from serpentine3d.core.cplane import CPlane
    cp = CPlane(origin=tuple(FAR + 0.01))
    m = cp.basis_matrix()
    assert m.dtype == np.float64
    assert abs(m[0, 3] - (FAR[0] + 0.01)) < 1e-9


def test_the_grid_fold_happens_in_float64(view):
    """The cplane translation folds into the matrix before the cast,
    exactly like a mesh anchor."""
    from serpentine3d.core.cplane import CPlane
    view.cplane = CPlane(origin=tuple(FAR), name="Site")
    view._grid = {k: _Bucket() for k in
                  ("minor", "major", "axis_x", "axis_y")}
    for b in view._grid.values():
        b.count = 2
    mvp64 = np.eye(4) @ np.diag([1.0, 1.0, 1.0, 1.0])
    mvp64[0, 3] = -float(FAR[0])          # a camera looking at the plane
    view._draw_grid(mvp64)
    held = view._mvp_state.get(view._line_prog)
    truth = (mvp64 @ view.cplane.basis_matrix()).astype(np.float32)
    assert held is not None and np.array_equal(held, truth)
    assert abs(float(held[0, 3])) < 1.0, \
        "the fold left a huge float32 translation, so the grid swims"


# -- wiring that cannot execute without a real context --------------------

def test_the_frame_sets_the_anchor_and_folds_it_into_the_matrix():
    src = inspect.getsource(vp_mod.Viewport._paint_frame)
    assert "self._frame_anchor = view_anchor(" in src
    assert "anchored(mvp64, self._frame_anchor)" in src
    assert "self._draw_grid(mvp64" in src


def test_the_paper_side_has_no_anchor():
    src = inspect.getsource(vp_mod.Viewport._paint_frame)
    assert "self._frame_anchor = None" in src


def test_combs_arrows_and_image_planes_ride_the_anchor():
    for fn in (vp_mod.Viewport._draw_combs,
               vp_mod.Viewport._draw_direction_arrows,
               vp_mod.Viewport._draw_image_planes):
        assert "rebased(" in inspect.getsource(fn), fn.__qualname__
