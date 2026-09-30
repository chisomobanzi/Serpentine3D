"""With object snaps switched off, the Osnap bar has to look it.

The master "On" button greyed out on its own while End, Point, Mid, Cen,
Quad and Int stayed lit, so the bar with snaps off looked like the bar
with snaps on, and a sheet where nothing would snap read as snaps being
broken (QA, 2026-09-30). The types keep what they were set to, for when
snaps come back on, but look asleep while the master is off.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def bar():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from serpentine3d.app import MainWindow
    w = MainWindow()
    w.resize(1300, 850)
    try:
        yield w, w.osnap_bar
    finally:
        w.mark_saved()
        w.close()


def _looks(button):
    """The button as drawn, as bytes to compare."""
    img = button.grab().toImage()
    return bytes(img.constBits())


def test_the_types_stop_looking_on_when_the_master_is_off(bar):
    _w, osnaps = bar
    end = osnaps._buttons["end"]
    osnaps._master.setChecked(True)
    assert end.isChecked()
    lit = _looks(end)

    osnaps._master.setChecked(False)

    assert end.isChecked(), "End is still set for when snaps come back on"
    assert _looks(end) != lit, "End must not look on while snaps are off"

    osnaps._master.setChecked(True)

    assert _looks(end) == lit


def test_switching_snaps_off_by_command_dims_them_too(bar):
    w, osnaps = bar
    end = osnaps._buttons["end"]
    lit = _looks(end)

    w.run_command("osnap")
    w.processor.provide_text("All")
    w.processor.provide_text("Off")

    assert not w.viewport.snaps.enabled
    assert _looks(end) != lit


def test_a_type_that_is_off_looks_the_same_either_way(bar):
    _w, osnaps = bar
    perp = osnaps._buttons["perp"]
    assert not perp.isChecked()
    osnaps._master.setChecked(True)
    off = _looks(perp)

    osnaps._master.setChecked(False)

    assert _looks(perp) == off


def test_the_master_says_off_when_it_is_off(bar):
    _w, osnaps = bar
    osnaps._master.setChecked(True)
    assert osnaps._master.text() == "On"

    osnaps._master.setChecked(False)

    assert osnaps._master.text() == "Off"
