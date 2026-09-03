"""Getting at the object behind the one in front.

Asked for by a user: with several objects on the same line of sight, a
click always lands on the nearest one, and there was no way to reach past
it short of hiding things. The pick already knew about all of them, it
just threw everything but the front one away.

So: hold the button still for a moment (or Alt+click, if you know what you
want) and the ones under the cursor are offered as a list, nearest first.
A plain click is untouched.
"""

from __future__ import annotations

import pytest

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


def _stack(scene, count: int, size: float = 6.0):
    """`count` boxes one on top of another, all crossing the origin."""
    return [scene.add(g.make_box((-size / 2, -size / 2, i * 10.0),
                                 size, size, size), name=f"Box {i}")
            for i in range(count)]


def _centre(view):
    return view.width() / 2, view.height() / 2


# --- what is under the cursor ----------------------------------------------

def test_everything_under_the_cursor_is_offered(view):
    _stack(view.scene, 3)

    hits = view.pick_objects(*_centre(view))

    assert len(hits) == 3


def test_the_nearest_one_comes_first(view):
    """The list is the order you would meet them walking along the ray, so
    the top row is always the one a plain click would have given you."""
    boxes = _stack(view.scene, 3)

    hits = view.pick_objects(*_centre(view))

    # looking down from above, the highest box is the nearest
    assert hits == [boxes[2].id, boxes[1].id, boxes[0].id]


def test_a_plain_click_still_lands_on_the_nearest(view):
    """The whole point is that nothing about an ordinary click changes."""
    boxes = _stack(view.scene, 3)

    assert view.pick_object(*_centre(view)) == boxes[2].id


def test_clicking_past_everything_offers_nothing(view):
    _stack(view.scene, 3)

    assert view.pick_objects(5, 5) == []
    assert view.pick_object(5, 5) is None


def test_one_object_needs_no_choosing(view):
    """One hit means the chooser has nothing to ask, and the caller can
    tell without looking anything up."""
    box, = _stack(view.scene, 1)

    assert view.pick_objects(*_centre(view)) == [box.id]


def test_an_object_is_only_offered_once(view):
    """A box is hit by its faces and by every edge of them. One row each."""
    _stack(view.scene, 2)

    hits = view.pick_objects(*_centre(view))

    assert len(hits) == len(set(hits))


# --- and it respects everything a plain click respects ----------------------

def test_a_hidden_object_is_not_offered(view):
    boxes = _stack(view.scene, 3)
    view.scene.update(boxes[2].id, visible=False)

    hits = view.pick_objects(*_centre(view))

    assert boxes[2].id not in hits
    assert len(hits) == 2


def test_the_selection_filter_still_applies(view):
    """If you have told the app you are only picking curves, the chooser
    does not quietly offer you solids."""
    _stack(view.scene, 3)
    view.selection.filter_kinds = {"curve"}
    view.selection.filter_active = True

    assert view.pick_objects(*_centre(view)) == []


# --- the row the cursor is on lights up ------------------------------------

def test_the_row_under_the_cursor_lights_its_object(view):
    """Reading a list of names tells you nothing about which object is
    which, so pointing at a row has to light the thing itself."""
    boxes = _stack(view.scene, 2)

    view.set_choice_hover(boxes[1].id)

    assert view._looks_selected(boxes[1].id)
    assert not view._looks_selected(boxes[0].id)


def test_nothing_is_lit_once_the_chooser_has_gone(view):
    boxes = _stack(view.scene, 2)
    view.set_choice_hover(boxes[1].id)

    view.set_choice_hover(None)

    assert not view._looks_selected(boxes[1].id)


def test_a_selected_object_still_looks_selected(view):
    box, = _stack(view.scene, 1)
    view.selection.set([box.id])

    assert view._looks_selected(box.id)


# --- what a row says --------------------------------------------------------

def test_a_row_names_the_object_and_says_what_it_is():
    from serpentine3d.ui.object_chooser import chooser_rows
    scene = Scene()
    box = scene.add(g.make_box((0, 0, 0), 1, 1, 1), name="Lid")

    row, = chooser_rows(scene, [box.id])

    assert (row.obj_id, row.name, row.kind) == (box.id, "Lid", "Solid")


def test_a_row_carries_the_colour_the_object_is_drawn_in():
    """The swatch is what lets you match a row to something on screen
    before you have hovered it."""
    from serpentine3d.ui.object_chooser import chooser_rows
    scene = Scene()
    box = scene.add(g.make_box((0, 0, 0), 1, 1, 1))
    scene.update(box.id, color=(1.0, 0.0, 0.0))

    row, = chooser_rows(scene, [box.id])

    assert row.color == pytest.approx((1.0, 0.0, 0.0))


def test_a_kind_reads_as_words():
    from serpentine3d.ui.object_chooser import kind_label

    assert kind_label("pointcloud") == "Point cloud"
    assert kind_label("curve") == "Curve"


def test_an_object_that_has_gone_is_left_out():
    """The scene can change under an open chooser, and a row for something
    that is no longer there would pick nothing."""
    from serpentine3d.ui.object_chooser import chooser_rows
    scene = Scene()
    box = scene.add(g.make_box((0, 0, 0), 1, 1, 1))

    rows = chooser_rows(scene, [box.id, "gone"])

    assert [r.obj_id for r in rows] == [box.id]


def test_the_rows_keep_the_order_they_were_given():
    from serpentine3d.ui.object_chooser import chooser_rows
    scene = Scene()
    a = scene.add(g.make_box((0, 0, 0), 1, 1, 1), name="A")
    b = scene.add(g.make_box((0, 0, 5), 1, 1, 1), name="B")

    rows = chooser_rows(scene, [b.id, a.id])

    assert [r.name for r in rows] == ["B", "A"]


# --- when it opens, and when it stays out of the way ------------------------

def _press(view, x, y, alt=False):
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import Qt
    mods = (Qt.KeyboardModifier.AltModifier if alt
            else Qt.KeyboardModifier.NoModifier)
    ev = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(x, y),
                     QPointF(x, y), Qt.MouseButton.LeftButton,
                     Qt.MouseButton.LeftButton, mods)
    view.mousePressEvent(ev)
    return ev


def _shut(view):
    if view._chooser is not None:
        view._chooser.close()


def test_holding_still_opens_the_chooser(view):
    _stack(view.scene, 3)
    _press(view, *_centre(view))

    view._offer_the_stack()               # what the hold timer calls

    try:
        assert view._chooser is not None
        assert len(view._chooser._widgets) == 3
    finally:
        _shut(view)


def test_a_quick_click_never_gets_that_far(view):
    """The timer is what opens it, so a release has to call the timer off
    or a chooser lands after the click it belongs to has been dealt with."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    _stack(view.scene, 3)
    _press(view, *_centre(view))
    assert view._hold_timer.isActive()

    x, y = _centre(view)
    view.mouseReleaseEvent(QMouseEvent(
        QEvent.Type.MouseButtonRelease, QPointF(x, y), QPointF(x, y),
        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier))

    assert not view._hold_timer.isActive()
    assert view._chooser is None


def test_starting_a_selection_band_calls_the_hold_off(view):
    """Dragging out a band is not holding still, and it would be a nasty
    surprise to have a list appear over the band you are dragging."""
    from PySide6.QtCore import QPointF
    _stack(view.scene, 3)
    x, y = _centre(view)
    _press(view, x, y)

    view._track_band(QPointF(x + 40, y + 30))

    assert not view._hold_timer.isActive()
    view._offer_the_stack()
    assert view._chooser is None


def test_alt_click_opens_it_without_the_wait(view):
    _stack(view.scene, 3)

    _press(view, *_centre(view), alt=True)

    try:
        assert view._chooser is not None
        assert not view._hold_timer.isActive()
    finally:
        _shut(view)


def test_a_hold_over_a_single_object_leaves_the_click_alone(view):
    """Nothing to choose between, so no list: the release picks it exactly
    as it would have, and a slow click stays the same as a quick one."""
    _stack(view.scene, 1)
    _press(view, *_centre(view))

    view._offer_the_stack()

    assert view._chooser is None
    assert view._press_pos is not None, "the release still has a pick to do"


def test_the_hold_that_did_open_it_does_not_also_pick(view):
    """Otherwise letting go selects the front object behind the open list."""
    _stack(view.scene, 3)
    _press(view, *_centre(view))

    view._offer_the_stack()

    try:
        assert view._press_pos is None
    finally:
        _shut(view)


def test_picking_a_row_selects_that_object(view):
    """The chooser hands the id back through the same door a click uses, so
    everything a click does next — shift-adding, feeding a running command,
    pulling in the rest of a group — still happens."""
    boxes = _stack(view.scene, 3)
    got = []
    view.objectClicked.connect(lambda obj_id, mods: got.append(obj_id))
    _press(view, *_centre(view))
    view._offer_the_stack()

    try:
        rows = list(view._chooser._widgets)
        view._chooser._row_taken(rows[1])
    finally:
        _shut(view)

    assert got == [boxes[1].id]


def test_the_chooser_lets_go_of_the_highlight_when_it_closes(view):
    _stack(view.scene, 3)
    _press(view, *_centre(view))
    view._offer_the_stack()
    view._chooser.rowHovered.emit(view.scene.all()[0].id)
    assert view._choice_hover is not None

    _shut(view)

    assert view._choice_hover is None
    assert view._chooser is None


def test_the_nearest_object_is_lit_the_moment_it_opens(view):
    """Opening it should show you the object a plain click would have
    taken, so the list starts from something you can see."""
    boxes = _stack(view.scene, 3)
    _press(view, *_centre(view))

    view._offer_the_stack()

    try:
        assert view._choice_hover == boxes[2].id
    finally:
        _shut(view)


def test_the_hovered_object_lights_up_in_every_pane():
    """The object a row names is usually the one hidden behind something
    in the pane you clicked in. Lighting it only there would mean pointing
    at a row and seeing nothing happen."""
    from PySide6.QtWidgets import QApplication

    from serpentine3d.app import MainWindow
    QApplication.instance() or QApplication([])
    win = MainWindow()
    try:
        win.set_view_layout("quad")
        box = win.scene.add(g.make_box((0, 0, 0), 5, 5, 5))
        panes = win.all_viewports()
        assert len(panes) > 1, "a quad layout should give more than one pane"

        panes[0].set_choice_hover(box.id)

        assert all(v._looks_selected(box.id) for v in panes)
    finally:
        win.mark_saved()
        win.close()
