"""Finding the four-viewport layout, and the menu on a viewport's title.

The layout existed and nobody found it (GitHub #5 asked for a feature that
had shipped). Two reasons: a new drawing opened in a single view, and the
way to change that was three levels down a menu. So a fresh install now
opens in four, and every viewport carries its own menu on its title bar —
which is also where the display modes live, so changing one view to
wireframe no longer means changing the one that happens to be active.

What is tested here is which viewport a menu acts on and what the title
says afterwards. How it looks is Chisomo's to judge.
"""

import pytest

from serpentine3d.app import MainWindow


@pytest.fixture
def win(_qapp):
    """The conftest gives every test settings of its own, so the layout this
    opens in is the default rather than what the machine last left behind."""
    w = MainWindow()
    yield w
    w.close()


def test_a_fresh_install_opens_in_four_viewports(win):
    """The layout nobody could find is the one you now start in."""
    assert len(win.aux_docks) == 3
    assert all(d.isVisibleTo(win) for d in win.aux_docks)


def test_a_remembered_single_view_is_still_honoured(_qapp):
    """Defaulting to quad must not overrule someone who chose single last
    session — the default is for the first launch, not every launch."""
    first = MainWindow()
    first.set_view_layout("single")
    first._remember_window()
    first.close()

    second = MainWindow()
    try:
        assert not any(d.isVisibleTo(second) for d in second.aux_docks)
    finally:
        second.close()


def _menu_action(menu, text):
    for act in menu.actions():
        if act.text().replace("&", "") == text:
            return act
        if act.menu() is not None:
            found = _menu_action(act.menu(), text)
            if found is not None:
                return found
    return None


def test_the_menu_acts_on_its_own_viewport_not_the_active_one(win):
    """The whole point of a menu per title bar. Bound to the active viewport
    it would be a slower way to do what the View menu already does — and
    setting one pane to wireframe would change whichever pane was last
    clicked instead."""
    aux = win.aux_viewports[0]
    win._set_active_viewport(win.viewport)        # the primary is active
    before = win.viewport.display_mode

    menu = win._viewport_menu(aux)
    _menu_action(menu, "Wireframe").trigger()

    assert aux.display_mode == "wireframe"
    assert win.viewport.display_mode == before, "changed the wrong viewport"


def test_the_menu_sets_the_view_of_its_own_viewport(win):
    aux = win.aux_viewports[0]
    menu = win._viewport_menu(aux)
    _menu_action(menu, "Front").trigger()
    assert aux._view_name == "front"


def test_the_menu_says_which_view_and_mode_are_current(win):
    """Checkmarks, so the menu reports the state as well as setting it."""
    aux = win.aux_viewports[0]
    aux.set_view("right")
    aux.set_display_mode("ghosted")

    menu = win._viewport_menu(aux)
    assert _menu_action(menu, "Right").isChecked()
    assert _menu_action(menu, "Ghosted").isChecked()
    assert not _menu_action(menu, "Top").isChecked()


def test_there_is_one_view_menu_per_pane_not_two(win):
    """A set of view/mode chips was already floating inside each viewport,
    40 px below where the title bar now is. Two menus that do the same thing
    within a thumb's width of each other is worse than either alone, so the
    chips are gone and the title carries everything they had."""
    assert not hasattr(win.viewport, "_hud")


def test_every_named_view_is_reachable(win):
    """Including the three the chips had and the View menu does not — Back,
    Left and Bottom. Folding the chips in must not lose them."""
    menu = win._viewport_menu(win.viewport)
    for label in ("Top", "Bottom", "Front", "Back", "Left", "Right",
                  "Isometric", "Perspective"):
        assert _menu_action(menu, label) is not None, label


def test_every_display_mode_is_reachable(win):
    """GitHub #5 asked for a display settings menu. The View menu offers
    five of the eight; the ones left out are the analysis modes, which are
    the ones hardest to find by guessing a command name."""
    menu = win._viewport_menu(win.viewport)
    for mode in win.viewport.DISPLAY_MODES:
        assert _menu_action(menu, mode.capitalize()) is not None, mode


def test_the_title_follows_the_view(win):
    """A title still reading Perspective after the view was set to Top is
    worse than no title at all."""
    bar = win._primary_dock.titleBarWidget()
    win.viewport.set_view("top")
    assert "Top" in bar.button.text()


def test_the_title_follows_the_display_mode(win):
    bar = win._primary_dock.titleBarWidget()
    win.viewport.set_display_mode("wireframe")
    assert "Wireframe" in bar.button.text()


def test_the_layout_actions_are_in_the_view_menu_itself(win):
    """Four Viewports was three levels down: View, then Viewports, then the
    item. Nobody found it. It sits in View now."""
    view_menu = None
    for act in win.menuBar().actions():
        if act.text().replace("&", "") == "View":
            view_menu = act.menu()
    assert view_menu is not None

    top_level = [a.text().replace("&", "") for a in view_menu.actions()]
    assert "Four Viewports" in top_level
    assert "Single Viewport" in top_level
