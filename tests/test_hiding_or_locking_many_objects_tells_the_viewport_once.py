"""Isolate one object in a big file and the screen should not stall.

Isolate hides everything else, one object at a time, and the scene tells
its listeners about every one. The viewport is a listener, and it answers
each call by rebuilding its GPU buffers for the whole scene, so isolating
in a file of a few thousand objects rebuilds the whole drawing a few
thousand times over. The user sees a command that ought to be instant take
seconds, and the same is true of unisolate, of hiding a big selection and
showing it again, and of lockother and unlockall.

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


def _visible(scene):
    return [o.id for o in scene.all() if o.visible]


def _locked(scene):
    return [o.id for o in scene.all() if o.locked]


# -- the baseline every bulk command is held to --

def test_hiding_one_object_notifies_once(env):
    """The cost of the smallest possible change. Everything below must
    cost no more than this."""
    scene, _sel, _hist, _ctx, proc = env
    boxes = _boxes(scene)
    counter = _Counter(scene)
    _select_and_finish(proc, "hide", [boxes[0].id])
    assert counter.calls == 1
    assert len(_visible(scene)) == MANY - 1


# -- isolate / unisolate --

def test_isolating_one_of_many_notifies_once(env):
    scene, _sel, _hist, _ctx, proc = env
    boxes = _boxes(scene)
    counter = _Counter(scene)
    _select_and_finish(proc, "isolate", [boxes[0].id])
    assert _visible(scene) == [boxes[0].id], "only the kept box should show"
    assert counter.calls == 1, (
        f"isolate hid {MANY - 1} objects and woke the listeners "
        f"{counter.calls} times; one change, one notification")


def test_unisolating_many_notifies_once(env):
    scene, _sel, _hist, _ctx, proc = env
    boxes = _boxes(scene)
    _select_and_finish(proc, "isolate", [boxes[0].id])
    counter = _Counter(scene)
    proc.run("unisolate")
    assert len(_visible(scene)) == MANY, "everything should be back"
    assert counter.calls == 1, (
        f"unisolate restored {MANY - 1} objects and woke the listeners "
        f"{counter.calls} times; one change, one notification")


# -- hide a big selection / show --

def test_hiding_many_selected_notifies_once(env):
    scene, _sel, _hist, _ctx, proc = env
    boxes = _boxes(scene)
    counter = _Counter(scene)
    _select_and_finish(proc, "hide", [b.id for b in boxes])
    assert _visible(scene) == []
    assert counter.calls == 1, (
        f"hiding {MANY} objects woke the listeners {counter.calls} times")


def test_showing_many_hidden_notifies_once(env):
    scene, _sel, _hist, _ctx, proc = env
    boxes = _boxes(scene)
    _select_and_finish(proc, "hide", [b.id for b in boxes])
    counter = _Counter(scene)
    proc.run("show")
    assert len(_visible(scene)) == MANY
    assert counter.calls == 1, (
        f"showing {MANY} objects woke the listeners {counter.calls} times")


# -- lockother / unlockall --

def test_locking_all_others_notifies_once(env):
    scene, _sel, _hist, _ctx, proc = env
    boxes = _boxes(scene)
    counter = _Counter(scene)
    _select_and_finish(proc, "lockother", [boxes[0].id])
    assert sorted(_locked(scene)) == sorted(b.id for b in boxes[1:])
    assert counter.calls == 1, (
        f"lockother locked {MANY - 1} objects and woke the listeners "
        f"{counter.calls} times")


def test_unlocking_all_notifies_once(env):
    scene, _sel, _hist, _ctx, proc = env
    boxes = _boxes(scene)
    _select_and_finish(proc, "lockother", [boxes[0].id])
    counter = _Counter(scene)
    proc.run("unlockall")
    assert _locked(scene) == []
    assert counter.calls == 1, (
        f"unlockall released {MANY - 1} objects and woke the listeners "
        f"{counter.calls} times")
