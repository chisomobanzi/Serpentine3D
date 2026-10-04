"""A hidden tool strip has a visible way back through the View menu."""

import json

import pytest
from PySide6.QtWidgets import QToolBar, QToolButton

from serpentine3d.ui.tool_palette import ToolPalette


@pytest.fixture
def windows(tmp_path, monkeypatch, _qapp):
    monkeypatch.setenv("SERP3D_CONFIG", str(tmp_path / "settings.json"))
    monkeypatch.setenv("SERP3D_NO_RECOVER", "1")
    opened = []

    def open_window():
        from serpentine3d.app import MainWindow

        window = MainWindow()
        opened.append(window)
        # Real show/hide events keep Qt's visibility and check marks honest.
        # Painting the GL panes is unnecessary for this menu interaction.
        window.setUpdatesEnabled(False)
        window.show()
        _qapp.processEvents()
        return window

    yield open_window
    for window in opened:
        window.close()


def _toolbar(window):
    bars = window.findChildren(QToolBar, "toolPalette")
    assert len(bars) == 1, "the tool strip must stay a single toolbar"
    return bars[0]


def _view_action(window):
    view = next((a.menu() for a in window.menuBar().actions()
                 if a.text().replace("&", "") == "View"), None)
    assert view is not None
    matches = [a for a in view.actions()
               if a.text().replace("&", "") == "Tools Toolbar"]
    assert len(matches) == 1, (
        "View needs an obvious Tools Toolbar action to bring back the strip")
    action = matches[0]
    assert action.isCheckable(), "the menu should show whether the strip is up"
    assert action.isEnabled()
    return action


def _buttons(toolbar):
    palette = toolbar.findChild(ToolPalette)
    assert palette is not None
    buttons = palette.findChildren(QToolButton)
    assert len(buttons) > 24, "the strip must still carry all its tools"
    assert {"Line", "Fillet", "Delete"} <= {b.text() for b in buttons}
    return buttons


def test_view_can_hide_and_restore_the_existing_tools_toolbar(windows):
    window = windows()
    toolbar = _toolbar(window)
    buttons = _buttons(toolbar)
    action = _view_action(window)
    assert toolbar.isVisible() and action.isChecked()

    for _ in range(2):
        action.trigger()
        assert not toolbar.isVisible()
        assert not action.isChecked()
        action.trigger()
        assert toolbar.isVisible()
        assert action.isChecked()
        assert _toolbar(window) is toolbar
        assert _buttons(toolbar) == buttons


@pytest.mark.parametrize("hide", ["hide", "close"])
def test_the_view_check_mark_tracks_the_toolbar_hidden_elsewhere(windows, hide):
    window = windows()
    toolbar = _toolbar(window)
    action = _view_action(window)

    getattr(toolbar, hide)()
    assert not toolbar.isVisible()
    assert not action.isChecked(), "a hidden strip must not stay checked in View"
    action.trigger()
    assert toolbar.isVisible(), "View should reopen the strip hidden elsewhere"
    assert action.isChecked()

    toolbar.hide()
    toolbar.show()
    assert toolbar.isVisible()
    assert action.isChecked(), "a strip shown elsewhere must become checked"


def test_view_can_restore_a_tools_toolbar_saved_hidden(windows, tmp_path):
    window = windows()
    _toolbar(window).close()
    window.close()
    stored = json.loads((tmp_path / "settings.json").read_text())
    assert stored["window"]["state"], "the hidden toolbar layout must be saved"

    reopened = windows()
    toolbar = _toolbar(reopened)
    buttons = _buttons(toolbar)
    assert not toolbar.isVisible(), "the saved layout should start with it hidden"
    action = _view_action(reopened)
    assert not action.isChecked()

    action.trigger()
    assert toolbar.isVisible()
    assert action.isChecked()
    assert _toolbar(reopened) is toolbar
    assert _buttons(toolbar) == buttons
