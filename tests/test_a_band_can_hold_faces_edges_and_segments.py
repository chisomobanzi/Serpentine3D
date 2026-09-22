"""Ctrl+Shift and a dragged band hold faces, edges and segments (issue #30).

Ctrl+Shift-click takes hold of one face, edge or curve segment at a time.
Asked for: the same chord with a band, so that a row of edges or the
segments down one side of a drawing can be taken in a single sweep instead
of a click each.

The two kinds of band mean what they mean for objects. A window, dragged
left to right, holds a part only when all of it lies inside. A crossing
band, dragged right to left, holds whatever it touches, and touching has
to be measured properly: a long edge passes through a small band with
neither end inside it, and a small band dropped in the middle of a big
face has no corner of it inside at all. Both count.

Like the click, the band adds to what is held and takes no objects; a
sweep that catches nothing changes nothing. A wireframe view offers no
faces to either.
"""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager

CTRL_SHIFT = (Qt.KeyboardModifier.ControlModifier
              | Qt.KeyboardModifier.ShiftModifier)


@pytest.fixture
def vp():
    if not QApplication.instance():
        QApplication([])
    from serpentine3d.ui.viewport import Viewport
    scene = Scene()
    view = Viewport(scene, SelectionManager(scene))
    view.resize(800, 600)
    view.camera.set_standard_view("top")
    try:
        yield view
    finally:
        view.deleteLater()
        QApplication.processEvents()


def _look(vp):
    vp.zoom_extents()


def _zigzag(vp):
    """Three segments: along the bottom, up the right side, back along
    the top. Open, so the left side is empty."""
    obj = vp.scene.add(g.make_polyline(
        [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)]), name="Zigzag")
    _look(vp)
    return obj


def _box(vp):
    obj = vp.scene.add(g.make_box((0, 0, 0), 10, 10, 10), name="Box")
    _look(vp)
    return obj


def _top_face(shape):
    for i, f in enumerate(g.faces_of(shape)):
        if g.face_normal(f)[2] > 0.9:
            return i
    raise AssertionError("no upward face")


def _band_round(vp, pts, pad=6.0):
    """A screen rect a few pixels clear of where these world points land."""
    scr = vp.camera.project(np.asarray(pts, float), vp.width(), vp.height())
    return (float(scr[:, 0].min() - pad), float(scr[:, 1].min() - pad),
            float(scr[:, 0].max() + pad), float(scr[:, 1].max() + pad))


def _window(vp, rect):
    return vp._band_pick(*rect, False, CTRL_SHIFT)


def _crossing(vp, rect):
    return vp._band_pick(*rect, True, CTRL_SHIFT)


def _held(vp, kind):
    return sorted((oid, i) for oid, k, i in vp.selection.subobjects if k == kind)


# --- segments of a curve ---------------------------------------------------

def test_a_window_round_one_segment_holds_that_segment(vp):
    zz = _zigzag(vp)

    assert _window(vp, _band_round(vp, [(10, 0, 0), (10, 10, 0)])) is None

    assert _held(vp, "edge") == [(zz.id, 1)], (
        "the bottom and top segments have an end outside the window")


def test_a_crossing_band_holds_a_segment_it_only_cuts_through(vp):
    """Neither end of the segment is inside; the band sits on its middle."""
    zz = _zigzag(vp)

    _crossing(vp, _band_round(vp, [(5, 0, 0)]))

    assert _held(vp, "edge") == [(zz.id, 0)]


def test_a_crossing_band_holds_everything_it_touches(vp):
    zz = _zigzag(vp)

    _crossing(vp, _band_round(vp, [(10, 0, 0), (10, 10, 0)]))

    assert _held(vp, "edge") == [(zz.id, 0), (zz.id, 1), (zz.id, 2)], (
        "the corners it encloses are ends of the other two segments")


# --- faces and edges of a solid --------------------------------------------

def test_a_window_round_a_solid_holds_every_face_and_edge(vp):
    box = _box(vp)
    corners = [(x, y, z) for x in (0, 10) for y in (0, 10) for z in (0, 10)]

    _window(vp, _band_round(vp, corners))

    assert len(_held(vp, "face")) == 6
    assert len(_held(vp, "edge")) == 12
    assert all(oid == box.id for oid, _ in _held(vp, "face"))


def test_a_crossing_band_in_the_middle_of_a_face_holds_it(vp):
    """No corner inside, no edge crossed: the band lies wholly on the face."""
    box = _box(vp)

    _crossing(vp, _band_round(vp, [(5, 5, 10)]))

    assert (box.id, _top_face(box.shape)) in _held(vp, "face")
    assert _held(vp, "edge") == [], "the band touched no edge"


def test_a_window_that_cuts_an_edge_off_does_not_hold_it(vp):
    box = _box(vp)
    lower_left = [(x, y, z) for x in (0, 5) for y in (0, 5) for z in (0, 10)]

    _window(vp, _band_round(vp, lower_left))

    edges = _held(vp, "edge")
    # the four vertical edges at (0,0), and nothing lying along X or Y,
    # which all run on to 10 and out of the window
    assert len(edges) == 1, edges
    assert box.id == edges[0][0]


def test_wireframe_offers_no_faces(vp):
    box = _box(vp)
    vp.display_mode = "wireframe"
    corners = [(x, y, z) for x in (0, 10) for y in (0, 10) for z in (0, 10)]

    _window(vp, _band_round(vp, corners))

    assert _held(vp, "face") == []
    assert len(_held(vp, "edge")) == 12
    assert box.id == _held(vp, "edge")[0][0]


# --- how it sits with what is already held ---------------------------------

def test_the_band_adds_to_what_is_held(vp):
    zz = _zigzag(vp)
    vp.selection.toggle_subobject(zz.id, "edge", 0)

    _window(vp, _band_round(vp, [(10, 0, 0), (10, 10, 0)]))

    assert _held(vp, "edge") == [(zz.id, 0), (zz.id, 1)]


def test_a_band_that_catches_nothing_changes_nothing(vp):
    zz = _zigzag(vp)
    vp.selection.toggle_subobject(zz.id, "edge", 0)
    empty = _band_round(vp, [(30, 30, 0)])

    assert _window(vp, empty) is None, "a Ctrl+Shift band never takes objects"

    assert _held(vp, "edge") == [(zz.id, 0)]
    assert vp.selection.ids == []


def test_a_plain_band_still_takes_objects(vp):
    zz = _zigzag(vp)
    rect = _band_round(vp, [(0, 0, 0), (10, 10, 0)])

    assert vp._band_pick(*rect, False, Qt.KeyboardModifier.NoModifier) == [zz.id]
    assert vp.selection.subobjects == []


def test_a_locked_object_gives_up_no_parts(vp):
    zz = _zigzag(vp)
    zz.locked = True

    _window(vp, _band_round(vp, [(0, 0, 0), (10, 10, 0)]))

    assert vp.selection.subobjects == []


# --- and the mouse actually gets there -------------------------------------

def _mouse(vp, kind, x, y, button, mods):
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    ev = QMouseEvent(kind, QPointF(x, y), QPointF(x, y),
                     Qt.MouseButton.LeftButton, button, mods)
    {QEvent.Type.MouseButtonPress: vp.mousePressEvent,
     QEvent.Type.MouseMove: vp.mouseMoveEvent,
     QEvent.Type.MouseButtonRelease: vp.mouseReleaseEvent}[kind](ev)


def test_a_ctrl_shift_drag_from_the_mouse_holds_the_parts_it_swept(vp):
    """The press, the drag and the release, as Qt delivers them, so the
    chord is known to reach the band and not be spent on the click."""
    from PySide6.QtCore import QEvent
    zz = _zigzag(vp)
    x0, y0, x1, y1 = _band_round(vp, [(10, 0, 0), (10, 10, 0)])

    _mouse(vp, QEvent.Type.MouseButtonPress, x0, y0,
           Qt.MouseButton.LeftButton, CTRL_SHIFT)
    _mouse(vp, QEvent.Type.MouseMove, x1, y1,
           Qt.MouseButton.LeftButton, CTRL_SHIFT)
    _mouse(vp, QEvent.Type.MouseButtonRelease, x1, y1,
           Qt.MouseButton.NoButton, CTRL_SHIFT)

    assert _held(vp, "edge") == [(zz.id, 1)]
    assert vp.selection.ids == []
