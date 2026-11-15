"""A middle click offers Join and Explode side by side above what the popup
always held: up to twelve recent commands, the staples and the palette."""

import pytest
from PySide6.QtWidgets import QApplication, QToolButton, QWidgetAction

from serpentine3d.app import MainWindow

STAPLES = ["line", "circle", "extrude", "move", "zoomextents"]


@pytest.fixture
def window(tmp_path, monkeypatch):
    monkeypatch.setenv("SERP3D_CONFIG", str(tmp_path / "cfg.json"))
    monkeypatch.setenv("SERP3D_AUTOSAVE_DIR", str(tmp_path / "autosave"))
    w = MainWindow()
    yield w
    w.processor.cancel()
    w._saved_revision = w.scene.revision
    w.close()


def _run(window, *names):
    for name in names:
        window.command_line.run_command(name)
        window.processor.cancel()
    QApplication.processEvents()


def _buttons(menu):
    row, = [a.defaultWidget() for a in menu.actions()
            if isinstance(a, QWidgetAction)]
    return row.findChildren(QToolButton)


def _entries(menu):
    return [a.text() for a in menu.actions()
            if not a.isSeparator() and not isinstance(a, QWidgetAction)]


def test_join_and_explode_sit_side_by_side_above_the_recent_commands(window):
    _run(window, "sphere", "circle", "box", "copy")
    menu = window._mmb_menu()
    join, explode = _buttons(menu)
    assert (join.text(), explode.text()) == ("Join", "Explode")
    assert not join.icon().isNull() and not explode.icon().isNull()
    assert all(b.property("framed") and not b.autoRaise()
               for b in (join, explode)), (
        "Both read as buttons before the pointer reaches them")
    assert isinstance(menu.actions()[0], QWidgetAction), (
        "The two buttons come first")
    recent = ["copy", "box", "circle", "sphere"]
    assert _entries(menu) == (
        recent + [s for s in STAPLES if s not in recent]
        + ["Command palette…"]), "all four recent commands are retained"


def test_each_button_is_as_wide_as_what_it_shows(window):
    from PySide6.QtCore import QPoint
    menu = window._mmb_menu()
    menu.popup(QPoint(100, 100))
    QApplication.processEvents()
    join, explode = _buttons(menu)
    assert join.width() == join.sizeHint().width()
    assert explode.width() == explode.sizeHint().width()
    assert join.width() < explode.width()
    assert join.y() == explode.y()
    assert join.x() + join.width() <= explode.x()
    menu.close()


@pytest.mark.parametrize("index, name", [(0, "join"), (1, "explode")])
def test_a_popup_button_runs_its_command(window, index, name):
    menu = window._mmb_menu()
    _buttons(menu)[index].click()
    assert window.processor.active is not None
    assert window.processor.active.name == name


def test_with_no_history_the_staples_still_show(window):
    assert _entries(window._mmb_menu()) == STAPLES + ["Command palette…"]


def test_recent_commands_keep_twelve_distinct_names_most_recent_first(window):
    _run(window, "sphere", "circle", "box", "copy", "line", "polyline",
         "curve", "interpcrv", "arc", "ellipse", "rectangle", "point",
         "extrude", "move", "sphere", "circle")
    recent = ["circle", "sphere", "move", "extrude", "point", "rectangle",
              "ellipse", "arc", "interpcrv", "curve", "polyline", "line"]
    assert window.command_line.recent_commands() == recent
    assert _entries(window._mmb_menu()) == (
        recent + [s for s in STAPLES if s not in recent]
        + ["Command palette…"])
