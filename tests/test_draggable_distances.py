"""Distances you can drag, and that show you what you are about to make.

tests/test_command_interaction.py is the structural rule — no command may ask
for a distance in the model with a keyboard-only request. These are the
behavioural half: that the drag resolves to the right size, that the ghost is
the shape you are actually going to get, and that typing the number still
works for anyone who has the figure already.
"""

import math

import pytest

import serpentine3d.commands  # registers all commands  # noqa: F401
from serpentine3d.commands.base import CommandContext, CommandProcessor
from serpentine3d.core import geometry as g
from serpentine3d.core.history import History
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager


@pytest.fixture
def env():
    scene = Scene()
    selection = SelectionManager(scene)
    history = History(scene)
    ctx = CommandContext(scene, selection, history)
    return scene, selection, history, ctx, CommandProcessor(ctx)


def _torus_volume(major, minor):
    return 2 * math.pi ** 2 * major * minor ** 2


# -- torus: the one that was reported --

def test_torus_major_radius_can_be_dragged(env):
    scene, _sel, _hist, _ctx, proc = env
    proc.run("torus")
    proc.provide_text("0,0,0")
    ghost = proc.preview_for((10, 0, 0))
    assert ghost is not None, "no ghost while dragging the major radius"
    assert g.shape_kind(ghost) == "curve", (
        "the major radius alone does not describe a solid yet — show the "
        "circle it sweeps")


def test_torus_minor_radius_ghosts_the_solid(env):
    scene, _sel, _hist, _ctx, proc = env
    proc.run("torus")
    proc.provide_text("0,0,0")
    proc.provide_text("10")
    ghost = proc.preview_for((12, 0, 0))
    assert ghost is not None, "no ghost while dragging the tube radius"
    assert g.shape_kind(ghost) == "solid"
    assert g.volume(ghost) == pytest.approx(_torus_volume(10, 2), rel=1e-3)


def test_torus_still_takes_typed_numbers(env):
    scene, _sel, _hist, _ctx, proc = env
    proc.run("torus")
    proc.provide_text("0,0,0")
    proc.provide_text("10")
    proc.provide_text("2")
    assert not proc.busy
    assert g.volume(scene.all()[0].shape) == pytest.approx(
        _torus_volume(10, 2), rel=1e-3)


def test_torus_dragged_end_to_end(env):
    scene, _sel, _hist, _ctx, proc = env
    proc.run("torus")
    proc.provide_text("0,0,0")
    proc.provide((10.0, 0.0, 0.0))
    proc.provide((12.0, 0.0, 0.0))
    assert not proc.busy
    assert g.volume(scene.all()[0].shape) == pytest.approx(
        _torus_volume(10, 2), rel=1e-3)


def test_a_torus_with_no_tube_is_not_created(env):
    scene, _sel, _hist, _ctx, proc = env
    proc.run("torus")
    proc.provide_text("0,0,0")
    proc.provide_text("10")
    assert proc.preview_for((10, 0, 0)) is None
    proc.provide((10.0, 0.0, 0.0))
    assert scene.all() == []


# -- ellipse --

def test_ellipse_radii_can_be_dragged(env):
    scene, _sel, _hist, _ctx, proc = env
    proc.run("ellipse")
    proc.provide_text("0,0,0")
    assert proc.preview_for((10, 0, 0)) is not None
    proc.provide((10.0, 0.0, 0.0))
    ghost = proc.preview_for((0, 4, 0))
    assert ghost is not None and g.shape_kind(ghost) == "curve"
    proc.provide((0.0, 4.0, 0.0))
    assert not proc.busy and len(scene.all()) == 1


def test_ellipse_still_takes_typed_numbers(env):
    scene, _sel, _hist, _ctx, proc = env
    proc.run("ellipse")
    proc.provide_text("0,0,0")
    proc.provide_text("10")
    proc.provide_text("4")
    assert not proc.busy
    lo, hi = g.bbox(scene.all()[0].shape)
    assert hi[0] - lo[0] == pytest.approx(20, rel=1e-3)
    assert hi[1] - lo[1] == pytest.approx(8, rel=1e-3)


# -- helix --

def test_helix_radius_can_be_dragged(env):
    """Nothing describes a helix until the pitch is in as well, so the first
    drag shows the circle the helix will wind around."""
    scene, _sel, _hist, _ctx, proc = env
    proc.run("helix")
    proc.provide_text("0,0,0")
    ghost = proc.preview_for((5, 0, 0))
    assert ghost is not None, "no ghost while dragging the helix radius"
    assert g.shape_kind(ghost) == "curve"


def test_helix_pitch_can_be_dragged_up_the_axis(env):
    scene, _sel, _hist, _ctx, proc = env
    proc.run("helix")
    proc.provide_text("0,0,0")
    proc.provide((5.0, 0.0, 0.0))
    assert proc.request.axis_lock is not None, (
        "pitch is a rise along the helix axis — lock the drag to it")
    ghost = proc.preview_for((0, 0, 4))
    assert ghost is not None, "no ghost while dragging the pitch"


def test_helix_still_takes_typed_numbers(env):
    scene, _sel, _hist, _ctx, proc = env
    proc.run("helix")
    proc.provide_text("0,0,0")
    proc.provide_text("5")
    proc.provide_text("4")
    proc.provide_text("3")
    assert not proc.busy
    lo, hi = g.bbox(scene.all()[0].shape)
    assert hi[2] - lo[2] == pytest.approx(12, rel=1e-2)   # 3 turns x pitch 4
    # radius 5, so 10 across — a helix is a B-spline and its bounding box
    # follows the control poles, which stand a little outside the curve
    assert 10 <= hi[0] - lo[0] < 11.5


# -- editing commands: the distance comes off the geometry, not off a click --

def _box(scene, sel=None, corner=(0, 0, 0), size=10):
    obj = scene.add(g.make_box(corner, size, size, size))
    if sel is not None:
        sel.set([obj.id])
    return obj


def test_pushpull_drags_along_the_face_it_is_moving(env):
    scene, sel, _hist, _ctx, proc = env
    obj = _box(scene)
    top = max(range(len(g.faces_of(obj.shape))),
              key=lambda i: g.face_point_normal(g.faces_of(obj.shape)[i])[0][2])
    sel.subobjects = [(obj.id, "face", top)]
    proc.run("pushpull")
    assert proc.request.axis_lock is not None, (
        "push/pull moves a face along its own normal — lock the drag to it")
    ghost = proc.preview_for((5, 5, 14))
    assert ghost is not None, "no ghost while dragging the face"
    assert g.volume(ghost) == pytest.approx(1000 + 4 * 100, rel=1e-3)


def test_pushpull_inward_is_a_negative_drag(env):
    scene, sel, _hist, _ctx, proc = env
    obj = _box(scene)
    faces = g.faces_of(obj.shape)
    top = max(range(len(faces)),
              key=lambda i: g.face_point_normal(faces[i])[0][2])
    sel.subobjects = [(obj.id, "face", top)]
    proc.run("pushpull")
    proc.provide((5.0, 5.0, 7.0))
    assert not proc.busy
    assert g.volume(scene.get(obj.id).shape) == pytest.approx(700, rel=1e-3)


def test_pushpull_still_takes_typed_numbers(env):
    scene, sel, _hist, _ctx, proc = env
    obj = _box(scene)
    faces = g.faces_of(obj.shape)
    top = max(range(len(faces)),
              key=lambda i: g.face_point_normal(faces[i])[0][2])
    sel.subobjects = [(obj.id, "face", top)]
    proc.run("pushpull")
    proc.provide_text("4")
    assert not proc.busy
    assert g.volume(scene.get(obj.id).shape) == pytest.approx(1400, rel=1e-3)


def _outward_from(proc, radius):
    """Where the offset drag starts, and the way out of the circle from it."""
    base, _dir = proc.request.number_from
    return base, tuple(c / radius for c in base)


def test_offset_grows_when_you_drag_away_from_the_curve(env):
    """OCC picks its own sign for an offset. What matters is that the curve
    ends up under the cursor, whichever side that is."""
    scene, sel, _hist, _ctx, proc = env
    circ = scene.add(g.make_circle((0, 0, 0), 5))
    sel.set([circ.id])
    proc.run("offset")
    assert proc.request.number_from is not None, (
        "an offset distance should be draggable off the curve")
    base, out = _outward_from(proc, 5)
    ghost = proc.preview_for(tuple(b + 3 * o for b, o in zip(base, out)))
    assert ghost is not None, "no ghost while dragging the offset"
    lo, hi = g.bbox(ghost)
    assert hi[0] - lo[0] == pytest.approx(16, rel=1e-3)


def test_offset_shrinks_when_you_drag_into_the_curve(env):
    scene, sel, _hist, _ctx, proc = env
    circ = scene.add(g.make_circle((0, 0, 0), 5))
    sel.set([circ.id])
    proc.run("offset")
    base, out = _outward_from(proc, 5)
    proc.provide(tuple(b - 2 * o for b, o in zip(base, out)))
    assert not proc.busy
    made = [o for o in scene.all() if o.id != circ.id]
    lo, hi = g.bbox(made[0].shape)
    assert hi[0] - lo[0] == pytest.approx(6, rel=1e-3)


def test_offset_still_takes_typed_numbers(env):
    scene, sel, _hist, _ctx, proc = env
    circ = scene.add(g.make_circle((0, 0, 0), 5))
    sel.set([circ.id])
    proc.run("offset")
    proc.provide_text("2")
    assert not proc.busy
    made = [o for o in scene.all() if o.id != circ.id]
    assert len(made) == 1


def test_shell_thickness_is_dragged_off_the_wall(env):
    """A 1 mm wall on a 10 mm box should be a 1 mm drag, so the drag starts
    at the surface being thickened, not at the middle of the solid."""
    scene, sel, _hist, _ctx, proc = env
    _box(scene, sel)
    proc.run("shell")
    assert proc.request.number_from is not None
    base, _dir = proc.request.number_from
    assert math.dist(base, (10, 5, 5)) < 1e-6
    ghost = proc.preview_for((11, 5, 5))
    assert ghost is not None, "no ghost while dragging the wall thickness"
    assert g.volume(ghost) < 1000


def test_shell_still_takes_typed_numbers(env):
    scene, sel, _hist, _ctx, proc = env
    obj = _box(scene, sel)
    proc.run("shell")
    proc.provide_text("1")
    assert not proc.busy
    assert g.volume(scene.get(obj.id).shape) == pytest.approx(
        1000 - 8 ** 3, rel=0.05)


def test_fillet_asks_for_the_corner_before_the_radius(env):
    """You cannot show a fillet until you know which corner it is on, so the
    corner is picked first and the radius is then dragged out of it."""
    scene, sel, _hist, _ctx, proc = env
    a = scene.add(g.make_line((0, 0, 0), (10, 0, 0)))
    b = scene.add(g.make_line((10, 0, 0), (10, 10, 0)))
    proc.run("fillet")
    proc.click_object(a.id)          # max_count=1 advances on the click
    proc.click_object(b.id)
    assert "corner" in proc.request.prompt.lower()
    proc.provide((10.0, 0.0, 0.0))
    assert proc.request.number_from is not None, (
        "the fillet radius should be draggable out of the corner")
    assert proc.preview_for((8, 0, 0)) is not None, (
        "no ghost while dragging the fillet radius")
    proc.provide((8.0, 0.0, 0.0))
    assert not proc.busy


def test_filletedge_radius_is_dragged_off_the_solid(env):
    scene, sel, _hist, _ctx, proc = env
    _box(scene, sel)
    proc.run("filletedge")
    assert proc.request.number_from is not None
    base, _dir = proc.request.number_from
    assert math.dist(base, (10, 5, 5)) < 1e-6, (
        "a 1 mm fillet on a 10 mm box should be a 1 mm drag")
    ghost = proc.preview_for((11, 5, 5))
    assert ghost is not None, "no ghost while dragging the fillet radius"
    assert g.volume(ghost) < 1000, "a fillet takes material off a box corner"


def test_filletedge_still_takes_typed_numbers(env):
    scene, sel, _hist, _ctx, proc = env
    obj = _box(scene, sel)
    proc.run("filletedge")
    proc.provide_text("1")
    assert not proc.busy
    assert g.volume(scene.get(obj.id).shape) < 1000


def test_chamferedge_distance_is_dragged_off_the_solid(env):
    scene, sel, _hist, _ctx, proc = env
    _box(scene, sel)
    proc.run("chamferedge")
    assert proc.request.number_from is not None
    ghost = proc.preview_for((11, 5, 5))
    assert ghost is not None, "no ghost while dragging the chamfer distance"
    assert g.volume(ghost) < 1000


def test_chamferedge_on_picked_edges_is_dragged_too(env):
    scene, sel, _hist, _ctx, proc = env
    obj = _box(scene)
    sel.subobjects = [(obj.id, "edge", 0)]
    proc.run("chamferedge")
    assert proc.request.number_from is not None, (
        "picking edges first should not cost you the drag")
    assert proc.preview_for((11, 5, 5)) is not None


def test_contour_spacing_is_dragged_along_the_contour_axis(env):
    scene, sel, _hist, _ctx, proc = env
    _box(scene, sel)
    proc.run("contour")
    proc.provide_text("Z")
    assert proc.request.number_from is not None
    assert proc.request.axis_lock is not None, (
        "contour spacing is a rise up the contour axis — lock the drag to it")
    ghost = proc.preview_for((5, 5, 2.5))
    assert ghost is not None, "no ghost while dragging the contour spacing"


def test_contour_still_takes_typed_numbers(env):
    scene, sel, _hist, _ctx, proc = env
    _box(scene, sel)
    proc.run("contour")
    proc.provide_text("Z")
    proc.provide_text("2")
    assert not proc.busy
    made = [o for o in scene.all() if o.kind == "curve"]
    assert len(made) >= 4


def test_offsetsrf_is_dragged_along_the_surface_normal(env):
    scene, sel, _hist, _ctx, proc = env
    face = scene.add(g.planar_face(g.make_rectangle((0, 0, 0), (10, 10, 0))))
    sel.set([face.id])
    proc.run("offsetsrf")
    assert proc.request.number_from is not None
    ghost = proc.preview_for((5, 5, 3))
    assert ghost is not None, "no ghost while dragging the surface offset"
    lo, hi = g.bbox(ghost)
    assert lo[2] == pytest.approx(3, abs=1e-6)


def test_offsetsrf_still_takes_typed_numbers(env):
    scene, sel, _hist, _ctx, proc = env
    face = scene.add(g.planar_face(g.make_rectangle((0, 0, 0), (10, 10, 0))))
    sel.set([face.id])
    proc.run("offsetsrf")
    proc.provide_text("2")
    assert not proc.busy
    assert len([o for o in scene.all() if o.id != face.id]) == 1


def test_pipe_radius_is_dragged_off_the_rail(env):
    scene, sel, _hist, _ctx, proc = env
    rail = scene.add(g.make_line((0, 0, 0), (0, 0, 10)))
    sel.set([rail.id])
    proc.run("pipe")
    assert proc.request.number_from is not None
    base, _dir = proc.request.number_from
    assert math.dist(base, (0, 0, 5)) < 1e-6, (
        "a pipe radius is measured out from the rail it wraps")
    ghost = proc.preview_for((2, 0, 5))
    assert ghost is not None, "no ghost while dragging the pipe radius"
    lo, hi = g.bbox(ghost)
    assert hi[0] - lo[0] == pytest.approx(4, rel=1e-2)


def test_pipe_still_takes_typed_numbers(env):
    scene, sel, _hist, _ctx, proc = env
    rail = scene.add(g.make_line((0, 0, 0), (0, 0, 10)))
    sel.set([rail.id])
    proc.run("pipe")
    proc.provide_text("1")
    proc.provide_text("")
    assert not proc.busy or len(scene.all()) == 2


def test_extend_is_dragged_out_of_the_end_it_extends(env):
    """The drag starts at the end you chose and runs the way the curve was
    already heading, so the cursor sits on the new end of the curve."""
    scene, sel, _hist, _ctx, proc = env
    line = scene.add(g.make_line((0, 0, 0), (10, 0, 0)))
    sel.set([line.id])
    proc.run("extend")
    proc.provide_text("End")
    assert proc.request.number_from is not None
    base, direction = proc.request.number_from
    assert math.dist(base, (10, 0, 0)) < 1e-6
    assert direction == pytest.approx((1, 0, 0), abs=1e-6)
    ghost = proc.preview_for((13, 0, 0))
    assert ghost is not None, "no ghost while dragging the extension"
    lo, hi = g.bbox(ghost)
    assert hi[0] == pytest.approx(13, abs=1e-3)


def test_extend_from_the_start_runs_the_other_way(env):
    scene, sel, _hist, _ctx, proc = env
    line = scene.add(g.make_line((0, 0, 0), (10, 0, 0)))
    sel.set([line.id])
    proc.run("extend")
    proc.provide_text("Start")
    base, direction = proc.request.number_from
    assert math.dist(base, (0, 0, 0)) < 1e-6
    assert direction == pytest.approx((-1, 0, 0), abs=1e-6)


def test_extend_still_takes_typed_numbers(env):
    scene, sel, _hist, _ctx, proc = env
    line = scene.add(g.make_line((0, 0, 0), (10, 0, 0)))
    sel.set([line.id])
    proc.run("extend")
    proc.provide_text("End")
    proc.provide_text("3")
    assert not proc.busy
    lo, hi = g.bbox(scene.get(line.id).shape)
    assert hi[0] == pytest.approx(13, abs=1e-3)


def test_textobject_asks_where_before_how_big(env):
    """Text height is a size in the model, so it is dragged — but there is
    nothing to drag it from until the text has somewhere to sit."""
    scene, sel, _hist, _ctx, proc = env
    proc.run("textobject")
    proc.provide_text("Hi")
    assert "position" in proc.request.prompt.lower()
    proc.provide((0.0, 0.0, 0.0))
    assert proc.request.number_from is not None
    ghost = proc.preview_for((0, 20, 0))
    assert ghost is not None, "no ghost while dragging the text height"
    lo, hi = g.bbox(ghost)
    assert hi[1] - lo[1] == pytest.approx(20, rel=0.35), (
        "the ghost should be as tall as the drag")


def test_textobject_still_takes_typed_numbers(env):
    scene, sel, _hist, _ctx, proc = env
    proc.run("textobject")
    proc.provide_text("Hi")
    proc.provide_text("0,0,0")
    proc.provide_text("10")
    assert not proc.busy
    assert scene.all()


def test_array_spacing_puts_the_next_copy_under_the_cursor(env):
    scene, sel, _hist, _ctx, proc = env
    _box(scene, sel, size=2)
    proc.run("array")
    proc.provide_text("2")           # count X
    proc.provide_text("1")           # count Y
    assert proc.request.number_from is not None
    base, _dir = proc.request.number_from
    assert math.dist(base, (1, 1, 1)) < 1e-6, (
        "spacing is centre to centre, so the drag starts at the centre")
    ghost = proc.preview_for((9, 1, 1))
    assert ghost is not None, "no ghost while dragging the array spacing"
    lo, hi = g.bbox(ghost)
    assert (lo[0] + hi[0]) / 2 == pytest.approx(9, abs=1e-6), (
        "the copy should be centred under the cursor")


def test_array_spacing_y_is_dragged_too(env):
    scene, sel, _hist, _ctx, proc = env
    _box(scene, sel, size=2)
    proc.run("array")
    proc.provide_text("1")
    proc.provide_text("2")
    proc.provide_text("5")           # spacing X (unused, count X is 1)
    assert proc.request.number_from is not None
    assert proc.preview_for((1, 9, 1)) is not None


def test_array_still_takes_typed_numbers(env):
    scene, sel, _hist, _ctx, proc = env
    obj = _box(scene, sel, size=2)
    proc.run("array")
    proc.provide_text("2")
    proc.provide_text("1")
    proc.provide_text("8")
    assert not proc.busy
    made = [o for o in scene.all() if o.id != obj.id]
    assert len(made) == 1
    lo, _hi = g.bbox(made[0].shape)
    assert lo[0] == pytest.approx(8, abs=1e-6)
