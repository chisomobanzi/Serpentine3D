"""A new group stays in hand for the next modeling operation (issue #63)."""

import numpy as np
import pytest

from serpentine3d.commands.base import PointReq, SelectReq
from serpentine3d.core import geometry as g


ENTRY_PATHS = ("preselected", "picked", "extended")


def _boxes(scene):
    return [scene.add(g.make_box((x, 0, 0), 2, 2, 2), name=name)
            for x, name in ((0, "A"), (6, "B"), (20, "Unrelated"))]


def _group(proc, selection, objects, entry):
    ids = [o.id for o in objects]
    if entry == "preselected":
        selection.set(ids)
    elif entry == "extended":
        selection.set(ids[:1])
    assert proc.run("group")
    if entry != "preselected":
        assert isinstance(proc.request, SelectReq)
        if entry == "picked":
            proc.click_object(ids[0])
        proc.click_object(ids[1])
        proc.finish_selection()
    assert not proc.busy


def _geometry(scene):
    return {o.id: (o.name, o.kind, tuple(map(tuple, o.bbox())),
                   g.volume(o.shape))
            for o in scene.all()}


@pytest.mark.parametrize("entry", ENTRY_PATHS)
def test_a_new_group_keeps_exactly_its_members_selected(env, entry):
    scene, selection, _history, _ctx, proc = env
    a, b, unrelated = _boxes(scene)
    before = _geometry(scene)

    _group(proc, selection, [a, b], entry)

    gid = scene.get(a.id).group_id
    assert gid and scene.get(b.id).group_id == gid
    assert scene.get(unrelated.id).group_id is None
    assert set(scene.expand_group_ids([a.id])) == {a.id, b.id}
    assert _geometry(scene) == before, "Grouping changed the objects"
    assert set(selection.ids) == {a.id, b.id}, (
        "Group released its members instead of leaving them ready to use")
    assert selection.subobjects == []
    assert not selection.is_selected(unrelated.id)


@pytest.mark.parametrize("entry", ENTRY_PATHS)
def test_move_can_use_the_new_group_without_picking_again(env, entry):
    scene, selection, _history, _ctx, proc = env
    a, b, unrelated = _boxes(scene)
    before = {o.id: np.asarray(o.bbox()) for o in scene.all()}
    _group(proc, selection, [a, b], entry)
    gid = scene.get(a.id).group_id

    assert proc.run("move")
    assert isinstance(proc.request, PointReq), (
        "Move asked for objects even though Group had just selected them")
    proc.provide((0, 0, 0))
    proc.provide((3, 4, 5))

    assert not proc.busy
    for obj in (a, b):
        assert np.allclose(scene.get(obj.id).bbox(),
                           before[obj.id] + (3, 4, 5), atol=1e-6)
        assert scene.get(obj.id).group_id == gid
    assert np.allclose(scene.get(unrelated.id).bbox(), before[unrelated.id])


@pytest.mark.parametrize("entry", ENTRY_PATHS)
def test_the_viewports_keep_the_new_group_highlighted_and_on_the_gumball(
        env, entry):
    from serpentine3d.ui.viewport import Viewport

    scene, selection, _history, _ctx, proc = env
    a, b, unrelated = _boxes(scene)
    panes = [Viewport(scene, selection), Viewport(scene, selection)]
    observed = []
    selection.add_listener(lambda: observed.append(set(selection.ids)))
    try:
        _group(proc, selection, [a, b], entry)

        assert observed[-1] == {a.id, b.id}, (
            "Selection listeners received an empty selection after Group")
        assert selection.is_selected(a.id) and selection.is_selected(b.id)
        assert not selection.is_selected(unrelated.id)
        for pane in panes:
            assert pane.gumball.active(), "Group made the gumball disappear"
            anchor, _axes = pane.gumball.anchor_and_axes()
            assert np.allclose(anchor, (4, 1, 1), atol=1e-6)
    finally:
        for pane in panes:
            pane.close()


@pytest.mark.parametrize("entry", ENTRY_PATHS)
def test_group_membership_and_geometry_survive_undo_and_redo(env, entry):
    scene, selection, history, _ctx, proc = env
    a, b, unrelated = _boxes(scene)
    before = _geometry(scene)
    _group(proc, selection, [a, b], entry)
    gid = scene.get(a.id).group_id

    assert history.can_undo
    history.undo()
    assert all(o.group_id is None for o in scene.all())
    assert _geometry(scene) == before
    assert history.can_redo

    history.redo()
    assert scene.get(a.id).group_id == gid
    assert scene.get(b.id).group_id == gid
    assert scene.get(unrelated.id).group_id is None
    assert _geometry(scene) == before


@pytest.mark.parametrize("count,finish", ((0, True), (1, True),
                                          (1, False), (2, False)))
def test_an_unfinished_or_cancelled_group_does_not_group_anything(
        env, count, finish):
    scene, selection, history, _ctx, proc = env
    objects = _boxes(scene)
    before = _geometry(scene)
    assert proc.run("group")
    for obj in objects[:count]:
        proc.click_object(obj.id)
    if finish:
        proc.finish_selection()

    assert all(o.group_id is None for o in scene.all())
    assert _geometry(scene) == before
    if count == 1 and finish:
        assert proc.busy and isinstance(proc.request, SelectReq)
        assert selection.ids == [objects[0].id]
    proc.cancel()

    assert not proc.busy
    assert all(o.group_id is None for o in scene.all())
    assert _geometry(scene) == before
    assert not history.can_undo, "A cancelled Group recorded an edit"
