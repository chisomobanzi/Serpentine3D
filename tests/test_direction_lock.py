"""Tab freezes the direction a point is picked in (Rhino's direction snap).

Drawing a wall 3400 long at whatever angle the last one ran means aiming
the cursor once and then typing the distance. Ortho gives you that for the
four CPlane directions; this gives it for the direction you are actually
pointing in, which is the case ortho does not cover.

The lock is anchored to the base point it was taken from, so it lapses by
itself as soon as the command moves on to the next point.
"""

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager


def _qapp():
    return QApplication.instance() or QApplication([])


def _viewport(base=(0.0, 0.0, 0.0)):
    _qapp()
    from serpentine3d.ui.viewport import Viewport
    scene = Scene()
    vp = Viewport(scene, SelectionManager(scene))
    vp.resize(800, 600)
    vp.set_point_mode(True)
    vp.snap_base = base
    return vp


def _direction(vp, px, py):
    """Unit vector from the base to whatever the pixel resolves to."""
    pt = vp.world_point_at(px, py)
    assert pt is not None
    d = np.asarray(pt, float) - np.asarray(vp.snap_base, float)
    return d / np.linalg.norm(d)


def test_tab_locks_the_direction_the_cursor_is_pointing_in():
    """The lock holds the line, not a half-ray: as in Rhino, the cursor may
    still cross back over the base and pick the other way along it."""
    vp = _viewport()
    aimed = _direction(vp, 550, 220)
    loose = _direction(vp, 260, 430)
    assert not np.allclose(aimed, loose, atol=1e-3), \
        "the two pixels must differ, or the test proves nothing"

    assert vp.toggle_direction_lock(550, 220)
    assert np.allclose(_direction(vp, 600, 180), aimed, atol=1e-6)
    assert np.allclose(np.cross(_direction(vp, 260, 430), aimed), 0,
                       atol=1e-6)


def test_tab_again_releases_the_lock():
    vp = _viewport()
    loose = _direction(vp, 260, 430)
    assert vp.toggle_direction_lock(550, 220)
    assert not vp.toggle_direction_lock()
    assert np.allclose(_direction(vp, 260, 430), loose, atol=1e-9)


def test_the_locked_direction_still_takes_a_distance():
    """Locking the direction must leave the distance free, or the point
    could never be placed at all."""
    vp = _viewport()
    assert vp.toggle_direction_lock(550, 220)
    near = np.asarray(vp.world_point_at(500, 260), float)
    far = np.asarray(vp.world_point_at(700, 120), float)
    assert not np.allclose(near, far, atol=1e-6)


def test_the_lock_lapses_when_the_command_moves_to_the_next_point():
    vp = _viewport()
    assert vp.toggle_direction_lock(550, 220)
    vp.snap_base = (10.0, 4.0, 0.0)          # command picked a point
    loose = _viewport(base=(10.0, 4.0, 0.0))
    assert np.allclose(_direction(vp, 260, 430),
                       _direction(loose, 260, 430), atol=1e-9)
    assert vp.dir_lock is None


def test_the_lock_needs_a_base_point_and_a_direction():
    vp = _viewport()
    vp.snap_base = None
    assert not vp.toggle_direction_lock(550, 220)   # nothing to point from

    vp.snap_base = vp.world_point_at(550, 220)      # cursor is on the base
    assert not vp.toggle_direction_lock(550, 220)
    assert vp.dir_lock is None


def test_a_command_that_owns_the_direction_keeps_it():
    """Extrude already picks along its own axis; Tab must not fight it."""
    vp = _viewport()
    vp.point_axis = ((0, 0, 0), (0, 0, 1))
    assert not vp.toggle_direction_lock(550, 220)
    assert vp.dir_lock is None


def _tab_event():
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent
    return QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Tab,
                     Qt.KeyboardModifier.NoModifier)


def test_tab_works_with_the_focus_in_the_viewport():
    """Clicking in the viewport during a pick moves focus there, and Qt
    spends Tab on focus navigation before keyPressEvent ever sees it."""
    from PySide6.QtCore import QPointF
    vp = _viewport()
    vp._last_mouse = QPointF(550, 220)
    seen = []
    vp.tabPressed.connect(lambda: seen.append(True))
    assert vp.event(_tab_event())
    assert seen == [True]


def test_tab_still_moves_focus_when_no_point_is_wanted():
    vp = _viewport()
    vp.set_point_mode(False)
    seen = []
    vp.tabPressed.connect(lambda: seen.append(True))
    vp.event(_tab_event())
    assert seen == []


# -- the command line has to let Tab through --

def _command_line():
    _qapp()
    from serpentine3d.ui.command_line import CommandLine
    return CommandLine()


def test_tab_completes_a_command_name_when_no_point_is_pending():
    cl = _command_line()
    cl.input.setText("cir")
    cl.input.tabPressed.emit()
    assert cl.input.text().startswith("circle")


def test_tab_asks_for_a_direction_lock_while_a_point_is_pending():
    cl = _command_line()
    cl.point_pending = True
    cl.input.setText("cir")
    asked = []
    cl.tabPressed.connect(lambda: asked.append(True))
    cl.input.tabPressed.emit()
    assert asked == [True]
    assert cl.input.text() == "cir", "Tab must not also complete"


def test_the_app_tells_the_command_line_when_a_point_is_pending():
    _qapp()
    from serpentine3d.app import MainWindow
    w = MainWindow()
    assert not w.command_line.point_pending
    w.command_line.run_command("line")
    assert w.command_line.point_pending
    w.processor.cancel()
    w._sync_command_state()
    assert not w.command_line.point_pending


def test_tab_at_the_prompt_locks_the_viewports_direction():
    _qapp()
    from serpentine3d.app import MainWindow
    w = MainWindow()
    w.resize(900, 700)
    w.command_line.run_command("line")
    w.viewport.snap_base = (0.0, 0.0, 0.0)
    w.command_line.tabPressed.emit()             # no cursor seen yet
    assert w.viewport.dir_lock is None
    assert w.viewport.toggle_direction_lock(550, 220)
    w.command_line.tabPressed.emit()
    assert w.viewport.dir_lock is None
