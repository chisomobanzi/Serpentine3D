"""`curve` draws by control points, the way Rhino's Curve does.

Serpentine's `curve` used to interpolate through the picked points, which is
Rhino's `InterpCrv`. A Rhino user typing the command they use most got the
other tool and no sign that anything was wrong: both make a smooth curve
through roughly the right place, and only the control points give it away.
So the names now mean what they mean everywhere else, and the control point
curve, which the file importers could already build, is finally reachable by
hand.
"""

import pytest

import serpentine3d.commands  # registers all commands  # noqa: F401
from serpentine3d.commands.base import CommandContext, CommandProcessor, resolve
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


def _draw(proc, name, pts, finish=""):
    proc.run(name)
    for p in pts:
        proc.provide_text(p)
    if finish is not None:
        proc.provide_text(finish)


# --- the names -------------------------------------------------------------

def test_curve_is_the_control_point_one():
    assert resolve("curve").name == "curve"
    assert resolve("cv").name == "curve", (
        "cv means control vertex, so it belongs to the control point curve")


def test_interpcrv_is_its_own_command():
    assert resolve("interpcrv").name == "interpcrv"


def test_the_two_curve_commands_are_not_the_same_command():
    assert resolve("curve").name != resolve("interpcrv").name


# --- what each one builds --------------------------------------------------

PTS = ("0,0", "10,10", "20,-10", "30,0")
XYZ = [(0, 0, 0), (10, 10, 0), (20, -10, 0), (30, 0, 0)]


def test_curve_puts_its_control_points_where_you_picked(env):
    scene, _sel, _hist, _ctx, proc = env
    _draw(proc, "curve", PTS)
    assert not proc.busy
    poles = g.get_control_points(scene.all()[0].shape)
    assert len(poles) == len(XYZ)
    for got, want in zip(poles, XYZ):
        assert got == pytest.approx(want, abs=1e-9)


def test_a_control_point_curve_does_not_pass_through_its_middle_points(env):
    """The whole difference between the two commands. A degree 3 curve is
    pulled toward its interior poles, never onto them."""
    scene, _sel, _hist, _ctx, proc = env
    _draw(proc, "curve", PTS)
    shape = scene.all()[0].shape
    assert _distance_to_curve(shape, XYZ[1]) > 1.0, (
        "the curve went through an interior control point, so this is an "
        "interpolating curve wearing the other command's name")


def test_interpcrv_does_pass_through_every_point(env):
    scene, _sel, _hist, _ctx, proc = env
    _draw(proc, "interpcrv", PTS)
    assert not proc.busy
    shape = scene.all()[0].shape
    for want in XYZ:
        assert _distance_to_curve(shape, want) < 1e-6, (
            f"interpcrv missed {want}")


def test_both_ends_are_still_the_points_you_picked(env):
    """A control point curve is clamped, so the first and last poles are on
    the curve even though the middle ones are not."""
    scene, _sel, _hist, _ctx, proc = env
    _draw(proc, "curve", PTS)
    shape = scene.all()[0].shape
    assert _distance_to_curve(shape, XYZ[0]) < 1e-6
    assert _distance_to_curve(shape, XYZ[-1]) < 1e-6


# --- degree ----------------------------------------------------------------

def test_degree_can_be_chosen(env):
    scene, _sel, _hist, _ctx, proc = env
    proc.run("curve")
    proc.provide_text("degree")
    proc.provide_text("2")
    for p in PTS:
        proc.provide_text(p)
    proc.provide_text("")
    assert not proc.busy
    assert g.curve_degree(scene.all()[0].shape) == 2


def test_degree_defaults_to_three(env):
    scene, _sel, _hist, _ctx, proc = env
    _draw(proc, "curve", PTS)
    assert g.curve_degree(scene.all()[0].shape) == 3


def test_too_few_points_for_the_degree_still_draws(env):
    """Two points at degree 3 is a straight line, not an error. Rhino drops
    the degree to fit rather than refusing the curve."""
    scene, _sel, _hist, _ctx, proc = env
    _draw(proc, "curve", ("0,0", "10,0"))
    assert not proc.busy
    assert len(scene.all()) == 1
    assert g.curve_degree(scene.all()[0].shape) == 1


# --- closing ---------------------------------------------------------------

def test_a_control_point_curve_closes_on_its_first_point(env):
    scene, _sel, _hist, _ctx, proc = env
    proc.run("curve")
    for p in ("0,0", "10,0", "10,10"):
        proc.provide_text(p)
    proc.provide_text("0,0")
    assert not proc.busy
    assert g.is_closed_curve(scene.all()[0].shape)


def test_a_control_point_curve_closes_on_the_keyword(env):
    scene, _sel, _hist, _ctx, proc = env
    proc.run("curve")
    for p in ("0,0", "10,0", "10,10"):
        proc.provide_text(p)
    proc.provide_text("close")
    assert not proc.busy
    assert g.is_closed_curve(scene.all()[0].shape)


# --- helper ----------------------------------------------------------------

def _distance_to_curve(shape, point) -> float:
    """Shortest distance from a point to the curve, in model units."""
    return g.distance_point_to_shape(shape, point)
