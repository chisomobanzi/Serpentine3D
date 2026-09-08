"""Surface display controls, reached from the viewport they belong to.

Isocurves were drawn in every display mode, including rendered, with no
way to switch them off: `rendered` only swapped the fill colour. On a
surveyed model that is a wire cage over everything. The controls now belong
in the viewport title menu, leaving the right dock for Properties and Layers.

Two levels, as in Rhino. Each mode has a sensible default, and rendered's
is isocurves off, because a render is not a wireframe. On top of that sits
a per-viewport override for when the default is not what you want, and it
sticks until you clear it rather than resetting under you on a mode change.
"""

import inspect

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QDockWidget

from serpentine3d.app import MainWindow
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui.display_panel import DisplayPanel


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
    for settings in _display_windows():
        settings.close()
    w.close()
    w.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _menu_action(menu, text):
    def normalized(label):
        return label.replace("&", "").replace("…", "...").casefold()

    for action in menu.actions():
        if normalized(action.text()) == normalized(text):
            return action
        if action.menu() is not None:
            found = _menu_action(action.menu(), text)
            if found is not None:
                return found
    return None


def _display_windows():
    """Discover the settings through their visible controls, not an app field."""
    return [window for window in QApplication.topLevelWidgets()
            if window.isVisible()
            and any(box.text() == "Surface isocurves" and box.isVisible()
                    for box in window.findChildren(QCheckBox))]


def _open_display(win, viewport):
    menu = win._viewport_menu(viewport)
    action = _menu_action(menu, "Display settings…")
    assert action is not None, "the viewport menu has no Display settings entry"
    assert action.isEnabled()
    action.trigger()
    QApplication.processEvents()
    windows = _display_windows()
    assert len(windows) == 1, "Display settings should open one transient window"
    return windows[0]


def _controls(settings):
    boxes = {box.text(): box for box in settings.findChildren(QCheckBox)
             if box.isVisible()}
    assert "Surface isocurves" in boxes
    assert "Surface edges" in boxes
    modes = [box for box in settings.findChildren(QComboBox)
             if box.isVisible() and box.findData("shaded") >= 0]
    assert len(modes) == 1, "Display settings should expose the existing mode control"
    return modes[0], boxes["Surface isocurves"], boxes["Surface edges"]


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


# -- the reusable controls --

def test_the_panel_reads_its_viewport_without_changing_it(vp):
    vp.set_display_mode("rendered")
    vp.set_edges(False)
    panel = DisplayPanel(lambda: vp)

    assert panel.mode() == "rendered"
    assert not panel.isocurves_checked()
    assert not panel.edges_checked()
    vp.set_display_mode("shaded")
    assert vp.shows_isocurves(), "reading the default must not create an override"
    panel.refresh()
    assert panel.mode() == "shaded"
    assert panel.isocurves_checked()
    assert not panel.edges_checked()


def test_the_panel_can_change_all_three_display_controls(vp):
    vp.set_display_mode("rendered")
    panel = DisplayPanel(lambda: vp)

    panel.set_isocurves_checked(True)
    panel.set_edges_checked(False)
    panel.set_mode("wireframe")

    assert vp.shows_isocurves()
    assert not vp.shows_edges()
    assert vp.display_mode == "wireframe"


# -- the viewport menu owns the transient settings --

def test_display_does_not_take_space_from_properties_and_layers(win):
    docks = win.findChildren(QDockWidget)
    assert not any(dock.windowTitle() == "Display"
                   and win.dockWidgetArea(dock) != Qt.DockWidgetArea.NoDockWidgetArea
                   for dock in docks), "Display still occupies a permanent dock"
    for title, panel in (("Properties", win.properties),
                         ("Layers", win.layers_panel)):
        dock = next(dock for dock in docks if dock.windowTitle() == title)
        assert dock.widget() is panel
        assert win.dockWidgetArea(dock) == Qt.DockWidgetArea.RightDockWidgetArea
    assert win.centralWidget() is win.viewport_area
    assert len(win.aux_viewports) == 3


@pytest.mark.parametrize("pane_index", range(4))
def test_every_viewport_menu_opens_its_current_display_settings(win, pane_index):
    panes = [win.viewport, *win.aux_viewports]
    target = panes[pane_index]
    other = panes[(pane_index + 1) % len(panes)]
    target.set_display_mode("rendered")
    target.set_isocurves(True)
    target.set_edges(False)
    win._set_active_viewport(other)

    settings = _open_display(win, target)
    mode, iso, edges = _controls(settings)

    assert mode.currentData() == "rendered"
    assert iso.isChecked()
    assert not edges.isChecked()
    assert target.display_mode == "rendered"
    assert target.shows_isocurves()
    assert not target.shows_edges()


@pytest.mark.parametrize("switch_after_opening", [False, True])
def test_display_edits_stay_with_the_menu_viewport(win, switch_after_opening):
    target, other = win.aux_viewports[0], win.viewport
    target.set_display_mode("rendered")
    other.set_display_mode("shaded")
    other.set_isocurves(False)
    win._set_active_viewport(target if switch_after_opening else other)
    settings = _open_display(win, target)
    if switch_after_opening:
        win._set_active_viewport(other)
    mode, iso, edges = _controls(settings)

    assert mode.currentData() == "rendered", "the active pane stole the settings"
    iso.setChecked(True)
    edges.setChecked(False)
    mode.setCurrentIndex(mode.findData("wireframe"))

    assert target.display_mode == "wireframe"
    assert target.shows_isocurves()
    assert not target.shows_edges()
    assert other.display_mode == "shaded"
    assert not other.shows_isocurves()
    assert other.shows_edges()


def test_open_display_settings_follow_their_panes_external_mode_change(win):
    target, other = win.aux_viewports[0], win.viewport
    target.set_display_mode("shaded")
    settings = _open_display(win, target)
    mode, iso, _edges = _controls(settings)

    _menu_action(win._viewport_menu(target), "Rendered").trigger()
    QApplication.processEvents()
    assert mode.currentData() == "rendered"
    assert not iso.isChecked()

    other.set_display_mode("wireframe")
    assert mode.currentData() == "rendered", "another pane stole the settings"


def test_closing_and_reopening_reads_fresh_state_without_duplicate_windows(win):
    target = win.aux_viewports[0]
    settings = _open_display(win, target)
    for _ in range(3):
        settings = _open_display(win, target)
    settings.close()
    QApplication.processEvents()
    assert not _display_windows(), "closing Display must dismiss its controls"

    target.set_display_mode("ghosted")
    target.set_isocurves(False)
    target.set_edges(False)
    reopened = _open_display(win, target)
    mode, iso, edges = _controls(reopened)
    assert mode.currentData() == "ghosted"
    assert not iso.isChecked()
    assert not edges.isChecked()


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
