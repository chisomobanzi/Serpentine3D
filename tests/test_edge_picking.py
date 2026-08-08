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


# -- edges against faces -----------------------------------------------------
#
# Depth ordered the edges against each other, but the two kinds were never
# ranked against one another: every edge within reach of the cursor was
# resolved and returned before a face was so much as looked at. On a solid
# that means the edges around the hidden far corner take the click off the
# face you are pointing at, and there is nowhere on that face to click to
# get it, because the far corner sits in the middle of the shape.


def _solid_view(distance: float = 40.0):
    """A cube in three-quarter view, where its hidden edges land inside it.

    Seen this way the far corner projects to the middle of the silhouette,
    so a click there is over three edges nobody can see and over the face
    that hides them.
    """
    scene = Scene()
    box = scene.add(geometry.make_box((-5.0, -5.0, -5.0), 10.0, 10.0, 10.0),
                    name="box")
    view = vp_mod.Viewport(scene, SelectionManager(scene))
    view.resize(800, 600)
    view.camera.set_standard_view("perspective")
    view.camera.target = np.zeros(3)
    view.camera.distance = distance
    return scene, box, view


def _corner_pixel(view, box, farthest: bool):
    """Where a corner of the box lands, and how far off it is."""
    verts = np.asarray(box.mesh.vertices, float)
    away = np.linalg.norm(verts - view.camera.position, axis=1)
    i = int(np.argmax(away) if farthest else np.argmin(away))
    scr = view.camera.project(verts, view.width(), view.height())
    return float(scr[i, 0]), float(scr[i, 1]), float(scr[i, 2])


def _nearest_face_hit(view, box, px, py):
    """Ray distance to the first triangle under a pixel, or inf."""
    from serpentine3d.utils.math3d import ray_triangle_hits
    verts = np.asarray(box.mesh.vertices, float)
    tris = box.mesh.triangles
    origin, direction = view.camera.ray_through(px, py, view.width(),
                                                view.height())
    t = ray_triangle_hits(origin, direction, verts[tris[:, 0]],
                          verts[tris[:, 1]], verts[tris[:, 2]])
    t = np.where(np.isfinite(t), t, np.inf)
    return float(t.min()) if len(t) else np.inf


def test_the_face_in_front_beats_the_edges_hidden_behind_it():
    """Click into a solid and you get it, not the corner round the back."""
    scene, box, view = _solid_view()
    px, py, depth = _corner_pixel(view, box, farthest=True)

    segs = np.asarray(box.mesh.edge_segments, float).reshape(-1, 3)
    scr = view.camera.project(segs, view.width(), view.height())
    d2 = (scr[:, 0] - px) ** 2 + (scr[:, 1] - py) ** 2
    assert (d2 <= vp_mod.PICK_RADIUS_PX ** 2).any(), \
        "no hidden edge under the cursor; the test proves nothing"
    assert _nearest_face_hit(view, box, px, py) + 5.0 < depth, \
        "the far corner is not actually behind a face here"

    hit = view.pick_subobject(px, py)
    assert hit is not None, "nothing was picked at all"
    assert hit[1] == "face", "picked an edge hidden behind the face clicked on"


def test_an_edge_you_can_see_still_beats_the_face_behind_it():
    """Edges stay the easier target wherever they are actually drawn.

    They are a couple of pixels wide against a whole face, so ranking the
    two strictly on depth would put every edge out of reach: the face it
    borders is at the same distance and covers far more of the cursor.
    """
    scene, box, view = _solid_view()
    px, py, _ = _corner_pixel(view, box, farthest=False)

    hit = view.pick_subobject(px, py)
    assert hit is not None, "nothing was picked at all"
    assert hit[1] == "edge", "a visible edge lost its click to the face"


def test_wireframe_has_nothing_in_front_to_hide_behind():
    """No faces are drawn, so the edge behind is the edge you meant."""
    scene, box, view = _solid_view()
    view.display_mode = "wireframe"
    px, py, _ = _corner_pixel(view, box, farthest=True)

    hit = view.pick_subobject(px, py)
    assert hit is not None, "nothing was picked at all"
    assert hit[1] == "edge", "picked a face in a view that draws none"


# -- control points ----------------------------------------------------------
#
# The same complaint again one level down. Control points were ranked on
# nothing but how close they fell to the cursor in 2D, so on any shape with
# a back side — which is every surface seen face on — the point behind took
# the click whenever it happened to land a pixel nearer.


def _cv_line(near_at, far_at):
    """A line with a control point at each end and points turned on."""
    scene = Scene()
    line = scene.add(geometry.make_line(near_at, far_at), name="line")
    view = _viewport(scene)
    view.cv_enabled.add(line.id)
    pts = np.asarray(view._cv_points(line), float)
    scr = view.camera.project(pts, view.width(), view.height())
    assert scr[0, 2] < scr[1, 2], "the first control point is not the near one"
    return line, view, pts, scr


def test_the_control_point_in_front_wins_the_click():
    """Aimed at the far point, and the near one is well within reach."""
    line, view, pts, scr = _cv_line((0.0, 0.0, 0.0), (0.3, 40.0, 0.0))
    gap = float(np.hypot(scr[0, 0] - scr[1, 0], scr[0, 1] - scr[1, 1]))
    assert 0.5 < gap < vp_mod.PICK_DEPTH_BAND_PX, \
        f"the two points are {gap:.1f}px apart; the test proves nothing"

    hit = view._cv_hit(float(scr[1, 0]), float(scr[1, 1]))
    assert hit is not None, "nothing was picked at all"
    assert hit[1] == 0, "picked the control point behind the one in front"


def test_a_control_point_far_enough_off_is_not_the_one_you_meant():
    """Depth only settles points you could plausibly have been aiming at.

    Past the band the click goes where it was pointed, or a point at the
    front of the model would swallow every click aimed anywhere near it.
    """
    line, view, pts, scr = _cv_line((0.0, 0.0, 0.0), (2.0, 40.0, 0.0))
    gap = float(np.hypot(scr[0, 0] - scr[1, 0], scr[0, 1] - scr[1, 1]))
    assert gap > vp_mod.PICK_DEPTH_BAND_PX, \
        f"the two points are only {gap:.1f}px apart; the test proves nothing"

    hit = view._cv_hit(float(scr[1, 0]), float(scr[1, 1]))
    assert hit is not None, "nothing was picked at all"
    assert hit[1] == 1, "a distant point in front stole a click aimed past it"
