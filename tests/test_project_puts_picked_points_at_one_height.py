"""Project, as in Rhino: every picked point lands at one height.

Snapping to the corner of something standing above the plane used to start
the new curve up there too. With Project on, the point keeps the snap's X and
Y and takes the height set beside Project in the osnap bar, 0 by default.
"""

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.utils.config import Config

CORNER = (5.0, 3.0, 8.0)


def _viewport(cfg=None):
    QApplication.instance() or QApplication([])
    from serpentine3d.ui.viewport import Viewport
    scene = Scene()
    vp = Viewport(scene, SelectionManager(scene), config=cfg)
    vp.resize(800, 600)
    vp.set_point_mode(True)
    return vp


def _px(vp, world):
    scr = vp.camera.project(np.asarray([world], float),
                            vp.width(), vp.height())[0]
    return float(scr[0]), float(scr[1])


def _on_the_corner(vp):
    """Cursor over a snappable end point that floats above the plane."""
    vp.pending_points = [CORNER, (0.0, 0.0, 0.0)]
    return vp.world_point_at(*_px(vp, CORNER))


def test_off_by_default_and_a_snap_keeps_its_height():
    vp = _viewport()
    assert vp.snaps.project_enabled is False
    assert vp.snaps.project_z == 0.0
    assert _on_the_corner(vp) == pytest.approx(CORNER)


def test_a_snapped_point_lands_at_zero():
    vp = _viewport()
    vp.snaps.project_enabled = True
    assert _on_the_corner(vp) == pytest.approx((5.0, 3.0, 0.0))


def test_the_height_can_be_set():
    vp = _viewport()
    vp.snaps.project_enabled = True
    vp.snaps.project_z = 2.5
    assert _on_the_corner(vp) == pytest.approx((5.0, 3.0, 2.5))
    free = vp.world_point_at(300, 400)
    assert free[2] == pytest.approx(2.5)


def test_a_height_picked_along_an_axis_is_left_alone():
    vp = _viewport()
    vp.snaps.project_enabled = True
    vp.point_axis = ((0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    p = vp.world_point_at(*_px(vp, (0.0, 0.0, 4.0)))
    assert p[2] == pytest.approx(4.0, abs=0.05)


def test_every_launch_starts_with_project_off_at_zero(tmp_path):
    cfg = Config(path=str(tmp_path / "settings.json"))
    cfg.set("osnaps", "project", True)       # as an earlier build wrote it
    cfg.set("osnaps", "project_z", 12.5)
    vp = _viewport(Config(path=cfg.path))
    assert vp.snaps.project_enabled is False
    assert vp.snaps.project_z == 0.0


@pytest.fixture
def window():
    QApplication.instance() or QApplication([])
    from serpentine3d.app import MainWindow
    w = MainWindow()
    try:
        yield w
    finally:
        w.mark_saved()
        w.close()


def test_the_osnap_bar_switches_it_and_sets_the_height(window):
    bar = window.osnap_bar
    snaps = window.viewport.snaps
    assert not bar._project_z.isEnabled()
    bar._project.setChecked(True)
    assert snaps.project_enabled is True
    assert bar._project_z.isEnabled()
    bar._project_z.setValue(42.0)
    assert snaps.project_z == 42.0
    assert window.cfg.get("osnaps", "project_z") is None
    assert window.cfg.get("osnaps", "project") is None


def test_osnap_project_toggle_from_the_command_line(window):
    window.run_command("osnap")
    window.processor.provide_text("Project")
    window.processor.provide_text("On")
    assert window.viewport.snaps.project_enabled is True
    assert window.osnap_bar._project.isChecked()


def test_the_snap_marker_shows_where_the_first_point_will_land():
    """Before the first click there is no rubber band yet, so the snap
    marker is the preview: with Project on it is drawn at the height the
    point will take, not on the feature it snapped to."""
    vp = _viewport()
    _on_the_corner(vp)
    assert not vp._projecting()
    vp.snaps.project_enabled = True
    assert vp._projecting()
    vp.point_axis = ((0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    assert not vp._projecting()


def test_the_height_field_has_no_arrows(window):
    from PySide6.QtWidgets import QAbstractSpinBox
    assert (window.osnap_bar._project_z.buttonSymbols()
            == QAbstractSpinBox.ButtonSymbols.NoButtons)


def test_a_click_in_selects_the_number_to_type_over(window):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    bar = window.osnap_bar
    bar._project.setChecked(True)
    window.show()
    edit = bar._project_z.lineEdit()
    QTest.mouseClick(edit, Qt.MouseButton.LeftButton, pos=QPoint(4, 8))
    for _ in range(3):
        QApplication.processEvents()
    assert edit.selectedText() == "0.00"
    QTest.keyClicks(edit, "7")
    QTest.keyClick(edit, Qt.Key.Key_Return)
    assert window.viewport.snaps.project_z == 7.0


def test_the_cursor_stays_off_the_z(window):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    box = window.osnap_bar._project_z
    edit = box.lineEdit()
    edit.deselect()
    edit.setCursorPosition(0)
    assert edit.cursorPosition() == len(box.prefix())
    QTest.keyClick(edit, Qt.Key.Key_Home)
    assert edit.cursorPosition() == len(box.prefix())
    assert edit.text().startswith("Z ")
