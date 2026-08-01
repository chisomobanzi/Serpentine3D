"""Every tool stays on the palette, in one column, at full size.

Thirty-two tools want 1076 px of column. A window 936 px tall — which is
what the saved geometry restores to — gives the left strip 854, so Trim,
Split, Offset, Fillet, Join, Explode, Control points and Delete fell off
the bottom into a chevron nobody finds. Eight tools, Delete among them,
gone because the window was not tall enough.

The strip does not answer that by doubling its width, and it does not
answer it by shrinking the icons either — they are small enough already.
The tools keep their size and the overflow scrolls.
"""

import pytest
from PySide6.QtWidgets import QToolButton

from serpentine3d.ui.tool_palette import BUTTON, ICON, MARGIN, ToolPalette

# The real palette's shape: thirty-two tools in seven groups.
GROUPS = [[(f"Tool {g}{i}", f"tool{g}{i}") for i in range(n)]
          for g, n in enumerate([6, 6, 4, 5, 3, 4, 4])]
TOOLS = sum(len(g) for g in GROUPS)
RESTORED = 854                               # what a restored window gives


@pytest.fixture
def palette(_qapp):
    p = ToolPalette(GROUPS, lambda command: None)
    yield p
    p.deleteLater()


def _buttons(palette):
    return palette.findChildren(QToolButton)


def test_every_tool_gets_a_button(palette):
    assert len(_buttons(palette)) == TOOLS


def test_the_tools_are_one_column_stacked_in_order(palette):
    palette.resize(60, RESTORED)
    palette.reflow()
    assert palette.columns() == 1
    assert len({b.x() for b in _buttons(palette)}) == 1, "a second column"
    tops = [b.y() for b in _buttons(palette)]
    assert tops == sorted(tops)
    assert len(set(tops)) == TOOLS


def test_a_short_window_does_not_shrink_the_tools(palette):
    """The icons are the thing that is already too small. A window with
    no room for all of them is not a reason to make them harder to hit."""
    palette.resize(60, 400)
    palette.reflow()
    assert all(b.size().toTuple() == (BUTTON, BUTTON)
               for b in _buttons(palette))
    assert all(b.iconSize().toTuple() == (ICON, ICON)
               for b in _buttons(palette) if not b.icon().isNull())


def test_a_short_window_asks_for_more_height_than_it_has(palette):
    """Which is how the scroll area is told to scroll. The alternative is
    tools nobody can reach."""
    palette.resize(60, 400)
    assert palette.sizeHint().height() > 400


def test_the_strip_is_never_wider_than_one_tool(palette):
    assert palette.sizeHint().width() == BUTTON + MARGIN * 2


def test_a_group_rule_is_a_line_under_something(palette):
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
        assert isinstance(pal.parentWidget().parentWidget(), QScrollArea), (
            "the palette needs somewhere to scroll on a short screen")
        assert len(pal.findChildren(QToolButton)) > 24, (
            "the palette should carry every tool, not the two dozen that "
            "happened to fit")
    finally:
        win.close()


def test_it_can_be_measured_while_it_is_still_being_built(_qapp):
    """A size hint is answerable the moment the widget exists, and the
    buttons are parented on well before reflow works out a height.  An
    AttributeError raised inside a Qt override does not surface as itself:
    it comes back as a bare SystemError from wherever Qt happened to ask."""
    seen = []

    class Watched(ToolPalette):
        def _button(self, label, command, invoke):
            seen.append(self.sizeHint().height())     # mid-construction
            return super()._button(label, command, invoke)

    palette = Watched(GROUPS, lambda command: None)
    assert seen and all(h >= 0 for h in seen)
    assert palette.sizeHint().height() > 0
