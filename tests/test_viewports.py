"""Dockable viewports: model + paper side by side, focused-pane routing."""

import json

import pytest


@pytest.fixture
def window(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({}))
    monkeypatch.setenv("SERP3D_CONFIG", str(cfg))
    monkeypatch.setenv("SERP3D_AUTOSAVE_DIR", str(tmp_path / "autosave"))
    from serpentine3d.app import MainWindow
    w = MainWindow()
    yield w
    w._saved_revision = w.scene.revision   # else closeEvent blocks on the
    w.close()                              # save-changes dialog, headless


def test_dock_viewport_model_and_paper_side_by_side(window):
    from PySide6.QtWidgets import QDockWidget
    from serpentine3d.core.layout import Layout
    lay = Layout(name="Sheet 1")
    window.scene.layouts.append(lay)

    window.processor.run("newviewport")
    window.processor.provide_text("Right")
    window.processor.provide_text("Sheet 1")
    assert len(window.dock_viewports) == 1
    vp2 = window.dock_viewports[0]
    dock = vp2.parentWidget()
    assert isinstance(dock, QDockWidget)
    assert dock.windowTitle() == "Sheet 1 viewport"
    # the star feature: 3D model and the paper sheet coexist
    assert window.viewport.space == "model"
    assert vp2.space == lay.id
    assert vp2 in window.all_viewports()


def test_space_tabs_act_on_focused_pane(window):
    from serpentine3d.core.layout import Layout
    lay = Layout(name="Sheet 1")
    window.scene.layouts.append(lay)
    window._refresh_space_tabs()
    vp2 = window.new_viewport_dock("Right")
    assert window.active_viewport is vp2

    # switching space moves only the focused pane
    window.switch_space(lay.id)
    assert vp2.space == lay.id
    assert window.viewport.space == "model"

    # focus back on the main pane: tabs highlight its space again
    window._set_active_viewport(window.viewport)
    assert window.ctx.viewport is window.viewport
    idx = window.space_tabs.currentIndex()
    assert window.space_tabs.tabData(idx) == "model"


def test_closed_dock_leaves_fanout_and_focus(window):
    vp2 = window.new_viewport_dock("Floating")
    assert vp2 in window.all_viewports()
    vp2.parentWidget().close()
    assert vp2 not in window.all_viewports()
    assert window.active_viewport is window.viewport   # falls back

    # point-mode fanout only reaches live panes (no crash on the dead one)
    window.processor.run("line")
    assert window.viewport.point_mode
    window.processor.cancel()


def test_zoom_selected_targets_focused_pane(window):
    from serpentine3d.core import geometry as g
    obj = window.scene.add(g.make_box((50, 50, 50), 2, 2, 2))
    window.selection.set([obj.id])
    vp2 = window.new_viewport_dock("Right")
    before_main = float(window.viewport.camera.distance)
    window.processor.run("zoomselected")
    assert vp2.camera.distance < 30                 # focused pane framed it
    assert window.viewport.camera.distance == before_main


def _rmb_click(vp, pos=None):
    from PySide6.QtCore import QPoint
    from PySide6.QtCore import Qt as QtC
    from PySide6.QtTest import QTest
    QTest.mouseClick(vp, QtC.MouseButton.RightButton,
                     pos=pos or QPoint(200, 150))


def test_right_click_finishes_selection(window):
    from serpentine3d.core import geometry as g
    c1 = window.scene.add(g.make_circle((0, 0, 0), 5))
    c2 = window.scene.add(g.make_circle((0, 0, 10), 3))
    window.processor.run("loft")
    window.processor.click_object(c1.id)
    window.processor.click_object(c2.id)
    _rmb_click(window.viewport)          # "press enter when done"
    assert not window.processor.busy
    assert window.scene.all()[-1].kind in ("surface", "solid")


def test_right_click_repeats_last_command(window):
    window.processor.run("circle")
    window.processor.provide_text("0,0,0")
    window.processor.provide_text("5")
    assert not window.processor.busy
    _rmb_click(window.viewport)          # idle: repeat 'circle'
    assert window.processor.busy
    assert "circle" in window.processor.prompt_text().lower() \
        or "center" in window.processor.prompt_text().lower()
    window.processor.cancel()


def test_right_drag_does_not_trigger_enter(window):
    from PySide6.QtCore import QPoint
    from PySide6.QtCore import Qt as QtC
    from PySide6.QtTest import QTest
    window.processor.run("circle")       # busy; a drag must not advance it
    vp = window.viewport
    QTest.mousePress(vp, QtC.MouseButton.RightButton, pos=QPoint(100, 100))
    QTest.mouseRelease(vp, QtC.MouseButton.RightButton, pos=QPoint(160, 130))
    assert window.processor.busy         # still waiting for the center
    window.processor.cancel()


def test_right_click_accepts_defaults(window):
    from serpentine3d.core import geometry as g
    c = window.scene.add(g.make_circle((0, 0, 0), 5))
    window.selection.set([c.id])
    window.processor.run("extrude")      # preselection consumed
    _rmb_click(window.viewport)          # accept default distance 10
    assert not window.processor.busy
    solid = window.scene.all()[-1]
    assert solid.kind == "solid"
    assert g.bbox(solid.shape)[1][2] == pytest.approx(10)
