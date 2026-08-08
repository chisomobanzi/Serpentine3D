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


# -- and then you type the distance --

def _ctx(vp):
    from serpentine3d.commands.base import CommandContext
    scene = vp.scene
    return CommandContext(scene, SelectionManager(scene), None, viewport=vp)


def test_a_typed_length_runs_along_the_locked_direction():
    """Which is the point of locking one: aim once, then type 3400."""
    from serpentine3d.commands.base import PointReq, parse_value
    vp = _viewport()
    assert vp.toggle_direction_lock(550, 220)
    base, direction = vp.dir_lock
    ok, pt = parse_value(PointReq("End of line"), "3400", _ctx(vp))
    assert ok, pt
    assert np.allclose(pt, np.asarray(base, float)
                       + 3400 * np.asarray(direction, float))


def test_a_bare_length_with_no_lock_is_still_not_a_point():
    """Nothing says where it would go."""
    from serpentine3d.commands.base import PointReq, parse_value
    vp = _viewport()
    ok, _ = parse_value(PointReq("End of line"), "3400", _ctx(vp))
    assert not ok


def test_the_commands_own_direction_beats_the_lock():
    """Extrude asks for its height along its own axis. A lock taken while
    some earlier point was being picked has no business bending that."""
    from serpentine3d.commands.base import PointReq, parse_value
    vp = _viewport()
    assert vp.toggle_direction_lock(550, 220)
    req = PointReq("Height", number_from=((0.0, 0.0, 0.0), (0.0, 0.0, 1.0)))
    ok, pt = parse_value(req, "10", _ctx(vp))
    assert ok and np.allclose(pt, (0.0, 0.0, 10.0))


def test_coordinates_still_mean_coordinates_under_a_lock():
    """A lock constrains the cursor. Typing an actual point overrides it,
    the same way it overrides ortho."""
    from serpentine3d.commands.base import PointReq, parse_value
    vp = _viewport()
    assert vp.toggle_direction_lock(550, 220)
    ok, pt = parse_value(PointReq("End of line"), "5,6,7", _ctx(vp))
    assert ok and np.allclose(pt, (5.0, 6.0, 7.0))


def test_a_length_typed_at_the_prompt_finishes_the_line():
    """End to end: pick a start, Tab, type the length, get a line."""
    _qapp()
    from serpentine3d.app import MainWindow
    w = MainWindow()
    w.resize(900, 700)
    w.command_line.run_command("line")
    w.processor.provide((0.0, 0.0, 0.0))
    vp = w.active_viewport
    assert vp.snap_base is not None, "the second point has no base to run from"
    assert vp.toggle_direction_lock(550, 220)
    direction = np.asarray(vp.dir_lock[1], float)

    w.command_line.input.setText("3400")
    w.command_line.submit_input()

    try:
        assert len(w.scene.all()) == 1, "the typed length made no point"
        assert np.allclose(w.ctx.last_point, 3400 * direction, atol=1e-6)
    finally:
        w.mark_saved()         # or closing asks to save and waits forever
        w.close()


# -- snapping still works while a direction is held --

def _normal(vp):
    return np.asarray(vp.cplane.normal, float)


def test_a_snap_lands_on_the_locked_line_instead_of_being_ignored():
    """Holding a direction used to switch the object snaps off altogether,
    so drawing to the height of something already built meant guessing at
    it. The snap belongs on the line, beside whatever it found."""
    vp = _viewport()
    assert vp.toggle_direction_lock(550, 220)
    base, direction = (np.asarray(v, float) for v in vp.dir_lock)
    aside = np.cross(direction, _normal(vp))
    found = base + 37.0 * direction + 12.0 * aside
    vp.snaps.find = lambda *a, **k: (tuple(found), "end")

    pt = np.asarray(vp.world_point_at(300, 400), float)
    assert np.allclose(pt, base + 37.0 * direction, atol=1e-6)
    assert vp._active_snap is not None, "the snap marker still has to show"


def test_the_locked_line_is_still_free_when_nothing_snaps():
    vp = _viewport()
    assert vp.toggle_direction_lock(550, 220)
    vp.snaps.find = lambda *a, **k: None
    base, direction = (np.asarray(v, float) for v in vp.dir_lock)
    pt = np.asarray(vp.world_point_at(300, 400), float)
    assert np.allclose(np.cross(pt - base, direction), 0, atol=1e-6)
    assert vp._active_snap is None


# -- Ctrl stands an axis up from the CPlane (Rhino's elevator) --

def test_ctrl_locks_a_vertical_through_the_point_under_the_cursor():
    vp = _viewport()
    ground = np.asarray(vp.world_point_at(550, 220), float)
    assert vp.lock_elevation(550, 220)
    base, direction = vp.dir_lock
    assert np.allclose(base, ground)
    assert np.isclose(abs(float(np.dot(direction, _normal(vp)))), 1.0)


def test_the_elevator_works_before_any_point_has_been_picked():
    """Which is its whole purpose: putting the *first* point off the CPlane,
    where there is no base to have aimed from and Tab has nothing to do."""
    vp = _viewport()
    vp.snap_base = None
    assert not vp.toggle_direction_lock(550, 220)
    assert vp.lock_elevation(550, 220)
    assert vp.locked_direction() is not None


def test_the_elevator_holds_the_cursor_on_the_vertical():
    vp = _viewport()
    vp.snap_base = None
    assert vp.lock_elevation(550, 220)
    base, direction = (np.asarray(v, float) for v in vp.dir_lock)
    for px, py in ((300, 120), (700, 500)):
        pt = np.asarray(vp.world_point_at(px, py), float)
        assert np.allclose(np.cross(pt - base, direction), 0, atol=1e-6)


def test_a_typed_height_runs_up_the_elevator():
    """The same sentence the Tab lock understands, because it is the same
    lock underneath."""
    from serpentine3d.commands.base import PointReq, parse_value
    vp = _viewport()
    vp.snap_base = None
    assert vp.lock_elevation(550, 220)
    base, direction = vp.dir_lock
    ok, pt = parse_value(PointReq("Start of line"), "50", _ctx(vp))
    assert ok, pt
    assert np.allclose(pt, np.asarray(base, float)
                       + 50 * np.asarray(direction, float))


def test_the_elevator_lapses_when_the_command_moves_on():
    """It is anchored to a point of its own, not to the command's base, so
    it needs its own reason to expire."""
    vp = _viewport()
    assert vp.lock_elevation(550, 220)
    vp.snap_base = (10.0, 4.0, 0.0)          # the command took its point
    assert vp.locked_direction() is None
    assert vp.dir_lock is None


def test_a_command_that_owns_its_axis_keeps_it_from_the_elevator():
    vp = _viewport()
    vp.point_axis = ((0, 0, 0), (0, 0, 1))
    assert not vp.lock_elevation(550, 220)
    assert vp.dir_lock is None


def _press(vp, px, py, ctrl=False):
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    vp.mousePressEvent(QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(px, py),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier if ctrl
        else Qt.KeyboardModifier.NoModifier))


def test_ctrl_click_sets_the_elevation_rather_than_picking_the_point():
    vp = _viewport()
    picked = []
    vp.pointPicked.connect(picked.append)
    _press(vp, 550, 220, ctrl=True)
    assert picked == [], "that click chose the base, not the point"
    assert vp.locked_direction() is not None


def test_the_click_after_it_takes_the_point_up_the_axis():
    vp = _viewport()
    _press(vp, 550, 220, ctrl=True)
    base, direction = (np.asarray(v, float) for v in vp.dir_lock)
    picked = []
    vp.pointPicked.connect(picked.append)
    _press(vp, 560, 120)
    assert len(picked) == 1
    assert np.allclose(np.cross(np.asarray(picked[0], float) - base,
                                direction), 0, atol=1e-6)


def test_a_plain_click_still_just_picks_the_point():
    vp = _viewport()
    picked = []
    vp.pointPicked.connect(picked.append)
    _press(vp, 550, 220)
    assert len(picked) == 1
    assert vp.dir_lock is None


def _move(vp, px, py):
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    vp.mouseMoveEvent(QMouseEvent(
        QEvent.Type.MouseMove, QPointF(px, py),
        Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier))


def test_the_elevator_reads_out_the_height_as_you_move():
    """Without the readout you are dragging a point up an invisible axis
    with nothing to aim at."""
    vp = _viewport()
    vp.snap_base = None
    assert vp.lock_elevation(550, 220)
    base = np.asarray(vp.dir_lock[0], float)
    _move(vp, 550, 140)
    assert vp._draw_span is not None, "no height shown"
    a, b = (np.asarray(v, float) for v in vp._draw_span)
    assert np.allclose(a, base, atol=1e-6)
    assert np.linalg.norm(b - a) > 1e-6


def test_the_commands_own_leg_still_wins_the_readout():
    """A command drawing a rubber band is already measuring the thing you
    care about; the elevator must not talk over it."""
    vp = _viewport()
    assert vp.lock_elevation(550, 220)
    leg = np.array([[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]]])
    vp.set_preview(leg)
    _move(vp, 550, 140)
    a, b = (np.asarray(v, float) for v in vp._draw_span)
    assert np.allclose(a, (0.0, 0.0, 0.0)) and np.allclose(b, (1.0, 0.0, 0.0))


def test_the_held_axis_is_drawn_long_enough_to_leave_the_view():
    """Both ways from the base, because the lock holds the whole line."""
    from serpentine3d.ui.viewport import _axis_guide
    seg = _axis_guide((1.0, 2.0, 3.0), (0.0, 0.0, 2.0), 50.0)
    assert np.allclose(seg[0], (1.0, 2.0, -47.0))
    assert np.allclose(seg[1], (1.0, 2.0, 53.0))


def test_the_viewport_draws_that_guide_while_a_direction_is_held():
    """The draw path cannot run headless, so the seam is what gets checked:
    an elevator with no rubber band against it needs the axis on screen or
    Ctrl looks like it did nothing."""
    import inspect
    from serpentine3d.ui.viewport import Viewport
    src = inspect.getsource(Viewport._draw_preview)
    assert "_axis_guide" in src and "_locked_axis" in src


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


# -- Tab with Shift held is a different key --

def _shift_tab_event():
    """What X sends for Shift+Tab, which is not Key_Tab with a modifier.

    Verified against a real X server, not remembered: the keystroke
    arrives as Key_Backtab. It matters because Shift is the ortho
    override, so aim-with-Shift then Tab is the ordinary way to reach
    this feature and the only Tab the code saw was the one nobody
    presses.
    """
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent
    return QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Backtab,
                     Qt.KeyboardModifier.ShiftModifier)


def test_shift_tab_locks_the_direction_too():
    from PySide6.QtCore import QPointF
    vp = _viewport()
    vp._last_mouse = QPointF(550, 220)
    seen = []
    vp.tabPressed.connect(lambda: seen.append(True))
    assert vp.event(_shift_tab_event())
    assert seen == [True]


def test_shift_tab_still_moves_focus_when_no_point_is_wanted():
    vp = _viewport()
    vp.set_point_mode(False)
    seen = []
    vp.tabPressed.connect(lambda: seen.append(True))
    vp.event(_shift_tab_event())
    assert seen == []


def test_the_lock_holds_the_ortho_direction_once_shift_is_let_go():
    """The whole move: hold Shift to aim square, Tab, stop holding Shift."""
    vp = _viewport()
    vp.ortho = True                      # what holding Shift amounts to
    assert vp.toggle_direction_lock(550, 220)
    axis = np.asarray(vp.dir_lock[1], float)
    assert np.count_nonzero(np.abs(axis) > 1e-9) == 1, axis
    vp.ortho = False
    assert np.allclose(np.cross(_direction(vp, 600, 180), axis), 0,
                       atol=1e-6)


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


def test_shift_tab_at_the_prompt_asks_for_a_direction_lock():
    """The prompt keeps the focus through most of a pick, so the key has
    to survive there too."""
    cl = _command_line()
    cl.point_pending = True
    asked = []
    cl.tabPressed.connect(lambda: asked.append(True))
    assert cl.input.event(_shift_tab_event())
    assert asked == [True]


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
