"""Interface scale and font (GitHub #74), Settings → Display.

The whole-UI scale is Qt's own QT_SCALE_FACTOR, which Qt reads only as
the QApplication is built — so the launcher plants it in the environment
before Qt exists, and the page says the next launch. The interface font
is a plain application font: applied live by the dialog, and read from
the saved settings at startup.
"""

import os
import sys

import pytest
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication, QWidget

from serpentine3d import app as app_mod
from serpentine3d import launcher
from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui import theme
from serpentine3d.ui import viewport as vp_mod
from serpentine3d.ui.settings_dialog import SettingsDialog
from serpentine3d.utils import autosave as autosave_mod
from serpentine3d.utils.config import Config

FAMILY = "DejaVu Sans"          # on every Linux CI box this runs on


class _Window(QWidget):
    """Just enough window for the dialog to build its pages against."""

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        scene = Scene()
        self.viewport = vp_mod.Viewport(scene, SelectionManager(scene),
                                        config=cfg)
        self.osnap_bar = type("_Bar", (), {"refresh": lambda self: None})()

    def apply_user_shortcuts(self):
        pass

    def apply_user_aliases(self):
        pass


@pytest.fixture
def dlg(tmp_path):
    cfg = Config(path=str(tmp_path / "settings.json"))
    return SettingsDialog(_Window(cfg)), cfg


def has_family(name):
    return QFontDatabase.hasFamily(name)


# ------------------------------------------------------------- the launcher

def test_the_launcher_plants_the_saved_scale(monkeypatch, tmp_path):
    cfg = Config(path=str(tmp_path / "settings.json"))
    cfg.set("display", "ui_scale", 1.25)
    monkeypatch.setenv("SERP3D_CONFIG", cfg.path)
    monkeypatch.delenv("QT_SCALE_FACTOR", raising=False)
    launcher._apply_ui_scale()
    assert os.environ["QT_SCALE_FACTOR"] == "1.25"


def test_the_default_scale_leaves_the_environment_alone(monkeypatch, tmp_path):
    cfg = Config(path=str(tmp_path / "settings.json"))
    monkeypatch.setenv("SERP3D_CONFIG", cfg.path)
    monkeypatch.delenv("QT_SCALE_FACTOR", raising=False)
    launcher._apply_ui_scale()
    assert "QT_SCALE_FACTOR" not in os.environ


def test_a_hand_edited_scale_is_ignored(monkeypatch, tmp_path):
    cfg = Config(path=str(tmp_path / "settings.json"))
    cfg.set("display", "ui_scale", "big")
    monkeypatch.setenv("SERP3D_CONFIG", cfg.path)
    monkeypatch.delenv("QT_SCALE_FACTOR", raising=False)
    launcher._apply_ui_scale()
    assert "QT_SCALE_FACTOR" not in os.environ


# --------------------------------------------------------------- the dialog

def test_the_scale_slider_persists(dlg):
    d, cfg = dlg
    d.sl_scale.setValue(125)
    assert cfg.get("display", "ui_scale") == 1.25
    assert d.lbl_scale.text() == "125%"


def test_the_font_picker_saves_and_applies_live(dlg):
    if not has_family(FAMILY):
        pytest.skip(f"{FAMILY} not installed")
    d, cfg = dlg
    assert d.cb_font.itemText(0) == "System default"
    d.cb_font.setCurrentIndex(d.cb_font.findText(FAMILY))
    assert cfg.get("display", "interface_font") == FAMILY
    assert QApplication.instance().font().family() == FAMILY
    d.cb_font.setCurrentIndex(0)          # back to the system default
    assert cfg.get("display", "interface_font") == ""


def test_a_saved_font_comes_back_selected(tmp_path):
    if not has_family(FAMILY):
        pytest.skip(f"{FAMILY} not installed")
    cfg = Config(path=str(tmp_path / "settings.json"))
    cfg.set("display", "interface_font", FAMILY)
    d = SettingsDialog(_Window(cfg))
    assert d.cb_font.currentText() == FAMILY


def test_a_saved_scale_comes_back_on_the_slider(tmp_path):
    cfg = Config(path=str(tmp_path / "settings.json"))
    cfg.set("display", "ui_scale", 1.25)
    d = SettingsDialog(_Window(cfg))
    assert d.sl_scale.value() == 125
    assert d.lbl_scale.text() == "125%"


# ------------------------------------------------------------------- theme

def test_the_startup_apply_reads_the_saved_font(monkeypatch, tmp_path):
    if not has_family(FAMILY):
        pytest.skip(f"{FAMILY} not installed")
    cfg = Config(path=str(tmp_path / "settings.json"))
    cfg.set("display", "interface_font", FAMILY)
    monkeypatch.setenv("SERP3D_CONFIG", cfg.path)
    app = QApplication.instance()
    before = app.font()
    try:
        theme.apply_saved_interface_font(app)
        assert app.font().family() == FAMILY
    finally:
        app.setFont(before)


def test_no_saved_font_leaves_the_platform_default(monkeypatch, tmp_path):
    cfg = Config(path=str(tmp_path / "settings.json"))
    monkeypatch.setenv("SERP3D_CONFIG", cfg.path)
    app = QApplication.instance()
    before = app.font()
    try:
        theme.apply_saved_interface_font(app)
        assert app.font() == before
    finally:
        app.setFont(before)


# -------------------------------------------------------------- the restart


class _FakeWindow(QWidget):
    """Just enough window for restart_app to plan a restart against."""

    def __init__(self, scene, dirty, path):
        super().__init__()
        self.scene = scene
        self._dirty = dirty
        self.ctx = type("_Ctx", (), {"current_path": path})()
        self.echoes = []
        self.saved = False
        self.closed = False
        self._restarting = False
        self._pick_cancel = False
        self.command_line = self

    @property
    def dirty(self):
        return self._dirty

    def _file_save(self):
        if self._pick_cancel:      # the Save dialog was cancelled
            return
        self.saved = True
        self._dirty = False

    def echo(self, message):
        self.echoes.append(message)

    def close(self):
        self.closed = True


class _Box:
    """A QMessageBox stand-in that answers with the named button."""

    chosen = None                  # set per test
    instance = None

    class Icon:
        Question = object()

    class ButtonRole:
        AcceptRole = object()
        RejectRole = object()
        DestructiveRole = object()

    def __init__(self, parent=None):
        _Box.instance = self
        self.buttons = []          # (label, role, button-object)

    def setWindowTitle(self, _): pass
    def setIcon(self, _): pass
    def setText(self, _): pass
    def setInformativeText(self, _): pass
    def setDefaultButton(self, _): pass
    def exec(self): pass

    def addButton(self, label, role):
        button = object()
        self.buttons.append((label, role, button))
        return button

    def clickedButton(self):
        for label, role, button in self.buttons:
            if label == _Box.chosen:
                return button
        return None


class _Proc:
    started = []

    @staticmethod
    def startDetached(program, arguments):
        _Proc.started.append((program, arguments))
        return True


@pytest.fixture
def restart(tmp_path, monkeypatch):
    _Box.chosen = None
    _Proc.started = []
    monkeypatch.setattr(app_mod, "QMessageBox", _Box)
    monkeypatch.setattr(app_mod, "QProcess", _Proc)
    handoff = str(tmp_path / "handoff.serp")
    monkeypatch.setattr(autosave_mod, "HANDOFF_PATH", handoff)
    return handoff


def _scene_with_content():
    scene = Scene()
    scene.add(g.make_box((0, 0, 0), 1, 1, 1))
    return scene


def _box_labels():
    return [label for label, role, button in _Box.instance.buttons]


def test_restart_offers_save_first_for_a_dirty_saved_doc(restart):
    win = _FakeWindow(_scene_with_content(), dirty=True, path="/tmp/doc.serp")
    _Box.chosen = "Cancel"
    app_mod.restart_app(win)
    assert _box_labels() == ["Save and Restart", "Restart without Saving",
                             "Cancel"]
    assert not win.closed and _Proc.started == []
    assert not os.path.exists(restart)


def test_restart_without_saving_hands_the_work_over(restart):
    win = _FakeWindow(_scene_with_content(), dirty=True, path="/tmp/doc.serp")
    _Box.chosen = "Restart without Saving"
    app_mod.restart_app(win)
    assert win.closed and win._restarting
    assert os.path.exists(restart)          # the handoff copy landed
    (program, args), = _Proc.started
    assert program == sys.executable
    assert args[:2] == ["-m", "serpentine3d"]
    assert args[2] == restart
    assert args[3:5] == ["--restart-origin", "/tmp/doc.serp"]


def test_save_and_restart_saves_then_relaunches_clean(restart):
    win = _FakeWindow(_scene_with_content(), dirty=True, path="/tmp/doc.serp")
    _Box.chosen = "Save and Restart"
    app_mod.restart_app(win)
    assert win.saved and win.closed and win._restarting
    assert not os.path.exists(restart)      # no handoff needed
    (program, args), = _Proc.started
    assert args == ["-m", "serpentine3d", "/tmp/doc.serp"]


def test_a_cancelled_save_dialog_stops_the_restart(restart):
    win = _FakeWindow(_scene_with_content(), dirty=True, path=None)
    win._pick_cancel = True
    _Box.chosen = "Save As… and Restart"
    app_mod.restart_app(win)
    assert _box_labels() == ["Save As… and Restart", "Restart without Saving",
                             "Cancel"]
    assert not win.closed and _Proc.started == []
    assert not os.path.exists(restart)


def test_a_clean_doc_restarts_straight_from_disk(restart):
    win = _FakeWindow(_scene_with_content(), dirty=False, path="/tmp/doc.serp")
    _Box.chosen = "Restart"
    app_mod.restart_app(win)
    assert _box_labels() == ["Restart", "Cancel"]   # no save to offer
    assert win.closed and win._restarting
    (program, args), = _Proc.started
    assert args == ["-m", "serpentine3d", "/tmp/doc.serp"]


def test_an_untitled_dirty_doc_hands_over_with_no_origin(restart):
    win = _FakeWindow(_scene_with_content(), dirty=True, path=None)
    _Box.chosen = "Restart without Saving"
    app_mod.restart_app(win)
    (program, args), = _Proc.started
    assert args == ["-m", "serpentine3d", restart, "--restart-origin", ""]


def test_restart_command_knows_where_it_runs_from(monkeypatch):
    monkeypatch.delenv("APPIMAGE", raising=False)
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert app_mod._restart_command() == [sys.executable,
                                          "-m", "serpentine3d"]
    monkeypatch.setenv("APPIMAGE", "/tmp/Serpentine3D.AppImage")
    assert app_mod._restart_command() == ["/tmp/Serpentine3D.AppImage"]
    monkeypatch.delenv("APPIMAGE", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert app_mod._restart_command() == [sys.executable]


def test_the_restart_origin_flag_parses():
    assert app_mod._restart_origin(
        ["--restart-origin", "a.serp"]) == "a.serp"
    assert app_mod._restart_origin(["--restart-origin", ""]) == ""
    assert app_mod._restart_origin([]) is None
    assert app_mod._restart_origin(["--restart-origin"]) is None


def test_the_restart_button_enables_only_after_a_scale_change(dlg):
    d, cfg = dlg
    assert not d.btn_restart.isEnabled()      # nothing to apply yet
    d.sl_scale.setValue(125)
    assert d.btn_restart.isEnabled()
    d.sl_scale.setValue(100)                  # back to the launch scale
    assert not d.btn_restart.isEnabled()
