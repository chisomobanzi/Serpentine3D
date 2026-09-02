"""One object holding many separate curves must not take a viewport down.

Reported by a user: select the curves make2d produced, press Delete, and one
of the four panes stops drawing while the other three carry on. The cause is
nowhere near make2d. `shape_kind` calls a compound of loose edges a "curve",
because that is what it looks like and what every display path wants to hear,
but `curve_endpoints` only knows edges and wires and raises "Not a curve" on
a compound. Between those two sits `sweep_adds_nothing`, which the gumball
asks once per axis, from inside `paint`, to decide whether to draw the
extrude box. A GeometryError there escapes through `paintGL`, and that pane
is finished for the rest of the session.

make2d is only the usual way to end up holding one of these. Explode, import
a DXF of loose linework, or any other multi-curve object gets there too, so
the fix belongs in the geometry, and the gumball is hardened as well: a hint
about which handles to draw is never worth a dead viewport.
"""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui.viewport import Viewport


def _loose_curves():
    """What make2d hands back: several separate edges in one object, not a
    wire — they do not meet end to end."""
    return g.make_compound([g.make_line((0, 0, 0), (10, 0, 0)),
                            g.make_line((0, 5, 0), (10, 5, 0)),
                            g.make_line((0, 0, 0), (0, 5, 0))])


# --- the geometry question underneath --------------------------------------

def test_a_compound_of_curves_is_still_called_a_curve():
    """Guarding the assumption the rest of this file rests on. If this ever
    changes, the display paths that branch on kind need to change with it."""
    assert g.shape_kind(_loose_curves()) == "curve"


def test_asking_whether_a_sweep_adds_anything_answers_for_a_compound():
    """It used to raise. Three horizontal-ish lines pulled up in z sweep out
    three surfaces, so the honest answer is that the sweep adds plenty."""
    assert g.sweep_adds_nothing(_loose_curves(), (0, 0, 1)) is False


def test_a_compound_adds_nothing_only_when_none_of_its_pieces_would():
    """Two parallel straight lines swept along their own direction stay
    lines. Nothing is added, and the extrude box should not be drawn."""
    flat = g.make_compound([g.make_line((0, 0, 0), (10, 0, 0)),
                            g.make_line((0, 5, 0), (10, 5, 0))])
    assert g.sweep_adds_nothing(flat, (1, 0, 0)) is True
    assert g.sweep_adds_nothing(flat, (0, 1, 0)) is False


def test_one_piece_that_would_grow_is_enough():
    """A straight line and a bent one, swept along the straight one's own
    length: the bend still sweeps out a surface, so the answer is no."""
    mixed = g.make_compound([
        g.make_line((0, 0, 0), (10, 0, 0)),
        g.make_arc_3pt((0, 5, 0), (5, 8, 0), (10, 5, 0))])
    assert g.sweep_adds_nothing(mixed, (1, 0, 0)) is False


# --- and the pane that was dying -------------------------------------------

@pytest.fixture
def pane():
    QApplication.instance() or QApplication([])
    scene = Scene()
    vp = Viewport(scene, SelectionManager(scene))
    vp.resize(800, 600)
    vp.camera.target = np.array([5.0, 2.5, 0.0])
    vp.camera.distance = 60.0
    return vp


def test_the_gumball_can_be_asked_about_a_drawing_of_loose_curves(pane):
    """The call that came out of paintGL and killed the pane."""
    obj = pane.scene.add(_loose_curves())
    pane.selection.set([obj.id])

    for axis in ((1, 0, 0), (0, 1, 0), (0, 0, 1)):
        pane.gumball._can_extrude(axis)          # must not raise


def test_a_shape_it_cannot_measure_is_assumed_to_be_extrudable(pane,
                                                               monkeypatch):
    """Belt and braces. Whatever else turns up that the geometry cannot
    answer for, the gumball draws the handle and lets the extrude itself
    report the problem, because being wrong about a handle costs one useless
    box and being wrong here costs the pane."""
    obj = pane.scene.add(_loose_curves())
    pane.selection.set([obj.id])

    def _explode(*a, **k):
        raise g.GeometryError("no idea")

    monkeypatch.setattr(g, "sweep_adds_nothing", _explode)
    assert pane.gumball._can_extrude((0, 0, 1)) is True


def test_deleting_the_drawing_leaves_the_gumball_with_nothing_to_say(pane):
    """The actual sequence from the report: select it, delete it, and the
    next frame's gumball has an empty selection and draws nothing."""
    obj = pane.scene.add(_loose_curves())
    pane.selection.set([obj.id])
    pane.gumball._can_extrude((0, 0, 1))         # warm the per-axis cache

    pane.scene.remove(obj.id)
    pane.selection.clear()

    assert pane.gumball._can_extrude((0, 0, 1)) is False
