"""The list of recent files on the welcome screen.

A long name pushed a horizontal scrollbar into the bottom of the card: an
unstyled one, in a dialog with a fixed width, asking you to scroll sideways
to read a filename. The width is never going to change, so the name is what
has to give — and it gives in the middle, where a file's own name is, rather
than at the end, where its kind is.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QListWidget, QWidget

from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui import viewport as vp_mod
from serpentine3d.ui.welcome import WelcomeScreen
from serpentine3d.utils.config import Config

LONG = "HGS2_3DM_124_SAM_CAVE_INTERIOR_AND_EXTERIOR_SURVEY_001_final.3dm"


class _Window(QWidget):
    """Just enough window for the welcome screen to read."""

    def __init__(self, cfg, files):
        super().__init__()
        self.cfg = cfg
        self._files = files
        scene = Scene()
        self.viewport = vp_mod.Viewport(scene, SelectionManager(scene),
                                        config=cfg)

    def recent_files(self):
        return list(self._files)


@pytest.fixture
def listing(tmp_path):
    paths = []
    for name in (LONG, "stool.serp"):
        p = tmp_path / name
        p.write_text("")
        paths.append(str(p))
    cfg = Config(path=str(tmp_path / "settings.json"))
    dlg = WelcomeScreen(_Window(cfg, paths))
    dlg.show()                      # the card has its real width only laid out
    QApplication.processEvents()
    return dlg, dlg.findChild(QListWidget), paths


def test_a_long_name_is_elided_rather_than_scrolled_to(listing):
    _dlg, lst, _paths = listing
    assert (lst.horizontalScrollBarPolicy()
            == Qt.ScrollBarPolicy.ScrollBarAlwaysOff)


def test_it_gives_in_the_middle_so_the_kind_of_file_survives(listing):
    _dlg, lst, _paths = listing
    assert lst.textElideMode() == Qt.TextElideMode.ElideMiddle


def test_the_name_is_too_long_for_the_card_in_the_first_place(listing):
    """Otherwise the two above are about a case that never happens."""
    _dlg, lst, _paths = listing
    assert lst.sizeHintForColumn(0) > lst.viewport().width()


def test_the_whole_path_is_still_there_to_be_read(listing):
    """Eliding is a display, not a loss: the tooltip has all of it, and what
    gets opened is the path, not the label."""
    _dlg, lst, paths = listing
    assert lst.item(0).toolTip() == paths[0]
    assert lst.item(0).data(Qt.ItemDataRole.UserRole) == paths[0]


def test_a_short_name_is_left_alone(listing):
    _dlg, lst, _paths = listing
    assert lst.item(1).text() == "stool.serp"
