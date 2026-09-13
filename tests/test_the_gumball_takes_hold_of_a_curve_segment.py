"""Ctrl+Shift-click a segment of a polyline and the gumball moves just that
segment, with the sides it meets stretching after it (issue #25).

A held edge of a solid turns the gumball into a fillet handle; a held
segment of a curve has nothing to fillet and gets the whole gumball
instead, standing on the segment. The drag maths needs a live pane, so
the gumball is driven through the same fake viewport the other sub-object
tests use.
"""

import math

import numpy as np
import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.cplane import CPlane
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui.gumball import Gumball


class _Cam:
    """Looks straight down, so a drag along Y and a turn about Z both meet
    the ray."""
    def ray_through(self, px, py, w, h):
        return np.array([px, py, 100.0]), np.array([0.0, 0.0, -1.0])

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
        self.cv_enabled = set()
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

    def window_discard_checkpoint(self):
        self._checkpoints.pop()


def _edge_at(shape, mid):
    for i, e in enumerate(g.edges_of(shape)):
        if math.dist(g.centroid(e), mid) < 1e-6:
            return i
    raise AssertionError(f"no edge with midpoint {mid}")


def _rect_scene():
    scene = Scene()
    obj = scene.add(g.make_polyline(
        [(0, 0, 0), (10, 0, 0), (10, 6, 0), (0, 6, 0)], closed=True))
    sel = SelectionManager(scene)
    bottom = _edge_at(obj.shape, (5, 0, 0))
    sel.toggle_subobject(obj.id, "edge", bottom)
    return scene, sel, obj, bottom


def test_a_held_segment_gets_the_whole_gumball_standing_on_it():
    scene, sel, obj, bottom = _rect_scene()
    gb = Gumball(_VP(scene, sel))
    assert gb.active() is True
    assert gb._fillet_mode() is False, "a curve segment has nothing to fillet"
    handles = gb.handles()
    for kind in ("move", "rot", "scale"):
        for i in range(3):
            assert (kind, i) in handles, f"{kind} {i} missing"
    anchor, _axes = gb.anchor_and_axes()
    assert anchor == pytest.approx((5, 0, 0), abs=1e-6)


def test_dragging_a_side_resizes_the_rectangle_and_keeps_holding_it():
    scene, sel, obj, bottom = _rect_scene()
    vp = _VP(scene, sel)
    gb = Gumball(vp)
    assert gb.begin_drag(("move", 1), 5.0, 5.0, 0) is True
    assert gb.drag["segments"] == {obj.id: [bottom]}
    assert vp._checkpoints == ["gumball move"]

    gb.apply_scalar(-2.0)
    shape = scene.get(obj.id).shape
    lo, hi = g.bbox(shape)
    assert lo == pytest.approx((0, -2, 0), abs=1e-6)
    assert hi == pytest.approx((10, 6, 0), abs=1e-6)
    assert g.is_closed_curve(shape) and len(g.edges_of(shape)) == 4

    gb.apply_scalar(0.0)                       # back to where it started
    lo, _hi = g.bbox(scene.get(obj.id).shape)
    assert lo == pytest.approx((0, 0, 0), abs=1e-6)

    gb.apply_scalar(-3.0)
    gb.end_drag()
    shape = scene.get(obj.id).shape
    assert g.bbox(shape)[0] == pytest.approx((0, -3, 0), abs=1e-6)
    # still holding the same side, wherever it is in the rebuilt curve
    held = [(o, k, i) for (o, k, i) in sel.subobjects if k == "edge"]
    assert len(held) == 1
    mid = g.centroid(g.edges_of(shape)[held[0][2]])
    assert mid == pytest.approx((5, -3, 0), abs=1e-6)


def test_turning_a_side_swings_its_neighbours():
    scene, sel, obj, bottom = _rect_scene()
    gb = Gumball(_VP(scene, sel))
    assert gb.begin_drag(("rot", 2), 5.0, 5.0, 0) is True
    gb.apply_scalar(90.0)
    gb.end_drag()
    ends = {tuple(round(v, 6) for v in p)
            for e in g.edges_of(scene.get(obj.id).shape)
            for p in g.curve_endpoints(e)}
    assert {(5.0, -5.0, 0.0), (5.0, 5.0, 0.0),
            (0.0, 6.0, 0.0), (10.0, 6.0, 0.0)} <= ends


def test_a_solid_edge_is_still_a_fillet_handle():
    scene = Scene()
    box = scene.add(g.make_box((0, 0, 0), 10, 10, 10))
    sel = SelectionManager(scene)
    sel.toggle_subobject(box.id, "edge", 0)
    gb = Gumball(_VP(scene, sel))
    assert gb._fillet_mode() is True
    assert gb._segment_target() is None
