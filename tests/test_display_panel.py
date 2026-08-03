"""Turning surface isocurves and edges off, and a panel to do it in (#5).

Isocurves were drawn in every display mode, including rendered, with no
way to switch them off: `rendered` only swapped the fill colour. On a
surveyed model that is a wire cage over everything, and the reporter asked
for what Rhino has, a Display panel beside Properties.

Two levels, as in Rhino. Each mode has a sensible default, and rendered's
is isocurves off, because a render is not a wireframe. On top of that sits
a per-viewport override for when the default is not what you want, and it
sticks until you clear it rather than resetting under you on a mode change.
"""

import inspect

import pytest

from serpentine3d.app import MainWindow
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager


def _viewport(scene=None):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from serpentine3d.ui.viewport import Viewport
    scene = scene or Scene()
    return Viewport(scene, SelectionManager(scene))


@pytest.fixture
def vp(_qapp):
    return _viewport()


@pytest.fixture
def win(_qapp):
    w = MainWindow()
    yield w
    w.close()


# -- what each mode asks for by itself --

def test_a_shaded_view_shows_isocurves(vp):
    vp.set_display_mode("shaded")
    assert vp.shows_isocurves()


def test_a_rendered_view_does_not(vp):
    """The complaint in the issue, in one line."""
    vp.set_display_mode("rendered")
    assert not vp.shows_isocurves()


def test_every_mode_shows_edges_by_default(vp):
    for mode in vp.DISPLAY_MODES:
        vp.set_display_mode(mode)
        assert vp.shows_edges(), f"{mode} lost its edges"


# -- and the override on top --

def test_isocurves_can_be_forced_on_in_a_rendered_view(vp):
    vp.set_display_mode("rendered")
    vp.set_isocurves(True)
    assert vp.shows_isocurves()


def test_isocurves_can_be_forced_off_in_a_shaded_view(vp):
    vp.set_display_mode("shaded")
    vp.set_isocurves(False)
    assert not vp.shows_isocurves()


def test_edges_can_be_turned_off(vp):
    vp.set_edges(False)
    assert not vp.shows_edges()


def test_clearing_the_override_hands_the_mode_back(vp):
    vp.set_display_mode("rendered")
    vp.set_isocurves(True)
    vp.set_isocurves(None)
    assert not vp.shows_isocurves()


def test_an_override_survives_a_mode_change(vp):
    """Asking for no isocurves is a preference, not a per-mode accident.
    Rebuilding it from the mode would switch them back on behind you."""
    vp.set_display_mode("shaded")
    vp.set_isocurves(False)
    vp.set_display_mode("wireframe")
    assert not vp.shows_isocurves()


def test_each_pane_answers_for_itself(win):
    """Four panes, four display modes already. The toggle is the same kind
    of per-pane thing and must not leak across."""
    a, b = win.viewport, win.aux_viewports[0]
    a.set_isocurves(False)
    assert not a.shows_isocurves()
    assert b.shows_isocurves()


# -- the drawing, which cannot be run here: it is GL --

def test_the_draw_loop_asks_before_drawing_isocurves():
    from serpentine3d.ui.viewport import Viewport

    src = inspect.getsource(Viewport._draw_objects)
    assert "shows_isocurves(" in src
    assert "shows_edges(" in src


# -- the panel the reporter actually asked for --

def test_the_window_has_a_display_panel(win):
    assert win.display_panel is not None
    assert win._display_dock.objectName() == "displayDock"


def test_the_panel_reads_the_pane_you_are_in(win):
    aux = win.aux_viewports[0]
    aux.set_display_mode("rendered")
    win._set_active_viewport(aux)

    assert win.display_panel.mode() == "rendered"
    assert not win.display_panel.isocurves_checked()


def test_ticking_isocurves_turns_them_on_in_that_pane(win):
    aux = win.aux_viewports[0]
    aux.set_display_mode("rendered")
    win._set_active_viewport(aux)

    win.display_panel.set_isocurves_checked(True)

    assert aux.shows_isocurves()
    assert win.viewport.shows_isocurves() is True  # untouched, default on


def test_unticking_edges_turns_them_off_in_that_pane(win):
    win._set_active_viewport(win.viewport)
    win.display_panel.set_edges_checked(False)
    assert not win.viewport.shows_edges()


def test_changing_pane_repoints_the_panel(win):
    a, b = win.viewport, win.aux_viewports[0]
    win._set_active_viewport(a)
    win.display_panel.set_isocurves_checked(False)

    win._set_active_viewport(b)

    assert win.display_panel.isocurves_checked(), "still showing the old pane"


def test_the_panel_can_change_the_display_mode(win):
    win._set_active_viewport(win.viewport)
    win.display_panel.set_mode("wireframe")
    assert win.viewport.display_mode == "wireframe"


def test_the_panel_follows_a_mode_change_it_did_not_make(win):
    """The mode can be reached from the menu, the viewport title and the
    command line, none of which go through the panel. A panel reading
    Shaded over a rendered view is worse than no panel."""
    win._set_active_viewport(win.viewport)
    win.processor.run("rendered")

    assert win.display_panel.mode() == "rendered"
    assert not win.display_panel.isocurves_checked()


def test_a_background_pane_does_not_steal_the_panel(win):
    """Only the pane you are in gets to say what the panel shows."""
    win._set_active_viewport(win.viewport)
    win.viewport.set_display_mode("shaded")

    win.aux_viewports[0].set_display_mode("wireframe")

    assert win.display_panel.mode() == "shaded"


# -- and from the command line, because everything else is --
#
# Driven through the processor, which is where the macro form
# ("osnap mid toggle") is implemented. MainWindow._on_submit truncates
# what's typed to its first token, so at the GUI prompt `isocurves off`
# runs `isocurves` and asks. That is older than this command.

def test_the_command_turns_isocurves_off(win):
    win._set_active_viewport(win.viewport)
    win.processor.run("isocurves off")
    assert not win.viewport.shows_isocurves()


def test_the_command_turns_them_back_on(win):
    win._set_active_viewport(win.viewport)
    win.processor.run("isocurves off")
    win.processor.run("isocurves on")
    assert win.viewport.shows_isocurves()


def test_the_command_can_toggle(win):
    """Bare `isocurves` asks, the way every other option prompt does, and
    Toggle is what it offers when you would rather not think about it."""
    win._set_active_viewport(win.viewport)
    was = win.viewport.shows_isocurves()
    win.processor.run("isocurves toggle")
    assert win.viewport.shows_isocurves() is not was
