"""The shortcut preset is discoverable, editable, and restorable in Settings."""

import json

import pytest
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QApplication, QLabel, QMessageBox,
                               QPushButton, QTableWidgetItem)

from serpentine3d.ui.settings_dialog import SettingsDialog
from tests.test_default_shortcuts import PRESETS, _lines, open_window, press


def _canonical(key):
    return QKeySequence(key).toString()


def _rows(dialog):
    table = dialog.key_table
    return {_canonical(table.item(r, 0).text()): table.item(r, 1).text()
            for r in range(table.rowCount())
            if table.item(r, 0) and table.item(r, 1)}


def _row(dialog, key):
    table = dialog.key_table
    for r in range(table.rowCount()):
        if table.item(r, 0) and _canonical(table.item(r, 0).text()) == key:
            return r
    pytest.fail(f"Settings does not show the active {key} binding")


def _dialog(window):
    dialog = SettingsDialog(window)
    for r in range(dialog.sidebar.count()):
        if dialog.sidebar.item(r).text() == "Shortcuts":
            dialog.sidebar.setCurrentRow(r)
            break
    return dialog


def _remove(dialog, key):
    dialog.key_table.setCurrentCell(_row(dialog, key), 0)
    removes = [button for button in
               dialog.pages.currentWidget().findChildren(QPushButton)
               if button.text() == "Remove"]
    assert removes, "The keyboard table needs a Remove button"
    removes[0].click()
    QApplication.processEvents()


def _restore(dialog, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    buttons = [button for button in
               dialog.pages.currentWidget().findChildren(QPushButton)
               if all(word in button.text().lower()
                      for word in ("restore", "keyboard", "default"))]
    assert buttons, "Shortcuts needs a Restore keyboard defaults button"
    buttons[0].click()
    QApplication.processEvents()


def _reload(open_window, window):
    """Start another real window from the persisted settings, as at restart."""
    stored = json.loads(open(window.cfg.path, encoding="utf-8").read())
    window.hide()
    return open_window(stored)


def _fire(window, monkeypatch, key):
    fired = []
    monkeypatch.setattr(window, "run_command", fired.append)
    window.show()
    window.activateWindow()
    window.command_line.input.clear()
    press(window, key)
    return fired


def _menu_action(window, label):
    actions = [action for action in window.findChildren(QAction)
               if action.text().replace("&", "").split("\t")[0].strip()
               == label]
    assert len(actions) == 1, f"Expected one menu action labelled {label!r}"
    return actions[0]


def test_settings_lists_presets_and_existing_builtin_bindings(open_window):
    window = open_window()
    dialog = _dialog(window)
    rows = _rows(dialog)
    assert set(PRESETS).issubset(rows), "The factory preset is incomplete"
    missing = {key for key in ("Ctrl+E", "Ctrl+C", "Ctrl+V", "Ctrl+S", "F10")
               if key not in rows}
    assert not missing, f"Settings hides existing built-in keys: {missing}"
    assert rows["Ctrl+E"] == "zoomextents"
    assert rows["F10"] == "pointson"


@pytest.mark.parametrize("key,command", [("Ctrl+G", "group"),
                                       ("Ctrl+E", "zoomextents")])
def test_changing_a_key_applies_once_and_survives_restart(
        open_window, monkeypatch, key, command):
    window = open_window()
    dialog = _dialog(window)
    dialog.key_table.item(_row(dialog, key), 0).setText("Ctrl+B")
    assert _fire(window, monkeypatch, key) == []
    assert _fire(window, monkeypatch, "Ctrl+B") == [command]
    restarted = _reload(open_window, window)
    assert _fire(restarted, monkeypatch, key) == []
    assert _fire(restarted, monkeypatch, "Ctrl+B") == [command]


@pytest.mark.parametrize("key", ["Ctrl+H", "Ctrl+E", "F10"])
def test_removing_a_factory_key_disables_it_now_and_after_restart(
        open_window, monkeypatch, key):
    window = open_window()
    dialog = _dialog(window)
    _remove(dialog, key)
    assert _fire(window, monkeypatch, key) == []
    restarted = _reload(open_window, window)
    assert key not in _rows(_dialog(restarted))
    assert _fire(restarted, monkeypatch, key) == []


def test_settings_rebuild_keeps_copy_and_paste_as_clipboard_actions(open_window):
    window = open_window()
    dialog = _dialog(window)
    # A real edit rebuilds all keyboard bindings, including built-in entries.
    dialog.key_table.item(_row(dialog, "Ctrl+G"), 1).setText("selnone")
    window.selection.set(_lines(window))
    QApplication.clipboard().setText("old text")
    press(window, "Ctrl+C")
    assert QApplication.clipboard().text() == "2 objects copied in Serpentine3D"
    assert not window.processor.busy, "Ctrl+C started the model Copy command"
    before = len(window.scene.all())
    press(window, "Ctrl+V")
    assert len(window.scene.all()) == before + 2
    assert not window.processor.busy


def test_removing_clipboard_keys_disables_and_restoring_reenables_them(
        open_window, monkeypatch):
    window = open_window()
    dialog = _dialog(window)
    _remove(dialog, "Ctrl+C")
    _remove(dialog, "Ctrl+V")
    for active in (window, _reload(open_window, window)):
        active.show()
        active.activateWindow()
        active.selection.set(_lines(active))
        QApplication.clipboard().setText("untouched")
        press(active, "Ctrl+C")
        press(active, "Ctrl+V")
        assert QApplication.clipboard().text() == "untouched"
        assert active.command_line.input.text() == ""
        assert len(active.scene.all()) == 2
    _restore(_dialog(active), monkeypatch)
    press(active, "Ctrl+C")
    press(active, "Ctrl+V")
    assert len(active.scene.all()) == 4


def test_keyboard_restore_retains_other_settings_and_resets_keys_after_reload(
        open_window, monkeypatch):
    window = open_window()
    window.cfg.set("mouse", "orbit_button", "middle")
    window.cfg.set("mouse", "chords", {"ctrl+mmb": "zoomselected"})
    window.cfg.set("aliases", {"mycircle": "circle"})
    window.cfg.set("osnaps", "enabled", False)
    before = {key: json.loads(json.dumps(value))
              for key, value in window.cfg.data.items()
              if key != "shortcuts"}
    dialog = _dialog(window)
    factory_rows = _rows(dialog)
    dialog.key_table.item(_row(dialog, "Ctrl+G"), 0).setText("Ctrl+B")
    _remove(dialog, "Ctrl+H")
    _restore(dialog, monkeypatch)
    assert _rows(dialog) == factory_rows
    assert {key: value for key, value in window.cfg.data.items()
            if key != "shortcuts"} == before
    for active in (window, _reload(open_window, window)):
        assert _fire(active, monkeypatch, "Ctrl+B") == []
        assert _fire(active, monkeypatch, "Ctrl+G") == ["group"]
        assert _fire(active, monkeypatch, "Ctrl+E") == ["zoomextents"]


def test_equivalent_duplicate_keys_show_a_conflict_and_keep_last_valid_bindings(
        open_window, monkeypatch):
    window = open_window()
    dialog = _dialog(window)
    before = json.loads(open(window.cfg.path, encoding="utf-8").read())["shortcuts"]
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *args, **kwargs: warnings.append(str(args)))
    table = dialog.key_table
    row = table.rowCount()
    table.insertRow(row)
    table.setItem(row, 0, QTableWidgetItem("ctrl+g"))
    table.setItem(row, 1, QTableWidgetItem("line"))
    QApplication.processEvents()
    feedback = warnings + [label.text() for label in dialog.findChildren(QLabel)]
    feedback += [table.item(r, c).toolTip()
                 for r in range(table.rowCount()) for c in range(2)
                 if table.item(r, c)]
    assert any(any(word in message.lower()
                   for word in ("conflict", "duplicate", "already bound"))
               for message in feedback), "Duplicate keys have no visible feedback"
    assert json.loads(open(window.cfg.path, encoding="utf-8").read())["shortcuts"] == before
    assert _fire(window, monkeypatch, "Ctrl+G") == ["group"]
    table.item(row, 0).setText("Ctrl+B")
    assert _fire(window, monkeypatch, "Ctrl+G") == ["group"]
    assert _fire(window, monkeypatch, "Ctrl+B") == ["line"]


def test_modelling_menu_labels_show_current_keys_after_edit_remove_and_restore(
        open_window, monkeypatch):
    window = open_window()
    expected = {"Group": "Ctrl+G", "Ungroup": "Ctrl+Shift+G",
                "Hide": "Ctrl+H", "Show all": "Ctrl+Shift+H",
                "Lock": "Ctrl+L", "Unlock all": "Ctrl+Shift+L",
                "Trim": "Ctrl+T", "Join": "Ctrl+J"}
    for label, key in expected.items():
        action = _menu_action(window, label)
        assert key in [sequence.toString() for sequence in action.shortcuts()]
    dialog = _dialog(window)
    dialog.key_table.item(_row(dialog, "Ctrl+G"), 0).setText("Ctrl+B")
    action = _menu_action(window, "Group")
    assert [key.toString() for key in action.shortcuts()] == ["Ctrl+B"]
    assert _fire(window, monkeypatch, "Ctrl+B") == ["group"]
    assert _fire(window, monkeypatch, "Ctrl+G") == []
    _remove(dialog, "Ctrl+B")
    assert action.shortcuts() == []
    _restore(dialog, monkeypatch)
    assert [key.toString() for key in action.shortcuts()] == ["Ctrl+G"]
    assert _fire(window, monkeypatch, "Ctrl+G") == ["group"]
