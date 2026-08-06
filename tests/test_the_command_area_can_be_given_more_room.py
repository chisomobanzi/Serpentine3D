"""You can drag the command area taller and take the room off the viewport.

The command dock was pinned shut two ways over. Its container was laid out
with a Fixed vertical size policy, which handed the dock a maximum height
equal to the height it opened at, so there was no separator to grab:
nothing above it could give it room, because it would not take any. And the
history view inside it carried `setMaximumHeight(64)`, so even had the dock
grown, the echoed history would have sat in the same four lines with the
new space empty below it.

Room given to the command area now goes to the history, which is the part
worth reading back, and it still opens at the height it always did.

The drag itself wants a window that has actually been laid out on a screen,
so what is checked here is everything that made the drag impossible: the
caps, the size policies and where the room goes once there is some. The
grip is checked by hand.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QSizePolicy

# What the dock has always opened at. Fonts and DPI move it about, so this
# is a range around the shape of it rather than a number off one machine.
START_MIN, START_MAX = 90, 260
UNBOUNDED = 100_000        # Qt's own "no maximum" is 16777215


@pytest.fixture
def win(tmp_path, monkeypatch):
    monkeypatch.setenv("SERP3D_CONFIG", str(tmp_path / "settings.json"))
    monkeypatch.setenv("SERP3D_NO_RECOVER", "1")
    from serpentine3d.app import MainWindow
    w = MainWindow()
    w.resize(1400, 900)
    w.layout().activate()
    yield w
    w.close()


def _tall(widget, height):
    """Give a widget the room a separator drag would give it.

    Nobody showed this window, so no resize event is delivered and the
    layout does not know to think again: it has to be told.
    """
    widget.resize(widget.width() or 800, height)
    widget.layout().invalidate()
    widget.layout().activate()


def test_it_still_asks_to_open_at_the_height_it_always_did(win):
    """Being draggable is not an excuse to start out eating the viewport."""
    asked = win._cmd_dock.widget().sizeHint().height()
    assert START_MIN <= asked <= START_MAX


def test_nothing_caps_the_command_area_at_the_height_it_opens_at(win):
    """The bug as it was met: no grip, because the dock would not take room
    however much was offered it."""
    assert win._cmd_dock.maximumHeight() > UNBOUNDED
    assert win._cmd_dock.widget().sizePolicy().verticalPolicy() \
        is not QSizePolicy.Policy.Fixed


def test_nothing_caps_the_history_either(win):
    assert win.command_line.echo_view.maximumHeight() > UNBOUNDED


def test_the_history_grows_into_the_room_the_command_area_is_given(win):
    """Four lines of history in a pane three times that tall would be a
    taller command area with nothing to show for it."""
    cl = win.command_line
    _tall(cl, cl.sizeHint().height())
    before = cl.echo_view.height()
    _tall(cl, cl.sizeHint().height() + 200)
    assert cl.echo_view.height() >= before + 190


def test_the_prompt_keeps_its_own_height_while_the_history_grows(win):
    """Only the history is worth more room; the row under it should stay
    put rather than share the growth."""
    cl = win.command_line
    _tall(cl, cl.sizeHint().height())
    line = cl.input.height()
    _tall(cl, cl.sizeHint().height() + 200)
    assert cl.input.height() == line


def test_the_osnap_bar_keeps_its_own_height_too(win):
    box = win._cmd_dock.widget()
    _tall(box, box.sizeHint().height())
    bar = win.osnap_bar.height()
    _tall(box, box.sizeHint().height() + 200)
    assert win.osnap_bar.height() == bar


def test_the_history_cannot_be_squeezed_away_to_nothing(win):
    """Dragging the other way has a floor: a command line with no line of
    history left on it is not a command line."""
    cl = win.command_line
    floor = cl.minimumSizeHint().height()
    one_line = cl.echo_view.minimumSizeHint().height()
    assert floor >= cl.input.sizeHint().height() + one_line
