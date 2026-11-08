"""A shell with no face open keeps the solid's outside and is hollow
inside (#121).

Given no face to open, OpenCascade's thick solid hands back the solid moved
in by the wall: the inside of the shell, not the shell. So `box 0 10 10 10`
and a wall of 1 came back as a solid 8 mm box. With no face picked, a
shell is now the solid with that inside taken out of it.
"""

import math

import pytest

import serpentine3d.commands  # registers all commands  # noqa: F401
from serpentine3d.commands.base import CommandContext, CommandProcessor
from serpentine3d.core import geometry as g
from serpentine3d.core.history import History
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager


def _same_box(shape, lo, hi):
    got_lo, got_hi = g.bbox(shape)
    assert got_lo == pytest.approx(lo, abs=1e-6)
    assert got_hi == pytest.approx(hi, abs=1e-6)


def test_a_box_shelled_closed_keeps_its_outside():
    box = g.make_box((0, 0, 0), 10, 10, 10)
    shelled = g.shell_solid(box, 1)
    assert g.is_valid(shelled)
    _same_box(shelled, (0, 0, 0), (10, 10, 10))
    # 1000 of box less the 8 x 8 x 8 inside
    assert g.volume(shelled) == pytest.approx(488, rel=1e-6)
    assert len(g.faces_of(shelled)) == 12


def test_a_cylinder_shelled_closed_keeps_its_outside():
    cylinder = g.make_cylinder((0, 0, 0), 5, 10)
    shelled = g.shell_solid(cylinder, 1)
    _same_box(shelled, (-5, -5, 0), (5, 5, 10))
    assert g.volume(shelled) == pytest.approx(
        math.pi * (25 * 10 - 16 * 8), rel=1e-6)


def test_a_star_shelled_closed_keeps_its_points():
    pts = []
    for i in range(10):
        r = 10 if i % 2 == 0 else 4
        a = math.pi / 2 + i * math.pi / 5
        pts.append((r * math.cos(a), r * math.sin(a), 0))
    star = g.extrude(g.make_polyline(pts, closed=True), (0, 0, 1), 5,
                     cap=True)
    shelled = g.shell_solid(star, 0.5)
    lo, hi = g.bbox(star)
    _same_box(shelled, lo, hi)
    assert 0 < g.volume(shelled) < 0.5 * g.volume(star)


@pytest.fixture
def env():
    scene = Scene()
    selection = SelectionManager(scene)
    ctx = CommandContext(scene, selection, History(scene))
    return scene, ctx, CommandProcessor(ctx)


def test_the_reported_steps_keep_the_box_its_size(env):
    """Named at the prompt rather than clicked, the box has no face to
    open, so it is shelled closed: hollow, and still 10 mm across."""
    scene, _ctx, proc = env
    box = scene.add(g.make_box((0, 0, 0), 10, 10, 10))
    proc.run("shell")
    proc.provide_text(box.name)
    proc.finish_selection()
    proc.provide_text("1")
    assert not proc.busy
    shelled = scene.get(box.id).shape
    _same_box(shelled, (0, 0, 0), (10, 10, 10))
    assert g.volume(shelled) == pytest.approx(488, rel=1e-6)


def test_a_wall_too_thick_says_so_and_leaves_the_solid(env):
    scene, ctx, proc = env
    said = []
    ctx.echo = said.append
    box = scene.add(g.make_box((0, 0, 0), 10, 10, 10))
    proc.run("shell")
    proc.provide_text(box.name)
    proc.finish_selection()
    proc.provide_text("6")
    assert not proc.busy
    assert g.volume(scene.get(box.id).shape) == pytest.approx(1000)
    assert any("thick" in line.lower() for line in said), said
