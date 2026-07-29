"""No dialog is glued to the main window.

Under GNOME's attach-modal-dialogs a DIALOG-type window is fixed to its
parent: it cannot be moved on its own, and dragging it drags the whole
application window along behind it. Four places have run into this and each
dodged it privately — the file picker, the open-progress dialog, the STL
quality prompt, the welcome screen — while Settings, opened the same way,
never did.

So the rule is stated here once, for every dialog the app puts on screen,
rather than remembered four more times.
"""

import sys

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui import viewport as vp_mod
from serpentine3d.ui.dialogs import untether
from serpentine3d.ui.help_browser import HelpBrowser
from serpentine3d.ui.palette import CommandPalette
from serpentine3d.ui.settings_dialog import SettingsDialog
from serpentine3d.ui.welcome import WelcomeScreen
from serpentine3d.utils.config import Config

linux_only = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="attach-modal-dialogs is a GNOME/Linux behaviour")


class _Window(QWidget):
    """Just enough window to be a dialog's parent."""

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        scene = Scene()
        self.viewport = vp_mod.Viewport(scene, SelectionManager(scene),
                                        config=cfg)
        self.osnap_bar = type("_Bar", (), {"refresh": lambda self: None})()
        self.recent_files = list

    def apply_user_shortcuts(self):
        pass

    def apply_user_aliases(self):
        pass


@pytest.fixture
def win(tmp_path):
    return _Window(Config(path=str(tmp_path / "settings.json")))


@linux_only
@pytest.mark.parametrize("build", [
    pytest.param(lambda w: SettingsDialog(w), id="settings"),
    pytest.param(lambda w: WelcomeScreen(w), id="welcome"),
    pytest.param(lambda w: HelpBrowser(w), id="help"),
    pytest.param(lambda w: CommandPalette(w, lambda _: None), id="palette"),
])
def test_no_dialog_is_tethered_to_the_window_that_opened_it(build, win):
    dlg = build(win)
    assert dlg.windowType() != Qt.WindowType.Dialog, (
        "DIALOG-type: GNOME will glue it to the main window, so it cannot be "
        "moved on its own and dragging it drags the application with it")


@linux_only
def test_settings_opens_as_a_window_of_its_own(win):
    assert SettingsDialog(win).windowType() == Qt.WindowType.Window


def test_untether_puts_the_dialog_over_the_window_it_belongs_to(win):
    """Losing the tether loses the free placement that came with it — an
    untethered window lands wherever the manager felt like putting it."""
    win.setGeometry(200, 150, 900, 700)
    dlg = QWidget(win)
    dlg.resize(400, 300)
    untether(dlg, over=win)

    assert abs(dlg.frameGeometry().center().x()
               - win.frameGeometry().center().x()) <= 1
    assert abs(dlg.frameGeometry().center().y()
               - win.frameGeometry().center().y()) <= 1


def test_untether_leaves_other_platforms_alone(win, monkeypatch):
    """Only GNOME attaches dialogs. Elsewhere a DIALOG-type window is the
    right thing to be, and taking it away would cost the dialog its
    stay-above-the-parent behaviour for nothing."""
    monkeypatch.setattr(sys, "platform", "darwin")
    dlg = QWidget(win, Qt.WindowType.Dialog)
    untether(dlg)

    assert dlg.windowType() == Qt.WindowType.Dialog
