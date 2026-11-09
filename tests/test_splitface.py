"""`splitface`: divide a face and leave the object in one piece.

`split` takes a solid apart. This is for wanting part of a face to work on,
so the solid has to come back as the same solid with more faces: same object,
same volume, still closed, and with its neighbours' edges broken to match.
"""

import pytest
from OCP.BRepCheck import BRepCheck_Analyzer

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
    said = []
    ctx.add_echo_listener(said.append)
    return scene, selection, history, CommandProcessor(ctx), said


def _facing(shape, axis, sign):
    return next(i for i, f in enumerate(g.faces_of(shape))
                if sign * g.face_point_normal(f)[1][axis] > 0.9)


def _box(scene):
    return scene.add(g.make_box((0.0, 0.0, 0.0), 10.0, 10.0, 10.0))


def _split(proc, cutter):
    proc.run("splitface")
    proc.click_object(cutter.id)
    proc.finish_selection()
    assert not proc.busy


def test_a_line_over_a_face_divides_it_and_the_solid_stays_whole(env):
    scene, sel, _hist, proc, _said = env
    box = _box(scene)
    line = scene.add(g.make_line((5.0, -1.0, 20.0), (5.0, 11.0, 20.0)))
    sel.subobjects.append((box.id, "face", _facing(box.shape, 2, 1)))
    _split(proc, line)
    kept = scene.get(box.id)
    assert kept.kind == "solid"
    assert len(g.faces_of(kept.shape)) == 7
    assert len(g.edges_of(kept.shape)) == 15    # the neighbours broke too
    assert BRepCheck_Analyzer(kept.shape).IsValid()
    assert g.volume(kept.shape) == pytest.approx(1000.0)
    assert len(scene.all()) == 2                # no loose pieces
    assert sel.subobjects == []                 # those numbers mean nothing now


def test_undo_gives_the_face_back(env):
    scene, sel, hist, proc, _said = env
    box = _box(scene)
    line = scene.add(g.make_line((5.0, -1.0, 10.0), (5.0, 11.0, 10.0)))
    sel.subobjects.append((box.id, "face", _facing(box.shape, 2, 1)))
    _split(proc, line)
    hist.undo()
    assert len(g.faces_of(scene.get(box.id).shape)) == 6


def test_a_closed_curve_cuts_an_island_out_of_a_face(env):
    scene, sel, _hist, proc, _said = env
    box = _box(scene)
    circle = scene.add(g.make_circle((5.0, 5.0, 10.0), 2.0))
    sel.subobjects.append((box.id, "face", _facing(box.shape, 2, 1)))
    _split(proc, circle)
    kept = scene.get(box.id)
    assert kept.kind == "solid"
    assert len(g.faces_of(kept.shape)) == 7


def test_one_cutter_divides_every_held_face(env):
    scene, sel, _hist, proc, _said = env
    box = _box(scene)
    line = scene.add(g.make_line((5.0, -1.0, 10.0), (5.0, 11.0, 10.0)))
    sel.subobjects.extend([(box.id, "face", _facing(box.shape, 2, 1)),
                           (box.id, "face", _facing(box.shape, 1, -1))])
    _split(proc, line)
    kept = scene.get(box.id)
    assert kept.kind == "solid"
    assert len(g.faces_of(kept.shape)) == 8
    assert g.volume(kept.shape) == pytest.approx(1000.0)


def test_a_cylinder_wall_can_be_divided(env):
    scene, sel, _hist, proc, _said = env
    cyl = scene.add(g.make_cylinder((0.0, 0.0, 0.0), 5.0, 10.0))
    before = g.volume(cyl.shape)
    line = scene.add(g.make_line((-5.0, -9.0, 5.0), (-5.0, 9.0, 5.0)))
    sel.subobjects.append((cyl.id, "face", 0))
    _split(proc, line)
    kept = scene.get(cyl.id)
    assert kept.kind == "solid"
    assert len(g.faces_of(kept.shape)) == 4
    assert g.volume(kept.shape) == pytest.approx(before)


def test_a_loose_surface_stays_one_object(env):
    scene, sel, _hist, proc, _said = env
    face = g.faces_of(g.make_box((0.0, 0.0, 0.0), 10.0, 10.0, 10.0))[0]
    srf = scene.add(g.copy_shape(face))
    p, n = g.face_point_normal(face)
    across = tuple(1.0 if abs(v) < 0.5 else 0.0 for v in n)
    a = tuple(c + 20.0 * v for c, v in zip(p, across))
    b = tuple(c - 20.0 * v for c, v in zip(p, across))
    cutter = scene.add(g.make_line(a, b))
    sel.subobjects.append((srf.id, "face", 0))
    proc.run("splitface")
    proc.click_object(cutter.id)
    proc.finish_selection()
    assert not proc.busy
    assert len(scene.all()) == 2
    assert len(g.faces_of(scene.get(srf.id).shape)) == 2


def test_a_cutter_that_misses_changes_nothing(env):
    scene, sel, _hist, proc, said = env
    box = _box(scene)
    line = scene.add(g.make_line((50.0, -1.0, 10.0), (50.0, 11.0, 10.0)))
    sel.subobjects.append((box.id, "face", _facing(box.shape, 2, 1)))
    _split(proc, line)
    assert len(g.faces_of(scene.get(box.id).shape)) == 6
    assert any("nothing to split" in m for m in said)


def test_the_object_cannot_be_its_own_cutter(env):
    scene, sel, _hist, proc, said = env
    box = _box(scene)
    sel.subobjects.append((box.id, "face", 0))
    proc.run("splitface")
    proc.click_object(box.id)
    assert proc.busy
    assert any("not accepted" in m for m in said)
    proc.cancel()


def test_with_no_face_held_it_says_what_to_do(env):
    _scene, _sel, _hist, proc, said = env
    proc.run("splitface")
    assert not proc.busy
    assert any("Ctrl+Shift-click" in m for m in said)
