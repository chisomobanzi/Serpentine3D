"""`4view` lays the four panes out again, whatever state they were left in.

It built the 2x2 once, the first time it was asked, and after that only
un-hid the three side panes. So every way of disturbing the layout was a
one-way door: close the Perspective pane with the x on its title bar and
nothing brought it back, drag two panes into a tab stack and they stayed
stacked, float one off and it stayed floating. The arrangement is saved
between sessions too, so a window that got into that state came back into
it every launch with no way out.

Asking for four viewports now means four viewports, in a 2x2, every time.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def win(tmp_path, monkeypatch):
    monkeypatch.setenv("SERP3D_CONFIG", str(tmp_path / "settings.json"))
    monkeypatch.setenv("SERP3D_NO_RECOVER", "1")
    from serpentine3d.app import MainWindow
    w = MainWindow()
    w.set_view_layout("quad")
    yield w
    w.close()


def _panes(w):
    return [w._primary_dock] + list(w.aux_docks)


def _showing(w):
    return [d for d in _panes(w) if d.isVisibleTo(w)]


def test_the_quad_starts_out_as_four_panes_side_by_side(win):
    assert len(_showing(win)) == 4
    assert not win.tabifiedDockWidgets(win._primary_dock)


def test_it_reopens_the_pane_you_closed_with_the_x(win):
    """The Perspective pane is the primary one and it has a close button
    like any other, so it was the easiest of the four to lose for good."""
    win._primary_dock.close()
    assert len(_showing(win)) == 3
    win.set_view_layout("quad")
    assert len(_showing(win)) == 4


def test_it_reopens_a_side_pane_you_closed(win):
    win.aux_docks[1].close()
    win.set_view_layout("quad")
    assert len(_showing(win)) == 4


def test_it_pulls_the_panes_back_out_of_a_tab_stack(win):
    """Two panes dragged onto each other become tabs, and a tab stack is
    not four viewports however many of them are in it."""
    win.tabifyDockWidget(win._primary_dock, win.aux_docks[0])
    assert win.tabifiedDockWidgets(win._primary_dock)
    win.set_view_layout("quad")
    assert not win.tabifiedDockWidgets(win._primary_dock)
    assert len(_showing(win)) == 4


def test_it_brings_a_floated_pane_back_into_the_window(win):
    win.aux_docks[2].setFloating(True)
    win.set_view_layout("quad")
    assert not win.aux_docks[2].isFloating()
    assert len(_showing(win)) == 4


def test_a_single_view_still_leaves_you_the_one_pane(win):
    """1view after closing the Perspective pane used to leave the window
    with nothing in it at all."""
    win._primary_dock.close()
    win.set_view_layout("single")
    assert _showing(win) == [win._primary_dock]


def test_the_panes_keep_the_views_they_are_named_for(win):
    win.tabifyDockWidget(win._primary_dock, win.aux_docks[0])
    win.set_view_layout("quad")
    assert [v._view_name for v in win.aux_viewports] == \
        ["top", "front", "right"]


def test_asking_twice_does_not_make_more_panes(win):
    win.set_view_layout("quad")
    win.set_view_layout("quad")
    assert len(win.aux_viewports) == 3
    assert len(_showing(win)) == 4


def test_a_session_that_ended_with_no_pane_left_opens_on_one(
        tmp_path, monkeypatch):
    """The arrangement is saved and restored verbatim, so a window closed
    with every pane shut would otherwise open with nothing in it at all,
    and there would be nothing to type `4view` into."""
    monkeypatch.setenv("SERP3D_CONFIG", str(tmp_path / "settings.json"))
    monkeypatch.setenv("SERP3D_NO_RECOVER", "1")
    from serpentine3d.app import MainWindow
    w = MainWindow()
    w.set_view_layout("quad")
    for dock in _panes(w):
        dock.close()
    w.isVisible = lambda: True
    w.close()

    again = MainWindow()
    assert _showing(again)
    again.set_view_layout("quad")
    assert len(_showing(again)) == 4
    again.close()
