"""The ghost under the cursor ends up where the cursor is.

It was capped at 30 updates a second, and a move inside the gap was
dropped with nothing to make up for it. A point's ghost costs a fraction
of a millisecond, so the cap only made it trail behind the cursor, and
when the cursor stopped inside a gap the ghost stayed where it had been.
"""

from __future__ import annotations

import pytest

from serpentine3d.app import MainWindow


@pytest.fixture
def window():
    w = MainWindow()
    asked = []
    real = w.processor.preview_for

    def spy(value):
        asked.append(tuple(value))
        return real(value)

    w.processor.preview_for = spy
    w.run_command("points")
    yield w, asked
    w.mark_saved()
    w.close()


def test_a_cheap_ghost_follows_every_move(window):
    w, asked = window
    for x in (1.0, 2.0, 3.0):
        w._on_mouse_world((x, 0.0, 0.0))
    assert asked == [(1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (3.0, 0.0, 0.0)]


def test_an_expensive_ghost_catches_up_with_where_the_cursor_stopped(
        window):
    from PySide6.QtCore import QCoreApplication, QElapsedTimer
    w, asked = window
    w._on_mouse_world((1.0, 0.0, 0.0))
    w._ghost_cost_ms = 50.0                 # as if it took that long
    w._on_mouse_world((2.0, 0.0, 0.0))      # inside the gap: skipped
    assert asked[-1] == (1.0, 0.0, 0.0)
    clock = QElapsedTimer()
    clock.start()
    while asked[-1] != (2.0, 0.0, 0.0) and clock.elapsed() < 2000:
        QCoreApplication.processEvents()
    assert asked[-1] == (2.0, 0.0, 0.0)


def test_a_pick_in_the_model_is_made_with_a_drawn_crosshair(window):
    """The system cursor goes over everything and is rounded and scaled
    its own way, so in the model the frame draws the crosshair, centred
    by the same projection as the point in its gap."""
    from PySide6.QtCore import Qt
    w, _asked = window
    vp = w.viewport
    assert vp._cursor_shape == "drawn"
    assert vp.cursor().shape() == Qt.CursorShape.BlankCursor
    w.processor.provide_text("")
    assert vp.cursor().shape() == Qt.CursorShape.ArrowCursor
    w.run_command("line")                    # before its first point
    assert vp.cursor().shape() == Qt.CursorShape.BlankCursor
    w.processor.cancel()
    assert vp.cursor().shape() == Qt.CursorShape.ArrowCursor
