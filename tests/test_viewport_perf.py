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


# -- _sync_gpu: the other per-object, per-frame pass --------------------------
#
# _sync_gpu runs every frame too, and asks every object for its effective
# linetype so it can notice when the answer changed. A drawing has a handful of
# layers and thousands of objects, so that question has very few distinct
# answers — and resolving it per object meant a layer lookup each time.


def _layered(count: int, layers: int):
    """A viewport over `count` curves spread across `layers` layers."""
    view = _viewport(count)
    ids = [view.scene.layers.create(f"L{i}").id for i in range(layers)]
    for i, obj in enumerate(view.scene.all()):
        obj.layer_id = ids[i % len(ids)]
    view._gpu.clear()                 # let _sync_gpu build them for real
    return view, ids


class _CountingLayers:
    """The scene's LayerManager, counting how often a layer is looked up."""

    def __init__(self, inner):
        self._inner = inner
        self.gets = 0

    def get(self, layer_id):
        self.gets += 1
        return self._inner.get(layer_id)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def test_layers_are_not_looked_up_once_per_object(gl):
    """A drawing is thousands of objects over a few dozen layers. Asking the
    layer manager for each object's layer, every frame, is the same answer
    fetched over and over."""
    view, ids = _layered(150, 5)
    view._sync_gpu()                                  # first pass: builds them
    counter = _CountingLayers(view.scene.layers)
    view.scene.layers = counter
    view._sync_gpu()                                  # steady state

    assert counter.gets <= 2 * len(ids), (
        f"{counter.gets} layer lookups for 150 objects on {len(ids)} layers")


def test_a_changed_layer_linetype_reaches_its_objects(gl):
    """The dangerous half: a cached answer that outlives the thing it was
    cached from means changing a layer to Dashed does nothing on screen."""
    view, ids = _layered(12, 2)
    view._sync_gpu()
    before = {oid: g.dash_key for oid, g in view._gpu.items()}
    assert set(before.values()) == {"Continuous"}

    view.scene.layers.set_linetype(ids[0], "Dashed")
    view._sync_gpu()

    on_layer0 = [o.id for o in view.scene.all() if o.layer_id == ids[0]]
    assert on_layer0
    for oid in on_layer0:
        assert view._gpu[oid].dash_key == "Dashed", (
            "layer set to Dashed but its objects still draw Continuous")


def test_an_objects_own_linetype_still_overrides_its_layer(gl):
    """Resolution is ByLayer *by default*; an object that names its own
    linetype must keep it whatever the layer says."""
    view, ids = _layered(6, 1)
    obj = view.scene.all()[0]
    obj.linetype = "Dotted"
    view.scene.layers.set_linetype(ids[0], "Dashed")
    view._sync_gpu()

    assert view._gpu[obj.id].dash_key == "Dotted"
    others = [o for o in view.scene.all() if o.id != obj.id]
    assert all(view._gpu[o.id].dash_key == "Dashed" for o in others)


# -- picking: the same per-object question, asked on click -------------------
#
# Clicking runs a ray against every object, prefiltered by projecting each
# object's bounding box to the screen. That projection needs the camera's
# view-projection matrix — which was rebuilt from scratch inside the loop, once
# per object, when the camera does not move during a pick.


class _CountingCamera:
    """Counts how often the camera builds a matrix from its pose."""

    def __init__(self, cam):
        self.cam = cam
        self.views = 0
        real = cam.view_matrix

        def counted():
            self.views += 1
            return real()

        cam.view_matrix = counted


def test_the_camera_matrix_is_not_rebuilt_once_per_object_when_picking(gl):
    """The camera cannot move part-way through a click, so every object was
    paying to rebuild the same matrix — and `look_at` runs two `np.cross`
    calls, which is where the pick time actually went."""
    view = _viewport(120)
    counter = _CountingCamera(view.camera)
    view.pick_object(400.0, 300.0)

    assert counter.views <= 4, (
        f"{counter.views} view matrices built for one pick over 120 objects")


def test_picking_does_not_rebuild_the_matrix_more_as_the_scene_grows(gl):
    """The real check: whatever the fixed cost is, it must not scale."""
    small = _viewport(20)
    few = _CountingCamera(small.camera)
    small.pick_object(400.0, 300.0)

    big = _viewport(200)
    many = _CountingCamera(big.camera)
    big.pick_object(400.0, 300.0)

    assert many.views <= few.views, (
        f"{few.views} for 20 objects, {many.views} for 200")


def test_a_moved_camera_picks_from_its_new_pose(gl):
    """The dangerous half: a matrix cached across camera moves means clicking
    selects whatever *used* to be under the cursor."""
    view = _viewport(40, spread=4.0)
    view.camera.set_standard_view("top")
    view.zoom_extents()
    first = view.pick_object(400.0, 300.0)
    assert first is not None, "nothing under the cursor to begin with"

    view.camera.pan(4000.0, 4000.0, view.height())   # far away from everything
    assert view.pick_object(400.0, 300.0) is None, (
        "camera panned off the model but the pick still hit an object")

    view.camera.pan(-4000.0, -4000.0, view.height())
    assert view.pick_object(400.0, 300.0) == first, (
        "camera panned back but the pick no longer finds the object")


def test_a_resized_viewport_projects_at_the_new_size(gl):
    """Viewport size feeds the projection as much as the camera pose does."""
    view = _viewport(40, spread=4.0)
    view.camera.set_standard_view("top")
    view.zoom_extents()
    corner = view.pick_object(780.0, 580.0)

    view.resize(1600, 1200)
    # the same *pixel* is now a different point in the model
    assert view.pick_object(780.0, 580.0) != corner or corner is None


class _CountingProject:
    """Counts how often the camera is asked to project a batch of points."""

    def __init__(self, cam):
        self.calls = 0
        real = cam.project

        def counted(points, width, height):
            self.calls += 1
            return real(points, width, height)

        cam.project = counted


def test_the_pick_prefilter_projects_in_one_batch(gl):
    """Projecting eight corners is a few dozen flops wrapped in a lot of numpy
    call overhead, so per object the overhead is the whole cost. The same test
    over every object at once is one call instead of thousands — the shape
    `_cull` already uses for drawing."""
    view = _viewport(300)
    counter = _CountingProject(view.camera)
    view.pick_object(400.0, 300.0)

    assert counter.calls < 30, (
        f"{counter.calls} project calls for one pick over 300 objects")


def test_the_batched_prefilter_agrees_with_the_one_it_replaced(gl):
    """Batching must narrow the loop, not widen the test. The single-object
    version is the specification, so the two must return the same set."""
    view = _viewport(120, spread=8.0)
    view.camera.set_standard_view("top")
    view.zoom_extents()
    w, h = view.width(), view.height()
    r = vp_mod.PICK_RADIUS_PX

    objs = view.scene.visible_objects()
    for px, py in ((400.0, 300.0), (5.0, 5.0), (799.0, 599.0), (250.0, 480.0)):
        rect = (px - r, py - r, px + r, py + r)
        batched = {o.id for o in view._pick_candidates(objs, *rect, w, h)}
        one_at_a_time = {o.id for o in objs
                         if not view._pick_reject(o.mesh, *rect, w, h)}
        assert batched == one_at_a_time, f"disagree at ({px}, {py})"


def test_the_prefilter_actually_rejects_something(gl):
    """A prefilter that keeps everything would satisfy the test above while
    doing nothing, so pin that it really is narrowing the loop."""
    view = _viewport(120, spread=8.0)
    view.camera.set_standard_view("top")
    view.zoom_extents()
    w, h = view.width(), view.height()
    r = vp_mod.PICK_RADIUS_PX

    objs = view.scene.visible_objects()
    # aim at something that is definitely there: one object's own centre
    mn, mx = objs[0].mesh.bounds()
    scr = view.camera.project(np.array([(mn + mx) / 2.0]), w, h)
    px, py = float(scr[0, 0]), float(scr[0, 1])

    kept = view._pick_candidates(objs, px - r, py - r, px + r, py + r, w, h)
    assert objs[0].id in {o.id for o in kept}, "missed the object aimed at"
    assert len(kept) < len(objs), (
        f"all {len(objs)} survived a {2 * r:.0f}px window — nothing rejected")


def _look_away(camera):
    """Aim the camera along -X from far out on +X, leaving the model at the
    origin squarely behind it — no object straddling the camera plane."""
    camera.azimuth = 0.0
    camera.elevation = 0.0
    camera.distance = 10.0
    camera.target = np.array([-1000.0, 0.0, 0.0])


def test_objects_behind_the_camera_are_not_pick_candidates(gl):
    """Working inside a model means most of it is behind you. A box whose every
    corner is behind the camera plane cannot be under the cursor, but the
    projection of such a box is meaningless, so it was kept unconditionally —
    and zoomed in that was most of what the ray then had to be tested against."""
    view = _viewport(200, spread=8.0)
    w, h = view.width(), view.height()
    r = vp_mod.PICK_RADIUS_PX
    objs = view.scene.visible_objects()
    _look_away(view.camera)

    kept = view._pick_candidates(objs, 400 - r, 300 - r, 400 + r, 300 + r, w, h)
    assert not kept, f"{len(kept)} of {len(objs)} objects behind the camera kept"


def test_an_object_straddling_the_camera_plane_is_still_a_candidate(gl):
    """The dangerous half. A box with corners on both sides of the camera
    plane projects nonsense — part of it is genuinely in front of you, so it
    must survive the prefilter and be settled by the ray test."""
    scene = Scene()
    selection = SelectionManager(scene)
    # one long curve running from well behind the camera to well in front
    scene.add(geometry.make_polyline([(0, -500, 0), (0, 500, 0)]), name="thru")
    view = vp_mod.Viewport(scene, selection)
    view.resize(800, 600)
    view._mesh_prog, view._line_prog, view._thick_prog = 11, 12, 13
    view._max_line_width = 1.0
    for obj in scene.all():
        obj.mesh
        view._gpu[obj.id] = _FakeGpu()

    view.camera.target = np.zeros(3)
    view.camera.distance = 10.0            # inside the curve's span
    w, h = view.width(), view.height()
    r = vp_mod.PICK_RADIUS_PX

    kept = view._pick_candidates(scene.all(), 400 - r, 300 - r,
                                 400 + r, 300 + r, w, h)
    assert len(kept) == 1, "curve running through the camera was prefiltered out"
