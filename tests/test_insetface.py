"""`insetface`: a rim and an inner face, cut from the face itself.

The boundary of a face offset inward and used as a `splitface` cutter, so
the object stays one object. The usual next move is to push the inner face.
"""

import pytest
from OCP.BRepCheck import BRepCheck_Analyzer

from serpentine3d.commands.base import (
    CommandContext, CommandProcessor, resolve,
)
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


def _top(shape):
    return _facing(shape, 2, 1)


def _box(scene):
    return scene.add(g.make_box((0.0, 0.0, 0.0), 10.0, 10.0, 10.0))


def _inset(proc, text):
    proc.run("insetface")
    proc.provide_text(text)
    assert not proc.busy


def _whole(obj, faces, vol):
    assert obj.kind == "solid"
    assert len(g.faces_of(obj.shape)) == faces
    assert BRepCheck_Analyzer(obj.shape).IsValid()
    assert g.volume(obj.shape) == pytest.approx(vol)


@pytest.mark.parametrize("axis, sign", [(0, 1), (0, -1), (1, 1), (1, -1),
                                        (2, 1), (2, -1)])
def test_every_side_of_a_box_insets_inward(env, axis, sign):
    scene, sel, _hist, proc, _said = env
    box = _box(scene)
    index = _facing(box.shape, axis, sign)
    sel.subobjects.append((box.id, "face", index))
    loops = g.inset_loops(g.faces_of(box.shape)[index], 1.0)
    across = [(a, b) for a, b in zip(*g.bbox(loops[0]))]
    spans = sorted(round(b - a, 3) for a, b in across)
    assert spans == [0.0, 8.0, 8.0]             # inward, whichever way it faces
    _inset(proc, "1")
    _whole(scene.get(box.id), 7, 1000.0)
    assert len(scene.all()) == 1
    assert sel.subobjects == []


def test_the_inner_face_can_then_be_pushed_in(env):
    scene, sel, _hist, proc, _said = env
    box = _box(scene)
    sel.subobjects.append((box.id, "face", _top(box.shape)))
    _inset(proc, "1")
    shape = scene.get(box.id).shape
    faces = g.faces_of(shape)
    inner = next(i for i, f in enumerate(faces)
                 if g.face_point_normal(f)[1][2] > 0.9
                 and len(g.edges_of(f)) == 4)
    assert g.volume(g.push_pull(shape, inner, -2.0)) == pytest.approx(872.0)


def test_undo_gives_the_face_back(env):
    scene, sel, hist, proc, _said = env
    box = _box(scene)
    sel.subobjects.append((box.id, "face", _top(box.shape)))
    _inset(proc, "1")
    hist.undo()
    assert len(g.faces_of(scene.get(box.id).shape)) == 6


def test_a_round_face_insets_to_a_ring(env):
    scene, sel, _hist, proc, _said = env
    cyl = scene.add(g.make_cylinder((0.0, 0.0, 0.0), 5.0, 10.0))
    before = g.volume(cyl.shape)
    sel.subobjects.append((cyl.id, "face", _top(cyl.shape)))
    _inset(proc, "1")
    _whole(scene.get(cyl.id), 4, before)


def test_an_inward_corner_stays_a_corner(env):
    scene, sel, _hist, proc, _said = env
    outline = g.make_polyline([(0, 0, 0), (10, 0, 0), (10, 4, 0), (4, 4, 0),
                               (4, 10, 0), (0, 10, 0)], closed=True)
    solid = scene.add(g.extrude(g.planar_face(outline), (0, 0, 1), 5.0))
    sel.subobjects.append((solid.id, "face", _top(solid.shape)))
    loops = g.inset_loops(g.faces_of(solid.shape)[_top(solid.shape)], 1.0)
    assert len(g.edges_of(loops[0])) == 6       # no arc rounding the corner
    _inset(proc, "1")
    _whole(scene.get(solid.id), 9, 320.0)


def test_a_hole_keeps_a_rim_of_its_own(env):
    scene, sel, _hist, proc, _said = env
    shape = g.boolean_difference(
        g.make_box((0.0, 0.0, 0.0), 10.0, 10.0, 10.0),
        g.make_cylinder((5.0, 5.0, -1.0), 2.0, 12.0))
    holed = scene.add(shape)
    before = g.volume(shape)
    sel.subobjects.append((holed.id, "face", _top(shape)))
    _inset(proc, "1")
    _whole(scene.get(holed.id), 9, before)      # inner, and a rim each side


def test_every_held_face_is_inset(env):
    scene, sel, _hist, proc, _said = env
    box = _box(scene)
    sel.subobjects.extend([(box.id, "face", _top(box.shape)),
                           (box.id, "face", _facing(box.shape, 1, -1))])
    _inset(proc, "1")
    _whole(scene.get(box.id), 8, 1000.0)


def test_a_loose_flat_surface_stays_one_object(env):
    scene, sel, _hist, proc, _said = env
    outline = g.make_polyline([(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)],
                              closed=True)
    srf = scene.add(g.planar_face(outline))
    sel.subobjects.append((srf.id, "face", 0))
    _inset(proc, "1")
    assert len(scene.all()) == 1
    assert len(g.faces_of(scene.get(srf.id).shape)) == 2


@pytest.mark.parametrize("text", ["5", "6"])
def test_an_inset_too_wide_for_the_face_changes_nothing(env, text):
    scene, sel, _hist, proc, said = env
    box = _box(scene)
    sel.subobjects.append((box.id, "face", _top(box.shape)))
    _inset(proc, text)
    assert len(g.faces_of(scene.get(box.id).shape)) == 6
    assert any("too large" in m for m in said)


def test_a_curved_face_is_refused_not_crashed_on(env):
    scene, sel, _hist, proc, said = env
    cyl = scene.add(g.make_cylinder((0.0, 0.0, 0.0), 5.0, 10.0))
    wall = next(i for i, f in enumerate(g.faces_of(cyl.shape))
                if abs(g.face_point_normal(f)[1][2]) < 0.1)
    sel.subobjects.append((cyl.id, "face", wall))
    _inset(proc, "1")
    assert len(g.faces_of(scene.get(cyl.id).shape)) == 3
    assert any("flat face" in m for m in said)


def test_a_flat_face_held_with_a_curved_one_stops_the_edit(env):
    scene, sel, _hist, proc, said = env
    cyl = scene.add(g.make_cylinder((0.0, 0.0, 0.0), 5.0, 10.0))
    sel.subobjects.extend([(cyl.id, "face", i) for i in range(3)])
    _inset(proc, "1")
    assert len(g.faces_of(scene.get(cyl.id).shape)) == 3
    assert any("flat face" in m for m in said)


def test_the_prompt_previews_the_loops(env):
    scene, sel, _hist, proc, _said = env
    box = _box(scene)
    sel.subobjects.append((box.id, "face", _top(box.shape)))
    proc.run("insetface")
    assert proc.preview_shape("1") is not None
    assert proc.preview_shape("6") is None      # too wide, nothing to show
    proc.cancel()
    assert len(g.faces_of(scene.get(box.id).shape)) == 6


def test_with_no_face_held_it_says_what_to_do(env):
    _scene, _sel, _hist, proc, said = env
    proc.run("insetface")
    assert not proc.busy
    assert any("Ctrl+Shift-click" in m for m in said)


def test_inset_is_a_name_for_it():
    assert resolve("inset").name == "insetface"
