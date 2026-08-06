"""The `+` on the space-tab strip sits next to the tabs and says what it is.

Two things were wrong with that strip. A `QTabBar` reserves room for the
scroll buttons it might one day need, and it asks for that room as a
minimum, so a bar holding the single `Model` tab still demanded fifty
pixels more than the tab, which came out as a gap between the tab and the
button. It only needs that floor when the tabs are wider than the strip,
which with one tab they are not.

And the button was a bare `+`. A drafting sheet is the one thing in the
app you would never guess is behind it, so it spells itself out until you
have made one, and goes back to being a `+` once you know.
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


def test_the_tabs_ask_for_no_more_room_than_the_tabs_need(win):
    """The gap, measured where it comes from."""
    tabs = win.space_tabs
    assert tabs.minimumSizeHint().width() <= tabs.sizeHint().width()


def test_the_button_sits_next_to_the_tab(win):
    """The gap as it was met, in pixels, on a strip that has been laid
    out. The window itself was never shown, so the strip it built has
    never had a size; this asks for the same one again and gives it one."""
    row = win._build_space_tab_row()
    row.resize(640, 26)
    row.layout().invalidate()
    row.layout().activate()
    tabs = win.space_tabs
    assert tabs.width() == tabs.tabRect(0).width(), "wider than its tabs"
    gap = win.add_space_btn.x() - (tabs.x() + tabs.width())
    assert 0 <= gap <= 6, f"{gap}px between the last tab and the button"


def test_a_strip_too_narrow_for_its_tabs_can_still_scroll(win):
    """The floor is only dropped where it is not needed. Six sheets in a
    strip with room for two has to keep its scroll buttons, or the tabs
    off the end become unreachable."""
    tabs = win.space_tabs
    for _ in range(6):
        win._new_sheet("A3")
    assert tabs.minimumSizeHint().width() < tabs.sizeHint().width()
    assert tabs.usesScrollButtons()


def test_the_button_spells_itself_out_until_you_have_a_layout(win):
    assert "layout" in win.add_space_btn.text().lower()


def test_it_goes_back_to_a_plus_once_a_layout_exists(win):
    win._new_sheet("A3")
    assert win.add_space_btn.text().strip() == "+"


def test_losing_the_last_layout_brings_the_words_back(win):
    """Undo the sheet you just made and you are a newcomer again."""
    win._new_sheet("A3")
    win.scene.layouts.clear()
    win.scene.notify()
    assert "layout" in win.add_space_btn.text().lower()
