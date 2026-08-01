"""New window width belongs to the viewports.

Maximising the window used to hand every new pixel to the Properties /
Layers column: a 400 px wider window meant a 400 px wider panel and not
one pixel more drawing. The panel is a fixed-content column — the fields
do not get better with more room — where the viewport is the whole point
of the extra screen.

So the panel column holds the width it has across a window resize, and
everything the resize gained or lost lands on the panes. Dragging the
splitter is untouched: that is the user setting the width on purpose, and
the next resize holds the new one.
"""

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QResizeEvent

from serpentine3d.app import MainWindow, PANEL_WIDTH, clamp_panel_width


@pytest.fixture
def win(_qapp):
    w = MainWindow()
    w._balance_docks()            # normally a singleShot away from __init__
    yield w
    w.close()


def test_the_panel_column_offers_a_width_to_hold(win):
    assert win._keep_panel_width() == win._prop_dock.width()


def test_a_hidden_panel_column_has_no_width_to_hold(win):
    """Nothing docked on the right is not a zero-width panel, it is no
    panel — holding 0 would be a claim about a column that is not there."""
    win._prop_dock.hide()
    win._layer_dock.hide()
    assert win._keep_panel_width() is None


def test_a_floating_panel_is_not_the_column(win):
    """Torn off, its width is its own window's and says nothing about how
    much of the main window the right-hand column should keep."""
    win._prop_dock.setFloating(True)
    win._layer_dock.hide()
    assert win._keep_panel_width() is None


def _record(win):
    """Stand in for the one method that touches the real layout. Activating
    it offscreen would drive a QOpenGLWidget through a resize with no
    context behind it, which takes the whole test run down."""
    asked = []
    win._set_panel_width = lambda w: asked.append(w)
    return asked


def test_growing_the_window_holds_the_panel_at_its_width(win):
    """The whole point: the panel keeps what it had, so the surplus has
    nowhere to go but the viewports."""
    asked = _record(win)
    width = win._panel_width

    win.resizeEvent(QResizeEvent(QSize(2400, 900), QSize(1400, 900)))
    win._hold_panel_width()       # the singleShot, run by hand

    assert asked == [width], "the resize let the panel take the new width"


def test_shrinking_the_window_also_takes_from_the_viewports(win):
    """Symmetry, and the more useful half: dragging a window narrower
    should eat into the drawing before it eats the panel someone sized."""
    asked = _record(win)
    width = win._panel_width
    win.resizeEvent(QResizeEvent(QSize(900, 900), QSize(1400, 900)))
    win._hold_panel_width()
    assert asked == [width]


def _dock_resized(win, dock, width):
    """The dock being resized, however it came about."""
    ev = QResizeEvent(QSize(width, dock.height()), dock.size())
    win.eventFilter(dock, ev)


def test_a_width_chosen_by_dragging_is_the_one_held(win):
    """The splitter is how you say you want a wider panel. A drag resizes
    the dock while the window stays put, which is how it is told apart from
    a window resize — that reaches the dock first and the window after."""
    win._last_size = win.size()                    # settled: no resize afoot
    _dock_resized(win, win._prop_dock, 517)
    assert win._panel_width == 517


def test_the_panel_swelling_during_a_window_resize_is_not_a_choice(win):
    """The bug itself, seen from the other side: Qt widens the dock as part
    of laying the window out, before the window hears about the resize at
    all. Mistaking that for a drag would record the swollen width and leave
    nothing to put back."""
    win._last_size = QSize(1400, 900)              # what the window last was
    win.resize(2400, 900)                          # ... and now it is not
    before = win._panel_width
    _dock_resized(win, win._prop_dock, 1200)
    assert win._panel_width == before


def test_a_torn_off_panel_is_not_a_choice_about_this_window(win):
    win._last_size = win.size()
    win._prop_dock.setFloating(True)
    _dock_resized(win, win._prop_dock, 900)
    assert win._panel_width != 900


# ------------------------------------------------ what comes back on restore

def test_a_modest_saved_width_comes_back_untouched():
    """Someone who chose 340 px meant 340 px."""
    assert clamp_panel_width(340, 1444) == 340


def test_a_saved_half_the_window_does_not_come_back():
    """A panel dragged to half of a maximised window was saved at that
    width, and is restored into a window that is not maximised — where the
    same number is now most of the screen."""
    assert clamp_panel_width(924, 1444) < 924


def test_the_clamp_leaves_the_panel_usable_on_a_small_window():
    """A share of a narrow window is narrower than the fields in it. The
    floor is what a fresh window opens at, not a fraction."""
    assert clamp_panel_width(900, 800) >= min(PANEL_WIDTH, 400)


def test_no_saved_width_is_nothing_to_clamp():
    assert clamp_panel_width(None, 1444) is None


def test_restoring_a_fat_panel_puts_it_back_to_a_share(_qapp):
    w = MainWindow()
    try:
        w.resize(1444, 900)
        asked = _record(w)
        w._docks_restored = True
        w._keep_panel_width = lambda: 924
        w._balance_docks()
        assert asked == [clamp_panel_width(924, w.width())]
    finally:
        w.close()


def test_restoring_a_reasonable_panel_leaves_the_layout_alone(_qapp):
    """Nothing to correct, so nothing is touched — the restored layout is
    the user's and re-imposing a width on it is the bug in GitHub #5."""
    w = MainWindow()
    try:
        w.resize(1444, 900)
        asked = _record(w)
        w._docks_restored = True
        w._keep_panel_width = lambda: 300
        w._balance_docks()
        assert asked == []
        assert w._panel_width == 300
    finally:
        w.close()


def test_nothing_is_held_before_the_docks_are_balanced(_qapp):
    """A window mid-construction has not laid out yet, and holding the
    width it has at that moment would pin the panel to a placeholder —
    and would race _balance_docks, which is also still to come."""
    w = MainWindow()
    try:
        asked = _record(w)
        w.resizeEvent(QResizeEvent(QSize(2400, 900), QSize(1400, 900)))
        w._hold_panel_width()
        assert asked == []
    finally:
        w.close()
