"""A bare 0 places a position at the world origin; scalar prompts keep zero."""

import pytest

from serpentine3d.commands.base import (
    CommandContext, CommandProcessor, LengthReq, NumberReq, PointReq, parse_value,
)
from serpentine3d.core import geometry as g
from serpentine3d.core.cplane import CPlane
from serpentine3d.core.history import History
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager


ORIGIN = (0.0, 0.0, 0.0)
AWAY = (5.0, 6.0, 7.0)
DIRECTION = (0.0, 1.0, 0.0)


def _context(*, last_point=None, aim=None):
    scene = Scene()
    selection = SelectionManager(scene)
    ctx = CommandContext(scene, selection, History(scene))
    # A moved, turned plane and an earlier pick must not redefine world zero.
    ctx.replay_cplane = CPlane(origin=(40, -30, 25), normal=(0, 1, 0),
                              xdir=(0, 0, 1))
    ctx.last_point = last_point
    ctx.replay_aim = aim
    said = []
    ctx.add_echo_listener(said.append)
    return scene, selection, ctx, CommandProcessor(ctx), said


@pytest.mark.parametrize("last_point,aim", [
    (None, None),
    (AWAY, None),
    (AWAY, (AWAY, DIRECTION)),
])
def test_zero_is_an_absolute_position_before_and_after_another_pick(last_point,
                                                                  aim):
    _scene, _selection, ctx, _proc, _said = _context(last_point=last_point,
                                                   aim=aim)
    ok, position = parse_value(PointReq("Position"), "0", ctx)
    assert ok, position
    assert position == pytest.approx(ORIGIN)


def test_zero_is_an_absolute_position_even_with_a_direction_locked():
    _scene, _selection, ctx, _proc, _said = _context(last_point=AWAY)

    class LockedViewport:
        def locked_direction(self):
            return AWAY, DIRECTION

    ctx.viewport = LockedViewport()
    ok, position = parse_value(PointReq("End of line"), "0", ctx)
    assert ok, position
    assert position == pytest.approx(ORIGIN)


def _created_shape(command, answers):
    scene, _selection, ctx, proc, said = _context(last_point=AWAY)
    assert proc.run(command)
    proc.provide_text(answers[0])
    assert ctx.last_point == pytest.approx(ORIGIN), said
    for answer in answers[1:]:
        proc.provide_text(answer)
    assert not proc.busy, said
    assert len(scene.all()) == 1, said
    return scene.all()[0].shape


@pytest.mark.parametrize("command,rest", [
    ("line", ("10,20,30",)),
    ("circle", ("4",)),
    ("box", ("10,20,30", "4")),
])
def test_geometry_started_at_zero_matches_explicit_world_coordinates(command,
                                                                    rest):
    explicit = _created_shape(command, ("0,0,0", *rest))
    shorthand = _created_shape(command, ("0", *rest))
    for actual, expected in zip(g.bbox(shorthand), g.bbox(explicit)):
        assert actual == pytest.approx(expected, abs=1e-6)
    if command == "box":
        assert g.volume(shorthand) == pytest.approx(g.volume(explicit))
    else:
        assert g.curve_length(shorthand) == pytest.approx(g.curve_length(explicit))


@pytest.mark.parametrize("aim", [None, (AWAY, DIRECTION)])
def test_a_line_can_finish_at_zero_after_starting_away_from_the_origin(aim):
    scene, _selection, ctx, proc, said = _context(aim=aim)
    proc.run("line")
    proc.provide_text("5,6,7")
    proc.provide_text("0")
    assert not proc.busy, said
    assert len(scene.all()) == 1, said
    assert ctx.last_point == pytest.approx(ORIGIN)
    assert g.bbox(scene.all()[0].shape)[0] == pytest.approx(ORIGIN, abs=1e-6)
    assert g.curve_length(scene.all()[0].shape) == pytest.approx(sum(
        c * c for c in AWAY) ** 0.5)


def test_moving_to_zero_previews_and_commits_the_same_world_origin():
    scene, selection, _ctx, proc, said = _context(aim=(AWAY, DIRECTION))
    obj = scene.add(g.make_box(AWAY, 2, 3, 4))
    selection.set([obj.id])
    proc.run("move")
    proc.provide_text("5,6,7")
    explicit = proc.preview_shape("0,0,0")
    shorthand = proc.preview_shape("0")
    assert explicit is not None
    assert shorthand is not None, "typing 0 should preview the move to world zero"
    for actual, expected in zip(g.bbox(shorthand), g.bbox(explicit)):
        assert actual == pytest.approx(expected, abs=1e-6)
    assert g.bbox(shorthand)[0] == pytest.approx(ORIGIN, abs=1e-6)
    proc.provide_text("0")
    assert not proc.busy, said
    for actual, expected in zip(g.bbox(scene.get(obj.id).shape), g.bbox(shorthand)):
        assert actual == pytest.approx(expected, abs=1e-6)


@pytest.mark.parametrize("command,before_zero,after_zero,reason", [
    ("circle", ("5,6,7",), (), "radius"),
    ("circle", ("5,6,7", "Diameter"), (), "radius"),
    ("box", ("5,6,7",), (), "length"),
    ("box", ("5,6,7", "10"), (), "width"),
    ("box", ("5,6,7", "15,6,17"), (), "height"),
    ("scale", ("5,6,7",), (), "scale factor"),
    ("scalenu", ("5,6,7",), ("1", "1"), "scale factor"),
])
def test_zero_at_a_numeric_prompt_keeps_its_numeric_meaning_away_from_origin(
        command, before_zero, after_zero, reason):
    scene, selection, _ctx, proc, said = _context(aim=(AWAY, DIRECTION))
    original = None
    if command in ("scale", "scalenu"):
        original = scene.add(g.make_box(AWAY, 2, 3, 4))
        selection.set([original.id])
    proc.run(command)
    for answer in before_zero:
        proc.provide_text(answer)
    assert proc.busy, said
    proc.provide_text("0")
    for answer in after_zero:
        proc.provide_text(answer)
    assert not proc.busy, said
    assert any("zero" in line.lower() and reason in line.lower()
               for line in said), said
    if original is None:
        assert not scene.all(), "zero dimension should not make nonzero geometry"
    else:
        assert len(scene.all()) == 1
        lo, hi = g.bbox(scene.get(original.id).shape)
        assert lo == pytest.approx(AWAY, abs=1e-6)
        assert hi == pytest.approx((7, 9, 11), abs=1e-6)


@pytest.mark.parametrize("numeric_req", [
    LengthReq("Distance"),
    NumberReq("Scale factor"),
])
def test_a_numeric_request_still_returns_numeric_zero(numeric_req):
    _scene, _selection, ctx, _proc, _said = _context(
        last_point=AWAY, aim=(AWAY, DIRECTION))
    ok, value = parse_value(numeric_req, "0", ctx)
    assert ok, value
    assert isinstance(value, (int, float))
    assert value == 0


@pytest.mark.parametrize("text,expected", [
    ("3,4,5", (3, 4, 5)),
    ("0,0,0", ORIGIN),
    ("@1,2,3", (6, 8, 10)),
    ("12", (5, 18, 7)),
    ("2cm", (5, 26, 7)),
])
def test_full_relative_coordinates_and_nonzero_distances_keep_their_meaning(
        text, expected):
    _scene, _selection, ctx, _proc, _said = _context(
        last_point=AWAY, aim=(AWAY, DIRECTION))
    ok, value = parse_value(PointReq("End of line"), text, ctx)
    assert ok, value
    assert value == pytest.approx(expected)
