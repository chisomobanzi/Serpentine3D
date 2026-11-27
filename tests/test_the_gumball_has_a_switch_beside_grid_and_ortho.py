"""The gumball is switched on and off from the bar under the command line.

Grid and Ortho have a button there, and the gumball had only the `gumball`
command, which nobody finds. The button is the same switch: it saves beside
the gumball's alignment, every pane follows it, and the command moves the
button too.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def window(tmp_path, monkeypatch):
    monkeypatch.setenv("SERP3D_CONFIG", str(tmp_path / "settings.json"))
    monkeypatch.setenv("SERP3D_NO_RECOVER", "1")
    from serpentine3d.app import MainWindow
    w = MainWindow()
    try:
        yield w
    finally:
        w.mark_saved()
        w.close()


def test_the_bar_has_a_gumball_button_that_starts_on(window):
    button = window.osnap_bar._gumball
    assert button.text() == "Gumball"
    assert button.isCheckable()
    assert button.isChecked() == window.viewport.gumball.enabled is True


def test_the_button_switches_the_gumball_off_and_on(window):
    button = window.osnap_bar._gumball
    button.setChecked(False)
    assert not window.viewport.gumball.enabled
    assert all(not vp.gumball.enabled for vp in window.all_viewports())
    button.setChecked(True)
    assert window.viewport.gumball.enabled


def test_switching_it_off_keeps_the_alignment(window):
    window.viewport.gumball.set_align("world")
    window.osnap_bar._gumball.setChecked(False)
    assert window.cfg.get("gumball", "enabled") is False
    assert window.cfg.get("gumball", "align") == "world"


def test_the_command_moves_the_button(window):
    button = window.osnap_bar._gumball
    window.run_command("gumball")
    assert not window.viewport.gumball.enabled
    assert not button.isChecked()
    window.run_command("gumball")
    assert button.isChecked()
