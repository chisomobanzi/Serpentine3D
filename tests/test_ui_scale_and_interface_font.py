"""Interface scale and font (GitHub #74), Settings → Display.

The whole-UI scale is Qt's own QT_SCALE_FACTOR, which Qt reads only as
the QApplication is built — so the launcher plants it in the environment
before Qt exists, and the page says the next launch. The interface font
is a plain application font: applied live by the dialog, and read from
the saved settings at startup.
"""

import os

import pytest
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication, QWidget

from serpentine3d import launcher
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui import theme
from serpentine3d.ui import viewport as vp_mod
from serpentine3d.ui.settings_dialog import SettingsDialog
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
