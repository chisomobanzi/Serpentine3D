"""Ortho from a snapped base must stay at the base's depth.

Snap a line's start to a corner that floats off the construction plane,
hold Shift, and drag right: the front view shows a level line, and the
top view showed a diagonal — the constrained point kept the plane's
depth (zero) instead of the base's. Ortho means the point lies on an
axis THROUGH the base, all three coordinates of it, not just the one
the cursor is driving.
"""

import numpy as np
import pytest

from serpentine3d.core.cplane import PRESETS
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager


def _front_vp(scene):
    from serpentine3d.ui.viewport import Viewport
    vp = Viewport(scene, SelectionManager(scene))
    vp.resize(900, 700)
    vp.camera.target = np.zeros(3)
    vp.camera.distance = 6000.0
    vp.camera.set_standard_view("front")
    vp.cplane = PRESETS["front"]()
    vp.point_axis = None
    return vp


def _px(vp, world):
    scr = vp.camera.project(np.asarray([world], float),
                            vp.width(), vp.height())[0]
    return float(scr[0]), float(scr[1])


def test_ortho_keeps_a_snapped_bases_depth():
    scene = Scene()
    vp = _front_vp(scene)
    vp.set_point_mode(True)
    vp.ortho = True
    vp.snap_base = (10.0, 300.0, 50.0)     # snapped off the front plane
    px, py = _px(vp, (2000.0, 0.0, 55.0))  # dragging right, roughly level
    p = vp.world_point_at(px, py)
    assert p is not None
    assert p[1] == pytest.approx(300.0, abs=1e-6)   # the base's depth
    assert p[2] == pytest.approx(50.0, abs=1e-6)    # the base's height
    assert p[0] == pytest.approx(2000.0, abs=1.0)   # the cursor's reach


def test_ortho_up_keeps_the_depth_too():
    scene = Scene()
    vp = _front_vp(scene)
    vp.set_point_mode(True)
    vp.ortho = True
    vp.snap_base = (10.0, 300.0, 50.0)
    px, py = _px(vp, (12.0, 0.0, 1500.0))  # dragging up
    p = vp.world_point_at(px, py)
    assert p is not None
    assert p[0] == pytest.approx(10.0, abs=1e-6)
    assert p[1] == pytest.approx(300.0, abs=1e-6)
    assert p[2] == pytest.approx(1500.0, abs=1.0)


def test_ortho_on_the_plane_is_unchanged():
    """A base on the plane constrained exactly as before."""
    scene = Scene()
    vp = _front_vp(scene)
    vp.set_point_mode(True)
    vp.ortho = True
    vp.snap_base = (0.0, 0.0, 0.0)
    px, py = _px(vp, (800.0, 0.0, 60.0))
    p = vp.world_point_at(px, py)
    assert p is not None
    assert p[1] == pytest.approx(0.0, abs=1e-6)
    assert p[2] == pytest.approx(0.0, abs=1e-6)
    assert p[0] == pytest.approx(800.0, abs=1.0)
