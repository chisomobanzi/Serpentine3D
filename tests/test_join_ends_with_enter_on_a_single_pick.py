"""Join needs two things to join. Enter or a right-click with only one
picked ends the command, rather than asking for a second one forever."""

import pytest

from serpentine3d.commands.base import CommandContext, CommandProcessor
from serpentine3d.core import geometry as g
from serpentine3d.core.history import History
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager


@pytest.fixture
def env():
    scene = Scene()
    sel = SelectionManager(scene)
    history = History(scene)
    ctx = CommandContext(scene, sel, history)
    return scene, sel, history, CommandProcessor(ctx)


def test_enter_with_one_preselected_curve_ends_join(env):
    scene, sel, history, proc = env
    line = scene.add(g.make_line((0, 0, 0), (5, 0, 0)))
    revision = scene.revision
    sel.set([line.id])
    proc.run("join")
    assert proc.busy, "one curve is not enough to start on its own"
    proc.finish_selection()
    assert not proc.busy
    assert [o.id for o in scene.all()] == [line.id]
    assert scene.revision == revision
    assert not history.can_undo, "finishing without a join must not leave an undo step"


def test_enter_with_one_picked_curve_ends_join(env):
    scene, _sel, history, proc = env
    line = scene.add(g.make_line((0, 0, 0), (5, 0, 0)))
    revision = scene.revision
    proc.run("join")
    proc.click_object(line.id)
    proc.finish_selection()
    assert not proc.busy
    assert [o.id for o in scene.all()] == [line.id]
    assert scene.revision == revision
    assert not history.can_undo, "finishing without a join must not leave an undo step"


def test_two_curves_still_join(env):
    scene, _sel, _history, proc = env
    a = scene.add(g.make_line((0, 0, 0), (5, 0, 0)))
    b = scene.add(g.make_line((5, 0, 0), (5, 5, 0)))
    proc.run("join")
    proc.click_object(a.id)
    proc.click_object(b.id)
    proc.finish_selection()
    assert not proc.busy
    assert len(scene.all()) == 1


def test_other_commands_still_ask_again(env):
    """Loft with one curve keeps waiting for the next, as before."""
    scene, _sel, _history, proc = env
    circle = scene.add(g.make_circle((0, 0, 0), 5))
    proc.run("loft")
    proc.click_object(circle.id)
    proc.finish_selection()
    assert proc.busy
    proc.cancel()


@pytest.mark.parametrize("preselected", [True, False])
def test_a_right_click_with_one_curve_ends_join(tmp_path, monkeypatch, preselected):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    from serpentine3d.app import MainWindow
    monkeypatch.setenv("SERP3D_CONFIG", str(tmp_path / "cfg.json"))
    monkeypatch.setenv("SERP3D_AUTOSAVE_DIR", str(tmp_path / "autosave"))
    window = MainWindow()
    try:
        line = window.scene.add(g.make_line((0, 0, 0), (5, 0, 0)))
        revision = window.scene.revision
        if preselected:
            window.selection.set([line.id])
        window.processor.run("join")
        if not preselected:
            window.processor.click_object(line.id)
        assert window.processor.busy
        QTest.mouseClick(window.viewport, Qt.MouseButton.RightButton,
                         pos=QPoint(200, 150))
        assert not window.processor.busy
        assert [o.id for o in window.scene.all()] == [line.id]
        assert window.scene.revision == revision
        assert not window.history.can_undo
    finally:
        window.processor.cancel()
        window._saved_revision = window.scene.revision
        window.close()
