"""Zoom Selected should fill the viewport with what you selected.

It framed the bounding *sphere* of the selection in the *vertical* field of
view, and then backed off another 15%. Three things wrong with that at once:
the sphere around a box is much bigger than the box (half the diagonal, not
half the height), the viewport is wider than it is tall so the horizontal
room went unused, and the extra 15% was on top of both. A wide flat model —
a set, a floor plan, most of what anyone zooms to — came back filling under
half the frame.

The check here is what you would check by eye: project the corners of what
was framed and see where they land. Filling the frame means the tighter of
the two directions reaches the edge; not overshooting means neither goes
past it.
"""

import numpy as np
import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager

pytest.importorskip("PySide6")

# How close to the edge counts as filled. Not 1.0: a hair of margin keeps
# the outermost edge from sitting exactly on the boundary pixel.
FILLS = 0.92


@pytest.fixture
def view():
    from serpentine3d.ui.viewport import Viewport
    scene = Scene()
    sel = SelectionManager(scene)
    vp = Viewport(scene, sel)
    vp.resize(1600, 900)
    return vp


def corners(mn, mx):
    mn, mx = np.asarray(mn, float), np.asarray(mx, float)
    return np.array([[x, y, z] for x in (mn[0], mx[0])
                     for y in (mn[1], mx[1])
                     for z in (mn[2], mx[2])], float)


def ndc_extent(vp, pts) -> tuple[float, float]:
    """How far across the frame the points reach, as a fraction of half its
    width and half its height. 1.0 is the edge."""
    w, h = vp.width(), vp.height()
    mvp = vp.camera.proj_matrix(w, h) @ vp.camera.view_matrix()
    clip = np.hstack([pts, np.ones((len(pts), 1))]) @ mvp.T
    ndc = clip[:, :3] / clip[:, 3:4]
    return float(np.abs(ndc[:, 0]).max()), float(np.abs(ndc[:, 1]).max())


def test_zoom_selected_fills_the_frame(view):
    """The shape that shows the bug: wide, flat, off to one side."""
    obj = view.scene.add(g.make_box((100, 100, 20), 40, 30, 5))
    view.selection.set([obj.id])
    assert view.zoom_selected()

    x, y = ndc_extent(view, corners(*obj.bbox()))
    assert max(x, y) >= FILLS, (
        f"selection reaches only {max(x, y):.2f} of the frame")
    assert max(x, y) <= 1.0, f"selection runs off the frame at {max(x, y):.2f}"


def test_zoom_selected_uses_the_width_of_a_wide_viewport(view):
    """A wide viewport has room at the sides, so a plan wider than it is
    deep should come back filling the width. Fitting it to the height
    instead — which is what ignoring the window's shape does — leaves it
    reaching barely half way across."""
    obj = view.scene.add(g.make_box((0, 0, 0), 100, 40, 2))
    view.selection.set([obj.id])
    view.camera.set_standard_view("top")
    view.zoom_selected()

    x, y = ndc_extent(view, corners(*obj.bbox()))
    assert x >= FILLS, f"width unused: reaches {x:.2f}"
    assert y <= 1.0


def test_a_taller_viewport_frames_the_same_thing_differently(view):
    """The fit has to read the shape of the window, not assume one."""
    obj = view.scene.add(g.make_box((0, 0, 0), 60, 60, 2))
    view.selection.set([obj.id])
    view.camera.set_standard_view("top")

    view.zoom_selected()
    wide = view.camera.distance
    view.resize(900, 1600)
    view.zoom_selected()
    assert view.camera.distance > wide, (
        "a portrait window has to pull back further for a square plan")
    x, y = ndc_extent(view, corners(*obj.bbox()))
    assert max(x, y) >= FILLS
    assert max(x, y) <= 1.0


def test_zoom_selected_fills_a_parallel_view_too(view):
    obj = view.scene.add(g.make_box((5, 5, 0), 20, 10, 10))
    view.selection.set([obj.id])
    view.camera.set_standard_view("front")
    assert view.camera.projection == "parallel"
    view.zoom_selected()

    x, y = ndc_extent(view, corners(*obj.bbox()))
    assert max(x, y) >= FILLS
    assert max(x, y) <= 1.0


def test_zoom_selected_frames_several_objects_together(view):
    a = view.scene.add(g.make_box((0, 0, 0), 5, 5, 5))
    b = view.scene.add(g.make_box((50, 40, 10), 5, 5, 5))
    view.selection.set([a.id, b.id])
    view.zoom_selected()

    mn = np.minimum(a.bbox()[0], b.bbox()[0])
    mx = np.maximum(a.bbox()[1], b.bbox()[1])
    assert np.allclose(view.camera.target, (np.array(mn) + mx) / 2)
    x, y = ndc_extent(view, corners(mn, mx))
    assert max(x, y) >= FILLS
    assert max(x, y) <= 1.0


def test_zoom_extents_fills_the_frame(view):
    """Same fit, whether it is the selection or the whole drawing."""
    view.scene.add(g.make_box((0, 0, 0), 30, 20, 4))
    view.scene.add(g.make_box((-40, 10, 0), 6, 6, 6))
    view.zoom_extents()

    x, y = ndc_extent(view, corners(*view.scene.bbox()))
    assert max(x, y) >= FILLS
    assert max(x, y) <= 1.0


def test_a_selection_with_no_size_still_leaves_a_usable_view(view):
    """A point has no size to fill the frame with; it must not put the
    camera on top of it or divide by nothing."""
    obj = view.scene.add(g.make_point((3, 4, 5)))
    view.selection.set([obj.id])
    view.zoom_selected()

    assert np.allclose(view.camera.target, (3, 4, 5))
    assert 0.1 < view.camera.distance < 1e4
    assert np.isfinite(view.camera.position).all()


def test_zoom_selected_says_no_when_nothing_is_selected(view):
    assert view.zoom_selected() is False
