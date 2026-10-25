"""The grid cannot push the near plane into a far model.

The clip planes wrap the drawing and the grid together, so that a far
plane snug around a small model does not crop the grid it sits on, and
the near plane is held within a million to one of the far one, for the
depth buffer's sake. Out at survey coordinates the grid stays at the
world's origin, so the far plane reached 6,200 km back to it, the near
plane went out to 6.5 m, and a survey peg or a patch of scan zoomed to
extents was clipped away whole: an empty view, until the grid was
hidden.

The grid writes no depth, so it has no claim on the depth buffer's
budget. It still stretches the far plane as far as it likes, but the near
plane is now measured against the drawing alone.
"""

from __future__ import annotations

import numpy as np
import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui import viewport as vp_mod
from serpentine3d.ui.camera import Camera


FAR = (500_000.0, 6_200_000.0, 12.0)


def _viewport():
    scene = Scene()
    vp = vp_mod.Viewport(scene, SelectionManager(scene))
    vp.resize(800, 600)
    vp.set_view("perspective")
    return vp, scene


def _peg(scene, at=FAR):
    """A survey peg: a metre square, half a metre tall."""
    return scene.add(g.make_box(at, 1.0, 1.0, 0.5), name="peg")


def _reach(box, eye):
    lo, hi = (np.asarray(c, float) for c in box)
    corners = np.array([(x, y, z) for x in (lo[0], hi[0])
                        for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
    return np.linalg.norm(corners - eye, axis=1)


def _framed(vp):
    vp._refresh_camera_bounds()
    vp.zoom_extents()


# -- the planes ----------------------------------------------------------------

@pytest.mark.parametrize("grid", [True, False], ids=["grid on", "grid off"])
def test_a_peg_far_from_home_sits_between_its_clip_planes(grid):
    vp, scene = _viewport()
    vp.grid_visible = grid
    _peg(scene)
    _framed(vp)

    near, far = vp.camera.clip_planes()
    reach = _reach(scene.bbox(), vp.camera.position)

    assert near < reach.min(), f"the near plane at {near:.3g} clips the peg"
    assert reach.max() < far


def test_the_grid_still_stretches_the_far_plane_beside_a_small_model():
    """Why the grid rides along at all: zoomed in on a small model at
    home, a far plane snug around the model would crop the grid."""
    vp, scene = _viewport()
    scene.add(g.make_box((0, 0, 0), 1, 1, 1), name="small")
    _framed(vp)

    _near, far = vp.camera.clip_planes()
    e = vp._grid_params[0]
    grid = _reach(((-e, -e, 0), (e, e, 0)), vp.camera.position)

    assert grid.max() < far


def test_the_drawing_keeps_its_million_to_one():
    """The budget the grid gave up still holds across the drawing itself:
    zoomed right in on one corner of a 50 m model, the near plane stays
    within a million to one of the model's far side."""
    cam = Camera()
    big = ((0.0, 0.0, 0.0), (50_000.0, 50_000.0, 20_000.0))
    cam.scene_bounds = cam.drawing_bounds = big
    cam.distance = 0.5

    near, far = cam.clip_planes()

    assert far / near <= 2e6


def test_picking_hears_about_the_drawing_too():
    """The cached view-projection behind every click is keyed on what the
    planes are made of, the drawing's box included."""
    cam = Camera()
    cam.target = np.array(FAR)
    cam.distance = 3.0
    e = 100.0
    cam.scene_bounds = ((-e, -e, 0.0), (FAR[0] + 1, FAR[1] + 1, FAR[2] + 1))
    before = cam._view_proj(800, 600)[0].copy()

    cam.drawing_bounds = (FAR, (FAR[0] + 1, FAR[1] + 1, FAR[2] + 1))
    after = cam._view_proj(800, 600)[0]
    fresh = cam.proj_matrix(800, 600) @ cam.view_matrix()

    # exact, not allclose: the planes move the translation column by tens
    # of units on millions, well inside any relative tolerance
    assert not np.array_equal(before, after)
    assert np.array_equal(after, fresh)


# -- on a real GL surface ------------------------------------------------------

@pytest.fixture
def window(_qapp):
    from serpentine3d.app import MainWindow
    w = MainWindow()
    w.set_view_layout("single")
    w.resize(900, 700)
    w.show()
    vp = w.viewport
    vp.grabFramebuffer()            # makes the context, where there is one
    if not (vp.isValid() and getattr(vp, "_mesh_prog", 0)):
        # Offscreen, Qt hands back an image and a GL 2.0 context all the
        # same, but the viewport's own shaders never compile on it: only
        # they say whether this viewport can really draw.
        w.mark_saved()
        w.close()
        pytest.skip("no GL 3.3 to draw with here (CI runs offscreen)")
    yield w, vp
    w.mark_saved()
    w.close()


def test_a_far_peg_draws_with_the_grid_on(window):
    w, vp = window
    peg = _peg(w.scene)
    w.scene.update(peg.id, color=(1.0, 0.0, 0.0))
    w.scene.notify()
    vp.set_view("perspective")
    vp.zoom_extents()
    assert vp.grid_visible

    image = vp.grabFramebuffer()
    centre = image.pixelColor(image.width() // 2, image.height() // 2)

    assert centre.red() > centre.green() + 60, \
        f"the middle of the view is {centre.name()}, not the red peg"
