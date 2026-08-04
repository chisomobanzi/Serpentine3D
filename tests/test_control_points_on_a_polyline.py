"""Points on, for a polyline.

Draw a polyline, ask for its points so you can nudge a corner, and nothing
happens. Every route to a control point went through one edge's b-spline
and gave up the moment it was handed more than one, so a polyline — which
is a wire of a segment per corner, and one of the commonest things anybody
draws — was told to explode itself first. Exploding it is exactly what you
do not want: the thing you are trying to edit stops being one object.

A corner where two segments meet is one point to the eye and to the hand.
Dragging it has to take both segments with it, or the polyline comes apart
at the seam.
"""

import numpy as np
import pytest

from serpentine3d.core import geometry as g

CORNERS = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 10.0, 0.0),
           (20.0, 10.0, 0.0)]


def _near(a, b, tol=1e-6):
    return np.allclose(np.asarray(a, float), np.asarray(b, float), atol=tol)


# -- reading them off --

def test_a_polyline_has_a_control_point_at_every_corner():
    pts = g.get_control_points(g.make_polyline(CORNERS))
    assert len(pts) == len(CORNERS)
    assert _near(pts, CORNERS)


def test_a_closed_polyline_does_not_repeat_the_point_it_starts_on():
    """The last segment comes back to the first corner. That corner is one
    point, and offering it twice would let you drag half of it away."""
    pts = g.get_control_points(g.make_polyline(CORNERS, closed=True))
    assert len(pts) == len(CORNERS)


def test_a_single_line_still_reads_the_way_it_did():
    pts = g.get_control_points(g.make_line((0, 0, 0), (5, 0, 0)))
    assert len(pts) == 2
    assert _near(pts[0], (0, 0, 0)) and _near(pts[-1], (5, 0, 0))


# -- and moving them --

def test_dragging_a_corner_takes_both_its_segments_with_it():
    moved = g.move_control_point(g.make_polyline(CORNERS), 1,
                                 (10.0, -4.0, 0.0))
    pts = g.get_control_points(moved)
    assert len(pts) == len(CORNERS)
    assert _near(pts[1], (10.0, -4.0, 0.0))
    assert _near(pts[0], CORNERS[0]) and _near(pts[3], CORNERS[3])
    # still one curve, not two loose ends
    assert len(g.edges_of(moved)) == len(CORNERS) - 1
    assert g.curve_length(moved) > 0


def test_dragging_an_end_moves_only_the_segment_it_belongs_to():
    moved = g.move_control_point(g.make_polyline(CORNERS), 0,
                                 (-5.0, -5.0, 0.0))
    pts = g.get_control_points(moved)
    assert _near(pts[0], (-5.0, -5.0, 0.0))
    assert _near(pts[1:], CORNERS[1:])


def test_dragging_the_far_end_moves_only_its_own_segment():
    last = len(CORNERS) - 1
    moved = g.move_control_point(g.make_polyline(CORNERS), last,
                                 (25.0, 15.0, 0.0))
    pts = g.get_control_points(moved)
    assert _near(pts[last], (25.0, 15.0, 0.0))
    assert _near(pts[:last], CORNERS[:last])


def test_a_point_that_is_not_there_is_refused():
    with pytest.raises(g.GeometryError):
        g.move_control_point(g.make_polyline(CORNERS), 99, (0, 0, 0))


# -- what the user actually does --

def test_pointson_turns_them_on_for_a_polyline():
    import serpentine3d.commands                                # noqa: F401
    from PySide6.QtWidgets import QApplication
    from serpentine3d.commands.base import CommandContext, CommandProcessor
    from serpentine3d.core.history import History
    from serpentine3d.core.scene import Scene
    from serpentine3d.core.selection import SelectionManager
    from serpentine3d.ui.viewport import Viewport
    QApplication.instance() or QApplication([])
    scene = Scene()
    sel = SelectionManager(scene)
    vp = Viewport(scene, sel)
    ctx = CommandContext(scene, sel, History(scene), viewport=vp)
    said = []
    ctx.add_echo_listener(said.append)
    obj = scene.add(g.make_polyline(CORNERS))
    sel.set([obj.id])
    CommandProcessor(ctx).run("pointson")
    assert obj.id in vp.cv_enabled, said
    assert "Control points on for 1" in said[-1]


def test_the_viewport_finds_a_polylines_control_points():
    """The pane draws and hits from its own cache, by its own route."""
    from PySide6.QtWidgets import QApplication
    from serpentine3d.core.scene import Scene
    from serpentine3d.core.selection import SelectionManager
    from serpentine3d.ui.viewport import Viewport
    QApplication.instance() or QApplication([])
    scene = Scene()
    vp = Viewport(scene, SelectionManager(scene))
    obj = scene.add(g.make_polyline(CORNERS))
    pts = vp._cv_points(obj)
    assert pts is not None and len(pts) == len(CORNERS)
