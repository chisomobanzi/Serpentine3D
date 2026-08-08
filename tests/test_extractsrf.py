"""`extractsrf`: take a face off a polysurface and keep it.

Rhino's ExtractSrf, and the option that matters is Copy. Copy=No pulls
the face out, so what is left is an open polysurface with a hole where
the face was. Copy=Yes leaves the original whole and hands you a
duplicate, which is the safe one and therefore not the default: Rhino
defaults it to No and so do we, because the usual reason to reach for
this is to rebuild a face, not to collect one.
"""

import pytest

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


def _kinds(scene):
    return sorted(o.kind for o in scene.all())


def test_extract_takes_the_face_out_of_the_solid(env):
    scene, sel, _hist, _ctx, proc = env
    box = scene.add(g.make_box((0.0, 0.0, 0.0), 2.0, 3.0, 4.0))
    sel.subobjects.append((box.id, "face", 0))
    proc.run("extractsrf")
    proc.provide_text("No")
    assert not proc.busy
    assert len(scene.all()) == 2
    left = scene.get(box.id)
    assert left is not None
    assert len(g.faces_of(left.shape)) == 5     # the hole stays a hole
    assert left.kind == "surface"               # no longer a closed solid
    face = next(o for o in scene.all() if o.id != box.id)
    assert len(g.faces_of(face.shape)) == 1


def test_copy_leaves_the_original_whole(env):
    scene, sel, _hist, _ctx, proc = env
    box = scene.add(g.make_box((0.0, 0.0, 0.0), 2.0, 3.0, 4.0))
    sel.subobjects.append((box.id, "face", 0))
    proc.run("extractsrf")
    proc.provide_text("Yes")
    assert not proc.busy
    kept = scene.get(box.id)
    assert kept.kind == "solid"
    assert len(g.faces_of(kept.shape)) == 6
    assert _kinds(scene) == ["solid", "surface"]


def test_copy_defaults_to_no(env):
    """Enter through the prompt and you get Rhino's default."""
    scene, sel, _hist, _ctx, proc = env
    box = scene.add(g.make_box((0.0, 0.0, 0.0), 2.0, 3.0, 4.0))
    sel.subobjects.append((box.id, "face", 1))
    proc.run("extractsrf")
    proc.provide_text("")
    assert not proc.busy
    assert len(g.faces_of(scene.get(box.id).shape)) == 5


def test_extracting_every_face_leaves_nothing_behind(env):
    """A polysurface with no faces left is not an empty object."""
    scene, sel, _hist, _ctx, proc = env
    box = scene.add(g.make_box((0.0, 0.0, 0.0), 2.0, 3.0, 4.0))
    for i in range(6):
        sel.subobjects.append((box.id, "face", i))
    proc.run("extractsrf")
    proc.provide_text("No")
    assert not proc.busy
    assert scene.get(box.id) is None
    assert _kinds(scene) == ["surface"] * 6


def test_several_faces_of_several_solids(env):
    scene, sel, _hist, _ctx, proc = env
    a = scene.add(g.make_box((0.0, 0.0, 0.0), 2.0, 3.0, 4.0))
    b = scene.add(g.make_box((9.0, 0.0, 0.0), 2.0, 3.0, 4.0))
    sel.subobjects += [(a.id, "face", 0), (a.id, "face", 2),
                       (b.id, "face", 1)]
    proc.run("extractsrf")
    proc.provide_text("No")
    assert not proc.busy
    assert len(g.faces_of(scene.get(a.id).shape)) == 4
    assert len(g.faces_of(scene.get(b.id).shape)) == 5
    assert len(scene.all()) == 5                # 2 remainders + 3 faces


def test_the_extracted_face_keeps_its_layer(env):
    scene, sel, _hist, _ctx, proc = env
    layer = scene.layers.create("Hull")
    box = scene.add(g.make_box((0.0, 0.0, 0.0), 2.0, 3.0, 4.0),
                    layer_id=layer.id)
    sel.subobjects.append((box.id, "face", 0))
    proc.run("extractsrf")
    proc.provide_text("No")
    face = next(o for o in scene.all() if o.id != box.id)
    assert face.layer_id == layer.id


def test_it_asks_for_faces_when_none_are_picked(env):
    scene, _sel, _hist, ctx, proc = env
    scene.add(g.make_box((0.0, 0.0, 0.0), 2.0, 3.0, 4.0))
    said = []
    ctx.echo = said.append
    proc.run("extractsrf")
    assert not proc.busy
    assert len(scene.all()) == 1
    assert any("face" in line.lower() for line in said)


def test_an_edge_pick_is_not_a_face_pick(env):
    scene, sel, _hist, ctx, proc = env
    box = scene.add(g.make_box((0.0, 0.0, 0.0), 2.0, 3.0, 4.0))
    sel.subobjects.append((box.id, "edge", 0))
    said = []
    ctx.echo = said.append
    proc.run("extractsrf")
    assert not proc.busy
    assert len(scene.all()) == 1
    assert scene.get(box.id).kind == "solid"


def test_extract_is_undoable(env):
    scene, sel, hist, _ctx, proc = env
    box = scene.add(g.make_box((0.0, 0.0, 0.0), 2.0, 3.0, 4.0))
    sel.subobjects.append((box.id, "face", 0))
    proc.run("extractsrf")
    proc.provide_text("No")
    assert len(scene.all()) == 2
    hist.undo()
    assert len(scene.all()) == 1
    assert scene.get(box.id).kind == "solid"
    assert len(g.faces_of(scene.get(box.id).shape)) == 6


# -- the geometry helper underneath ---------------------------------------

def test_remove_faces_sews_what_is_left():
    box = g.make_box((0.0, 0.0, 0.0), 2.0, 3.0, 4.0)
    rest = g.remove_faces(box, [0])
    assert rest is not None
    assert len(g.faces_of(rest)) == 5
    assert g.shape_kind(rest) == "surface"


def test_remove_faces_of_everything_is_nothing():
    box = g.make_box((0.0, 0.0, 0.0), 2.0, 3.0, 4.0)
    assert g.remove_faces(box, range(6)) is None


def test_remove_one_of_two_faces_leaves_a_lone_surface():
    box = g.make_box((0.0, 0.0, 0.0), 2.0, 3.0, 4.0)
    two = g.remove_faces(box, [0, 1, 2, 3])
    assert len(g.faces_of(two)) == 2
    one = g.remove_faces(two, [0])
    assert len(g.faces_of(one)) == 1
