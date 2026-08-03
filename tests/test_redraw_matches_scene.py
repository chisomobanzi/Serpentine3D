"""After an edit, what is drawn is what the scene holds.

Three bugs in a row were the same shape: the model changed and the picture
did not follow, because something the viewport had cached still claimed to
be current. Each was found by eye, on one command, by chance. This states
the invariant once and runs the editing commands through it.

The check is on the bookkeeping, not on pixels — which is where the bugs
were. `_sync_gpu` decides what to upload and what to reuse, and a recording
stand-in for the buffers lets a test read back exactly what it decided.
"""

import numpy as np
import pytest

import serpentine3d.commands  # registers commands   # noqa: F401
from serpentine3d.commands.base import CommandContext, CommandProcessor
from serpentine3d.core import geometry as g
from serpentine3d.core.history import History
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui import viewport as vp_mod


class _Recorder:
    """Stands in for the buffers on the card, and remembers what went into
    them. The vertices are copied: the point is to know what was uploaded,
    which must not be able to change afterwards to match."""

    def __init__(self, mesh, dash=None, dash_key=None):
        self.mesh_key = mesh.uid
        self.vertices = np.array(mesh.vertices, float, copy=True)
        self.dash_key = dash_key
        self.tri_count = self.line_count = self.iso_count = 0
        self.released = False

    def release(self):
        self.released = True


def check_drawn_matches_scene(view):
    """The invariant. Raises with what diverged, so a failure names the
    object and the distance rather than just saying False.

    Measured against what the scene shows, not everything it holds. Hidden
    geometry used to be uploaded too, and asking for it back is asking for
    the 93%-wasted meshing that GitHub #5 hit. So "not drawn" is the right
    answer for a hidden object, and the check below insists on it.
    """
    view._sync_gpu()
    scene = view.scene
    shown = scene.visible_objects()
    live = {o.id for o in shown}

    held = set(view._gpu) | set(view._tess_pending)
    orphans = held - {o.id for o in scene.all()}
    assert not orphans, f"drawing {len(orphans)} object(s) the scene has lost"
    hidden = held & {o.id for o in scene.all() if o.id not in live}
    assert not hidden, (
        f"holding buffers for {len(hidden)} object(s) nothing will draw")

    for obj in shown:
        gpu = view._gpu.get(obj.id)
        if gpu is None:
            entry = view._tess_pending.get(obj.id)
            assert entry is not None, f"{obj.name} is neither drawn nor pending"
            assert entry[0] is obj.shape, (
                f"{obj.name} is standing in for geometry it no longer has")
            continue

        assert gpu.mesh_key == obj.mesh.uid, (
            f"{obj.name} is drawn from a mesh it no longer has")
        want = np.asarray(obj.mesh.vertices, float)
        assert gpu.vertices.shape == want.shape, (
            f"{obj.name}: {len(gpu.vertices)} vertices drawn, "
            f"{len(want)} in the scene")
        if len(want):
            drift = np.abs(gpu.vertices - want).max()
            assert drift < 1e-6, (
                f"{obj.name} is drawn {drift:.3g} away from where it is")


@pytest.fixture
def env(monkeypatch):
    """A viewport wired to record instead of upload, plus the machinery to
    run real commands against it."""
    monkeypatch.setattr(vp_mod, "_GpuObject", _Recorder)
    scene = Scene()
    sel = SelectionManager(scene)
    hist = History(scene)
    view = vp_mod.Viewport(scene, sel)
    proc = CommandProcessor(CommandContext(scene, sel, hist))
    return scene, sel, hist, view, proc


def test_the_check_notices_a_stale_drawing(env, monkeypatch):
    """The invariant has to be able to fail, or running it over the command
    set proves nothing. Put the old bug back — buffers remembered by the
    address of their mesh — and it must be caught."""
    scene, _sel, _hist, view, _proc = env
    obj = scene.add(g.make_box((0, 0, 0), 1, 1, 1))
    check_drawn_matches_scene(view)

    stale = view._gpu[obj.id]
    moved = scene.replace_shape(obj.id, g.translate(obj.shape, (10, 0, 0)))
    stale.mesh_key = moved.mesh.uid          # what a recycled address did

    with pytest.raises(AssertionError, match="drawn .* away from where it is"):
        check_drawn_matches_scene(view)


def test_the_check_notices_a_stale_placeholder(env, monkeypatch):
    """And the other half of it: the box drawn while something is still
    being meshed, left behind at the old shape.

    The old scheduling is put back rather than the bad state planted by
    hand, because `_sync_gpu` repairs a planted one on its way past — which
    is the fix doing its job, and would have made this prove nothing."""
    scene, _sel, _hist, view, _proc = env
    monkeypatch.setattr(type(view), "ASYNC_FACE_COUNT", 1)
    monkeypatch.setattr(view, "_worker_pool", lambda: _NoPool())
    real = view._schedule_tess
    monkeypatch.setattr(view, "_schedule_tess",
                        lambda obj: True if obj.id in view._tess_pending
                        else real(obj))          # pending per object, as was

    obj = scene.add(g.make_box((0, 0, 0), 1, 1, 1))
    check_drawn_matches_scene(view)
    scene.replace_shape(obj.id, g.translate(obj.shape, (10, 0, 0)))

    with pytest.raises(AssertionError, match="no longer has"):
        check_drawn_matches_scene(view)


class _NoPool:
    """Accepts work and never runs it, so the pending state stays visible."""

    def submit(self, fn):
        pass


# --- the editing commands, run against the invariant --------------------

SCENARIOS = {}


def scenario(fn):
    """One editing session, written the way the command expects to be
    driven. What it leaves behind does not matter — the check is not on the
    result but on whether the drawing kept up with it."""
    SCENARIOS[fn.__name__] = fn
    return fn


def _box(scene, at=(0, 0, 0), size=10.0):
    return scene.add(g.make_box(at, size, size, size))


def _pick(proc, *objs):
    for o in objs:
        proc.click_object(o.id)
    proc.finish_selection()


@scenario
def move(scene, proc):
    o = _box(scene)
    proc.run("move")
    _pick(proc, o)
    proc.provide_text("0,0,0")
    proc.provide_text("50,30,0")


@scenario
def copy(scene, proc):
    o = _box(scene)
    proc.run("copy")
    _pick(proc, o)
    proc.provide_text("0,0,0")
    proc.provide_text("40,0,0")
    proc.provide_text("")


@scenario
def rotate(scene, proc):
    o = _box(scene, at=(5, 0, 0))
    proc.run("rotate")
    _pick(proc, o)
    proc.provide_text("0,0,0")
    proc.provide_text("90")


@scenario
def rotate3d(scene, proc):
    o = _box(scene, at=(5, 0, 0))
    proc.run("rotate3d")
    _pick(proc, o)
    proc.provide_text("0,0,0")
    proc.provide_text("0,0,10")
    proc.provide_text("45")


@scenario
def scale(scene, proc):
    o = _box(scene)
    proc.run("scale")
    _pick(proc, o)
    proc.provide_text("0,0,0")
    proc.provide_text("3")


@scenario
def scalenu(scene, proc):
    o = _box(scene)
    proc.run("scalenu")
    _pick(proc, o)
    proc.provide_text("0,0,0")
    proc.provide_text("2")
    proc.provide_text("3")
    proc.provide_text("0.5")


@scenario
def mirror(scene, proc):
    o = _box(scene, at=(5, 0, 0))
    proc.run("mirror")
    _pick(proc, o)
    proc.provide_text("0,0,0")
    proc.provide_text("0,10,0")
    proc.provide_text("")


@scenario
def array(scene, proc):
    o = _box(scene, size=2.0)
    proc.run("array")
    _pick(proc, o)
    proc.provide_text("3")
    proc.provide_text("2")
    proc.provide_text("1")
    proc.provide_text("5")
    proc.provide_text("5")
    proc.provide_text("5")


@scenario
def arraypolar(scene, proc):
    o = _box(scene, at=(20, 0, 0), size=2.0)
    proc.run("arraypolar")
    _pick(proc, o)
    proc.provide_text("0,0,0")
    proc.provide_text("6")
    proc.provide_text("360")


@scenario
def setpt(scene, proc):
    # A curve, not a solid: setpt works on control points, and handing it a
    # box means it does nothing at all and the scenario checks nothing.
    c = scene.add(g.make_control_curve([(0, 0, 3), (5, 8, 7),
                                        (12, -3, 2), (18, 4, 9)]))
    proc.run("setpt")
    _pick(proc, c)
    proc.provide_text("0,0,0")


@scenario
def projecttocplane(scene, proc):
    c = scene.add(g.make_control_curve([(0, 0, 3), (5, 8, 7),
                                        (12, -3, 2), (18, 4, 9)]))
    proc.run("projecttocplane")
    _pick(proc, c)


@scenario
def booleanunion(scene, proc):
    a = _box(scene)
    b = _box(scene, at=(5, 5, 5))
    proc.run("booleanunion")
    _pick(proc, a, b)


@scenario
def booleandifference(scene, proc):
    a = _box(scene)
    _box(scene, at=(5, 5, 5))
    proc.run("booleandifference")
    _pick(proc, a)
    _pick(proc, scene.all()[1])


@scenario
def booleanintersection(scene, proc):
    a = _box(scene)
    b = _box(scene, at=(5, 5, 5))
    proc.run("booleanintersection")
    _pick(proc, a)
    _pick(proc, b)


@scenario
def fillet_edges(scene, proc):
    o = _box(scene)
    proc.run("filletedge")
    _pick(proc, o)
    proc.provide_text("1")


@scenario
def chamfer_edges(scene, proc):
    o = _box(scene)
    proc.run("chamferedge")
    _pick(proc, o)
    proc.provide_text("1")


@scenario
def shell(scene, proc):
    o = _box(scene)
    proc.run("shell")
    _pick(proc, o)
    proc.provide_text("1")


@scenario
def explode(scene, proc):
    o = _box(scene)
    proc.run("explode")
    _pick(proc, o)


@scenario
def delete(scene, proc):
    a = _box(scene)
    _box(scene, at=(40, 0, 0))
    proc.run("delete")
    _pick(proc, a)


@scenario
def extrude_a_curve(scene, proc):
    c = scene.add(g.make_circle((0, 0, 0), 5))
    proc.run("extrude")
    _pick(proc, c)
    proc.provide_text("10")


@scenario
def revolve_a_curve(scene, proc):
    c = scene.add(g.make_line((5, 0, 0), (5, 0, 10)))
    proc.run("revolve")
    _pick(proc, c)
    proc.provide_text("0,0,0")
    proc.provide_text("0,0,10")
    proc.provide_text("360")


@scenario
def offset_a_curve(scene, proc):
    c = scene.add(g.make_circle((0, 0, 0), 5))
    proc.run("offset")
    _pick(proc, c)
    proc.provide_text("1")


@scenario
def rebuild_a_curve(scene, proc):
    c = scene.add(g.make_control_curve([(0, 0, 0), (5, 8, 0),
                                        (12, -3, 0), (18, 4, 0)]))
    proc.run("rebuild")
    _pick(proc, c)
    proc.provide_text("8")
    proc.provide_text("3")


@scenario
def join_curves(scene, proc):
    a = scene.add(g.make_line((0, 0, 0), (10, 0, 0)))
    b = scene.add(g.make_line((10, 0, 0), (10, 10, 0)))
    proc.run("join")
    _pick(proc, a, b)


@scenario
def loft_curves(scene, proc):
    a = scene.add(g.make_circle((0, 0, 0), 5))
    b = scene.add(g.make_circle((0, 0, 10), 8))
    proc.run("loft")
    _pick(proc, a, b)


@scenario
def planar_surface(scene, proc):
    c = scene.add(g.make_circle((0, 0, 0), 5))
    proc.run("planarsrf")
    _pick(proc, c)


@scenario
def change_layer(scene, proc):
    o = _box(scene)
    scene.layers.create("Second")
    proc.run("changelayer")
    _pick(proc, o)
    proc.provide_text("Second")


def _drive(scene, proc, name):
    """Run one scenario, refusing to let a broken script pass quietly. A
    command handed geometry it does not accept finishes without complaint
    and edits nothing, and a check over nothing always succeeds."""
    before = scene.revision
    SCENARIOS[name](scene, proc)
    assert not proc.busy, f"{name} left the command waiting"
    assert scene.revision != before, (
        f"{name} changed nothing, so it checked nothing — fix the scenario")
    assert scene.all(), f"{name} left nothing to check"


@scenario
def twist(scene, proc):
    o = _box(scene)
    proc.run("twist")
    _pick(proc, o)
    proc.provide_text("0,0,0")
    proc.provide_text("0,0,10")
    proc.provide_text("90")


@scenario
def bend(scene, proc):
    o = _box(scene)
    proc.run("bend")
    _pick(proc, o)
    proc.provide_text("0,0,0")
    proc.provide_text("0,0,10")
    proc.provide_text("45")


@scenario
def taper(scene, proc):
    o = _box(scene)
    proc.run("taper")
    _pick(proc, o)
    proc.provide_text("0,0,0")
    proc.provide_text("0,0,10")
    proc.provide_text("0.5")


@scenario
def smooth_a_curve(scene, proc):
    c = scene.add(g.make_polyline([(0, 0, 0), (5, 6, 0), (10, -4, 0),
                                   (15, 5, 0), (20, 0, 0)]))
    proc.run("smooth")
    _pick(proc, c)
    proc.provide_text("0.4")


@scenario
def divide_a_curve(scene, proc):
    c = scene.add(g.make_circle((0, 0, 0), 8))
    proc.run("divide")
    _pick(proc, c)
    proc.provide_text("6")


@scenario
def split_a_curve(scene, proc):
    line = scene.add(g.make_line((0, 0, 0), (20, 0, 0)))
    cutter = scene.add(g.make_line((10, -5, 0), (10, 5, 0)))
    proc.run("split")
    _pick(proc, line, cutter)


@scenario
def trim_a_curve(scene, proc):
    line = scene.add(g.make_line((0, 0, 0), (20, 0, 0)))
    cutter = scene.add(g.make_line((10, -5, 0), (10, 5, 0)))
    proc.run("trim")
    _pick(proc, cutter)
    _pick(proc, line)


@scenario
def pipe_a_curve(scene, proc):
    c = scene.add(g.make_line((0, 0, 0), (0, 0, 10)))
    proc.run("pipe")
    _pick(proc, c)
    proc.provide_text("1")


@scenario
def cap_an_open_surface(scene, proc):
    c = scene.add(g.make_circle((0, 0, 0), 5))
    proc.run("extrude")
    _pick(proc, c)
    proc.provide_text("10")
    proc.run("cap")
    _pick(proc, scene.all()[0])


@scenario
def hide_and_show(scene, proc):
    a = _box(scene)
    _box(scene, at=(40, 0, 0))
    proc.run("hide")
    _pick(proc, a)


@scenario
def group_objects(scene, proc):
    a = _box(scene)
    b = _box(scene, at=(40, 0, 0))
    proc.run("group")
    _pick(proc, a, b)


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_the_drawing_follows_the_edit(env, name):
    """Every scene change is checked as it happens: the viewport listens,
    so the invariant is run wherever a redraw would be."""
    scene, _sel, _hist, view, proc = env
    scene.add_listener(lambda *_: check_drawn_matches_scene(view))
    _drive(scene, proc, name)
    check_drawn_matches_scene(view)


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_the_drawing_follows_an_undo(env, name):
    """Undo puts geometry back that the viewport has already drawn once and
    has since thrown away — the same trap from the other direction."""
    scene, _sel, hist, view, proc = env
    _drive(scene, proc, name)
    check_drawn_matches_scene(view)

    scene.add_listener(lambda *_: check_drawn_matches_scene(view))
    assert hist.can_undo, f"{name} edited the scene but recorded no undo"
    proc.run("undo")
    check_drawn_matches_scene(view)
    proc.run("redo")
    check_drawn_matches_scene(view)


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_the_drawing_follows_the_edit_when_meshing_is_slow(env, name,
                                                           monkeypatch):
    """The same sweep with everything treated as heavy enough to mesh in
    the background. That path carries a second cache — the box drawn in the
    meantime — and an edit landing while the work is in flight is exactly
    where it went wrong before. The queue is held back so the scenarios
    genuinely edit things that are still being built, then drained."""
    scene, _sel, _hist, view, proc = env
    monkeypatch.setattr(type(view), "ASYNC_FACE_COUNT", 1)
    monkeypatch.setattr(type(view), "ASYNC_MESH_VERTICES", 1)
    pool = _HeldPool()
    monkeypatch.setattr(view, "_worker_pool", lambda: pool)
    scene.add_listener(lambda *_: check_drawn_matches_scene(view))

    _drive(scene, proc, name)
    check_drawn_matches_scene(view)
    pool.drain()
    check_drawn_matches_scene(view)


class _HeldPool:
    """Holds work until asked, so an edit can land on something that is
    still being meshed."""

    def __init__(self):
        self.queued = []

    def submit(self, fn):
        self.queued.append(fn)

    def drain(self):
        while self.queued:
            self.queued.pop(0)()
