"""Lock, group, relayer or restyle a big selection and the screen should
not stall.

Hide, isolate and lockother already change many objects with one word to
the scene's listeners. The rest of the bulk commands still go one object at
a time, and the scene tells its listeners about every one. The viewport is
a listener, and it answers each call by rebuilding its GPU buffers for the
whole scene, so locking a thousand objects rebuilds the drawing a thousand
times over. The same is true of group and ungroup, of moving a selection
to another layer, of setting a linetype or a material, of matching
properties across a selection, and of bringing it to the front or sending
it to the back.

Nobody wants the states in between. One command that changes many objects
is one change to the drawing, and the listeners should hear about it once,
exactly as they do when hiding a single object.

Each test also checks the drawing ended up right: a scene that never
notified at all would pass the count and fail the user.
"""

from __future__ import annotations

import pytest

from serpentine3d.core import geometry as g

MANY = 40


def _boxes(scene, n=MANY):
    return [scene.add(g.make_box((i * 20.0, 0.0, 0.0), 10.0, 10.0, 10.0),
                      name=f"Box {i}")
            for i in range(n)]


class _Counter:
    """Stands in for the viewport: counts every "objects" wake-up."""

    def __init__(self, scene):
        self.calls = 0
        scene.add_listener(self, kinds=("objects",))

    def __call__(self):
        self.calls += 1

    def reset(self):
        self.calls = 0


def _select_and_finish(proc, name, ids):
    proc.run(name)
    for i in ids:
        proc.click_object(i)
    proc.finish_selection()


def _locked(scene):
    return [o.id for o in scene.all() if o.locked]


# -- lock --

def test_locking_many_selected_notifies_once(env):
    scene, _sel, _hist, _ctx, proc = env
    boxes = _boxes(scene)
    counter = _Counter(scene)
    _select_and_finish(proc, "lock", [b.id for b in boxes])
    assert sorted(_locked(scene)) == sorted(b.id for b in boxes)
    assert counter.calls == 1, (
        f"lock locked {MANY} objects and woke the listeners "
        f"{counter.calls} times; one change, one notification")


# -- group / ungroup --

def test_grouping_many_notifies_once(env):
    scene, _sel, _hist, _ctx, proc = env
    boxes = _boxes(scene)
    counter = _Counter(scene)
    _select_and_finish(proc, "group", [b.id for b in boxes])
    groups = {scene.get(b.id).group_id for b in boxes}
    assert len(groups) == 1 and None not in groups, (
        "every box should be in the one new group")
    assert counter.calls == 1, (
        f"group joined {MANY} objects and woke the listeners "
        f"{counter.calls} times")


def test_ungrouping_many_notifies_once(env):
    scene, _sel, _hist, _ctx, proc = env
    boxes = _boxes(scene)
    _select_and_finish(proc, "group", [b.id for b in boxes])
    counter = _Counter(scene)
    _select_and_finish(proc, "ungroup", [b.id for b in boxes])
    assert all(scene.get(b.id).group_id is None for b in boxes), (
        "no box should be left in a group")
    assert counter.calls == 1, (
        f"ungroup released {MANY} objects and woke the listeners "
        f"{counter.calls} times")


# -- changelayer --

def test_moving_many_to_a_layer_notifies_once(env):
    scene, _sel, _hist, _ctx, proc = env
    boxes = _boxes(scene)
    walls = scene.layers.create("Walls")
    counter = _Counter(scene)
    _select_and_finish(proc, "changelayer", [b.id for b in boxes])
    proc.provide_text("Walls")
    assert all(scene.get(b.id).layer_id == walls.id for b in boxes), (
        "every box should now be on Walls")
    assert counter.calls == 1, (
        f"changelayer moved {MANY} objects and woke the listeners "
        f"{counter.calls} times")


# -- linetype --

def test_setting_linetype_on_many_notifies_once(env):
    scene, _sel, _hist, _ctx, proc = env
    boxes = _boxes(scene)
    counter = _Counter(scene)
    _select_and_finish(proc, "linetype", [b.id for b in boxes])
    proc.provide_text("Dashed")
    assert all(scene.get(b.id).linetype == "Dashed" for b in boxes)
    assert counter.calls == 1, (
        f"linetype restyled {MANY} objects and woke the listeners "
        f"{counter.calls} times")


# -- matchprops --

def test_matching_properties_onto_many_notifies_once(env):
    scene, _sel, _hist, _ctx, proc = env
    boxes = _boxes(scene)
    source, targets = boxes[0], boxes[1:]
    scene.update(source.id, color=(1.0, 0.0, 0.0), material={"opacity": 0.4})
    counter = _Counter(scene)
    proc.run("matchprops")
    proc.click_object(source.id)          # one source: the request closes
    for t in targets:
        proc.click_object(t.id)
    proc.finish_selection()
    assert all(scene.get(t.id).color == (1.0, 0.0, 0.0)
               and scene.get(t.id).material == {"opacity": 0.4}
               for t in targets), "every target should look like the source"
    assert counter.calls == 1, (
        f"matchprops changed {MANY - 1} objects and woke the listeners "
        f"{counter.calls} times")


# -- material / remove --

def test_assigning_material_to_many_notifies_once(env):
    scene, _sel, _hist, _ctx, proc = env
    boxes = _boxes(scene)
    counter = _Counter(scene)
    _select_and_finish(proc, "material", [b.id for b in boxes])
    proc.provide_text("Matte")
    materials = [scene.get(b.id).material for b in boxes]
    assert all(m for m in materials) and len({tuple(sorted(m.items()))
                                             for m in materials}) == 1, (
        "every box should carry the same Matte material")
    assert counter.calls == 1, (
        f"material dressed {MANY} objects and woke the listeners "
        f"{counter.calls} times")


def test_removing_material_from_many_notifies_once(env):
    scene, _sel, _hist, _ctx, proc = env
    boxes = _boxes(scene)
    _select_and_finish(proc, "material", [b.id for b in boxes])
    proc.provide_text("Matte")
    counter = _Counter(scene)
    _select_and_finish(proc, "material", [b.id for b in boxes])
    proc.provide_text("Remove")
    assert all(scene.get(b.id).material is None for b in boxes)
    assert counter.calls == 1, (
        f"material cleared {MANY} objects and woke the listeners "
        f"{counter.calls} times")


# -- bringtofront / sendtoback --

def test_bringing_many_to_front_notifies_once(env):
    scene, _sel, _hist, _ctx, proc = env
    boxes = _boxes(scene)
    top_before = max(o.draw_order for o in scene.all())
    counter = _Counter(scene)
    _select_and_finish(proc, "bringtofront", [b.id for b in boxes])
    assert all(scene.get(b.id).draw_order > top_before for b in boxes), (
        "every box should now draw above where the top used to be")
    assert counter.calls == 1, (
        f"bringtofront raised {MANY} objects and woke the listeners "
        f"{counter.calls} times")


def test_sending_many_to_back_notifies_once(env):
    scene, _sel, _hist, _ctx, proc = env
    boxes = _boxes(scene)
    bottom_before = min(o.draw_order for o in scene.all())
    counter = _Counter(scene)
    _select_and_finish(proc, "sendtoback", [b.id for b in boxes])
    assert all(scene.get(b.id).draw_order < bottom_before for b in boxes), (
        "every box should now draw below where the bottom used to be")
    assert counter.calls == 1, (
        f"sendtoback lowered {MANY} objects and woke the listeners "
        f"{counter.calls} times")
