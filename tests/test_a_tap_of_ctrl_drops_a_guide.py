"""A tap of Ctrl drops a temporary guide to snap and line up to (SmartTrack).

Ctrl already means other things while a point is wanted, so most of what
can go wrong here is a tap being heard where nobody tapped: Ctrl+Z, the
Ctrl+click elevator, Ctrl held for a while and let go.
"""

import json
from unittest.mock import MagicMock

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui import ctrl_tap

CTRL = Qt.KeyboardModifier.ControlModifier


def _viewport(base=None):
    QApplication.instance() or QApplication([])
    from serpentine3d.ui.viewport import Viewport
    scene = Scene()
    vp = Viewport(scene, SelectionManager(scene))
    vp.resize(800, 600)
    vp.set_point_mode(True)
    vp.snap_base = base
    return vp


def _pixel(vp, point):
    scr = vp.camera.project(np.asarray([point], float), vp.width(),
                            vp.height())[0]
    return float(scr[0]), float(scr[1])


# -- the guide itself --

def test_a_tap_drops_a_guide_where_a_click_would_land():
    vp = _viewport()
    px, py = _pixel(vp, (5.0, 3.0, 0.0))
    click = vp.world_point_at(px, py)
    assert vp.tap_guide(px, py)
    assert np.allclose(vp.snaps.guides[0], click)


def test_the_cursor_snaps_to_a_guide():
    vp = _viewport()
    vp.snaps.guides.append((5.0, 3.0, 0.0))
    px, py = _pixel(vp, (5.0, 3.0, 0.0))
    assert np.allclose(vp.world_point_at(px + 6, py - 5), (5.0, 3.0, 0.0))
    assert vp._active_snap[1] == "guide"


def test_a_guide_works_with_the_object_snaps_off():
    """You put it there for this drawing; it is not one of the object snaps."""
    vp = _viewport()
    vp.snaps.enabled = False
    vp.snaps.guides.append((5.0, 3.0, 0.0))
    px, py = _pixel(vp, (5.0, 3.0, 0.0))
    assert np.allclose(vp.world_point_at(px + 4, py), (5.0, 3.0, 0.0))


def test_a_second_tap_on_a_guide_takes_it_back():
    vp = _viewport()
    vp.snaps.guides.append((5.0, 3.0, 0.0))
    px, py = _pixel(vp, (5.0, 3.0, 0.0))
    assert vp.tap_guide(px + 4, py)
    assert vp.snaps.guides == []


def test_no_guide_without_a_point_being_picked():
    vp = _viewport()
    vp.set_point_mode(False)
    assert not vp.tap_guide(400, 300)
    assert vp.snaps.guides == []


def test_switched_off_the_guides_do_nothing():
    vp = _viewport()
    vp.snaps.guides.append((5.0, 3.0, 0.0))
    vp.snaps.tracking = False
    px, py = _pixel(vp, (5.0, 3.0, 0.0))
    assert not np.allclose(vp.world_point_at(px + 6, py - 5), (5.0, 3.0, 0.0))
    assert not vp.tap_guide(400, 300)


def test_guides_and_the_rail_in_use_are_drawn(monkeypatch):
    """Asked of the drawing code, since the tests may have no OpenGL."""
    from serpentine3d.ui import viewport as module
    vp = _viewport()
    vp.snaps.guides.append((5.0, 3.0, 0.0))
    px, py = _pixel(vp, (5.0, -6.0, 0.0))
    vp.world_point_at(px + 3, py)

    drawn = []

    class Buffer:
        def update(self, pts):
            drawn.append(len(pts))

    monkeypatch.setattr(module, "GL", MagicMock())
    monkeypatch.setattr(vp, "_preview", Buffer())
    monkeypatch.setattr(vp, "_draw_lines", lambda *a, **k: None)
    vp._draw_preview(None)
    assert drawn == [2, 4, 4]               # rail, guide, marker on the cursor


# -- lining up --

def test_the_cursor_lines_up_with_a_guide_along_each_cplane_axis():
    vp = _viewport()
    vp.snaps.guides.append((5.0, 3.0, 0.0))

    px, py = _pixel(vp, (5.0, -6.0, 0.0))
    pt = vp.world_point_at(px + 4, py)
    assert pt[0] == pytest.approx(5.0) and pt[1] < 0
    assert vp._active_snap[1] == "track"
    assert np.allclose(vp._guide_rails[0][0], (5.0, 3.0, 0.0))

    px, py = _pixel(vp, (-7.0, 3.0, 0.0))
    pt = vp.world_point_at(px, py + 4)
    assert pt[1] == pytest.approx(3.0) and pt[0] < 0


def test_two_guides_give_the_corner_their_rails_cross_at():
    vp = _viewport()
    vp.snaps.guides.extend([(5.0, 3.0, 0.0), (-4.0, -6.0, 0.0)])
    px, py = _pixel(vp, (5.0, -6.0, 0.0))
    pt = vp.world_point_at(px + 3, py + 3)
    assert np.allclose(pt, (5.0, -6.0, 0.0))
    assert len(vp._guide_rails) == 2


def test_away_from_every_rail_nothing_happens():
    vp = _viewport()
    free = vp.world_point_at(600, 150)
    vp.snaps.guides.append((-8.0, -8.0, 0.0))
    assert np.allclose(vp.world_point_at(600, 150), free)
    assert vp._guide_rails == [] and vp._active_snap is None


def test_a_guide_above_the_cplane_lines_up_without_lifting_the_point():
    """Sharing an X with something must not take its height as well."""
    vp = _viewport()
    vp.snaps.guides.append((5.0, 3.0, 7.0))
    px, py = _pixel(vp, (5.0, -6.0, 0.0))
    pt = vp.world_point_at(px + 3, py)
    assert pt[0] == pytest.approx(5.0) and pt[2] == pytest.approx(0.0)


def test_ortho_keeps_its_line_and_the_guide_says_where_along_it():
    vp = _viewport(base=(0.0, 0.0, 0.0))
    vp.ortho = True
    vp.snaps.guides.append((5.0, 3.0, 0.0))
    px, py = _pixel(vp, (5.0, 0.0, 0.0))
    pt = vp.world_point_at(px + 3, py + 3)
    assert np.allclose(pt, (5.0, 0.0, 0.0))


def test_a_rail_beats_the_grid_on_the_coordinate_it_holds():
    vp = _viewport()
    vp.grid_snap, vp.grid_snap_step = True, 1.0
    vp.snaps.guides.append((5.25, 3.0, 0.0))
    px, py = _pixel(vp, (5.25, -6.0, 0.0))
    pt = vp.world_point_at(px + 2, py)
    assert pt[0] == pytest.approx(5.25)
    assert pt[1] == pytest.approx(round(pt[1]))


def test_a_held_direction_runs_out_to_a_guide():
    vp = _viewport(base=(0.0, 0.0, 0.0))
    vp.point_axis = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))
    vp.snaps.guides.append((5.0, 3.0, 0.0))
    px, py = _pixel(vp, (5.0, 3.0, 0.0))
    assert np.allclose(vp.world_point_at(px, py), (5.0, 0.0, 0.0))


# -- telling a tap from everything else Ctrl does --

@pytest.fixture
def window(tmp_path, monkeypatch):
    from serpentine3d import app as app_module
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setenv("SERP3D_CONFIG", str(path))
    win = app_module.MainWindow()
    win.set_view_layout("single")
    win.show()
    win.activateWindow()
    QApplication.processEvents()

    # the cursor of the offscreen platform stays where the test left it
    class Cursor:
        at = win.viewport.mapToGlobal(QPoint(400, 300))

        @classmethod
        def pos(cls):
            return cls.at

    monkeypatch.setattr(app_module, "QCursor", Cursor)
    win.cursor_for_test = Cursor
    yield win
    win.processor.cancel()
    win.mark_saved()
    win.close()
    QApplication.processEvents()


def _tap(widget):
    QTest.keyPress(widget, Qt.Key.Key_Control, CTRL)
    QTest.keyRelease(widget, Qt.Key.Key_Control)


def test_a_tap_is_heard_with_the_command_line_holding_the_keyboard(window):
    window.run_command("polyline")
    window.command_line.focus()
    _tap(window.command_line.input)
    assert len(window.viewport.snaps.guides) == 1


def test_a_tap_with_no_command_running_does_nothing(window):
    _tap(window.viewport)
    assert window.viewport.snaps.guides == []


def test_a_tap_over_a_panel_is_nobodys_guide(window):
    window.run_command("polyline")
    window.cursor_for_test.at = window.viewport.mapToGlobal(QPoint(-40, -40))
    _tap(window.viewport)
    assert window.viewport.snaps.guides == []


def test_a_key_pressed_with_ctrl_is_not_a_tap(window):
    window.run_command("polyline")
    vp = window.viewport
    QTest.keyPress(vp, Qt.Key.Key_Control, CTRL)
    QTest.keyClick(vp, Qt.Key.Key_K, CTRL)
    QTest.keyRelease(vp, Qt.Key.Key_Control)
    assert vp.snaps.guides == []


def test_the_elevator_click_is_not_a_tap(window):
    window.run_command("polyline")
    vp = window.viewport
    QTest.keyPress(vp, Qt.Key.Key_Control, CTRL)
    QTest.mouseClick(vp, Qt.MouseButton.LeftButton, CTRL, QPoint(400, 300))
    QTest.keyRelease(vp, Qt.Key.Key_Control)
    assert vp.snaps.guides == []
    assert vp.dir_lock is not None


def test_ctrl_held_and_let_go_is_not_a_tap(window, monkeypatch):
    monkeypatch.setattr(ctrl_tap, "TAP_SECONDS", 0.0)
    window.run_command("polyline")
    _tap(window.viewport)
    assert window.viewport.snaps.guides == []


def test_shift_and_ctrl_together_are_not_a_tap(window):
    window.run_command("polyline")
    vp = window.viewport
    both = CTRL | Qt.KeyboardModifier.ShiftModifier
    QTest.keyPress(vp, Qt.Key.Key_Control, both)
    QTest.keyRelease(vp, Qt.Key.Key_Control, Qt.KeyboardModifier.ShiftModifier)
    assert vp.snaps.guides == []


# -- how long one lasts --

def test_guides_last_as_long_as_the_command(window):
    vp = window.viewport
    window.run_command("line")
    _tap(vp)
    vp.pointPicked.emit((-20.0, 0.0, 0.0))
    QApplication.processEvents()
    assert len(vp.snaps.guides) == 1, "gone between two points of one command"
    vp.pointPicked.emit((-20.0, 9.0, 0.0))
    QApplication.processEvents()
    assert not window.processor.busy
    assert vp.snaps.guides == []


def test_cancelling_the_command_clears_them(window):
    vp = window.viewport
    window.run_command("polyline")
    _tap(vp)
    window.processor.cancel()
    assert vp.snaps.guides == []


def test_the_bar_switch_clears_them_and_is_remembered(window):
    vp = window.viewport
    window.run_command("polyline")
    _tap(vp)
    window.osnap_bar._track.setChecked(False)
    assert vp.snaps.guides == [] and not vp.snaps.tracking
    assert window.cfg.get("smart_track") is False
