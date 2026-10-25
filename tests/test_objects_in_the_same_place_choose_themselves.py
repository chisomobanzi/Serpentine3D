"""Two objects in the same place ask which one you meant.

Asked for by a user: duplicates sitting exactly on top of each other can
only be told apart with Alt+click or by holding the button still, and
there is nothing to see that says a second one is there at all. One of
them is simply unreachable until you know the trick.

So a plain click on objects that are in the same place opens the chooser
by itself. Only there: something merely behind something else is picked
the way it always was, nearest first, or a click in a full drawing would
be a menu every time. Alt and the hold stay, because those reach what is
behind, which is a different question.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent

from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui import viewport as vp_mod


@pytest.fixture
def view():
    """A viewport looking down -Z at the origin, ready to pick."""
    scene = Scene()
    v = vp_mod.Viewport(scene, SelectionManager(scene))
    v.resize(800, 600)
    v.set_view("top")
    return v


def _centre(view):
    return view.width() / 2, view.height() / 2


def _box(scene, at=(0.0, 0.0, 0.0), size=6.0, name="Box"):
    x, y, z = at
    return scene.add(g.make_box((x - size / 2, y - size / 2, z),
                                size, size, size), name=name)


def _click(view, x, y, alt=False):
    """A plain press and release, as the mouse sends them."""
    mods = (Qt.KeyboardModifier.AltModifier if alt
            else Qt.KeyboardModifier.NoModifier)
    for kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
        ev = QMouseEvent(kind, QPointF(x, y), QPointF(x, y),
                         Qt.MouseButton.LeftButton,
                         Qt.MouseButton.LeftButton, mods)
        (view.mousePressEvent if kind == QEvent.Type.MouseButtonPress
         else view.mouseReleaseEvent)(ev)


def _shut(view):
    if view._chooser is not None:
        view._chooser.close()


def _clicked(view):
    """The object ids a click emitted, in order."""
    seen = []
    view.objectClicked.connect(lambda obj_id, _mods: seen.append(obj_id))
    return seen


# -- which hits count as the same place ------------------------------------

def test_hits_at_the_same_depth_are_in_the_same_place():
    hits = [(10.0, "a"), (10.0, "b"), (25.0, "c")]
    assert vp_mod.ids_in_the_same_place(hits) == ["a", "b"]


def test_a_hit_behind_another_is_not():
    hits = [(10.0, "a"), (10.2, "b")]
    assert vp_mod.ids_in_the_same_place(hits) == ["a"]


def test_a_hair_apart_still_counts_as_the_same_place():
    """Two imports of the same wall never land on the same number."""
    hits = [(10.0, "a"), (10.0 + 1e-7, "b")]
    assert vp_mod.ids_in_the_same_place(hits) == ["a", "b"]


def test_nothing_under_the_cursor_is_nobody():
    assert vp_mod.ids_in_the_same_place([]) == []


def test_one_hit_is_one_answer():
    assert vp_mod.ids_in_the_same_place([(5.0, "a")]) == ["a"]


# -- what a plain click does -----------------------------------------------

def test_two_objects_in_the_same_place_offer_themselves(view):
    _box(view.scene, name="First")
    _box(view.scene, name="Second")       # exactly on top of it

    _click(view, *_centre(view))

    try:
        assert view._chooser is not None, "a duplicate stayed unreachable"
        assert len(view._chooser._widgets) == 2
    finally:
        _shut(view)


def test_one_object_is_picked_without_being_asked_about(view):
    only = _box(view.scene, name="Only")
    seen = _clicked(view)

    _click(view, *_centre(view))

    assert view._chooser is None
    assert seen == [only.id]


def test_something_behind_something_else_is_still_picked_in_front(view):
    front = _box(view.scene, at=(0.0, 0.0, 20.0), name="Front")
    _box(view.scene, at=(0.0, 0.0, 0.0), name="Back")
    seen = _clicked(view)

    _click(view, *_centre(view))

    assert view._chooser is None, "a full drawing must not be a menu"
    assert seen == [front.id]


def test_a_curve_lying_on_a_face_still_goes_to_the_curve(view):
    """The pick puts a curve a hair in front of what it lies on, so that
    it can be taken at all. That is an answer, not a question."""
    _box(view.scene, name="Face")
    curve = view.scene.add(
        g.make_line((-2.0, 0.0, 6.0), (2.0, 0.0, 6.0)), name="Curve")
    seen = _clicked(view)

    _click(view, *_centre(view))

    assert view._chooser is None
    assert seen == [curve.id]


@pytest.mark.parametrize("distance", [0.8, 0.3])
def test_a_curve_on_a_face_seen_from_close_up_still_goes_to_the_curve(
        view, distance):
    """The nudge that keeps a curve in front of its face is a thousandth of
    the distance, so it shrinks as the camera closes in. Under a document
    unit away, a drawing in metres seen from a step back, it fell inside
    the document tolerance and the click asked a question it had answered."""
    _box(view.scene, name="Face")
    curve = view.scene.add(
        g.make_line((-2.0, 0.0, 6.0), (2.0, 0.0, 6.0)), name="Curve")
    view.camera.projection = "perspective"
    view.camera.target = view.camera.target * 0 + [0.0, 0.0, 6.0]
    view.camera.distance = distance
    seen = _clicked(view)

    _click(view, *_centre(view))

    assert view._chooser is None
    assert seen == [curve.id]


def test_objects_in_one_group_need_no_choosing(view):
    """Both rows would select the same thing, so there is no question."""
    a = _box(view.scene, name="First")
    b = _box(view.scene, name="Second")
    for obj in (a, b):
        view.scene.update(obj.id, group_id="one-group")
    seen = _clicked(view)

    _click(view, *_centre(view))

    assert view._chooser is None
    assert seen and seen[0] in (a.id, b.id)


def test_a_command_asking_for_a_point_is_left_alone(view):
    _box(view.scene, name="First")
    _box(view.scene, name="Second")
    view.set_point_mode(True)

    _click(view, *_centre(view))

    assert view._chooser is None, "a point is not a choice between objects"


def test_the_old_ways_in_still_work(view):
    """Alt reaches what is behind, which the automatic one does not."""
    _box(view.scene, at=(0.0, 0.0, 20.0), name="Front")
    _box(view.scene, at=(0.0, 0.0, 0.0), name="Back")

    _click(view, *_centre(view), alt=True)

    try:
        assert view._chooser is not None
        assert len(view._chooser._widgets) == 2
    finally:
        _shut(view)
