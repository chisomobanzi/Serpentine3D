"""Getting the view back, and locking everything but what you are on.

Two of Jonas's toolbar commands. `undoview` is the one you reach for after
an orbit that went too far: the drawing is fine, it is the camera that is
wrong, and the general undo is no help because nothing about the drawing
changed. `lockother` is the other half of isolate: leave everything on
screen to line up against, and make sure you cannot pick any of it.

A view change is a gesture, not a frame. A drag that turns the model right
round is one thing you did, so it is one step back, and that is what most
of these are about.
"""

import math

import pytest

from serpentine3d.ui.camera import Camera, ViewHistory


def _cam(**kw):
    cam = Camera()
    for k, v in kw.items():
        setattr(cam, k, v)
    return cam


# --------------------------------------------------------- camera state

def test_a_camera_can_say_where_it_is_and_be_put_back():
    cam = _cam(distance=123.0, azimuth=0.75, elevation=0.25, fov=32.0)
    cam.target[:] = (1.0, 2.0, 3.0)
    where = cam.state()
    cam.set_standard_view("top")
    cam.distance = 5.0
    cam.restore(where)
    assert cam.distance == 123.0
    assert cam.azimuth == pytest.approx(0.75)
    assert cam.elevation == pytest.approx(0.25)
    assert cam.fov == pytest.approx(32.0)
    assert list(cam.target) == [1.0, 2.0, 3.0]


def test_a_state_is_a_copy_not_a_window_onto_the_camera():
    """It is kept to go back to, so moving on must not rewrite it."""
    cam = Camera()
    where = cam.state()
    cam.target[:] = (9.0, 9.0, 9.0)
    cam.distance = 999.0
    assert where["target"] == [0.0, 0.0, 0.0]
    assert where["distance"] != 999.0


def test_two_cameras_in_the_same_place_say_the_same_thing():
    assert Camera().state() == Camera().state()


# -------------------------------------------------------- the history

def test_nothing_to_go_back_to_at_the_start():
    assert ViewHistory().undo({"distance": 1.0}) is None


def test_undo_hands_back_where_you_were():
    h = ViewHistory()
    h.record({"distance": 10.0})
    assert h.undo({"distance": 20.0}) == {"distance": 10.0}


def test_and_redo_brings_you_forward_again():
    h = ViewHistory()
    h.record({"distance": 10.0})
    h.undo({"distance": 20.0})
    assert h.redo({"distance": 10.0}) == {"distance": 20.0}


def test_there_is_nothing_forward_until_you_have_gone_back():
    assert ViewHistory().redo({"distance": 1.0}) is None


def test_moving_the_view_yourself_throws_the_forward_steps_away():
    """The same rule as the drawing's undo: once you go somewhere new from
    where you stepped back to, forward means nothing any more."""
    h = ViewHistory()
    h.record({"distance": 10.0})
    h.undo({"distance": 20.0})
    h.record({"distance": 10.0})
    assert h.redo({"distance": 30.0}) is None


def test_standing_still_is_not_a_view_change():
    """Every command asks the pane to paint, and a paint that finds the
    camera where it left it must not fill the history with nothing."""
    h = ViewHistory()
    h.record({"distance": 10.0})
    h.record({"distance": 10.0})
    h.undo({"distance": 20.0})
    assert h.undo({"distance": 10.0}) is None


def test_it_forgets_the_oldest_rather_than_growing_for_ever():
    h = ViewHistory(limit=3)
    for i in range(10):
        h.record({"distance": float(i)})
    assert h.undo({"distance": 99.0}) == {"distance": 9.0}
    assert h.undo({"distance": 9.0}) == {"distance": 8.0}
    assert h.undo({"distance": 8.0}) == {"distance": 7.0}
    assert h.undo({"distance": 7.0}) is None


# ------------------------------------------------- gestures, not frames

@pytest.fixture
def vp():
    from PySide6.QtWidgets import QApplication
    from serpentine3d.core.scene import Scene
    from serpentine3d.core.selection import SelectionManager
    from serpentine3d.ui.viewport import Viewport
    QApplication.instance() or QApplication([])
    scene = Scene()
    v = Viewport(scene, SelectionManager(scene))
    v.resize(800, 600)
    return v


def _orbit(vp, frames=6, at=0.0, step=0.01):
    """A drag: several changes in a row, no gap between them."""
    for i in range(frames):
        vp.camera.azimuth += 0.05
        vp.note_view_change(now=at + i * step)


def test_a_whole_drag_is_one_step_back(vp):
    start = vp.camera.state()
    vp.note_view_change(now=0.0)
    _orbit(vp, at=1.0)
    assert vp.view_history.undo(vp.camera.state()) == start


def test_two_gestures_are_two_steps_back(vp):
    vp.note_view_change(now=0.0)
    _orbit(vp, at=1.0)
    between = vp.camera.state()
    _orbit(vp, at=10.0)                  # a long pause, so a new gesture
    assert vp.view_history.undo(vp.camera.state()) == between


def test_a_paint_that_changes_nothing_records_nothing(vp):
    vp.note_view_change(now=0.0)
    for i in range(20):
        vp.note_view_change(now=float(i))
    assert vp.view_history.undo(vp.camera.state()) is None


def test_going_back_does_not_count_as_going_somewhere(vp):
    """Otherwise every undo would leave a step of its own behind and you
    would never get further back than the last one."""
    start = vp.camera.state()
    vp.note_view_change(now=0.0)
    _orbit(vp, at=1.0)
    assert vp.undo_view()
    vp.note_view_change(now=20.0)
    assert vp.camera.state() == start
    assert vp.view_history.undo(vp.camera.state()) is None


def test_a_move_right_after_an_undo_is_still_its_own_step(vp):
    vp.note_view_change(now=0.0)
    _orbit(vp, at=1.0)
    vp.undo_view()
    back = vp.camera.state()
    _orbit(vp, at=2.0)                   # straight away, no pause
    assert vp.view_history.undo(vp.camera.state()) == back


def test_the_paint_path_watches_the_view(vp):
    import inspect
    from serpentine3d.ui.viewport import Viewport
    assert "note_view_change" in inspect.getsource(Viewport._paint_frame)


def test_a_pane_keeps_its_own_view_history(vp):
    """Unlike points on: where the Top view has been says nothing about
    where the Perspective view has been."""
    from serpentine3d.ui.viewport import Viewport
    other = Viewport(vp.scene, vp.selection)
    assert other.view_history is not vp.view_history


# ------------------------------------------------------------ commands

@pytest.fixture
def env(vp):
    import serpentine3d.commands  # registers all commands  # noqa: F401
    from serpentine3d.commands.base import CommandContext, CommandProcessor
    from serpentine3d.core.history import History
    ctx = CommandContext(vp.scene, vp.selection, History(vp.scene),
                         viewport=vp)
    proc = CommandProcessor(ctx)
    echoes: list[str] = []
    ctx.add_echo_listener(echoes.append)
    return vp, proc, echoes


def test_undoview_puts_the_camera_back(env):
    vp, proc, _echoes = env
    start = vp.camera.state()
    vp.note_view_change(now=0.0)
    _orbit(vp, at=1.0)
    assert vp.camera.state() != start
    proc.run("undoview")
    assert vp.camera.state() == start


def test_redoview_brings_it_forward_again(env):
    vp, proc, _echoes = env
    vp.note_view_change(now=0.0)
    _orbit(vp, at=1.0)
    turned = vp.camera.state()
    proc.run("undoview")
    proc.run("redoview")
    assert vp.camera.state() == turned


def test_undoview_says_so_when_there_is_nowhere_to_go(env):
    _vp, proc, echoes = env
    proc.run("undoview")
    assert any("view" in m.lower() for m in echoes)


def test_undoview_leaves_the_drawing_alone(env):
    """It is the camera that moved, so the drawing's undo must not have a
    step of its own to take back afterwards."""
    vp, proc, _echoes = env
    from serpentine3d.core import geometry as g
    vp.scene.add(g.make_line((0.0, 0.0, 0.0), (10.0, 0.0, 0.0)))
    before = vp.scene.revision
    vp.note_view_change(now=0.0)
    _orbit(vp, at=1.0)
    proc.run("undoview")
    assert vp.scene.revision == before


def test_a_standard_view_is_a_step_you_can_take_back(env):
    """Not just dragging: typing `top` is a view change like any other."""
    vp, proc, _echoes = env
    vp.camera.azimuth = 1.0
    vp.note_view_change(now=0.0)
    start = vp.camera.state()
    vp.camera.set_standard_view("top")
    vp.note_view_change(now=5.0)
    proc.run("undoview")
    assert vp.camera.state() == start


# --------------------------------------------------------- lockother

def _two_objects(scene):
    from serpentine3d.core import geometry as g
    a = scene.add(g.make_line((0.0, 0.0, 0.0), (10.0, 0.0, 0.0)))
    b = scene.add(g.make_line((0.0, 5.0, 0.0), (10.0, 5.0, 0.0)))
    return a, b


def test_lockother_locks_everything_you_did_not_pick(env):
    vp, proc, _echoes = env
    a, b = _two_objects(vp.scene)
    proc.run("lockother")
    proc.click_object(a.id)
    proc.finish_selection()
    assert not vp.scene.get(a.id).locked
    assert vp.scene.get(b.id).locked


def test_what_you_picked_stays_picked(env):
    """The point of it is to carry on working on what you kept."""
    vp, proc, _echoes = env
    a, _b = _two_objects(vp.scene)
    proc.run("lockother")
    proc.click_object(a.id)
    proc.finish_selection()
    assert list(vp.selection.ids) == [a.id]


def test_lockother_says_how_many_it_locked(env):
    vp, proc, echoes = env
    a, _b = _two_objects(vp.scene)
    proc.run("lockother")
    proc.click_object(a.id)
    proc.finish_selection()
    assert any("lock" in m.lower() for m in echoes)


def test_unlockall_undoes_it(env):
    vp, proc, _echoes = env
    a, b = _two_objects(vp.scene)
    proc.run("lockother")
    proc.click_object(a.id)
    proc.finish_selection()
    proc.run("unlockall")
    assert not vp.scene.get(b.id).locked


def test_lockother_with_nothing_picked_locks_nothing(env):
    """Escaping out of the selection must not leave the whole drawing
    locked, which is the one mistake this command can make."""
    vp, proc, _echoes = env
    _a, b = _two_objects(vp.scene)
    proc.run("lockother")
    proc.finish_selection()
    assert not vp.scene.get(b.id).locked


def test_locking_hides_nothing(env):
    """Unlike isolate: the whole point is that the rest is still there to
    line the new work up against."""
    vp, proc, _echoes = env
    a, b = _two_objects(vp.scene)
    proc.run("lockother")
    proc.click_object(a.id)
    proc.finish_selection()
    assert vp.scene.get(b.id).visible


def test_the_api_says_which_objects_are_locked(env):
    """Otherwise a script that ran lockother has no way to find out what it
    can still touch, and a pick that quietly does nothing looks like a bug
    in the pick."""
    vp, proc, _echoes = env
    a, b = _two_objects(vp.scene)
    proc.run("lockother")
    proc.click_object(a.id)
    proc.finish_selection()
    from serpentine3d.api import SerpApi
    api = SerpApi.__new__(SerpApi)
    api.scene = vp.scene
    info = {o["name"]: o for o in (api._obj_info(o) for o in vp.scene.all())}
    assert info[vp.scene.get(a.id).name]["locked"] is False
    assert info[vp.scene.get(b.id).name]["locked"] is True


def test_the_angle_a_camera_reports_survives_a_round_trip():
    """A view saved and restored must be the same view, radians and all."""
    cam = _cam(azimuth=math.radians(-137.0), elevation=math.radians(11.5))
    other = Camera()
    other.restore(cam.state())
    assert other.state() == cam.state()
