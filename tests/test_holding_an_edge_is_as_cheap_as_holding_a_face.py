"""Holding an edge must not weigh the solid it belongs to.

Ctrl+Shift-clicking an edge took four and a half seconds on an ordinary
NURBS assembly, while holding a face of the same solid took fourteen
milliseconds. The fillet handle wants to point away from the solid, and
it asked for the solid's exact centre of mass to decide which way that
is. Integrating that over real NURBS geometry costs a few hundred
milliseconds, the answer was not remembered, and paint asks for the
target about thirty times a frame.

The middle of the object's bounds says which way is outward just as well
and is already known, and the target is now remembered between the
questions paint asks, as its face and segment siblings already were.
"""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from serpentine3d.core import geometry as g
from serpentine3d.core.cplane import CPlane
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui.gumball import Gumball


class _Cam:
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


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def held_edge(app):
    scene = Scene()
    box = scene.add(g.make_box((0, 0, 0), 10, 10, 10), name="Box")
    sel = SelectionManager(scene)
    sel.toggle_subobject(box.id, "edge", 0)
    return Gumball(_VP(scene, sel)), scene, sel, box


@pytest.fixture
def weighed(monkeypatch):
    """Count the integrations over the solid's own geometry."""
    from serpentine3d.core import occ
    calls = []
    real = occ.volume_properties

    def wrapped(shape):
        calls.append(shape)
        return real(shape)

    monkeypatch.setattr(occ, "volume_properties", wrapped)
    return calls


def _what_paint_asks(gb):
    """The questions a frame puts to the gumball, in the same order."""
    gb.active()
    gb._fillet_mode()
    gb.handles()
    gb.anchor_and_axes()


def test_a_frame_never_weighs_the_solid(held_edge, weighed):
    gb, _scene, _sel, _box = held_edge

    for _ in range(5):
        _what_paint_asks(gb)

    assert weighed == [], (
        "the middle of the bounds says which way is outward, and the bounds "
        "are already known")


def test_the_target_is_worked_out_once_per_frame(held_edge, monkeypatch):
    gb, _scene, _sel, _box = held_edge
    runs = []
    real = gb._fillet_target_of
    monkeypatch.setattr(gb, "_fillet_target_of",
                        lambda: runs.append(1) or real())

    _what_paint_asks(gb)

    assert len(runs) == 1, (
        f"paint asked for the target {len(runs)} times over; it only changes "
        "when the selection or the drawing does")


def test_the_handle_still_points_away_from_the_solid(held_edge):
    gb, _scene, _sel, box = held_edge

    target = gb._fillet_target()

    assert target is not None
    _oid, idxs, anchor, (_t1, _t2, out) = target
    assert idxs == [0]
    assert np.linalg.norm(out) == pytest.approx(1.0, abs=1e-6)
    middle = np.asarray(g.centroid(box.shape), float)
    assert np.dot(out, anchor - middle) > 0, "the arrow points outward"


def test_a_changed_selection_is_noticed(held_edge):
    gb, _scene, sel, box = held_edge
    first = gb._fillet_target()
    assert first is not None and first[1] == [0]

    sel.set_subobjects([])
    sel.toggle_subobject(box.id, "edge", 3)

    again = gb._fillet_target()
    assert again is not None and again[1] == [3], (
        "remembering must not outlast what it was remembered for")


def test_a_changed_shape_is_noticed(held_edge):
    gb, scene, _sel, box = held_edge
    before = gb._fillet_target()[2]

    # moved bodily, so every edge of it is somewhere else; growing it
    # along one axis leaves the edge at the origin exactly where it was
    scene.replace_shape(box.id, g.make_box((100, 50, 20), 10, 10, 10))

    after = gb._fillet_target()[2]
    assert not np.allclose(before, after), (
        "the edge moved with the shape, so the handle has to move too")
