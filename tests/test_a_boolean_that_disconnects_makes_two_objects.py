"""Cut a bar in half and you have two bars.

Serpentine kept it as one. The kernel was never confused: subtracting a
knife from a bar hands back a compound holding two solids, exactly as it
should. shape_kind() then classifies a compound by its contents, so a
compound of solids reports "solid", and from there nothing downstream had
any reason to look inside. One scene object, two lumps, and a gumball
sitting between them moving both.

The same blindness shows up in explode, which asks shape_kind() what it is
holding, gets "solid", and decomposes to faces. Exploding a severed bar
gave twelve faces rather than the two solids anyone would expect.

A solid with a hollow inside it is the case that says whether this is done
properly: it also has more than one shell, and it is emphatically still
one object.
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


def _bar(scene):
    """100 long, 10 square. Volume 10000."""
    return scene.add(g.make_box((0.0, 0.0, 0.0), 100.0, 10.0, 10.0),
                     name="Bar")


def _knife(scene):
    """Straight through the middle of the bar, severing it. Takes 2000."""
    return scene.add(g.make_box((40.0, -5.0, -5.0), 20.0, 20.0, 20.0),
                     name="Knife")


def _notch(scene):
    """Into the top of the bar but not through it. Takes 1000, severs nothing."""
    return scene.add(g.make_box((40.0, -5.0, 5.0), 20.0, 20.0, 20.0),
                     name="Notch")


def _solids(scene):
    return [o for o in scene.all() if o.kind == "solid"]


def _cut(proc, keep, cutter):
    proc.run("booleandifference")
    proc.click_object(keep.id)
    proc.finish_selection()
    proc.click_object(cutter.id)
    proc.finish_selection()


# -- the geometry helper --

def test_loose_pieces_finds_both_lumps():
    bar = g.make_box((0.0, 0.0, 0.0), 100.0, 10.0, 10.0)
    knife = g.make_box((40.0, -5.0, -5.0), 20.0, 20.0, 20.0)
    assert len(g.loose_pieces(g.boolean_difference(bar, knife))) == 2


def test_a_plain_solid_has_no_loose_pieces():
    assert g.loose_pieces(g.make_box((0.0, 0.0, 0.0), 1.0, 1.0, 1.0)) == []


def test_a_hollow_solid_has_no_loose_pieces():
    """The void gives it a second shell. Shells are not the thing to count."""
    outer = g.make_box((0.0, 0.0, 0.0), 20.0, 20.0, 20.0)
    void = g.make_box((5.0, 5.0, 5.0), 10.0, 10.0, 10.0)
    hollow = g.boolean_difference(outer, void)
    assert g.volume(hollow) == pytest.approx(8000 - 1000, rel=1e-6)
    assert g.loose_pieces(hollow) == []


def test_a_compound_holding_more_than_solids_is_left_whole():
    """Splitting it would hand back the solids and drop everything else."""
    mixed = g.make_compound([
        g.make_box((0.0, 0.0, 0.0), 10.0, 10.0, 10.0),
        g.make_box((50.0, 0.0, 0.0), 10.0, 10.0, 10.0),
        g.make_line((0.0, 0.0, 0.0), (10.0, 0.0, 0.0)),
    ])
    assert g.loose_pieces(mixed) == [], (
        "two solids in there, so counting solids alone says split, and the "
        "line would go in the bin")


# -- what the command leaves behind --

def test_cutting_a_bar_clean_through_makes_two_objects(env):
    scene, _sel, proc = env
    _cut(proc, _bar(scene), _knife(scene))
    assert len(_solids(scene)) == 2


def test_each_piece_carries_its_own_share_of_the_volume(env):
    scene, _sel, proc = env
    _cut(proc, _bar(scene), _knife(scene))
    vols = sorted(round(g.volume(o.shape), 6) for o in _solids(scene))
    assert vols == [pytest.approx(4000), pytest.approx(4000)]


def test_a_cut_that_severs_nothing_stays_one_object(env):
    scene, _sel, proc = env
    _cut(proc, _bar(scene), _notch(scene))
    left = _solids(scene)
    assert len(left) == 1
    assert g.volume(left[0].shape) == pytest.approx(9000, rel=1e-6)


def test_a_hollowed_solid_stays_one_object(env):
    scene, _sel, proc = env
    outer = scene.add(g.make_box((0.0, 0.0, 0.0), 20.0, 20.0, 20.0))
    void = scene.add(g.make_box((5.0, 5.0, 5.0), 10.0, 10.0, 10.0))
    _cut(proc, outer, void)
    assert len(_solids(scene)) == 1


def test_both_pieces_end_up_selected(env):
    scene, sel, proc = env
    _cut(proc, _bar(scene), _knife(scene))
    assert sorted(sel.ids) == sorted(o.id for o in _solids(scene))


def test_the_pieces_keep_the_layer_they_were_cut_from(env):
    scene, _sel, proc = env
    bar = _bar(scene)
    layer = bar.layer_id
    _cut(proc, bar, _knife(scene))
    assert {o.layer_id for o in _solids(scene)} == {layer}


def test_undoing_the_cut_puts_the_bar_back_as_one(env):
    """The second piece is a new object, so undo has to take it away again."""
    scene, _sel, proc = env
    _cut(proc, _bar(scene), _knife(scene))
    assert len(_solids(scene)) == 2, "the cut should have made two pieces"
    proc.ctx.history.undo()

    # the bar and the knife, exactly as they were before the command
    back = sorted(round(g.volume(o.shape), 6) for o in _solids(scene))
    assert back == [pytest.approx(8000), pytest.approx(10000)], (
        f"undo should give back the whole bar and the knife, got {back}")


def test_a_union_of_two_that_never_touch_makes_two_objects(env):
    scene, _sel, proc = env
    scene.add(g.make_box((0.0, 0.0, 0.0), 10.0, 10.0, 10.0))
    scene.add(g.make_box((50.0, 0.0, 0.0), 10.0, 10.0, 10.0))
    proc.run("booleanunion")
    proc.click_object(_solids(scene)[0].id)
    proc.click_object(_solids(scene)[1].id)
    proc.finish_selection()
    assert len(_solids(scene)) == 2


def test_a_union_of_two_that_do_touch_makes_one_object(env):
    scene, _sel, proc = env
    a = scene.add(g.make_box((0.0, 0.0, 0.0), 10.0, 10.0, 10.0))
    b = scene.add(g.make_box((5.0, 0.0, 0.0), 10.0, 10.0, 10.0))
    proc.run("booleanunion")
    proc.click_object(a.id)
    proc.click_object(b.id)
    proc.finish_selection()
    assert len(_solids(scene)) == 1


# -- explode, which was reading the same wrong answer --

def test_exploding_a_severed_result_gives_solids_not_faces():
    bar = g.make_box((0.0, 0.0, 0.0), 100.0, 10.0, 10.0)
    knife = g.make_box((40.0, -5.0, -5.0), 20.0, 20.0, 20.0)
    parts = g.explode(g.boolean_difference(bar, knife))
    assert len(parts) == 2, f"expected the two lumps, got {len(parts)} parts"
    assert all(g.shape_kind(p) == "solid" for p in parts)


def test_exploding_a_plain_solid_still_gives_its_faces():
    parts = g.explode(g.make_box((0.0, 0.0, 0.0), 10.0, 10.0, 10.0))
    assert len(parts) == 6
    assert all(g.shape_kind(p) == "surface" for p in parts)
