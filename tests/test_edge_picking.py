"""Which edge a click lands on when several are stacked behind each other.

Reported by a tester: "No depth sorting, tricky to select edges if other edges
are behind." Edges were ranked by how close they fell to the cursor on screen
and by nothing else, so an edge on the far side of a model could take a click
away from the one drawn in front of it, and the only way to reach the near one
was to find a spot where the far one happened to be further off in 2D.
"""

import numpy as np
import pytest

from serpentine3d.core import geometry
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui import viewport as vp_mod


def _viewport(scene):
    view = vp_mod.Viewport(scene, SelectionManager(scene))
    view.resize(800, 600)
    view.camera.set_standard_view("front")     # parallel, looking along +Y
    # Framed by hand rather than by zoom-to-fit. What is under test is which
    # of two edges wins a click, and that needs them landing a few pixels
    # apart — a property of the framing, which is not this test's subject and
    # should not be able to break it. At this distance the view is 60 units
    # tall over 600 pixels, so the 0.4 between them is 4 pixels.
    view.camera.distance = 72.46
    return view


def _screen(view, obj):
    """(x, y, depth) at the middle of the object's first edge segment."""
    pts = obj.mesh.edge_segments.reshape(-1, 3)[:2]
    scr = view.camera.project(pts, view.width(), view.height())
    return float(scr[:, 0].mean()), float(scr[:, 1].mean()), \
        float(scr[:, 2].mean())


@pytest.fixture
def stacked():
    """Two vertical lines, one behind the other, near enough to compete.

    Seen from the front they land about four pixels apart, well inside the
    pick radius, so a click between them is a genuine choice between the two.
    """
    scene = Scene()
    near = scene.add(geometry.make_polyline([(0.0, -20.0, -10.0),
                                             (0.0, -20.0, 10.0)]),
                     name="near")
    far = scene.add(geometry.make_polyline([(0.4, 20.0, -10.0),
                                            (0.4, 20.0, 10.0)]),
                    name="far")
    return scene, near, far


def test_the_edge_in_front_wins_the_click(stacked):
    """Both are under the cursor and the far one is the closer in 2D.

    That is the reported case: aiming at the near edge is not enough, because
    a stray edge behind it lands nearer the pixel you clicked.
    """
    scene, near, far = stacked
    view = _viewport(scene)
    x_near, _, d_near = _screen(view, near)
    x_far, y_far, d_far = _screen(view, far)
    px, py = x_far - 0.6, y_far

    assert d_near < d_far, "fixture is upside down: 'near' is not nearer"
    assert abs(x_near - px) < vp_mod.PICK_RADIUS_PX, "near edge out of reach"
    assert abs(x_far - px) < abs(x_near - px), \
        "far edge is not the tempting one"

    hit = view.pick_subobject(px, py)
    assert hit is not None, "nothing was picked at all"
    assert hit[0] == near.id, "picked the edge behind the one in front"


def test_a_far_edge_on_its_own_is_still_pickable(stacked):
    """Depth decides between candidates; it does not veto a lone one."""
    scene, near, far = stacked
    view = _viewport(scene)
    x_near, _, _ = _screen(view, near)
    x_far, y_far, _ = _screen(view, far)
    px = x_far + vp_mod.PICK_RADIUS_PX * 0.8
    assert abs(x_near - px) > vp_mod.PICK_RADIUS_PX, "near edge still in reach"

    hit = view.pick_subobject(px, y_far)
    assert hit is not None and hit[0] == far.id


def test_the_nearer_of_two_edges_on_one_object_wins():
    """The same ordering has to hold inside a single object, where the pick

    used to take whichever segment sat closest to the cursor in 2D.
    """
    scene = Scene()
    box = scene.add(geometry.make_box((-5.0, -5.0, -5.0), 10.0, 10.0, 10.0),
                    name="box")
    view = _viewport(scene)

    segs = box.mesh.edge_segments.reshape(-1, 3)
    scr = view.camera.project(segs, view.width(), view.height())
    # a vertical corner: the box's front and back edges stack up here
    px, py = float(scr[0, 0]), float(scr[0, 1])

    hit = view.pick_subobject(px, py)
    assert hit is not None and hit[1] == "edge"

    d2 = (scr[:, 0] - px) ** 2 + (scr[:, 1] - py) ** 2
    within = (d2 <= vp_mod.PICK_RADIUS_PX ** 2) & (scr[:, 2] > 0)
    assert within.sum() >= 4, "no competing edge here; the test proves nothing"

    on_hit = np.repeat(box.mesh.edge_of_segment, 2) == hit[2]
    assert float(scr[on_hit & within, 2].min()) == pytest.approx(
        float(scr[within, 2].min()), abs=1e-6), \
        "picked an edge that is not the front-most one under the cursor"
