"""Check for updates on startup works on Windows once it is ticked.

Ticking the installer's task did nothing when an earlier install had cleared
it, the app had no switch of its own to turn it back on, and a release found
on launch was announced in a timed status message that the next status
refresh wiped before anyone read it.
"""
from pathlib import Path

import pytest
from PySide6.QtWidgets import QMainWindow, QPushButton, QWidget

from serpentine3d.app import MainWindow
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui import viewport as vp_mod
from serpentine3d.ui.settings_dialog import SettingsDialog
from serpentine3d.utils.config import Config

ISS = (Path(__file__).resolve().parent.parent
       / "packaging" / "windows" / "installer.iss")


class _Window(QWidget):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        scene = Scene()
        self.viewport = vp_mod.Viewport(scene, SelectionManager(scene),
                                        config=cfg)
        self.osnap_bar = type("_Bar", (), {"refresh": lambda self: None})()
        self.manual_checks = 0

    def apply_user_shortcuts(self):
        pass

    def apply_user_aliases(self):
        pass

    def _check_updates_manual(self):
        self.manual_checks += 1


@pytest.fixture
def dlg(tmp_path):
    cfg = Config(path=str(tmp_path / "settings.json"))
    win = _Window(cfg)
    return SettingsDialog(win), cfg, win


def test_settings_show_the_switch_as_stored(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"check_updates": false}')
    cfg = Config(path=str(path))
    d = SettingsDialog(_Window(cfg))
    assert d.cb_check_updates.isChecked() is False


def test_ticking_the_switch_turns_the_check_back_on(dlg, tmp_path):
    d, cfg, _ = dlg
    d.cb_check_updates.setChecked(False)
    assert Config(path=cfg.path).get("check_updates") is False
    d.cb_check_updates.setChecked(True)
    assert Config(path=cfg.path).get("check_updates") is True


def test_check_now_runs_the_manual_check(dlg):
    d, _, win = dlg
    btn = next(b for b in d.findChildren(QPushButton)
               if b.text() == "Check Now")
    btn.click()
    assert win.manual_checks == 1


class _Main(QMainWindow):
    _on_update_available = MainWindow._on_update_available

    def __init__(self):
        super().__init__()
        self.manual_checks = 0

    def _check_updates_manual(self):
        self.manual_checks += 1


def test_a_found_release_stays_in_the_status_bar():
    win = _Main()
    win._on_update_available({"version": "9.9.9", "url": "", "download": ""})
    win.statusBar().showMessage("3 object(s)  ·  0 selected")
    btn = win._update_button
    assert "9.9.9" in btn.text()
    assert not btn.isHidden()
    btn.click()
    assert win.manual_checks == 1
    win._on_update_available({"version": "9.9.10", "url": "", "download": ""})
    assert len(win.statusBar().findChildren(QPushButton)) == 1
    assert "9.9.10" in win._update_button.text()


def test_installer_applies_a_ticked_task_to_an_existing_file():
    iss = ISS.read_text()
    assert "'\"check_updates\": true'" in iss
    assert "'\"check_updates\": false'" in iss
    assert "SaveStringToFile(CfgPath, Json" in iss
