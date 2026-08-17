"""Join two surfaces and you have one surface.

Serpentine's join was hard-gated to curves: pick two surfaces that share
an edge and the command would not even let you select them. The kernel has
sewn surfaces together in four other places for a while (cap_holes,
remove_faces, extend_surface, deform), so the capability was there, just
never wired to the command a Rhino user reaches for.

Rhino's Join on surfaces stitches coincident edges into one polysurface,
and a polysurface that ends up enclosing a volume becomes a solid. The
cases that pin the behaviour down: two faces meeting at an edge make an
open shell, the six faces of a box seal back into a solid, and surfaces
that touch nothing are left alone rather than swept into a meaningless
compound.
"""

from __future__ import annotations

import pytest

from serpentine3d.commands.base import CommandContext, CommandProcessor
from serpentine3d.core import geometry as g
from serpentine3d.core.history import History
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager


@pytest.fixture
def env():
    scene = Scene()
    sel = SelectionManager(scene)
    ctx = CommandContext(scene, sel, History(scene))
    return scene, sel, CommandProcessor(ctx)


def _rect(pts):
    """A planar face from a closed rectangle of corner points."""
    return g.planar_face(g.make_polyline([tuple(map(float, p)) for p in pts],
                                         closed=True))


def _floor():
    """A square in the XY plane, sharing its front edge with _wall()."""
    return _rect([(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)])


def _wall():
    """A square in the XZ plane, standing up on the floor's front edge."""
    return _rect([(0, 0, 0), (10, 0, 0), (10, 0, 10), (0, 0, 10)])


def _far():
    """A square nowhere near the other two."""
    return _rect([(100, 0, 0), (110, 0, 0), (110, 10, 0), (100, 10, 0)])


def _surfaces(scene):
    return [o for o in scene.all() if o.kind == "surface"]


def _solids(scene):
    return [o for o in scene.all() if o.kind == "solid"]


def _join(proc, objs):
    proc.run("join")
    for o in objs:
        proc.click_object(o.id)
    proc.finish_selection()


# -- the geometry helper --

def test_join_surfaces_sews_two_faces_into_one_shell():
    joined = g.join_surfaces([_floor(), _wall()])
    assert g.shape_kind(joined) == "surface"
    assert len(g.faces_of(joined)) == 2


def test_join_surfaces_seals_the_faces_of_a_box_into_a_solid():
    faces = g.faces_of(g.make_box((0.0, 0.0, 0.0), 10.0, 10.0, 10.0))
    joined = g.join_surfaces(faces)
    assert g.shape_kind(joined) == "solid"
    assert abs(g.volume(joined)) == pytest.approx(1000.0, rel=1e-6)


def test_join_surfaces_leaves_untouching_faces_as_separate_pieces():
    joined = g.join_surfaces([_floor(), _far()])
    assert len(g.joined_pieces(joined)) == 2


def test_joined_pieces_of_a_single_shell_is_one():
    assert len(g.joined_pieces(g.join_surfaces([_floor(), _wall()]))) == 1


# -- what the command leaves behind --

def test_joining_two_open_surfaces_makes_one_object(env):
    scene, _sel, proc = env
    a = scene.add(_floor(), name="Floor")
    scene.add(_wall(), name="Wall")
    _join(proc, _surfaces(scene) or [a])
    left = _surfaces(scene)
    assert len(left) == 1
    assert len(g.faces_of(left[0].shape)) == 2


def test_joining_the_faces_of_a_box_makes_a_solid(env):
    scene, _sel, proc = env
    for i, f in enumerate(g.faces_of(g.make_box((0.0, 0.0, 0.0),
                                                10.0, 10.0, 10.0))):
        scene.add(f, name=f"Face {i}")
    _join(proc, _surfaces(scene))
    assert len(_surfaces(scene)) == 0
    solids = _solids(scene)
    assert len(solids) == 1
    assert abs(g.volume(solids[0].shape)) == pytest.approx(1000.0, rel=1e-6)


def test_the_joined_object_keeps_the_first_ones_identity(env):
    scene, _sel, proc = env
    floor = scene.add(_floor(), name="Floor")
    fid, layer = floor.id, floor.layer_id
    scene.add(_wall(), name="Wall")
    _join(proc, _surfaces(scene))
    left = _surfaces(scene)
    assert len(left) == 1
    assert left[0].id == fid
    assert left[0].name == "Floor"
    assert left[0].layer_id == layer


def test_join_of_surfaces_that_share_no_edge_changes_nothing(env):
    scene, _sel, proc = env
    scene.add(_floor(), name="Floor")
    scene.add(_far(), name="Far")
    before = {o.id for o in _surfaces(scene)}
    _join(proc, _surfaces(scene))
    assert {o.id for o in _surfaces(scene)} == before


def test_both_joined_pieces_end_up_selected(env):
    scene, sel, proc = env
    for i, f in enumerate(g.faces_of(g.make_box((0.0, 0.0, 0.0),
                                                10.0, 10.0, 10.0))):
        scene.add(f, name=f"Face {i}")
    _join(proc, _surfaces(scene))
    assert sorted(sel.ids) == sorted(o.id for o in _solids(scene))


# -- curves must still join exactly as before --

def test_join_still_joins_curves(env):
    scene, _sel, proc = env
    a = scene.add(g.make_line((0.0, 0.0, 0.0), (10.0, 0.0, 0.0)), name="A")
    scene.add(g.make_line((10.0, 0.0, 0.0), (10.0, 10.0, 0.0)), name="B")
    _join(proc, [o for o in scene.all() if o.kind == "curve"] or [a])
    curves = [o for o in scene.all() if o.kind == "curve"]
    assert len(curves) == 1
    assert len(g.edges_of(curves[0].shape)) == 2
