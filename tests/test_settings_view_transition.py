"""The length of a view turn is on the Display page, not only in the JSON.

Someone who finds the motion slow, or who wants none of it, should not have
to read the reference to turn it down.
"""

import pytest
from PySide6.QtWidgets import QWidget

from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui import viewport as vp_mod
from serpentine3d.ui.settings_dialog import SettingsDialog
from serpentine3d.utils.config import Config


class _Window(QWidget):
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
    win = _Window(cfg)
    return SettingsDialog(win), cfg


def test_it_starts_at_what_the_viewport_uses(dlg):
    d, _ = dlg
    assert d.sp_transition.value() == int(vp_mod.VIEW_FLIGHT_MS)


def test_turning_it_down_is_saved(dlg):
    d, cfg = dlg
    d.sp_transition.setValue(90)
    assert cfg.get("display", "view_transition_ms") == 90


def test_zero_means_no_animation(dlg):
    """Which the viewport already reads as a cut."""
    d, cfg = dlg
    d.sp_transition.setValue(0)
    assert cfg.get("display", "view_transition_ms") == 0
    d.window.viewport.go_to_view("top")
    assert not d.window.viewport.flying


def test_the_rest_of_the_display_page_survives_it(dlg):
    d, cfg = dlg
    d.sp_transition.setValue(0)
    assert cfg.get("display", "grid_extent") == 100
    assert cfg.get("display", "default_mode") == "shaded"
