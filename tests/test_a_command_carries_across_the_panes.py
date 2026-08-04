"""Start a shape in one pane, finish it in another.

It did not work, and the reason was not the command: a Front or a Right pane
could not produce a point at all. Every pane drew on the world XY plane, and
a pane looking along that plane sends its pick ray straight down it, parallel,
never meeting it. `world_point_at` returned None, so the move emitted nothing
and the click had nothing to place. Half the panes in a four-pane layout were
somewhere you could look but not draw.

A pane set to a named standard view draws on the plane that view faces. Then
a line begun in Top and finished in Front is a line with height, which is the
whole reason for having the other three panes up.

A plane set by hand is a decision already made and a later view change leaves
it alone.
"""

import numpy as np
import pytest

from serpentine3d.app import MainWindow
from serpentine3d.core import cplane as cp
from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui.viewport import Viewport


@pytest.fixture
def vp():
    s = Scene()
    v = Viewport(s, SelectionManager(s))
    v.resize(400, 300)
    return v


# -- a pane you can look at is a pane you can draw in --

@pytest.mark.parametrize("view", ["top", "front", "right", "left", "back",
                                  "bottom", "perspective", "isometric"])
def test_every_pane_can_be_picked_in(vp, view):
    vp.set_view(view)
    assert vp.world_point_at(150.0, 120.0) is not None, view


def test_the_point_lands_on_the_plane_the_pane_faces(vp):
    """Front looks along -Y, so what you draw there is flat in Y and has the
    height the world XY plane cannot give you."""
    vp.set_view("front")
    a = vp.world_point_at(120.0, 100.0)
    b = vp.world_point_at(260.0, 200.0)
    assert abs(a[1]) < 1e-6 and abs(b[1]) < 1e-6
    assert abs(a[0] - b[0]) > 1e-6 and abs(a[2] - b[2]) > 1e-6


def test_right_draws_flat_in_x(vp):
    vp.set_view("right")
    a = vp.world_point_at(120.0, 100.0)
    b = vp.world_point_at(260.0, 200.0)
    assert abs(a[0]) < 1e-6 and abs(b[0]) < 1e-6
    assert abs(a[1] - b[1]) > 1e-6 and abs(a[2] - b[2]) > 1e-6


def test_top_and_perspective_still_draw_on_world_xy(vp):
    for view in ("top", "perspective"):
        vp.set_view(view)
        assert vp.cplane.is_world_xy(), view
        assert abs(vp.world_point_at(150.0, 120.0)[2]) < 1e-9


# -- a plane you set yourself is a decision, not a default --

def test_a_plane_set_by_hand_survives_a_view_change(vp):
    mine = cp.from_three_points((1, 2, 3), (2, 2, 3), (1, 3, 3))
    vp.set_cplane(mine)
    vp.set_view("front")
    assert vp.cplane is mine


def test_asking_for_the_world_plane_back_lets_the_views_speak_again(vp):
    vp.set_cplane(cp.from_three_points((1, 2, 3), (2, 2, 3), (1, 3, 3)))
    vp.set_cplane(cp.PRESETS["world"]())
    vp.set_view("front")
    assert np.allclose(vp.cplane.normal, (0, -1, 0))


# -- and in the layout the user actually has up --

def test_the_quad_panes_come_up_on_their_own_planes():
    w = MainWindow()
    w.set_view_layout("quad")
    normals = {v._view_name: tuple(np.round(v.cplane.normal, 6))
               for v in w.all_viewports()}
    assert normals["top"] == (0.0, 0.0, 1.0)
    assert normals["front"] == (0.0, -1.0, 0.0)
    assert normals["right"] == (1.0, 0.0, 0.0)
    w.close()


def test_a_line_begun_in_top_can_be_finished_in_front():
    """The point of the whole thing: the second pane gives the first one's
    drawing a height, and one line comes out of the two picks."""
    w = MainWindow()
    w.set_view_layout("quad")
    panes = {v._view_name: v for v in w.all_viewports()}
    for v in panes.values():
        v.resize(400, 300)
    w.processor.run("line")
    start = panes["top"].world_point_at(150.0, 120.0)
    w.processor.provide(start)
    end = panes["front"].world_point_at(260.0, 90.0)
    assert end is not None, "the front pane could not name a point"
    w.processor.provide(end)
    assert not w.processor.busy
    drawn = list(w.scene.objects.values())[-1]
    (mn, mx) = g.bbox(drawn.shape)
    assert mx[2] - mn[2] > 1e-6, "the line came out flat"
    w.mark_saved()         # or closing asks about saving and waits for ever
    w.close()
