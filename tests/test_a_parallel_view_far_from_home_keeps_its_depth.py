"""A parallel view of a far model sorts faces a few millimetres apart.

An orthographic view spreads the depth buffer's 24 bits evenly across its
slab, and the slab wrapped the grid as well as the drawing, so that the
grid, and a rubber band drawn on the construction plane, stayed inside it.
Out at survey coordinates the construction plane stays at the world's
origin: in a Front view of a model 6,200 km north the slab ran back to it,
and faces were sorted in steps of 0.4 units. A window 4 mm proud of its
wall lost to the wall.

So the slab wraps the drawing alone, and what lies outside it, the grid, a
rubber band on a construction plane at the origin, a ghost behind the
model, is kept by clamping its depth rather than clipping it away.
"""

from __future__ import annotations

import inspect

import numpy as np
import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui import viewport as vp_mod


X0, Y0, Z0 = 500_000.0, 6_200_000.0, 12.0
REVEAL = 0.004


def _viewport(view):
    scene = Scene()
    vp = vp_mod.Viewport(scene, SelectionManager(scene))
    vp.resize(800, 600)
    vp.set_view(view)
    return vp, scene


def _framed(vp):
    vp._refresh_camera_bounds()
    vp.zoom_extents()


def _depths(box, cam):
    lo, hi = (np.asarray(c, float) for c in box)
    corners = np.array([(x, y, z) for x in (lo[0], hi[0])
                        for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
    fwd = cam.target - cam.position
    fwd = fwd / np.linalg.norm(fwd)
    return (corners - cam.position) @ fwd


# -- the slab ----------------------------------------------------------------

def test_a_front_view_of_a_far_model_slices_depth_finely():
    vp, scene = _viewport("front")
    scene.add(g.make_box((X0, Y0, Z0), 1.0, 1.0, 1.0), name="peg")
    _framed(vp)
    assert vp.grid_visible

    near, far = vp.camera.clip_planes()

    step = (far - near) / 2 ** 24
    assert step < 1e-6, f"faces are sorted in steps of {step:.3g}"


def test_the_slab_still_holds_the_whole_drawing():
    vp, scene = _viewport("front")
    scene.add(g.make_box((X0, Y0, Z0), 1.0, 1.0, 1.0), name="peg")
    scene.add(g.make_box((X0 + 40, Y0 + 25, Z0), 2.0, 2.0, 2.0), name="shed")
    _framed(vp)

    near, far = vp.camera.clip_planes()
    depths = _depths(scene.bbox(), vp.camera)

    assert near < depths.min() and depths.max() < far


def test_with_nothing_drawn_the_slab_wraps_the_grid():
    vp, _scene = _viewport("top")
    _framed(vp)

    near, far = vp.camera.clip_planes()
    e = vp._grid_params[0]
    depths = _depths(((-e, -e, 0), (e, e, 0)), vp.camera)

    assert near < depths.min() and depths.max() < far


def test_the_frame_clamps_depth_before_the_grid_in_a_parallel_view():
    # The frame itself cannot be drawn offscreen; the GL tests below do it
    # where there is a display, and this keeps CI honest meanwhile.
    src = inspect.getsource(vp_mod.Viewport._paint_frame)
    assert "glEnable(GL.GL_DEPTH_CLAMP)" in src
    assert (src.index("glEnable(GL.GL_DEPTH_CLAMP)")
            < src.index("self._draw_grid("))


# -- on a real GL surface ----------------------------------------------------

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


def _square(scene, y, half, color, name):
    """A square facing the Front view, centred on (X0, y, Z0)."""
    rect = g.make_polyline([(X0 - half, y, Z0 - half), (X0 + half, y, Z0 - half),
                            (X0 + half, y, Z0 + half), (X0 - half, y, Z0 + half)],
                           closed=True)
    obj = scene.add(g.planar_face(rect), name=name)
    scene.update(obj.id, color=color)
    return obj


def _rgb(image) -> np.ndarray:
    """The image as an (h, w, 3) array, every pixel of it: a rubber band is
    a line 1.6 px wide, which sampling every other row can step over."""
    from PySide6.QtGui import QImage
    img = image.convertToFormat(QImage.Format.Format_RGBA8888)
    h, w = img.height(), img.width()
    rows = np.frombuffer(img.constBits(), np.uint8).reshape(
        h, img.bytesPerLine())
    return rows[:, :w * 4].reshape(h, w, 4)[..., :3].astype(int)


def _changed(before, after) -> int:
    """How many pixels an overlay changed. Counted against the same view
    without it rather than by its colour: gold blended over gold comes out
    a different gold wherever two layers of a ghost overlap."""
    return int((before != after).any(axis=2).sum())


def test_a_window_4mm_proud_of_its_wall_shows_in_a_front_view(window):
    w, vp = window
    # The wall first, so that a tie in depth goes to the wall: the window
    # has to be found nearer, not merely drawn later.
    _square(w.scene, Y0 + REVEAL, 1.0, (0.0, 0.0, 1.0), "wall")
    _square(w.scene, Y0, 0.5, (1.0, 0.0, 0.0), "window")
    w.scene.notify()
    vp.set_view("front")
    vp.zoom_extents()

    image = vp.grabFramebuffer()
    cx, cy = image.width() // 2, image.height() // 2
    wall = []
    for dx in (-30, -10, 0, 10, 30):
        for dy in (-30, 0, 30):
            c = image.pixelColor(cx + dx, cy + dy)
            if not c.red() > c.blue():
                wall.append(c.name())
    assert not wall, f"the wall shows through the window at {wall}"


def test_the_grid_still_draws_under_a_model_in_a_top_view(window):
    w, vp = window
    w.scene.add(g.make_box((3, 3, 10), 2, 2, 1), name="raised")
    w.scene.notify()
    vp.set_view("top")
    # well back from the box, so most of the view is the grid 10 units
    # below it, outside a slab that wraps the box
    vp.camera.target = np.array([4.0, 4.0, 10.5])
    vp.camera.distance = 30.0

    with_grid = _rgb(vp.grabFramebuffer())
    vp.grid_visible = False
    without = _rgb(vp.grabFramebuffer())
    vp.grid_visible = True

    differ = int((with_grid != without).any(axis=2).sum())
    assert differ > 100, "the grid below the model was clipped away"


def test_a_rubber_band_on_the_plane_at_home_still_draws(window):
    w, vp = window
    w.scene.add(g.make_box((X0, Y0, Z0), 1.0, 1.0, 1.0), name="peg")
    w.scene.notify()
    vp.set_view("front")
    vp.zoom_extents()
    before = _rgb(vp.grabFramebuffer())

    # on the Front construction plane, which stays at y = 0
    vp.set_preview(np.array([[[X0 - 0.2, 0.0, Z0 + 0.5],
                              [X0 + 1.2, 0.0, Z0 + 0.5]]]))
    after = _rgb(vp.grabFramebuffer())
    vp.set_preview(None)

    assert _changed(before, after) > 100, "the rubber band was clipped away"


def test_a_ghost_beyond_the_model_still_draws(window):
    w, vp = window
    w.scene.add(g.make_box((X0, Y0, Z0), 1.0, 1.0, 1.0), name="peg")
    w.scene.notify()
    vp.set_view("front")
    # framed on the peg and the ground to its right, a few units across
    vp.camera.target = np.array([X0 + 1.0, Y0, Z0 + 0.5])
    vp.camera.distance = 8.0
    before = _rgb(vp.grabFramebuffer())

    # to the right of the peg and 50 m behind it, so nothing hides it
    vp.set_ghost(g.make_box((X0 + 1.5, Y0 + 50, Z0), 0.5, 0.5, 0.5))
    after = _rgb(vp.grabFramebuffer())
    vp.set_ghost(None)

    assert _changed(before, after) > 100, "the ghost was clipped away"
