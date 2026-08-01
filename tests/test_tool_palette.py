"""Every tool stays on the palette, in one column.

Thirty-two tools at a comfortable size want 1073 px of column. A window
936 px tall — which is what the saved geometry restores to — gives the
left strip 854, so Trim, Split, Offset, Fillet, Join, Explode, Control
points and Delete fell off the bottom into a chevron nobody finds. Eight
tools, Delete among them, gone because the window was not tall enough.

The strip stays one button wide and gives each tool a little less height
instead. Below a floor it stops shrinking and scrolls, so nothing is ever
dropped, but at the sizes anyone works at they simply all fit.
"""

import pytest
from PySide6.QtWidgets import QToolButton

from serpentine3d.ui.tool_palette import (
    MAX_PITCH, MIN_PITCH, RULE, ToolPalette, button_pitch,
)

# The real palette's shape: thirty-two tools in seven groups.
GROUPS = [[(f"Tool {g}{i}", f"tool{g}{i}") for i in range(n)]
          for g, n in enumerate([6, 6, 4, 5, 3, 4, 4])]
TOOLS = sum(len(g) for g in GROUPS)
RESTORED = 854                               # what a restored window gives


# ----------------------------------------------------------------- the pitch

def test_a_tall_strip_leaves_the_tools_their_full_size():
    assert button_pitch(4000, 32, 6) == MAX_PITCH


def test_a_short_strip_takes_the_height_out_of_the_tools():
    """Rather than out of the number of them."""
    pitch = button_pitch(RESTORED, 32, 6)
    assert pitch < MAX_PITCH
    assert 32 * pitch + 6 * RULE <= RESTORED


def test_the_tools_stop_shrinking_before_they_stop_being_clickable():
    assert button_pitch(200, 32, 6) == MIN_PITCH


def test_no_tools_is_not_a_division_by_zero():
    assert button_pitch(200, 0, 0) == MAX_PITCH


# --------------------------------------------------------------- the palette

@pytest.fixture
def palette(_qapp):
    p = ToolPalette(GROUPS, lambda command: None)
    yield p
    p.deleteLater()


def _buttons(palette):
    return palette.findChildren(QToolButton)


def test_every_tool_gets_a_button(palette):
    assert len(_buttons(palette)) == TOOLS


def test_a_restored_window_holds_every_tool_without_doubling_up(palette):
    """The whole of it: one column, nothing below the fold."""
    palette.resize(60, RESTORED)
    palette.reflow()
    assert palette.columns() == 1
    assert len({b.x() for b in _buttons(palette)}) == 1, "a second column"
    assert all(b.geometry().bottom() <= RESTORED for b in _buttons(palette))


def test_the_strip_is_never_wider_than_one_tool(palette):
    palette.resize(60, RESTORED)
    palette.reflow()
    assert palette.sizeHint().width() <= MAX_PITCH + 6


def test_a_tall_window_gives_the_tools_their_room_back(palette):
    palette.resize(60, MAX_PITCH * TOOLS * 2)
    palette.reflow()
    assert palette.pitch() == MAX_PITCH


def test_the_tools_are_stacked_in_order(palette):
    palette.resize(60, RESTORED)
    palette.reflow()
    tops = [b.y() for b in _buttons(palette)]
    assert tops == sorted(tops)
    assert len(set(tops)) == TOOLS


def test_a_window_too_short_even_for_that_scrolls_rather_than_drops(palette):
    """Asking for more height than there is is how the scroll area is
    told to scroll — the alternative is tools nobody can reach."""
    palette.resize(60, 300)
    palette.reflow()
    assert palette.pitch() == MIN_PITCH
    assert palette.sizeHint().height() > 300


def test_a_group_rule_is_a_line_under_something(palette):
    palette.resize(60, RESTORED)
    palette.reflow()
    for rule in palette.rules():
        assert rule.y() > 0


# ------------------------------------------------------------- in the window

def test_the_toolbar_carries_the_palette(_qapp):
    from PySide6.QtWidgets import QScrollArea, QToolBar

    from serpentine3d.app import MainWindow
    win = MainWindow()
    try:
        bar = win.findChild(QToolBar, "toolPalette")
        pal = bar.findChild(ToolPalette)
        assert pal is not None, "the tool strip is not the palette"
        assert pal.findChild(QScrollArea) is None
        assert isinstance(pal.parentWidget().parentWidget(), QScrollArea), (
            "the palette needs somewhere to scroll on a short screen")
        assert len(pal.findChildren(QToolButton)) > 24, (
            "the palette should carry every tool, not the two dozen that "
            "happened to fit")
    finally:
        win.close()
