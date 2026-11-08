"""The strip over Properties: view changes, zooms, hide, isolate and lock.

A paired button runs its first command on a left click and its
counterpart on a right click, so Hide and Show share one place.
"""

import pytest
from PySide6.QtCore import QPoint

from serpentine3d.commands.base import resolve
from serpentine3d.ui.view_strip import TOOLS, ViewStrip


@pytest.fixture
def strip(_qapp):
    ran = []
    s = ViewStrip(ran.append)
    s.ran = ran
    yield s
    s.deleteLater()


def test_every_tool_has_a_drawn_icon_and_a_real_command(strip):
    for _label, command, _alt_label, alt_command in TOOLS:
        assert not strip.buttons[command].icon().isNull(), command
        assert resolve(command) is not None, command
        if alt_command:
            assert resolve(alt_command) is not None, alt_command


def test_a_left_click_runs_the_first_command(strip):
    strip.buttons["hide"].click()
    strip.buttons["undoview"].click()
    assert strip.ran == ["hide", "undoview"]


def test_a_right_click_runs_the_counterpart(strip):
    pairs = {c: alt for _l, c, _al, alt in TOOLS if alt}
    assert pairs == {"hide": "show", "isolate": "unisolate",
                     "lock": "unlockall", "lockother": "unlockall"}
    for command, alt in pairs.items():
        strip.buttons[command].customContextMenuRequested.emit(QPoint(1, 1))
        assert strip.ran[-1] == alt
    assert "Right-click" in strip.buttons["isolate"].toolTip()


def test_a_single_button_ignores_a_right_click(strip):
    strip.buttons["zoomextents"].customContextMenuRequested.emit(QPoint(1, 1))
    assert strip.ran == []
    assert "Right-click" not in strip.buttons["zoomextents"].toolTip()


def test_the_strip_sits_over_the_properties_title(_qapp):
    from serpentine3d.app import MainWindow
    win = MainWindow()
    try:
        head = win._prop_dock.titleBarWidget()
        assert win.view_strip.parentWidget() is head
        column = head.layout()
        assert (column.indexOf(win.view_strip)
                < column.indexOf(win._prop_title))
    finally:
        win.mark_saved()
        win.close()


def test_a_zoom_from_the_strip_leaves_a_pick_running(_qapp):
    from serpentine3d.app import MainWindow
    win = MainWindow()
    try:
        win.run_command("line")
        assert win.processor.busy
        win.view_strip.buttons["zoomextents"].click()
        win.view_strip.buttons["undoview"].click()
        assert win.processor.busy
        assert win.processor.active.name == "line"
    finally:
        win.processor.cancel()
        win.mark_saved()
        win.close()
