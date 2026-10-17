"""Interface scale and font (GitHub #74), Settings → Display.

The whole-UI scale is Qt's own QT_SCALE_FACTOR, which Qt reads only as
the QApplication is built — so the launcher plants it in the environment
before Qt exists, and a new scale needs a restart. The page previews it
live, says it is waiting on a restart, and asks once on Close; the
restart itself asks nothing, because the document comes back as it is.
The interface font is a plain application font: applied live by the
dialog, and read from the saved settings at startup.
"""

import json
import os
import sys

import pytest
from PySide6.QtGui import QColor, QFontDatabase
from PySide6.QtWidgets import QApplication, QWidget

from serpentine3d import app as app_mod
from serpentine3d import launcher
from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui import settings_dialog as sd_mod
from serpentine3d.ui import theme
from serpentine3d.ui import viewport as vp_mod
from serpentine3d.ui.settings_dialog import SettingsDialog
from serpentine3d.utils.autosave import AutosaveManager
from serpentine3d.utils.config import Config

FAMILY = "DejaVu Sans"          # on every Linux CI box this runs on


@pytest.fixture(autouse=True)
def _scale_env():
    """Put QT_SCALE_FACTOR back after each test. _apply_ui_scale writes
    os.environ itself, and monkeypatch.delenv on an unset variable keeps
    nothing to restore: a leaked 1.25 makes every later Settings page
    think a new scale waits, and ask about it on close."""
    before = os.environ.get("QT_SCALE_FACTOR")
    yield
    if before is None:
        os.environ.pop("QT_SCALE_FACTOR", None)
    else:
        os.environ["QT_SCALE_FACTOR"] = before


class _Window(QWidget):
    """Just enough window for the dialog to build its pages against."""

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        scene = Scene()
        self.viewport = vp_mod.Viewport(scene, SelectionManager(scene),
                                        config=cfg)
        self.osnap_bar = type("_Bar", (), {"refresh": lambda self: None})()
        self.echoes = []
        self.command_line = self

    def echo(self, message):
        self.echoes.append(message)

    def apply_user_shortcuts(self):
        pass

    def apply_user_aliases(self):
        pass


@pytest.fixture
def dlg(tmp_path, monkeypatch):
    monkeypatch.delenv("QT_SCALE_FACTOR", raising=False)   # running at 100%
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


def test_the_running_scale_is_what_the_launcher_planted(monkeypatch):
    # not the saved setting: that may already wait on a restart
    monkeypatch.delenv("QT_SCALE_FACTOR", raising=False)
    assert launcher.running_scale() == 1.0
    monkeypatch.setenv("QT_SCALE_FACTOR", "1.25")
    assert launcher.running_scale() == 1.25
    monkeypatch.setenv("QT_SCALE_FACTOR", "huge")
    assert launcher.running_scale() == 1.0


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


# ------------------------------------------------- a scale waiting on restart

class _Box:
    """A QMessageBox stand-in that answers with the named button."""

    chosen = None                  # set per test
    instance = None

    class Icon:
        Question = object()

    class ButtonRole:
        AcceptRole = object()
        RejectRole = object()

    def __init__(self, parent=None):
        _Box.instance = self
        self.text = ""
        self.buttons = []          # (label, button-object)

    def setWindowTitle(self, _): pass
    def setIcon(self, _): pass
    def setInformativeText(self, _): pass
    def setDefaultButton(self, _): pass
    def setEscapeButton(self, _): pass
    def exec(self): pass

    def setText(self, text):
        self.text = text

    def addButton(self, label, role):
        button = object()
        self.buttons.append((label, button))
        return button

    def clickedButton(self):
        return next((b for label, b in self.buttons
                     if label == _Box.chosen), None)


@pytest.fixture
def asked(monkeypatch):
    """The Close question answered by _Box, and restarts recorded."""
    _Box.chosen, _Box.instance = None, None
    restarts = []
    monkeypatch.setattr(sd_mod, "QMessageBox", _Box)
    monkeypatch.setattr(app_mod, "restart_app", restarts.append)
    return restarts


def _waiting(d):
    return not d.lbl_scale_pending.isHidden()


def test_a_scale_change_says_it_waits_on_a_restart(dlg):
    d, cfg = dlg
    assert not _waiting(d) and d.btn_restart_now.isHidden()
    assert d.footer_note.text() == "Changes apply immediately"
    d.sl_scale.setValue(125)
    assert _waiting(d) and d.lbl_scale_pending.text() == "after restart"
    assert not d.btn_restart_now.isHidden()
    assert d.footer_note.text() == \
        "Interface scale changes when Serpentine3D restarts"
    d.sl_scale.setValue(100)                  # back to what is running
    assert not _waiting(d) and d.btn_restart_now.isHidden()
    assert d.footer_note.text() == "Changes apply immediately"


def test_a_scale_left_for_later_still_waits_next_time(tmp_path, monkeypatch):
    # saved last time the page was open, never restarted into
    monkeypatch.delenv("QT_SCALE_FACTOR", raising=False)
    cfg = Config(path=str(tmp_path / "settings.json"))
    cfg.set("display", "ui_scale", 1.25)
    assert _waiting(SettingsDialog(_Window(cfg)))


def test_the_scale_already_running_does_not_wait(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_SCALE_FACTOR", "1.25")
    cfg = Config(path=str(tmp_path / "settings.json"))
    cfg.set("display", "ui_scale", 1.25)
    d = SettingsDialog(_Window(cfg))
    assert not _waiting(d)
    d.sl_scale.setValue(100)                  # going back down waits too
    assert _waiting(d)


def test_a_hand_edited_scale_opens_the_page_at_100(tmp_path, monkeypatch):
    monkeypatch.delenv("QT_SCALE_FACTOR", raising=False)
    cfg = Config(path=str(tmp_path / "settings.json"))
    cfg.set("display", "ui_scale", "big")
    d = SettingsDialog(_Window(cfg))
    assert d.sl_scale.value() == 100 and not _waiting(d)


def test_close_with_a_scale_waiting_asks_once(dlg, asked):
    d, cfg = dlg
    d.sl_scale.setValue(150)
    _Box.chosen = "Restart now"
    d.accept()                                # the Close button
    assert _Box.instance.text == "Restart now to switch to 150%?"
    assert [label for label, _ in _Box.instance.buttons] == \
        ["Restart now", "Later"]
    assert asked == [d.window]


def test_later_keeps_the_scale_for_next_time_and_says_so(dlg, asked):
    d, cfg = dlg
    d.sl_scale.setValue(150)
    _Box.chosen = "Later"
    d.accept()
    assert asked == [] and cfg.get("display", "ui_scale") == 1.5
    assert d.result() == d.DialogCode.Accepted
    assert d.window.echoes == [
        "Interface scale 150% applies the next time Serpentine3D starts."]


def test_escape_and_the_title_bar_close_ask_too(dlg, asked):
    d, cfg = dlg
    d.sl_scale.setValue(125)
    _Box.chosen = "Later"
    d.reject()                                # Esc, or the window's X
    assert _Box.instance is not None


def test_close_with_nothing_waiting_asks_nothing(dlg, asked):
    d, cfg = dlg
    d.sl_scale.setValue(125)
    d.sl_scale.setValue(100)
    d.accept()
    assert _Box.instance is None and asked == []


def test_restart_now_in_the_footer_restarts_without_asking(dlg, asked):
    d, cfg = dlg
    d.sl_scale.setValue(125)
    d.btn_restart_now.click()
    assert _Box.instance is None and asked == [d.window]


# ---------------------------------------------------------------- the preview

def _red_corner_dialog(tmp_path):
    """A window whose top-left 20 px are red, so the preview's growth can
    be measured in its pixels."""
    cfg = Config(path=str(tmp_path / "settings.json"))
    window = _Window(cfg)
    window.resize(600, 400)
    corner = QWidget(window)
    corner.setGeometry(0, 0, 20, 20)
    palette = corner.palette()
    palette.setColor(corner.backgroundRole(), QColor("#ff0000"))
    corner.setPalette(palette)
    corner.setAutoFillBackground(True)
    return SettingsDialog(window)


def _red(preview, x, y):
    """Red at logical (x, y), allowing for the blur at an edge."""
    image = preview.pixmap().toImage()
    dpr = image.devicePixelRatio()
    c = image.pixelColor(round(x * dpr), round(y * dpr))
    return c.red() > 200 and c.green() < 80 and c.blue() < 80


def test_the_preview_shows_the_interface_at_the_chosen_size(
        tmp_path, monkeypatch):
    monkeypatch.delenv("QT_SCALE_FACTOR", raising=False)
    d = _red_corner_dialog(tmp_path)
    preview = d.scale_preview
    assert _red(preview, 10, 10) and not _red(preview, 25, 10)  # as it is
    d.sl_scale.setValue(150)
    assert _red(preview, 25, 10) and not _red(preview, 35, 10)  # 20 → 30 px
    d.sl_scale.setValue(100)
    assert not _red(preview, 25, 10)


def test_the_preview_starts_from_the_running_scale(tmp_path, monkeypatch):
    # running at 125%: picking 150% grows it by 150/125, not by 150/100
    monkeypatch.setenv("QT_SCALE_FACTOR", "1.25")
    d = _red_corner_dialog(tmp_path)
    d.sl_scale.setValue(150)
    assert _red(d.scale_preview, 23, 10)            # 20 * 1.2 = 24
    assert not _red(d.scale_preview, 26, 10)


# -------------------------------------------------------------- the restart


class _FakeWindow(QWidget):
    """Just enough window for restart_app to restart."""

    def __init__(self, scene, dirty, path, autosave_dir):
        super().__init__()
        self.scene = scene
        self._dirty = dirty
        self.ctx = type("_Ctx", (), {"current_path": path})()
        self.autosave = AutosaveManager(scene, autosave_dir)
        self.echoes = []
        self.closed = False
        self._restarting = False
        self.command_line = self

    @property
    def dirty(self):
        return self._dirty

    def echo(self, message):
        self.echoes.append(message)

    def close(self):
        self.closed = True


class _Proc:
    started = []
    works = True

    @staticmethod
    def startDetached(program, arguments):
        _Proc.started.append((program, arguments))
        return _Proc.works


class _NoQuestions:
    def __init__(self, *_):
        raise AssertionError("a restart asks nothing")


@pytest.fixture
def restart(tmp_path, monkeypatch):
    _Proc.started, _Proc.works = [], True
    monkeypatch.setattr(app_mod, "QProcess", _Proc)
    monkeypatch.setattr(app_mod, "QMessageBox", _NoQuestions)
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delenv("APPIMAGE", raising=False)

    def window(dirty, path, scene=None):
        if scene is None:
            scene = Scene()
            scene.add(g.make_box((0, 0, 0), 1, 1, 1))
        return _FakeWindow(scene, dirty, path, str(tmp_path / "autosave"))
    return window


def _note(win):
    with open(win.autosave.handoff_path + ".json", encoding="utf-8") as f:
        return json.load(f)


def test_unsaved_work_is_handed_over_without_asking(restart):
    win = restart(dirty=True, path="/tmp/doc.serp")
    app_mod.restart_app(win)
    assert win.closed and win._restarting
    handoff = win.autosave.handoff_path
    assert os.path.exists(handoff)            # the work landed
    assert _note(win) == {"doc_path": "/tmp/doc.serp"}
    (program, args), = _Proc.started
    assert program == sys.executable
    assert args == ["-m", "serpentine3d", handoff]


def test_a_clean_doc_restarts_straight_from_disk(restart):
    win = restart(dirty=False, path="/tmp/doc.serp")
    app_mod.restart_app(win)
    assert win.closed and not os.path.exists(win.autosave.handoff_path)
    (program, args), = _Proc.started
    assert args == ["-m", "serpentine3d", "/tmp/doc.serp"]


def test_an_untitled_doc_hands_over_with_no_name(restart):
    win = restart(dirty=True, path=None)
    app_mod.restart_app(win)
    assert _note(win) == {"doc_path": None}
    (program, args), = _Proc.started
    assert args == ["-m", "serpentine3d", win.autosave.handoff_path]


def test_an_emptied_doc_hands_over_rather_than_reopening_its_file(restart):
    # everything deleted, unsaved: reopening from disk would undo that
    win = restart(dirty=True, path="/tmp/doc.serp", scene=Scene())
    app_mod.restart_app(win)
    (program, args), = _Proc.started
    assert args[-1] == win.autosave.handoff_path


def test_a_restart_that_cannot_start_keeps_this_session(restart):
    _Proc.works = False
    win = restart(dirty=True, path="/tmp/doc.serp")
    app_mod.restart_app(win)
    assert not win.closed and not win._restarting
    assert not os.path.exists(win.autosave.handoff_path)
    assert win.echoes == ["Could not start Serpentine3D again, "
                          "so it was not restarted."]


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


def test_the_handoff_is_kept_apart_from_crash_recovery(tmp_path):
    scene = Scene()
    scene.add(g.make_box((0, 0, 0), 1, 1, 1))
    manager = AutosaveManager(scene, str(tmp_path))
    manager.hand_over("/tmp/doc.serp")
    manager.clean_exit()                       # this session ends cleanly
    taker = AutosaveManager(Scene(), str(tmp_path))
    assert taker.find_recoverable() == []      # not a crashed session
    entry = taker.waiting_handoff()
    assert entry["doc_path"] == "/tmp/doc.serp"
    assert entry["path"] == manager.handoff_path
    taker.discard_handoff()
    assert taker.waiting_handoff() is None
    assert not os.path.exists(manager.handoff_path + ".json")
