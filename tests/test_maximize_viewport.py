"""Making the pane you are working in fill the window, and putting it back.

`1view` looked like this and is not: it hides the three aux panes and
leaves the *primary* one, which is the Perspective pane built at startup.
Work in Top and ask for a single view and Top is what you lose. There was
no way to make an aux pane full-size at all (GitHub #5).

So maximise acts on the pane you are in, sits on ++ctrl+m++ and a
double-click of the title the way Rhino's does, and the layout you had —
including splitter positions you dragged yourself — is what comes back.
"""

import pytest

from serpentine3d.app import MainWindow


@pytest.fixture
def win(_qapp):
    w = MainWindow()                       # a fresh install opens in quad
    yield w
    w.close()


def _dock(vp):
    return vp.parentWidget()


# -- it is the pane you are in, which is what 1view could not do --

def test_maximizing_keeps_the_pane_you_are_in(win):
    aux = win.aux_viewports[0]
    win._set_active_viewport(aux)

    assert win.toggle_maximized_viewport()

    assert not _dock(aux).isHidden()
    assert _dock(win.viewport).isHidden(), "kept the primary, like 1view"


def test_maximizing_hides_every_other_pane(win):
    win._set_active_viewport(win.viewport)
    win.toggle_maximized_viewport()

    assert not win._primary_dock.isHidden()
    assert all(d.isHidden() for d in win.aux_docks)


def test_it_can_be_told_which_pane_rather_than_asking(win):
    """The title bar knows which pane it belongs to; it should not have to
    make that pane active first just to be heard."""
    aux = win.aux_viewports[1]
    win._set_active_viewport(win.viewport)

    win.toggle_maximized_viewport(aux)

    assert not _dock(aux).isHidden()
    assert win._primary_dock.isHidden()


# -- and back again --

def test_toggling_again_brings_the_other_panes_back(win):
    win.toggle_maximized_viewport(win.viewport)
    win.toggle_maximized_viewport()

    assert not win._primary_dock.isHidden()
    assert all(not d.isHidden() for d in win.aux_docks)


def test_the_layout_you_had_is_what_comes_back(win):
    """Not an even 2x2. Splitters you dragged yourself are a choice, and
    rebuilding the default grid on the way back would throw it away every
    time you glanced at one pane full-size."""
    saved = []
    real = win.restoreState
    win.restoreState = lambda state, *a: (saved.append(bytes(state)),
                                          real(state, *a))[1]

    win.toggle_maximized_viewport(win.viewport)
    taken = bytes(win._maximized_state)
    win.toggle_maximized_viewport()

    assert saved == [taken], "restored something other than what it saved"


def test_a_second_toggle_restores_whichever_pane_was_maximized(win):
    """Maximise Top, then press again without clicking anything: the quad
    comes back rather than the toggle acting on the active pane afresh."""
    aux = win.aux_viewports[0]
    win.toggle_maximized_viewport(aux)
    win.toggle_maximized_viewport(win.viewport)

    assert not win._primary_dock.isHidden()
    assert all(not d.isHidden() for d in win.aux_docks)


# -- the edges --

def test_one_pane_on_its_own_is_already_as_big_as_it_gets(win):
    """Nothing to hide, so nothing happens — and no half-taken state that a
    second press would 'restore' into a layout that was never saved."""
    win.set_view_layout("single")

    assert not win.toggle_maximized_viewport()
    assert win.maximized_viewport is None
    assert not win._primary_dock.isHidden()


def test_asking_for_a_layout_forgets_that_a_pane_was_maximized(win):
    """`4view` is the user saying what they want on screen. Holding on to a
    stale maximise would make the next ++ctrl+m++ restore a layout from
    before it."""
    win.toggle_maximized_viewport(win.viewport)
    win.set_view_layout("quad")

    assert win.maximized_viewport is None


# -- the ways in --

def test_a_double_click_on_the_title_maximizes_that_pane(win):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    aux = win.aux_viewports[0]
    bar = _dock(aux).titleBarWidget()
    ev = QMouseEvent(QEvent.Type.MouseButtonDblClick, QPointF(40.0, 8.0),
                     QPointF(40.0, 8.0), Qt.MouseButton.LeftButton,
                     Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier)
    bar.mouseDoubleClickEvent(ev)

    assert win.maximized_viewport is aux


def test_the_command_maximizes_the_pane_you_are_in(win):
    aux = win.aux_viewports[0]
    win._set_active_viewport(aux)

    win.command_line.run_command("max")

    assert win.maximized_viewport is aux


def test_the_menu_offers_it_on_the_pane_it_belongs_to(win):
    from tests.test_viewport_title_menu import _menu_action

    aux = win.aux_viewports[2]
    win._set_active_viewport(win.viewport)

    menu = win._viewport_menu(aux)
    act = _menu_action(menu, "Maximize Viewport")
    assert act is not None
    act.trigger()

    assert win.maximized_viewport is aux


def test_the_view_menu_carries_it_too(win):
    from tests.test_viewport_title_menu import _menu_action

    view_menu = None
    for act in win.menuBar().actions():
        if act.text().replace("&", "") == "View":
            view_menu = act.menu()

    act = _menu_action(view_menu, "Maximize Viewport")
    assert act is not None
    assert act.shortcut().toString() == "Ctrl+M"
