"""Which way a curve runs, and which way a surface faces.

Rhino's Dir and Flip. Direction is invisible until something draws it and
then decides everything: which end an offset comes out on, which way a
sweep runs, which side of a surface a shell thickens. So there are two
halves here, the geometry that turns it round and the display that says
what it is now.
"""

import math

import pytest

from serpentine3d.core import geometry as g

SQUARE = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0),
          (10.0, 10.0, 0.0), (0.0, 10.0, 0.0)]


def _d3(a, b):
    return math.dist(a, b)


def _square_face():
    return g.planar_face(g.make_polyline(SQUARE, closed=True))


# ------------------------------------------------------------- geometry

def test_reversing_a_curve_swaps_its_ends():
    shape = g.make_polyline([(0.0, 0.0, 0.0), (10.0, 0.0, 0.0),
                             (10.0, 5.0, 0.0)])
    a, b = g.curve_endpoints(shape)
    c, d = g.curve_endpoints(g.reverse_curve(shape))
    assert _d3(c, b) < 1e-9
    assert _d3(d, a) < 1e-9


def test_a_reversed_curve_is_the_same_curve_backwards():
    """Turning it round is not meant to move it: the same points come off
    it, in the other order."""
    shape = g.make_control_curve([(0.0, 0.0, 0.0), (10.0, 12.0, 0.0),
                                  (20.0, -8.0, 0.0), (30.0, 4.0, 0.0)])
    there = g.sample_curve(shape, 21)
    back = g.sample_curve(g.reverse_curve(shape), 21)
    for a, b in zip(there, reversed(back)):
        assert _d3(a, b) < 1e-7


def test_a_curve_of_several_edges_reverses_all_of_them():
    """A polyline is a wire, and a wire turned round has to walk its edges
    the other way as well as reverse each one."""
    shape = g.make_polyline(SQUARE)
    out = g.reverse_curve(shape)
    assert len(g.edges_of(out)) == len(g.edges_of(shape))
    assert g.get_control_points(out) == list(reversed(SQUARE))


def test_a_closed_curve_still_closes_after_it_is_reversed():
    shape = g.make_polyline(SQUARE, closed=True)
    assert g.is_closed_curve(g.reverse_curve(shape))


def test_flipping_a_surface_turns_its_normal_round():
    face = _square_face()
    before = g.face_normal(g.faces_of(face)[0])
    after = g.face_normal(g.faces_of(g.flip_surface(face))[0])
    assert after == pytest.approx(tuple(-c for c in before), abs=1e-9)


def test_flipping_twice_is_where_you_started():
    face = _square_face()
    twice = g.flip_surface(g.flip_surface(face))
    assert g.face_normal(g.faces_of(twice)[0]) == pytest.approx(
        g.face_normal(g.faces_of(face)[0]), abs=1e-9)


def test_flipping_a_polysurface_turns_every_face():
    box = g.make_box((0.0, 0.0, 0.0), 10.0, 10.0, 10.0)
    before = [g.face_normal(f) for f in g.faces_of(box)]
    after = [g.face_normal(f) for f in g.faces_of(g.flip_surface(box))]
    assert len(after) == len(before)
    for b, a in zip(before, after):
        assert a == pytest.approx(tuple(-c for c in b), abs=1e-9)


# --------------------------------------------------------------- arrows

def test_a_curve_arrow_points_the_way_the_curve_runs():
    shape = g.make_line((0.0, 0.0, 0.0), (10.0, 0.0, 0.0))
    arrows = g.direction_arrows(shape, 4)
    assert len(arrows) == 4
    for _p, d in arrows:
        assert d == pytest.approx((1.0, 0.0, 0.0), abs=1e-9)


def test_the_arrows_turn_round_with_the_curve():
    shape = g.make_line((0.0, 0.0, 0.0), (10.0, 0.0, 0.0))
    for _p, d in g.direction_arrows(g.reverse_curve(shape), 4):
        assert d == pytest.approx((-1.0, 0.0, 0.0), abs=1e-9)


def test_curve_arrows_sit_on_the_curve():
    shape = g.make_control_curve([(0.0, 0.0, 0.0), (10.0, 12.0, 0.0),
                                  (20.0, -8.0, 0.0), (30.0, 4.0, 0.0)])
    for p, _d in g.direction_arrows(shape, 6):
        assert g.distance_point_to_shape(shape, p) < 1e-6


def test_surface_arrows_stand_along_the_normal():
    face = _square_face()
    arrows = g.direction_arrows(face, 9)
    assert len(arrows) >= 4
    for p, d in arrows:
        assert d == pytest.approx((0.0, 0.0, 1.0), abs=1e-9)
        assert g.distance_point_to_shape(face, p) < 1e-6


def test_surface_arrows_follow_the_flip():
    face = g.flip_surface(_square_face())
    for _p, d in g.direction_arrows(face, 9):
        assert d == pytest.approx((0.0, 0.0, -1.0), abs=1e-9)


def test_arrows_keep_off_the_part_that_was_trimmed_away():
    """A UV grid on a trimmed face lands outside it as often as not, and an
    arrow floating beside a surface says nothing about the surface."""
    disc = g.planar_face(g.make_circle((0.0, 0.0, 0.0), 5.0))
    arrows = g.direction_arrows(disc, 16)
    assert arrows
    for p, _d in arrows:
        assert math.hypot(p[0], p[1]) <= 5.0 + 1e-6


def test_every_face_of_a_solid_gets_arrows():
    box = g.make_box((0.0, 0.0, 0.0), 10.0, 10.0, 10.0)
    arrows = g.direction_arrows(box, 4)
    dirs = {tuple(round(c, 6) for c in d) for _p, d in arrows}
    assert len(dirs) == 6, "one outward normal per face of a box"


def test_a_point_has_no_direction_to_show():
    with pytest.raises(g.GeometryError):
        g.direction_arrows(g.make_point((0.0, 0.0, 0.0)), 4)


# ------------------------------------------------------------- commands

@pytest.fixture
def env():
    import serpentine3d.commands  # registers all commands  # noqa: F401
    from serpentine3d.commands.base import CommandContext, CommandProcessor
    from serpentine3d.core.history import History
    from serpentine3d.core.scene import Scene
    from serpentine3d.core.selection import SelectionManager
    scene = Scene()
    selection = SelectionManager(scene)
    ctx = CommandContext(scene, selection, History(scene))
    proc = CommandProcessor(ctx)
    echoes: list[str] = []
    ctx.add_echo_listener(echoes.append)
    return scene, selection, proc, echoes


def _run_on(proc, _selection, cmd, obj, *inputs):
    proc.run(cmd)
    proc.click_object(obj.id)
    proc.finish_selection()
    for text in inputs:
        proc.provide_text(text)


def test_flip_reverses_a_curve(env):
    scene, selection, proc, _echoes = env
    obj = scene.add(g.make_polyline([(0.0, 0.0, 0.0), (10.0, 0.0, 0.0),
                                     (10.0, 5.0, 0.0)]))
    before = g.curve_endpoints(obj.shape)
    _run_on(proc, selection, "flip", obj)
    assert not proc.busy
    after = g.curve_endpoints(scene.get(obj.id).shape)
    assert _d3(after[0], before[1]) < 1e-9


def test_flip_turns_a_surface_normal_round(env):
    scene, selection, proc, _echoes = env
    obj = scene.add(_square_face())
    before = g.face_normal(g.faces_of(obj.shape)[0])
    _run_on(proc, selection, "flip", obj)
    after = g.face_normal(g.faces_of(scene.get(obj.id).shape)[0])
    assert after == pytest.approx(tuple(-c for c in before), abs=1e-9)


def test_flip_says_how_many_it_turned(env):
    scene, selection, proc, echoes = env
    obj = scene.add(_square_face())
    _run_on(proc, selection, "flip", obj)
    assert any("flip" in m.lower() or "reversed" in m.lower() for m in echoes)


def test_flip_undoes(env):
    scene, selection, proc, _echoes = env
    _scene, _sel, _proc, _e = env
    obj = scene.add(_square_face())
    before = g.face_normal(g.faces_of(obj.shape)[0])
    _run_on(proc, selection, "flip", obj)
    proc.ctx.history.undo()
    assert g.face_normal(g.faces_of(scene.get(obj.id).shape)[0]) == \
        pytest.approx(before, abs=1e-9)


def test_dir_shows_the_arrows_while_it_runs(env):
    scene, selection, proc, _echoes = env
    obj = scene.add(_square_face())
    proc.run("dir")
    proc.click_object(obj.id)
    proc.finish_selection()
    assert obj.id in scene.dir_enabled
    assert proc.busy, "dir stays up until you are done looking"


def test_leaving_dir_puts_the_arrows_away(env):
    scene, selection, proc, _echoes = env
    obj = scene.add(_square_face())
    proc.run("dir")
    proc.click_object(obj.id)
    proc.finish_selection()
    proc.provide_text("")               # Enter
    assert not proc.busy
    assert obj.id not in scene.dir_enabled


def test_dir_can_flip_what_it_is_showing(env):
    """The whole point of looking is to turn it round when it is wrong,
    which is why Rhino puts Flip on the Dir prompt."""
    scene, selection, proc, _echoes = env
    obj = scene.add(_square_face())
    before = g.face_normal(g.faces_of(obj.shape)[0])
    proc.run("dir")
    proc.click_object(obj.id)
    proc.finish_selection()
    proc.provide_text("Flip")
    after = g.face_normal(g.faces_of(scene.get(obj.id).shape)[0])
    assert after == pytest.approx(tuple(-c for c in before), abs=1e-9)
    assert proc.busy, "still showing, so you can see what you just did"
    proc.provide_text("")


def test_dir_reverses_a_curve_too(env):
    scene, selection, proc, _echoes = env
    obj = scene.add(g.make_polyline([(0.0, 0.0, 0.0), (10.0, 0.0, 0.0),
                                     (10.0, 5.0, 0.0)]))
    before = g.curve_endpoints(obj.shape)
    proc.run("dir")
    proc.click_object(obj.id)
    proc.finish_selection()
    proc.provide_text("Flip")
    after = g.curve_endpoints(scene.get(obj.id).shape)
    assert _d3(after[0], before[1]) < 1e-9
    proc.provide_text("")


def test_a_scene_starts_with_no_arrows_on_it(env):
    scene, _selection, _proc, _echoes = env
    assert scene.dir_enabled == set()


# -------------------------------------------------------------- display
#
# The drawing itself cannot be exercised here: calling a viewport's GL path
# from an offscreen test takes the whole run down with it. So the arrows are
# tested through the geometry they are built from, and the paint path through
# the source that has to mention them.

@pytest.fixture
def vp():
    import numpy as np
    from PySide6.QtWidgets import QApplication
    from serpentine3d.core.scene import Scene
    from serpentine3d.core.selection import SelectionManager
    from serpentine3d.ui.viewport import Viewport
    QApplication.instance() or QApplication([])
    scene = Scene()
    v = Viewport(scene, SelectionManager(scene))
    v.resize(800, 600)
    v.camera.set_standard_view("top")
    v.camera.target = np.zeros(3)
    v.camera.distance = 40.0
    return v


def _fwd_right(cam):
    import numpy as np
    right, up = cam.right_up()
    return np.cross(right, up), right


def test_an_arrow_starts_where_it_is_and_runs_the_way_it_points(vp):
    import numpy as np
    from serpentine3d.ui.viewport import arrow_segments
    fwd, right = _fwd_right(vp.camera)
    p = np.array([[1.0, 2.0, 3.0]])
    d = np.array([[1.0, 0.0, 0.0]])
    segs = arrow_segments(p, d, fwd, right, np.array([2.0]))
    assert segs[0] == pytest.approx(p[0], abs=1e-9)
    assert segs[1] == pytest.approx([3.0, 2.0, 3.0], abs=1e-9)


def test_an_arrow_is_a_shaft_and_two_barbs(vp):
    import numpy as np
    from serpentine3d.ui.viewport import arrow_segments
    fwd, right = _fwd_right(vp.camera)
    p = np.zeros((4, 3))
    d = np.tile([1.0, 0.0, 0.0], (4, 1))
    segs = arrow_segments(p, d, fwd, right, np.full(4, 1.0))
    assert segs.shape == (4 * 6, 3)


def test_the_barbs_meet_at_the_tip_and_lean_back(vp):
    """An arrowhead you can read: both barbs touch the far end, and both
    trail behind it, so the head points where the shaft does."""
    import numpy as np
    from serpentine3d.ui.viewport import arrow_segments
    fwd, right = _fwd_right(vp.camera)
    d = np.array([[1.0, 0.0, 0.0]])
    segs = arrow_segments(np.zeros((1, 3)), d, fwd, right, np.array([2.0]))
    tip = segs[1]
    for a, b in (segs[2:4], segs[4:6]):
        assert a == pytest.approx(tip, abs=1e-9)
        assert np.dot(b - tip, d[0]) < 0, "a barb pointing forwards"


def test_the_head_does_not_collapse_when_the_arrow_faces_you(vp):
    """A normal pointing straight down the camera is exactly the case that
    matters, because that is what a surface you are looking at gives you."""
    import numpy as np
    from serpentine3d.ui.viewport import arrow_segments
    fwd, right = _fwd_right(vp.camera)
    for d in (fwd, -fwd):
        segs = arrow_segments(np.zeros((1, 3)), np.array([d]), fwd, right,
                              np.array([2.0]))
        assert np.isfinite(segs).all()
        assert np.linalg.norm(segs[3] - segs[5]) > 0.2, "a flat head"


def test_arrows_are_the_same_size_on_screen_wherever_they_are(vp):
    """Like the control point markers: a fixed size on the glass, so the
    far end of a curve is not covered in specks."""
    import numpy as np
    from serpentine3d.ui.viewport import ARROW_PX, arrow_segments, \
        cv_marker_size
    vp.camera.projection = "perspective"
    fwd, right = _fwd_right(vp.camera)
    ahead = vp.camera.target - vp.camera.position
    ahead = ahead / np.linalg.norm(ahead)
    pts = np.stack([vp.camera.position + ahead * 20.0,
                    vp.camera.position + ahead * 90.0])
    length = cv_marker_size(pts, vp.camera, 800, 600, ARROW_PX)
    d = np.tile(right, (2, 1))
    segs = arrow_segments(pts, d, fwd, right, length).reshape(2, 6, 3)
    on_glass = [np.linalg.norm(
        np.diff(vp.camera.project(one[:2], 800, 600)[:, :2], axis=0))
        for one in segs]
    assert on_glass[0] == pytest.approx(on_glass[1], rel=0.05)


def test_the_paint_path_draws_the_arrows(vp):
    import inspect
    from serpentine3d.ui.viewport import Viewport
    assert "_draw_direction_arrows" in inspect.getsource(Viewport._paint_frame)
    src = inspect.getsource(Viewport._draw_direction_arrows)
    assert "arrow_segments" in src
    assert "direction_arrows" in src


def test_the_arrows_a_pane_shows_are_the_drawings_not_its_own(vp):
    """Same reason points on is shared: which way a curve runs is a fact
    about the curve, not about the pane you asked in."""
    vp.scene.dir_enabled.add("whatever")
    assert vp.dir_enabled is vp.scene.dir_enabled
