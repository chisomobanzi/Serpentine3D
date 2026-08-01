"""Every tool stays on the palette.

Thirty-two tools stacked in one column want 1073 px. A window 936 px tall
— which is what the saved geometry restores to — gives the left strip 854,
so Trim, Split, Offset, Fillet, Join, Explode, Control points and Delete
fell off the bottom into a chevron nobody finds. Eight tools, including
Delete, gone from the palette because the window was not tall enough.

So the palette flows: when a column will not hold the rest, the rest go
into a second column beside it. The strip gets wider by one button rather
than shorter by eight tools, and it goes back to one column on a screen
tall enough to take it.
"""

import pytest
from PySide6.QtWidgets import QToolButton

from serpentine3d.ui.tool_palette import STEP, ToolPalette, flow_columns

GROUPS = [
    [("Line", "line"), ("Circle", "circle")],
    [("Box", "box"), ("Sphere", "sphere"), ("Delete", "delete")],
]


# ----------------------------------------------------------------- the flow

def test_what_fits_stays_in_one_column():
    assert flow_columns([10, 10, 10], 100) == [(0, 0), (0, 10), (0, 20)]


def test_the_one_that_would_overhang_starts_the_next_column():
    assert flow_columns([10, 10, 10], 25) == [(0, 0), (0, 10), (1, 0)]


def test_an_item_taller_than_the_column_is_still_placed():
    """Better one overhanging button than a tool with nowhere to go."""
    assert flow_columns([40], 25) == [(0, 0)]


def test_exactly_filling_a_column_does_not_open_an_empty_one():
    assert flow_columns([10, 10], 20) == [(0, 0), (0, 10)]


# -------------------------------------------------------------- the palette

@pytest.fixture
def palette(_qapp):
    p = ToolPalette(GROUPS, lambda command: None)
    yield p
    p.deleteLater()


def _buttons(palette):
    return palette.findChildren(QToolButton)


def test_every_tool_gets_a_button(palette):
    assert sorted(b.text() for b in _buttons(palette)) == [
        "Box", "Circle", "Delete", "Line", "Sphere"]


def test_a_short_palette_keeps_every_tool_on_screen(palette):
    """The bug itself: not one button may hang below the fold."""
    palette.resize(STEP * 3, STEP * 2)
    palette.reflow()
    assert all(b.geometry().bottom() <= palette.height()
               for b in _buttons(palette))


def test_a_short_palette_spends_width_instead_of_dropping_tools(palette):
    palette.resize(STEP * 3, STEP * 2)
    palette.reflow()
    assert palette.columns() > 1


def test_a_tall_palette_stays_a_single_strip(palette):
    palette.resize(STEP * 3, STEP * 40)
    palette.reflow()
    assert palette.columns() == 1
    assert palette.sizeHint().width() <= STEP + palette.margin() * 2


def test_the_palette_asks_for_the_width_its_columns_need(palette):
    palette.resize(STEP * 3, STEP * 2)
    palette.reflow()
    assert palette.sizeHint().width() >= palette.columns() * STEP


def test_a_group_rule_never_opens_a_column(palette):
    """A separator at the top of a column is a line under nothing."""
    palette.resize(STEP * 3, STEP * 2)
    palette.reflow()
    for rule in palette.rules():
        if rule.isVisible():
            assert rule.y() > 0


# ------------------------------------------------------------- in the window

def test_the_toolbar_carries_the_palette(_qapp):
    from PySide6.QtWidgets import QToolBar

    from serpentine3d.app import MainWindow
    win = MainWindow()
    try:
        bar = win.findChild(QToolBar, "toolPalette")
        pal = bar.findChild(ToolPalette)
        assert pal is not None, "the tool strip is not the flowing palette"
        assert len(pal.findChildren(QToolButton)) > 24, (
            "the palette should carry every tool, not the two dozen that "
            "happened to fit")
    finally:
        win.close()
