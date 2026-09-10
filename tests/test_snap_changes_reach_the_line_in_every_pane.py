"""Changing an object snap mid-line must affect whichever pane is drawing."""
import numpy as np
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest

from serpentine3d.app import MainWindow
from serpentine3d.core import geometry as g, occ
from serpentine3d.core.pointcloud import PointCloudShape

A, B = (-20., -10., 6.), (20., 10., 14.)


@pytest.fixture
def window():
    win = MainWindow()
    win.set_view_layout("quad")
    yield win
    win.processor.cancel()
    win.mark_saved()
    win.close()


def prepare(vp):
    vp.resize(900, 700)
    vp.set_view("top")
    vp.camera.target = np.zeros(3)
    vp.camera.distance = 100.
    vp.grid_snap = vp.ortho = False


def pixel(vp, point):
    xy = vp.camera.project(np.asarray([point]), vp.width(), vp.height())[0, :2]
    return QPoint(round(xy[0]) + 3, round(xy[1]) + 2)


def hover(vp, point):
    pos = QPointF(pixel(vp, point))
    vp.mouseMoveEvent(QMouseEvent(QMouseEvent.Type.MouseMove, pos, pos,
                                 Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                                 Qt.KeyboardModifier.NoModifier))


@pytest.mark.parametrize("pane", ["primary", "top", "extra"])
@pytest.mark.parametrize("kind", ["point", "end", "vertex"])
@pytest.mark.parametrize("master", [False, True])
def test_switching_snap_off_after_first_click_changes_preview_and_final_point(window, pane, kind, master):
    vp = (window.viewport if pane == "primary" else
          window.aux_viewports[0] if pane == "top" else window.new_viewport_dock())
    prepare(vp)
    if kind == "vertex":
        window.scene.add(g.make_point(A))
        window.scene.add(g.make_point(B))
        kind = "point"
    elif kind == "point":
        window.scene.add(PointCloudShape([A, B]))
    else:
        window.scene.add(g.make_line(A, B))
    window._set_active_viewport(vp)
    window.processor.run("line")
    QTest.mouseClick(vp, Qt.MouseButton.LeftButton, pos=pixel(vp, A))
    assert window.processor.request.rubber_from == pytest.approx(A)
    hover(vp, B)
    assert vp._active_snap[1] == kind
    assert vp._preview_data[-1] == pytest.approx(B)

    button = window.osnap_bar._master if master else window.osnap_bar._buttons[kind]
    button.click()
    hover(vp, B)
    assert vp._active_snap is None, "Disabled snap remained active in the drawing pane"
    unsnapped = vp.world_point_at(pixel(vp, B).x(), pixel(vp, B).y())
    assert unsnapped[2] == pytest.approx(0.)
    assert vp._preview_data[-1] == pytest.approx(unsnapped)
    # Switching back on must work within the same running command too.
    button.click()
    hover(vp, B)
    assert vp._active_snap[1] == kind
    button.click()
    hover(vp, B)
    existing = set(window.scene.objects)
    QTest.mouseClick(vp, Qt.MouseButton.LeftButton, pos=pixel(vp, B))
    created = [o for o in window.scene.all() if o.id not in existing]
    assert len(created) == 1
    edge = occ.edge_adaptor(g.edges_of(created[0].shape)[0])
    end = edge.Value(edge.LastParameter())
    assert (end.X(), end.Y(), end.Z()) == pytest.approx(unsnapped)


def test_osnap_command_in_another_pane_updates_bar_and_hidden_panes(window):
    window.scene.add(PointCloudShape([A, B]))
    top = window.aux_viewports[0]
    window._set_active_viewport(top)
    window.processor.run("osnap point off")
    assert not window.osnap_bar._buttons["point"].isChecked()
    window.set_view_layout("single")
    window.set_view_layout("quad")
    for vp in window.all_viewports():
        prepare(vp)
        xy = pixel(vp, B)
        assert vp.world_point_at(xy.x(), xy.y())[2] == pytest.approx(0.)
        assert vp._active_snap is None


def test_settings_changes_reach_a_line_already_started_in_top(window):
    from serpentine3d.ui.settings_dialog import SettingsDialog
    window.scene.add(PointCloudShape([A, B]))
    top = window.aux_viewports[0]
    prepare(top)
    window._set_active_viewport(top)
    window.processor.run("line")
    QTest.mouseClick(top, Qt.MouseButton.LeftButton, pos=pixel(top, A))
    dialog = SettingsDialog(window)
    try:
        dialog.os_boxes["point"].setChecked(False)
        hover(top, B)
        assert top._active_snap is None
        assert top._preview_data[-1, 2] == pytest.approx(0.)
    finally:
        dialog.close()
