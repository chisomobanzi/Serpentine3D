"""A layer can live under another layer, the way a drawing is organised.

An architect does not keep a flat list. A Rhino file arrives with
Walls::Interior, Walls::Exterior and Roof::Interior in it, and the shape of
that list is how the drawing is read: switch Walls off and everything under
it goes off with it. Serpentine kept one flat list, so opening such a file
threw the structure away, and the importer matched a layer by its leaf name
alone, which made Walls::Interior and Roof::Interior the same layer and
quietly poured one's objects into the other. Asked for by Lourenço Vaz
Pinto (GitHub #6).

This is the model underneath it: a layer that knows its parent, a parent
that hands its state down without overwriting what a child was set to, and
a delete that takes the whole branch.
"""

from __future__ import annotations

import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.deferred import DeferredShape
from serpentine3d.core.history import History
from serpentine3d.core.layers import DEFAULT_LAYER_ID, LayerManager
from serpentine3d.core.scene import Scene


def _walls_and_roof(layers):
    """Walls::Interior and Roof::Interior: the pair that used to collide."""
    walls = layers.create("Walls")
    roof = layers.create("Roof")
    return (walls, roof,
            layers.create("Interior", parent=walls.id),
            layers.create("Interior", parent=roof.id))


def _line(scene, layer_id):
    return scene.add(g.make_line((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
                     layer_id=layer_id)


# -- the tree --

def test_a_layer_starts_at_the_top_of_the_list():
    lm = LayerManager()
    assert lm.get(DEFAULT_LAYER_ID).parent is None
    assert lm.create("Walls").parent is None


def test_a_layer_made_under_another_is_one_of_its_children():
    lm = LayerManager()
    walls = lm.create("Walls")
    inner = lm.create("Interior", parent=walls.id)
    assert inner.parent == walls.id
    assert [la.id for la in lm.children(walls.id)] == [inner.id]
    assert lm.children(inner.id) == []


def test_children_come_back_in_the_order_they_were_made():
    lm = LayerManager()
    walls = lm.create("Walls")
    names = ["Interior", "Exterior", "Structure"]
    for name in names:
        lm.create(name, parent=walls.id)
    assert [la.name for la in lm.children(walls.id)] == names


def test_two_parents_can_each_hold_a_child_of_the_same_name():
    """The collision this whole thing is for."""
    lm = LayerManager()
    _walls, _roof, wall_inner, roof_inner = _walls_and_roof(lm)
    assert wall_inner.id != roof_inner.id
    assert lm.full_path(wall_inner.id) == "Walls::Interior"
    assert lm.full_path(roof_inner.id) == "Roof::Interior"


def test_a_layer_at_the_top_is_its_own_whole_path():
    lm = LayerManager()
    assert lm.full_path(DEFAULT_LAYER_ID) == "Default"


def test_a_layer_is_found_by_the_path_the_file_calls_it():
    lm = LayerManager()
    _walls, _roof, wall_inner, roof_inner = _walls_and_roof(lm)
    assert lm.find_by_path("Walls::Interior").id == wall_inner.id
    assert lm.find_by_path("roof::interior").id == roof_inner.id
    assert lm.find_by_path("Walls::Nothing") is None


# -- what a parent hands down --

def test_switching_a_parent_off_takes_its_children_with_it():
    lm = LayerManager()
    walls = lm.create("Walls")
    inner = lm.create("Interior", parent=walls.id)
    lm.set_visible(walls.id, False)
    assert not lm.is_visible(inner.id)
    assert lm.get(inner.id).visible, \
        "the parent flipped the child's own switch instead of covering it"


def test_a_child_switched_off_on_its_own_stays_off_when_the_parent_returns():
    lm = LayerManager()
    walls = lm.create("Walls")
    on = lm.create("Exterior", parent=walls.id)
    off = lm.create("Interior", parent=walls.id)
    lm.set_visible(off.id, False)
    lm.set_visible(walls.id, False)
    lm.set_visible(walls.id, True)
    assert lm.is_visible(on.id)
    assert not lm.is_visible(off.id), \
        "switching the parent back on overrode what the child was set to"


def test_a_layer_two_levels_down_answers_to_the_top_of_its_branch():
    lm = LayerManager()
    walls = lm.create("Walls")
    inner = lm.create("Interior", parent=walls.id)
    trim = lm.create("Trim", parent=inner.id)
    lm.set_visible(walls.id, False)
    assert not lm.is_visible(trim.id)


def test_locking_a_parent_locks_everything_under_it():
    lm = LayerManager()
    walls = lm.create("Walls")
    inner = lm.create("Interior", parent=walls.id)
    lm.set_locked(walls.id, True)
    assert lm.is_locked(inner.id)
    assert not lm.get(inner.id).locked, \
        "the parent flipped the child's own lock instead of covering it"
    lm.set_locked(walls.id, False)
    assert not lm.is_locked(inner.id)


def test_a_child_locked_on_its_own_stays_locked_when_the_parent_unlocks():
    lm = LayerManager()
    walls = lm.create("Walls")
    inner = lm.create("Interior", parent=walls.id)
    lm.set_locked(inner.id, True)
    lm.set_locked(walls.id, True)
    lm.set_locked(walls.id, False)
    assert lm.is_locked(inner.id)


# -- what the drawing does about it --

def test_an_object_under_a_switched_off_parent_is_not_drawn():
    scene = Scene()
    walls = scene.layers.create("Walls")
    inner = scene.layers.create("Interior", parent=walls.id)
    obj = _line(scene, inner.id)
    scene.layers.set_visible(walls.id, False)
    assert obj.id not in [o.id for o in scene.visible_objects()]


def test_an_object_under_a_locked_parent_cannot_be_picked():
    scene = Scene()
    walls = scene.layers.create("Walls")
    inner = scene.layers.create("Interior", parent=walls.id)
    obj = _line(scene, inner.id)
    scene.layers.set_locked(walls.id, True)
    assert not scene.is_selectable(obj.id)
    assert obj.id not in [o.id for o in scene.selectable_objects()]


def test_switching_a_parent_on_converts_what_was_waiting_under_it():
    """A hidden layer arrives from a .3dm unconverted and is converted when
    it comes back on (GitHub #5). A child that comes back on because its
    parent did is on screen too, so it has to be converted as well or it is
    a layer that is showing nothing.
    """
    scene = Scene()
    walls = scene.layers.create("Walls")
    inner = scene.layers.create("Interior", parent=walls.id)
    scene.layers.set_visible(walls.id, False)
    obj = scene.add(
        DeferredShape(lambda: [g.make_line((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))],
                      kind="curve"),
        layer_id=inner.id)
    assert not scene.get(obj.id).shape_ready
    scene.layers.set_visible(walls.id, True)
    assert scene.get(obj.id).shape_ready, \
        "the branch came back on with its geometry still unconverted"


# -- moving a layer around --

def test_a_layer_can_be_moved_under_another_one():
    lm = LayerManager()
    walls, roof, inner, _roof_inner = _walls_and_roof(lm)
    lm.set_parent(inner.id, roof.id)
    assert lm.full_path(inner.id) == "Roof::Interior"
    assert inner.id not in [la.id for la in lm.children(walls.id)]
    assert inner.id in [la.id for la in lm.children(roof.id)]


def test_a_layer_can_be_moved_back_to_the_top():
    lm = LayerManager()
    walls = lm.create("Walls")
    inner = lm.create("Interior", parent=walls.id)
    lm.set_parent(inner.id, None)
    assert lm.get(inner.id).parent is None
    assert lm.full_path(inner.id) == "Interior"


def test_a_layer_cannot_be_moved_under_its_own_child():
    """A branch that contains itself has no top, and every walk up it hangs."""
    lm = LayerManager()
    walls = lm.create("Walls")
    inner = lm.create("Interior", parent=walls.id)
    with pytest.raises(ValueError):
        lm.set_parent(walls.id, inner.id)
    with pytest.raises(ValueError):
        lm.set_parent(walls.id, walls.id)


# -- deleting --

def test_deleting_a_layer_deletes_the_layers_under_it():
    lm = LayerManager()
    walls = lm.create("Walls")
    inner = lm.create("Interior", parent=walls.id)
    lm.create("Trim", parent=inner.id)
    lm.remove(walls.id)
    assert [la.id for la in lm.all()] == [DEFAULT_LAYER_ID]


def test_deleting_a_branch_leaves_its_objects_on_the_default_layer():
    """Whatever was drawn on it is still the user's work, so it lands
    somewhere it can be seen rather than on a layer that is gone."""
    scene = Scene()
    walls = scene.layers.create("Walls")
    inner = scene.layers.create("Interior", parent=walls.id)
    on_parent = _line(scene, walls.id)
    on_child = _line(scene, inner.id)
    scene.remove_layer(walls.id)
    assert scene.get(on_parent.id).layer_id == DEFAULT_LAYER_ID
    assert scene.get(on_child.id).layer_id == DEFAULT_LAYER_ID
    assert [la.id for la in scene.layers.all()] == [DEFAULT_LAYER_ID]


def test_deleting_the_current_layer_branch_leaves_a_current_layer_behind():
    scene = Scene()
    walls = scene.layers.create("Walls")
    inner = scene.layers.create("Interior", parent=walls.id)
    scene.layers.current_id = inner.id
    scene.remove_layer(walls.id)
    assert scene.layers.current_id == DEFAULT_LAYER_ID


def test_purge_keeps_an_empty_parent_whose_child_is_still_in_use(env):
    """purge takes away layers nothing is drawn on. A parent holding a
    working child is not one of those: taking it would take the child."""
    scene, _sel, _hist, _ctx, proc = env
    walls = scene.layers.create("Walls")
    inner = scene.layers.create("Interior", parent=walls.id)
    _line(scene, inner.id)
    proc.run("purge")
    assert not proc.busy
    paths = [scene.layers.full_path(la.id) for la in scene.layers.all()]
    assert "Walls::Interior" in paths
    assert "Walls" in paths


def test_undo_brings_a_deleted_branch_back():
    scene = Scene()
    history = History(scene)
    walls = scene.layers.create("Walls")
    scene.layers.create("Interior", parent=walls.id)
    history.checkpoint("delete layer")
    scene.remove_layer(walls.id)
    history.undo()
    assert scene.layers.find_by_path("Walls::Interior") is not None
