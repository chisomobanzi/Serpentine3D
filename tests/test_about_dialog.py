"""The About box, which used to be three sentences and no version number.

An About box is read for one of two reasons: somebody wants to know what
this program is, or somebody is filing a bug and needs to say which build
they are on and what it is standing on. The old one answered the first
question and not the second — it did not name its own version, so the one
fact every bug report needs was the one fact it withheld.
"""

from __future__ import annotations

import json
import sys

import pytest
from PySide6.QtWidgets import QApplication, QWidget

from serpentine3d import __version__
from serpentine3d.ui.about import AboutDialog


@pytest.fixture
def parent():
    w = QWidget()
    yield w
    w.close()


@pytest.fixture
def dlg(parent):
    d = AboutDialog(parent)
    yield d
    d.close()


def test_it_says_which_version_you_are_running(dlg):
    """The whole reason anybody opens an About box twice."""
    from PySide6.QtWidgets import QLabel
    assert __version__ in dlg.summary_text()
    shown = [lb.text() for lb in dlg.findChildren(QLabel)
             if not lb.isHidden()]
    assert any(__version__ in t for t in shown), (
        f"no visible label carries {__version__}: {shown}")


def test_it_says_what_the_program_is_standing_on(dlg):
    """The half a bug report you cannot get from the reporter."""
    text = dlg.details_text()
    for label in ("Serpentine3D", "Python", "Qt", "OpenCASCADE", "Platform"):
        assert label in text, f"{label} missing from:\n{text}"
    assert __version__ in text
    assert f"{sys.version_info.major}.{sys.version_info.minor}" in text


def test_the_details_can_be_taken_in_one_click(dlg):
    """Nobody retypes a version table into an issue."""
    QApplication.clipboard().setText("")
    dlg.copy_details()
    assert QApplication.clipboard().text() == dlg.details_text()


def test_the_copy_button_says_it_took_and_then_goes_back(dlg):
    """A control left reading 'Copied' stops looking pressable."""
    dlg.copy_details()
    assert dlg._copy_btn.text() == "Copied"
    dlg._reset_copy_label()
    assert dlg._copy_btn.text() == "Copy details"


def test_the_links_are_the_ones_the_rest_of_the_project_uses(dlg):
    from serpentine3d.ui import welcome
    urls = dlg.link_urls()
    assert welcome._GITHUB in urls
    assert welcome._DOCS in urls
    assert any("ko-fi.com/chisomobanzi" in u for u in urls)


def test_it_still_says_where_the_name_comes_from(dlg):
    """The one thing the old box had that nothing else in the app says."""
    assert "Shona" in dlg.summary_text()


def test_it_names_its_licence(dlg):
    assert "MIT" in dlg.summary_text() or "MIT" in dlg.details_text()


def test_it_is_a_window_you_can_move_on_linux(dlg, monkeypatch):
    """Same rule as every other dialog: GNOME glues a DIALOG-type window to
    its parent, so on Linux it has to ask to be a NORMAL one."""
    from PySide6.QtCore import Qt
    flags = dlg.windowFlags()
    if sys.platform.startswith("linux"):
        assert flags & Qt.WindowType.Window


def test_the_help_menu_opens_this_one(tmp_path, monkeypatch):
    """Not the stock QMessageBox it used to raise."""
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({}))
    monkeypatch.setenv("SERP3D_CONFIG", str(cfg))
    monkeypatch.setenv("SERP3D_AUTOSAVE_DIR", str(tmp_path / "autosave"))
    from serpentine3d.app import MainWindow
    w = MainWindow()
    opened = []
    monkeypatch.setattr(AboutDialog, "exec", lambda self: opened.append(self))
    w._about()
    assert len(opened) == 1
    assert isinstance(opened[0], AboutDialog)
    w._saved_revision = w.scene.revision
    w.close()
