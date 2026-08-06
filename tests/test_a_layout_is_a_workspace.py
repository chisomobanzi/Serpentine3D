"""A tab is an arrangement of panes, not a setting on one pane.

`space` used to belong to a viewport. The strip along the bottom looked
like it spoke for the window and only ever wrote to whichever pane was
active, so making a sheet in a four-pane window turned the perspective
pane into paper and left the other three in model space. Making a second
sheet ate a second pane. And if the active pane happened to be tabbed
away behind another, pressing the button changed nothing you could see,
which is how it came in: "it doesn't create a new layout".

A tab is now a workspace. Model holds the panes you model in, each sheet
holds the panes you draft it on, and each remembers its own arrangement
across a switch. A pane can still be pointed at a sheet on its own, so a
drawing can sit beside the model it came from, which is the one thing
this is meant to do that Rhino will not.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def win(tmp_path, monkeypatch):
    monkeypatch.setenv("SERP3D_CONFIG", str(tmp_path / "settings.json"))
    monkeypatch.setenv("SERP3D_NO_RECOVER", "1")
    from serpentine3d.app import MainWindow
    w = MainWindow()
    w.resize(1400, 900)
    w.layout().activate()
    yield w
    w.mark_saved()
    w.close()


def test_the_window_has_a_space_of_its_own(win):
    """Not `active_viewport.space` read out through a property."""
    assert win.space == "model"


def test_making_a_sheet_does_not_leave_model_panes_beside_it(win):
    """The bug as it was met. Four panes, press the button, and you were
    left looking at paper in one of them and the model in the other
    three, which is not a drafting sheet, it is a mess."""
    win.set_view_layout("quad")
    lay = win._new_sheet("A3")
    assert win.space == lay.id
    assert win.all_viewports() == [win.viewport]
    assert win.viewport.space == lay.id


def test_the_model_panes_are_put_away_not_repurposed(win):
    """They are still Top, Front and Right when you go back for them."""
    win.set_view_layout("quad")
    win._new_sheet("A3")
    assert [vp.space for vp in win.aux_viewports] == ["model"] * 3


def test_a_second_sheet_does_not_eat_a_second_pane(win):
    """Two sheets and two model views, side by side, was the state that
    made it clear the tabs were not workspaces at all."""
    win.set_view_layout("quad")
    win._new_sheet("A3")
    b = win._new_sheet("A3")
    assert win.all_viewports() == [win.viewport]
    assert win.viewport.space == b.id
    assert len(win.scene.layouts) == 2


def test_going_back_to_model_brings_the_arrangement_back(win):
    """The whole point of a workspace. Four panes before, four after."""
    win.set_view_layout("quad")
    before = len(win.all_viewports())
    lay = win._new_sheet("A3")
    win.switch_space("model")
    assert win.space == "model"
    assert len(win.all_viewports()) == before
    assert lay.id in [l.id for l in win.scene.layouts]


def test_each_sheet_keeps_its_own_arrangement(win):
    """Leave Layout 1 with a model pane beside the paper and it is still
    there when you come back to it."""
    a = win._new_sheet("A3")
    extra = win.new_viewport_dock("Right")
    win.switch_space("model")
    win.switch_space(a.id)
    assert extra in win.all_viewports()
    assert extra.space == "model"


def test_clicking_a_pane_does_not_change_the_window_space(win):
    """`_set_active_viewport` used to refresh the tabs from the pane it
    had just been handed, so going back to a model pane silently snapped
    the strip to Model with nothing said about it."""
    win.set_view_layout("quad")
    lay = win._new_sheet("A3")
    win.switch_space("model")
    win._set_active_viewport(win.aux_viewports[0])
    assert win.space == "model"
    win.switch_space(lay.id)
    win._set_active_viewport(win.active_viewport)
    assert win.space == lay.id


def test_the_active_pane_on_a_sheet_is_the_sheet(win):
    """`active_viewport` fell back to the primary whenever the pane it
    was holding had a hidden dock. On a layout tab the primary is the
    hidden one, so the fallback has to pick something you can see."""
    lay = win._new_sheet("A3")
    assert win.active_viewport.space == lay.id
    assert win.active_viewport in win.all_viewports()


def test_the_tab_follows_the_window_not_the_pane(win):
    win.set_view_layout("quad")
    lay = win._new_sheet("A3")
    idx = win.space_tabs.currentIndex()
    assert win.space_tabs.tabData(idx) == lay.id
    win.switch_space("model")
    assert win.space_tabs.tabData(win.space_tabs.currentIndex()) == "model"


def test_losing_a_layout_puts_you_back_in_model_space(win):
    """Undo the sheet you are standing on and the tab under you goes."""
    lay = win._new_sheet("A3")
    win.scene.layouts.clear()
    win.scene.notify()
    assert win.space == "model"
    assert lay.id not in win._space_states


def test_a_pane_can_be_pointed_at_a_sheet_on_its_own(win):
    """The thing Rhino will not do, and the reason spaces stay a
    property of a pane underneath the workspaces."""
    lay = win._new_sheet("A3")
    win.switch_space("model")
    win.set_view_layout("quad")
    aux = win.aux_viewports[0]
    win.set_pane_space(aux, lay.id)
    assert aux.space == lay.id
    assert win.space == "model"          # the window did not move
    assert win.viewport.space == "model"


def test_a_pane_menu_offers_the_sheets(win):
    """The other half of it. Tabs are workspaces, but a space is still a
    property of a pane, and the pane's own menu is where you say so."""
    lay = win._new_sheet("A3")
    win.switch_space("model")
    win.set_view_layout("quad")
    aux = win.aux_viewports[0]
    menu = win._viewport_menu(aux)
    labels = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert "Model" in labels
    assert lay.name in labels
    next(a for a in menu.actions() if a.text() == lay.name).trigger()
    assert aux.space == lay.id
    assert win.space == "model"          # the window stayed where it was
    assert win.viewport.space == "model"


def test_a_pane_menu_says_nothing_about_space_with_no_sheets(win):
    """One space is not a choice."""
    menu = win._viewport_menu(win.viewport)
    labels = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert "Model" not in labels


def test_the_panels_do_not_move_when_you_change_tab(win):
    """A tab remembers its panes, not the whole window, so Properties
    stays where it was put."""
    area_before = win.dockWidgetArea(win.properties.parentWidget())
    win._new_sheet("A3")
    win.switch_space("model")
    assert win.dockWidgetArea(win.properties.parentWidget()) == area_before


def test_the_plus_button_offers_a_paper_size(win):
    """Clicking it used to make an A3 with nothing asked."""
    from PySide6.QtWidgets import QToolButton
    add = win.add_space_btn
    assert add.popupMode() == QToolButton.ToolButtonPopupMode.InstantPopup
    assert add.menu() is not None
    labels = [a.text() for a in add.menu().actions() if not a.isSeparator()]
    assert any("A3" in t for t in labels)
    assert len(win.scene.layouts) == 0
