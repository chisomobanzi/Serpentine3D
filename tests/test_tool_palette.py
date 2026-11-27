"""Every tool stays on the palette, in 1, 2, or more columns, at full size.

Thirty-two tools want 1076 px of column. A window 936 px tall — which is
what the saved geometry restores to — gives the left strip 854, so Trim,
Split, Offset, Fillet, Join, Explode, Control points and Delete fell off
the bottom into a chevron nobody finds. Eight tools, Delete among them,
gone because the window was not tall enough.

By default the strip is one column and scrolls, and dragging its right edge
snaps it to 1, 2, or more columns with tools flowing left-to-right within
each group.
"""

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QMainWindow, QScrollArea, QToolBar, QToolButton, QWidget

from serpentine3d.ui.tool_palette import (
    BUTTON,
    GAP,
    ICON,
    MARGIN,
    PITCH,
    ToolPalette,
    columns_for_width,
    tool_strip,
)

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


# ------------------------------------------------------------ multi-column

def test_multi_column_flows_left_to_right_within_each_group(palette):
    palette.set_columns(2)
    assert palette.columns() == 2
    assert palette.sizeHint().width() == 2 * PITCH - GAP + MARGIN * 2

    # First group has 6 tools: 3 rows of 2 columns, flowing left-to-right.
    first_group = _buttons(palette)[:6]
    xs = [b.x() for b in first_group]
    ys = [b.y() for b in first_group]
    assert xs == [MARGIN, MARGIN + PITCH] * 3
    assert ys[0] == ys[1] < ys[2] == ys[3] < ys[4] == ys[5]

    # Group rules span the full multi-column width.
    for rule in palette.rules():
        assert rule.width() == 2 * PITCH - GAP


def test_three_columns_reduces_height_and_clamps_bounds(palette):
    h1 = palette.sizeHint().height()
    palette.set_columns(3)
    assert palette.columns() == 3
    assert palette.sizeHint().width() == 3 * PITCH - GAP + MARGIN * 2
    assert palette.sizeHint().height() < h1

    palette.set_columns(0)
    assert palette.columns() == 1
    palette.set_columns(99)
    assert palette.columns() == 6


def test_columns_for_width_snaps_to_nearest_column():
    assert columns_for_width(10) == 1
    assert columns_for_width(BUTTON + MARGIN * 2) == 1
    assert columns_for_width(2 * PITCH - GAP + MARGIN * 2) == 2
    assert columns_for_width(3 * PITCH - GAP + MARGIN * 2) == 3
    assert columns_for_width(500, max_columns=6) == 6


def test_dragging_grip_snaps_toolbar_columns(_qapp):
    win = QMainWindow()
    win.resize(800, 900)
    win.setCentralWidget(QWidget())
    bar = QToolBar("Tools")
    bar.setOrientation(Qt.Orientation.Vertical)
    bar.setMovable(False)
    strip = tool_strip(GROUPS, lambda _c: None, bar)
    bar.addWidget(strip)
    win.addToolBar(Qt.ToolBarArea.LeftToolBarArea, bar)
    win.show()
    _qapp.processEvents()

    try:
        pal = strip.widget()
        grip = bar.findChild(QWidget, "toolPaletteGrip")
        assert grip is not None
        assert pal.columns() == 1

        def drag_to_local_x(target_x: int):
            start = grip.mapToGlobal(QPointF(grip.width() / 2, 20))
            end = QPointF(strip.mapToGlobal(grip.rect().topLeft())) + QPointF(target_x, 20)
            grip.mousePressEvent(QMouseEvent(
                QEvent.Type.MouseButtonPress, QPointF(1, 20), start,
                Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier))
            grip.mouseMoveEvent(QMouseEvent(
                QEvent.Type.MouseMove, QPointF(1, 20), end,
                Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier))
            grip.mouseReleaseEvent(QMouseEvent(
                QEvent.Type.MouseButtonRelease, QPointF(1, 20), end,
                Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier))
            _qapp.processEvents()

        drag_to_local_x(2 * PITCH - GAP + MARGIN * 2)
        assert pal.columns() == 2
        w2 = bar.width()

        drag_to_local_x(3 * PITCH - GAP + MARGIN * 2)
        assert pal.columns() == 3
        w3 = bar.width()
        assert w3 > w2

        drag_to_local_x(BUTTON + MARGIN * 2)
        assert pal.columns() == 1
        assert bar.width() < w2
    finally:
        win.close()


# ------------------------------------------------------------- in the window

def test_the_toolbar_carries_the_palette(_qapp):
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


def test_toolbar_columns_persists_in_window_config(tmp_path, monkeypatch, _qapp):
    monkeypatch.setenv("SERP3D_CONFIG", str(tmp_path / "settings.json"))
    monkeypatch.setenv("SERP3D_NO_RECOVER", "1")
    from serpentine3d.app import MainWindow

    win = MainWindow()
    pal = win.findChild(QToolBar, "toolPalette").findChild(ToolPalette)
    pal.set_columns(2)
    win.isVisible = lambda: True
    win.close()

    reopened = MainWindow()
    try:
        pal2 = reopened.findChild(QToolBar, "toolPalette").findChild(ToolPalette)
        assert pal2.columns() == 2
    finally:
        reopened.close()
