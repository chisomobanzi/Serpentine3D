"""Hold Ctrl, drag an arrow, and the line you are holding grows a surface.

Drawing a line and pulling it into a plane is the quickest way there is to
get a surface, and the gumball is already sitting on the line with an arrow
pointing the way. It only ever moved what it was holding, so making a surface
out of a line meant leaving the gumball, typing extrude and picking the line
again.

The handle for it is the filled box on each axis, which is where Rhino puts
it and where scale used to be. Scale moves out past the arrowhead as a hollow
box on the end of a dashed leader, so the two are told apart by their look
rather than by a key you have to be holding, and neither of them asks you to
combine a drag with the keyboard. The filled box only appears where there is
something to grow, so it says as much by being there.

Ctrl and a translate arrow does the same thing, for the hand that already
knows it from Rhino.
"""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui import gumball as gb
from serpentine3d.ui.viewport import Viewport

CTRL = Qt.KeyboardModifier.ControlModifier
NONE = Qt.KeyboardModifier.NoModifier
Z_ARROW = ("move", 2)
X_ARROW = ("move", 0)
Z_BOX = ("ext", 2)


@pytest.fixture
def pane():
    """A pane looking at the drawing the way it does when it opens."""
    QApplication.instance() or QApplication([])
    scene = Scene()
    vp = Viewport(scene, SelectionManager(scene))
    vp.resize(800, 600)
    vp.grid_snap = False
    vp.camera.target = np.array([5.0, 0.0, 0.0])
    vp.camera.distance = 60.0
    return vp


def _press_at(vp, anchor):
    """Screen coordinates of a point, for a press that starts a drag."""
    scr = vp.camera.project(np.asarray([anchor], float),
                            vp.width(), vp.height())
    return float(scr[0][0]), float(scr[0][1])


def _grab(vp, handle=Z_ARROW, modifiers=CTRL):
    """Take hold of a handle, as a press on it would."""
    anchor, _axes = vp.gumball.anchor_and_axes()
    px, py = _press_at(vp, anchor)
    return vp.gumball.begin_drag(handle, px, py, modifiers)


def _handle_at(vp, along, axis=2):
    """Where on screen a handle that far out along an axis is drawn."""
    anchor, axes = vp.gumball.anchor_and_axes()
    size = vp.gumball._size_world(anchor)
    return _press_at(vp, anchor + np.asarray(axes[axis], float) * along * size)


def _line(vp, a=(0.0, 0.0, 0.0), b=(10.0, 0.0, 0.0)):
    obj = vp.scene.add(g.make_line(a, b))
    vp.selection.set([obj.id])
    return obj


def _others(vp, obj):
    return [o for o in vp.scene.all() if o.id != obj.id]


def _height(shape):
    lo, hi = g.bbox(shape)
    return hi[2] - lo[2]


# -- the two boxes -----------------------------------------------------------

def test_the_filled_box_on_each_axis_is_the_extrude_handle(pane):
    _line(pane)
    assert pane.gumball.hit_test(*_handle_at(pane, gb.EXT_POS)) == Z_BOX


def test_scale_is_the_hollow_box_out_past_the_arrowhead(pane):
    """The two are told apart by their look and their distance, which is
    what saves you having to hold anything down."""
    _line(pane)
    assert gb.SCALE_POS > gb.CONE1 > gb.EXT_POS
    assert pane.gumball.hit_test(*_handle_at(pane, gb.SCALE_POS)) \
        == ("scale", 2)


def test_a_solid_has_nothing_to_grow_so_it_shows_no_filled_box(pane):
    box = pane.scene.add(g.make_box((0, 0, 0), 4, 4, 4))
    pane.selection.set([box.id])
    assert pane.gumball.hit_test(*_handle_at(pane, gb.EXT_POS)) != Z_BOX


def test_held_control_points_show_no_filled_box_either(pane):
    line = _line(pane)
    pane.cv_enabled.add(line.id)
    pane.selection.set([])
    pane.selection.set_subobjects([(line.id, "cv", 1)])
    assert pane.gumball.hit_test(*_handle_at(pane, gb.EXT_POS)) != Z_BOX


def test_a_held_edge_gets_a_filled_box_of_its_own(pane):
    """The edge gumball is one outward arrow, and the box goes on it, so the
    edge is not the one case that still needs the keyboard."""
    box = pane.scene.add(g.make_box((0, 0, 0), 4, 4, 4))
    pane.selection.set([box.id])
    pane.selection.set_subobjects([(box.id, "edge", 0)])
    assert pane.gumball.hit_test(*_handle_at(pane, gb.EXT_POS)) == Z_BOX


def test_the_box_grows_it_with_nothing_held_down(pane):
    line = _line(pane)
    assert _grab(pane, Z_BOX, NONE)
    pane.gumball.apply_scalar(10.0)
    pane.gumball.end_drag()
    made = _others(pane, line)
    assert len(made) == 1 and made[0].kind == "surface"
    assert g.surface_area(made[0].shape) == pytest.approx(100.0, rel=1e-6)


def test_a_typed_distance_works_on_the_box_too(pane):
    line = _line(pane)
    _grab(pane, Z_BOX, NONE)
    for ch in "12":
        pane.gumball.type_char(ch)
    assert pane.gumball.commit_typed()
    assert _height(_others(pane, line)[0].shape) == pytest.approx(12.0,
                                                                 abs=1e-6)


def test_a_box_with_nothing_to_grow_refuses_rather_than_moving_it(pane):
    """Better to do nothing than to quietly move the solid you were trying
    to grow."""
    box = pane.scene.add(g.make_box((0, 0, 0), 4, 4, 4))
    pane.selection.set([box.id])
    assert _grab(pane, Z_BOX, NONE) is False
    lo, _hi = g.bbox(pane.scene.get(box.id).shape)
    assert lo[2] == pytest.approx(0.0, abs=1e-6)


# -- a line becomes a surface -------------------------------------------------

def test_ctrl_dragging_an_arrow_turns_a_line_into_a_surface(pane):
    line = _line(pane)
    assert _grab(pane)
    pane.gumball.apply_scalar(10.0)
    pane.gumball.end_drag()
    made = _others(pane, line)
    assert len(made) == 1
    assert made[0].kind == "surface"
    assert g.surface_area(made[0].shape) == pytest.approx(100.0, rel=1e-6)


def test_the_line_you_pulled_the_surface_off_is_still_there(pane):
    """A curve is drawing you keep: the surface stands on it, it does not
    eat it."""
    line = _line(pane)
    _grab(pane)
    pane.gumball.apply_scalar(10.0)
    pane.gumball.end_drag()
    still = pane.scene.get(line.id)
    assert still is not None and still.kind == "curve"
    assert g.curve_length(still.shape) == pytest.approx(10.0, rel=1e-6)


def test_the_surface_stands_along_the_arrow_you_dragged(pane):
    line = _line(pane)
    _grab(pane, Z_ARROW)
    pane.gumball.apply_scalar(4.0)
    pane.gumball.end_drag()
    assert _height(_others(pane, line)[0].shape) == pytest.approx(4.0,
                                                                 abs=1e-6)


def test_the_arrow_the_other_way_pulls_the_surface_the_other_way(pane):
    line = _line(pane)
    _grab(pane, X_ARROW)
    pane.gumball.apply_scalar(6.0)
    pane.gumball.end_drag()
    lo, hi = g.bbox(_others(pane, line)[0].shape)
    assert hi[0] - lo[0] == pytest.approx(16.0, abs=1e-6)
    assert hi[2] - lo[2] == pytest.approx(0.0, abs=1e-6)


def test_a_plain_drag_still_only_moves_the_line(pane):
    line = _line(pane)
    assert _grab(pane, Z_ARROW, NONE)
    pane.gumball.apply_scalar(10.0)
    pane.gumball.end_drag()
    assert _others(pane, line) == []
    assert _height(pane.scene.get(line.id).shape) == pytest.approx(0.0,
                                                                  abs=1e-6)


def test_a_closed_curve_comes_back_as_a_solid(pane):
    """Pull a rectangle up and what you wanted was the box, not the tube."""
    rect = pane.scene.add(g.make_polyline(
        [(0, 0, 0), (10, 0, 0), (10, 6, 0), (0, 6, 0)], closed=True))
    pane.selection.set([rect.id])
    _grab(pane)
    pane.gumball.apply_scalar(5.0)
    pane.gumball.end_drag()
    made = _others(pane, rect)
    assert len(made) == 1
    assert g.volume(made[0].shape) == pytest.approx(300.0, rel=1e-6)


# -- a surface becomes a solid ------------------------------------------------

def test_a_surface_pulled_the_same_way_becomes_a_solid(pane):
    """And it is the same object: a spare surface buried in the face of the
    solid it grew into is clutter you cannot pick."""
    srf = pane.scene.add(g.planar_face(g.make_polyline(
        [(0, 0, 0), (10, 0, 0), (10, 6, 0), (0, 6, 0)], closed=True)))
    pane.selection.set([srf.id])
    _grab(pane)
    pane.gumball.apply_scalar(5.0)
    pane.gumball.end_drag()
    assert _others(pane, srf) == []
    assert g.volume(pane.scene.get(srf.id).shape) == pytest.approx(300.0,
                                                                  rel=1e-6)


def test_a_solid_has_nowhere_to_grow_so_it_just_moves(pane):
    box = pane.scene.add(g.make_box((0, 0, 0), 4, 4, 4))
    pane.selection.set([box.id])
    assert _grab(pane)
    pane.gumball.apply_scalar(3.0)
    pane.gumball.end_drag()
    assert _others(pane, box) == []
    lo, _hi = g.bbox(pane.scene.get(box.id).shape)
    assert lo[2] == pytest.approx(3.0, abs=1e-6)


# -- an edge picked off a solid ----------------------------------------------

def test_ctrl_dragging_a_held_edge_makes_a_surface_from_it(pane):
    box = pane.scene.add(g.make_box((0, 0, 0), 4, 4, 4))
    pane.selection.set([box.id])
    pane.selection.set_subobjects([(box.id, "edge", 0)])
    edge = g.edges_of(box.shape)[0]
    assert _grab(pane)
    pane.gumball.apply_scalar(2.0)
    pane.gumball.end_drag()
    made = _others(pane, box)
    assert len(made) == 1
    assert made[0].kind == "surface"
    assert g.surface_area(made[0].shape) == pytest.approx(
        g.curve_length(edge) * 2.0, rel=1e-6)
    assert g.volume(pane.scene.get(box.id).shape) == pytest.approx(64.0,
                                                                   rel=1e-6)


# -- the drag itself ---------------------------------------------------------

def test_the_readout_says_extrude_and_how_far(pane):
    _line(pane)
    _grab(pane)
    assert pane.gumball.apply_scalar(7.5).startswith("extrude")


def test_dragging_back_to_nothing_leaves_nothing_behind(pane):
    """Out and back again is where you started, not a stray copy of the
    line."""
    line = _line(pane)
    _grab(pane)
    pane.gumball.apply_scalar(8.0)
    pane.gumball.apply_scalar(0.0)
    pane.gumball.end_drag()
    assert _others(pane, line) == []


def test_letting_it_go_leaves_you_holding_the_new_surface(pane):
    line = _line(pane)
    _grab(pane)
    pane.gumball.apply_scalar(3.0)
    pane.gumball.end_drag()
    assert pane.selection.ids == [_others(pane, line)[0].id]


def test_cancelling_takes_back_what_the_drag_made(pane):
    line = _line(pane)
    _grab(pane)
    pane.gumball.apply_scalar(9.0)
    pane.gumball.cancel_drag()
    assert _others(pane, line) == []
    assert pane.scene.get(line.id).kind == "curve"


def test_a_typed_distance_extrudes_by_that_much(pane):
    line = _line(pane)
    _grab(pane)
    for ch in "12":
        pane.gumball.type_char(ch)
    assert pane.gumball.commit_typed()
    assert _height(_others(pane, line)[0].shape) == pytest.approx(12.0,
                                                                 abs=1e-6)


def test_held_control_points_are_moved_and_never_extruded(pane):
    """Ctrl is an extrude only where there is something to extrude."""
    line = _line(pane)
    pane.cv_enabled.add(line.id)
    pane.selection.set([])
    pane.selection.set_subobjects([(line.id, "cv", 1)])
    assert _grab(pane)
    pane.gumball.apply_scalar(5.0)
    pane.gumball.end_drag()
    assert _others(pane, line) == []
    pts = np.asarray(g.get_control_points(pane.scene.get(line.id).shape),
                     float)
    assert pts[1][2] == pytest.approx(5.0, abs=1e-6)
