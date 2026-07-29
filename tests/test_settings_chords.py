"""Mouse chords are editable in Settings, not just in the JSON file.

The keyboard page has had a shortcuts table for a while. This is the same
table for the mouse, on the page where the rest of the mouse lives.
"""

import pytest
from PySide6.QtWidgets import QTableWidgetItem, QWidget

from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui import viewport as vp_mod
from serpentine3d.ui.settings_dialog import SettingsDialog
from serpentine3d.utils.config import Config


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
    win = _Window(cfg)
    return SettingsDialog(win), cfg


def _set(table, row, chord, command):
    table.setItem(row, 0, QTableWidgetItem(chord))
    table.setItem(row, 1, QTableWidgetItem(command))


def test_keys_and_chords_share_one_page(dlg):
    """Both answer the same question — what do I press to run this — so
    finding one must not depend on knowing which device it lives on."""
    d, _ = dlg
    names = [d.sidebar.item(r).text() for r in range(d.sidebar.count())]
    assert "Shortcuts" in names
    assert "Keyboard" not in names and "Mouse Chords" not in names
    page = d.pages.widget(names.index("Shortcuts"))
    assert page.isAncestorOf(d.key_table), "the keyboard table is elsewhere"
    assert page.isAncestorOf(d.chord_table), "the chord table is elsewhere"


def test_the_table_shows_what_is_already_bound(tmp_path):
    cfg = Config(path=str(tmp_path / "settings.json"))
    cfg.set("mouse", "chords", {"ctrl+shift+mmb": "zoomselected"})
    d = SettingsDialog(_Window(cfg))
    rows = [(d.chord_table.item(r, 0).text(), d.chord_table.item(r, 1).text())
            for r in range(d.chord_table.rowCount())]
    assert rows == [("ctrl+shift+mmb", "zoomselected")]


def test_editing_a_row_binds_the_chord(dlg):
    d, cfg = dlg
    d.chord_table.insertRow(0)
    _set(d.chord_table, 0, "ctrl+shift+mmb", "ZoomSelected")

    assert cfg.get("mouse", "chords") == {"ctrl+shift+mmb": "zoomselected"}


def test_a_chord_that_is_not_one_is_not_saved(dlg):
    """Half-typed rows are normal while editing; they must not be stored as
    bindings that can never fire."""
    d, cfg = dlg
    d.chord_table.insertRow(0)
    _set(d.chord_table, 0, "ctrl+shift", "zoomselected")

    assert cfg.get("mouse", "chords") == {}


def test_removing_the_row_unbinds_it(dlg):
    d, cfg = dlg
    d.chord_table.insertRow(0)
    _set(d.chord_table, 0, "ctrl+shift+mmb", "zoomselected")
    d.chord_table.removeRow(0)
    d._chords_changed()

    assert cfg.get("mouse", "chords") == {}


def test_the_other_mouse_settings_survive_a_chord_edit(dlg):
    """The chords live under 'mouse' alongside orbit button and speeds —
    writing one must not flatten the rest."""
    d, cfg = dlg
    d.chord_table.insertRow(0)
    _set(d.chord_table, 0, "ctrl+shift+mmb", "zoomselected")

    assert cfg.get("mouse", "orbit_button") == "middle"
    assert cfg.get("mouse", "zoom_speed") == 1.0
