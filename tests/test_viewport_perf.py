"""What the draw loop is allowed to do per object, per frame.

A real scene here is 5900 objects — mostly curves — and the viewport drew every
one of them every frame, looking each shader uniform up by name as it went.
That is 26k `glGetUniformLocation` calls a frame before a single pixel is
filled, and a draw call for every object whether or not it is on screen.

These are GL *call counts*, not timings: the cost is the chatter, and counting
it is the same answer on any machine. The budgets below are deliberately loose
— they exist to catch work that scales with the number of objects, not to pin
an exact call sequence.
"""

import numpy as np
import pytest

from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.core import geometry
from serpentine3d.ui import viewport as vp_mod


class _GLRecorder:
    """Stands in for the OpenGL module and counts the calls made through it."""

    def __init__(self):
        self.calls = {}
        self._consts = {}

    def __getattr__(self, name):
        if name.startswith("GL_"):
            return self._consts.setdefault(name, 0x2000 + len(self._consts))

        def fn(*a, **k):
            self.calls[name] = self.calls.get(name, 0) + 1
            return 0
        return fn

    def n(self, name) -> int:
        return self.calls.get(name, 0)

    @property
    def draws(self) -> int:
        return self.n("glDrawArrays") + self.n("glDrawElements")


class _FakeGpu:
    """The buffer handles `_draw_objects` reads, without a GL context."""

    def __init__(self, lines=6, tris=0, isos=0):
        self.tri_vao, self.tri_count = 1, tris
        self.line_vao, self.line_count = 2, lines
        self.iso_vao, self.iso_count = 3, isos
        self.thick_vao, self.thick_count = 4, 0


@pytest.fixture
def gl(monkeypatch):
    rec = _GLRecorder()
    monkeypatch.setattr(vp_mod, "GL", rec)
    return rec


def _viewport(count: int, spread: float = 10.0):
    """A viewport over `count` short polylines, ready to draw."""
    scene = Scene()
    selection = SelectionManager(scene)
    rng = np.random.default_rng(3)
    for i in range(count):
        p = rng.uniform(-spread, spread, 3)
        q = p + rng.uniform(-1, 1, 3)
        scene.add(geometry.make_polyline([tuple(p), tuple(q)]), name=f"c{i}")
    view = vp_mod.Viewport(scene, selection)
    view.resize(800, 600)
    # stand in for initializeGL, which needs a context we haven't got
    view._mesh_prog, view._line_prog, view._thick_prog = 11, 12, 13
    view._max_line_width = 1.0
    for obj in scene.all():
        obj.mesh                              # tessellate now, not mid-draw
        view._gpu[obj.id] = _FakeGpu()
    return view


def _mvp(view):
    w, h = view.width(), view.height()
    v = view.camera.view_matrix()
    return ((view.camera.proj_matrix(w, h) @ v).astype(np.float32), v)


def test_uniform_locations_are_not_looked_up_once_per_object(gl):
    """Locations are fixed for the life of a program, so looking them up by
    name inside the loop is pure overhead — and it was the single biggest
    line item in the profile."""
    view = _viewport(60)
    mvp, v = _mvp(view)
    view._draw_objects(mvp, v)

    per_object = gl.n("glGetUniformLocation") / 60
    assert per_object < 1.0, (
        f"{gl.n('glGetUniformLocation')} lookups for 60 objects "
        f"({per_object:.1f} each)")


def test_uniform_lookups_do_not_grow_with_the_scene(gl):
    """The real check: whatever the fixed cost is, it must not scale."""
    small = _viewport(20)
    mvp, v = _mvp(small)
    small._draw_objects(mvp, v)
    few = gl.n("glGetUniformLocation")

    gl.calls.clear()
    big = _viewport(200)
    mvp, v = _mvp(big)
    big._draw_objects(mvp, v)
    many = gl.n("glGetUniformLocation")

    assert many <= few + 8, f"{few} lookups for 20 objects, {many} for 200"


def test_the_camera_matrix_is_uploaded_once_per_frame(gl):
    """Every object was re-sending the same 4x4 camera matrix to the line
    program before drawing its edges."""
    view = _viewport(50)
    mvp, v = _mvp(view)
    view._draw_objects(mvp, v)
    assert gl.n("glUniformMatrix4fv") < 10, (
        f"{gl.n('glUniformMatrix4fv')} matrix uploads for 50 objects")


def test_a_new_camera_matrix_is_always_uploaded(gl):
    """The skip above is the dangerous half of the change: a matrix that is
    held back is a frame drawn from the wrong camera. Moving the camera must
    always reach the GPU."""
    view = _viewport(8)
    mvp, v = _mvp(view)
    view._draw_objects(mvp, v)

    view.camera.distance *= 0.5
    moved, v2 = _mvp(view)
    gl.calls.clear()
    view._draw_objects(moved, v2)
    assert gl.n("glUniformMatrix4fv") >= 1, "camera moved but nothing uploaded"


def test_a_squashed_shadow_matrix_does_not_linger(gl):
    """Rendered mode stamps ground shadows with a flattened matrix on the same
    program the edges use. If that is left in place the model draws squashed
    onto the floor."""
    view = _viewport(6)
    view.display_mode = "rendered"
    mvp, v = _mvp(view)
    view._draw_objects(mvp, v)
    assert view._mvp_state.get(view._line_prog) is mvp, (
        "line program left holding the shadow's matrix")


def test_objects_outside_the_view_are_not_drawn(gl):
    """The cave file spans 60000 units; working inside it means nearly
    everything is off screen, and off-screen objects should cost nothing."""
    view = _viewport(40)
    mvp, v = _mvp(view)
    view._draw_objects(mvp, v)
    visible_draws = gl.draws

    scene = view.scene
    for i in range(40):                       # same again, far out of frame
        scene.add(geometry.make_polyline([(3e5 + i, 3e5, 3e5),
                                          (3e5 + i, 3e5 + 1, 3e5)]),
                  name=f"far{i}")
    for obj in scene.all():
        obj.mesh
        view._gpu.setdefault(obj.id, _FakeGpu())

    gl.calls.clear()
    view._draw_objects(mvp, v)
    assert gl.draws == visible_draws, (
        f"{gl.draws - visible_draws} draw calls for objects off screen")


def test_an_object_costs_about_two_gl_calls_to_draw(gl):
    """Bind its geometry, draw it. Program, colour, line width and camera are
    all shared with the object before it, and re-sending them per object was
    most of the frame: PyOpenGL charges a few microseconds a call, and at 5900
    objects that is the whole budget."""
    view = _viewport(80)
    mvp, v = _mvp(view)
    view._draw_objects(mvp, v)

    drawn = len(view._cull(mvp, view.scene.visible_objects()))
    assert drawn > 0
    total = sum(gl.calls.values())
    assert total / drawn < 3.0, (
        f"{total} GL calls to draw {drawn} objects ({total / drawn:.1f} each)")


def test_state_is_not_assumed_to_survive_between_frames(gl):
    """The skips are only safe within a frame — Qt's QPainter overlays reset
    GL behind the viewport's back — so each frame must re-assert what it
    depends on rather than trusting last frame's shadow."""
    view = _viewport(10)
    mvp, v = _mvp(view)
    view._draw_objects(mvp, v)
    view._reset_gl_state()

    gl.calls.clear()
    view._draw_objects(mvp, v)
    assert gl.n("glUseProgram") >= 1, "program never re-bound after a reset"
    assert gl.n("glUniformMatrix4fv") >= 1, "camera never re-sent after a reset"


def test_culling_keeps_the_draw_order(gl):
    """Draw order is not decoration: with GL_LESS the first-drawn wins a
    coincident depth tie, and translucent objects are sorted back to front.
    A cull that filters the list must not also reshuffle it."""
    view = _viewport(12)
    mvp, v = _mvp(view)
    objects = list(view.scene.visible_objects())
    kept = view._cull(mvp, objects)

    assert kept, "everything culled from a view fitted to the scene"
    assert kept == [o for o in objects if o in kept], "order changed"


def test_objects_inside_the_view_are_still_drawn(gl):
    """Guard on the other side: culling that eats visible geometry is worse
    than no culling at all."""
    view = _viewport(30)
    mvp, v = _mvp(view)
    view._draw_objects(mvp, v)
    assert gl.draws >= 30, f"only {gl.draws} draw calls for 30 objects in view"
