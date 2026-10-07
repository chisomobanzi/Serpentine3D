"""Ungroup leaves its chosen objects in hand for further work (issue #63)."""

import numpy as np
import pytest

from serpentine3d.commands.base import PointReq, SelectReq
from serpentine3d.core import geometry as g


ENTRY_PATHS = ("preselected", "picked")


def _boxes(scene):
    return [scene.add(g.make_box((x, 0, 0), 2, 2, 2), name=name)
            for x, name in ((0, "A"), (6, "B"), (20, "Unrelated"))]


def _geometry(scene):
    return {o.id: (o.name, o.kind, tuple(map(tuple, o.bbox())),
                   g.volume(o.shape))
            for o in scene.all()}


def _ungroup(proc, selection, objects, entry):
    ids = [o.id for o in objects]
    if entry == "preselected":
        selection.set(ids)
    assert proc.run("ungroup")
    if entry == "picked":
        assert isinstance(proc.request, SelectReq)
        for obj_id in ids:
            proc.click_object(obj_id)
        proc.finish_selection()
    assert not proc.busy


@pytest.mark.parametrize("entry", ENTRY_PATHS)
def test_ungroup_keeps_the_chosen_objects_without_changing_geometry(env, entry):
    scene, selection, _history, _ctx, proc = env
    a, b, unrelated = _boxes(scene)
    scene.update_many([a.id, b.id], group_id="chosen")
    before = _geometry(scene)

    _ungroup(proc, selection, [a, b], entry)

    assert scene.get(a.id).group_id is None
    assert scene.get(b.id).group_id is None
    assert _geometry(scene) == before, "Ungroup changed the objects"
    assert set(selection.ids) == {a.id, b.id}, (
        "Ungroup released its chosen objects instead of keeping them ready")
    assert selection.subobjects == []
    assert not selection.is_selected(unrelated.id)


@pytest.mark.parametrize("entry", ENTRY_PATHS)
def test_ungroup_keeps_a_mix_of_several_groups_and_ungrouped_objects(env, entry):
    scene, selection, _history, _ctx, proc = env
    objects = [scene.add(g.make_box((6 * i, 0, 0), 2, 2, 2), name=name)
               for i, name in enumerate(("A", "B", "C", "D", "Loose",
                                         "Unrelated A", "Unrelated B"))]
    a, b, c, d, loose, other_a, other_b = objects
    scene.update_many([a.id, b.id], group_id="first")
    scene.update_many([c.id, d.id], group_id="second")
    scene.update_many([other_a.id, other_b.id], group_id="unrelated")
    before = _geometry(scene)
    chosen = [a, b, c, d, loose]

    _ungroup(proc, selection, chosen, entry)

    assert all(scene.get(o.id).group_id is None for o in chosen)
    assert scene.get(other_a.id).group_id == "unrelated"
    assert scene.get(other_b.id).group_id == "unrelated"
    assert _geometry(scene) == before
    assert set(selection.ids) == {o.id for o in chosen}, (
        "Ungroup must also retain the already ungrouped chosen objects")
    assert not selection.is_selected(other_a.id)
    assert not selection.is_selected(other_b.id)


@pytest.mark.parametrize("entry", ENTRY_PATHS)
def test_move_can_use_ungrouped_objects_without_picking_again(env, entry):
    scene, selection, _history, _ctx, proc = env
    a, b, unrelated = _boxes(scene)
    scene.update_many([a.id, b.id], group_id="chosen")
    before = {o.id: np.asarray(o.bbox()) for o in scene.all()}
    _ungroup(proc, selection, [a, b], entry)

    assert proc.run("move")
    assert isinstance(proc.request, PointReq), (
        "Move asked for objects even though Ungroup had just chosen them")
    proc.provide((0, 0, 0))
    proc.provide((3, 4, 5))

    assert not proc.busy
    for obj in (a, b):
        assert np.allclose(scene.get(obj.id).bbox(),
                           before[obj.id] + (3, 4, 5), atol=1e-6)
        assert scene.get(obj.id).group_id is None
    assert np.allclose(scene.get(unrelated.id).bbox(), before[unrelated.id])


@pytest.mark.parametrize("entry", ENTRY_PATHS)
def test_viewports_keep_ungrouped_objects_highlighted_and_on_the_gumball(
        env, entry):
    from serpentine3d.ui.viewport import Viewport

    scene, selection, _history, _ctx, proc = env
    a, b, unrelated = _boxes(scene)
    scene.update_many([a.id, b.id], group_id="chosen")
    panes = [Viewport(scene, selection), Viewport(scene, selection)]
    observed = []
    selection.add_listener(lambda: observed.append(set(selection.ids)))
    try:
        _ungroup(proc, selection, [a, b], entry)

        assert observed[-1] == {a.id, b.id}, (
            "Selection listeners received an empty selection after Ungroup")
        assert selection.is_selected(a.id) and selection.is_selected(b.id)
        assert not selection.is_selected(unrelated.id)
        for pane in panes:
            assert pane.gumball.active(), "Ungroup made the gumball disappear"
            anchor, _axes = pane.gumball.anchor_and_axes()
            assert np.allclose(anchor, (4, 1, 1), atol=1e-6)
    finally:
        for pane in panes:
            pane.close()


@pytest.mark.parametrize("entry", ENTRY_PATHS)
def test_already_ungrouped_chosen_objects_stay_selected(env, entry):
    scene, selection, _history, _ctx, proc = env
    a, b, unrelated = _boxes(scene)
    before = _geometry(scene)

    _ungroup(proc, selection, [a, b], entry)

    assert all(o.group_id is None for o in scene.all())
    assert _geometry(scene) == before
    assert set(selection.ids) == {a.id, b.id}, (
        "Ungroup cleared the selection just because no membership changed")
    assert not selection.is_selected(unrelated.id)


@pytest.mark.parametrize("entry", ENTRY_PATHS)
def test_ungroup_membership_and_geometry_survive_undo_and_redo(env, entry):
    scene, selection, history, _ctx, proc = env
    a, b, unrelated = _boxes(scene)
    scene.update_many([a.id, b.id], group_id="chosen")
    before = _geometry(scene)
    _ungroup(proc, selection, [a, b], entry)

    assert history.can_undo
    history.undo()
    assert scene.get(a.id).group_id == "chosen"
    assert scene.get(b.id).group_id == "chosen"
    assert scene.get(unrelated.id).group_id is None
    assert _geometry(scene) == before
    assert history.can_redo

    history.redo()
    assert all(o.group_id is None for o in scene.all())
    assert _geometry(scene) == before


@pytest.mark.parametrize("count,finish", ((0, True), (0, False),
                                          (1, False), (2, False)))
def test_an_unfinished_or_cancelled_ungroup_leaves_membership_alone(
        env, count, finish):
    scene, selection, history, _ctx, proc = env
    a, b, unrelated = _boxes(scene)
    scene.update_many([a.id, b.id], group_id="chosen")
    before = _geometry(scene)
    assert proc.run("ungroup")
    assert isinstance(proc.request, SelectReq)
    for obj in (a, b)[:count]:
        proc.click_object(obj.id)
    if finish:
        proc.finish_selection()
    proc.cancel()

    assert not proc.busy
    assert scene.get(a.id).group_id == "chosen"
    assert scene.get(b.id).group_id == "chosen"
    assert scene.get(unrelated.id).group_id is None
    assert _geometry(scene) == before
    assert set(selection.ids) == {o.id for o in (a, b)[:count]}
    assert not history.can_undo, "A cancelled Ungroup created an undo entry"


def test_a_group_can_be_ungrouped_immediately_without_picking_again(env):
    scene, selection, _history, _ctx, proc = env
    a, b, unrelated = _boxes(scene)
    selection.set([a.id, b.id])
    assert proc.run("group")
    assert not proc.busy
    assert scene.get(a.id).group_id == scene.get(b.id).group_id

    assert proc.run("ungroup")

    assert not proc.busy, "Ungroup asked to pick the group again"
    assert scene.get(a.id).group_id is None
    assert scene.get(b.id).group_id is None
    assert set(selection.ids) == {a.id, b.id}, (
        "Group followed by Ungroup dropped the objects from the selection")
    assert not selection.is_selected(unrelated.id)


@pytest.fixture
def window():
    from serpentine3d.app import MainWindow

    w = MainWindow()
    yield w
    w._saved_revision = w.scene.revision
    w.close()


@pytest.mark.parametrize("entry", ("normal_group_pick", "command_picks"))
def test_real_viewport_picks_stay_selected_after_ungroup(window, entry):
    from PySide6.QtCore import Qt

    a, b, unrelated = _boxes(window.scene)
    window.scene.update_many([a.id, b.id], group_id="chosen")
    vp = window.viewport
    if entry == "normal_group_pick":
        vp.objectClicked.emit(a.id, Qt.KeyboardModifier.NoModifier)
        assert set(window.selection.ids) == {a.id, b.id}, (
            "An ordinary pick must select the existing group")
    assert window.processor.run("ungroup")
    if entry == "command_picks":
        assert isinstance(window.processor.request, SelectReq)
        vp.objectClicked.emit(a.id, Qt.KeyboardModifier.NoModifier)
        vp.objectClicked.emit(b.id, Qt.KeyboardModifier.NoModifier)
        window.processor.finish_selection()

    assert not window.processor.busy
    assert window.scene.get(a.id).group_id is None
    assert window.scene.get(b.id).group_id is None
    assert set(window.selection.ids) == {a.id, b.id}, (
        "Ungroup dropped the selection provided by the viewport")
    assert not window.selection.is_selected(unrelated.id)
    for pane in window.all_viewports():
        assert pane.gumball.active()


def test_former_group_members_can_be_picked_individually(window):
    from PySide6.QtCore import Qt

    a, b, unrelated = _boxes(window.scene)
    window.scene.update_many([a.id, b.id], group_id="chosen")
    window.selection.set([a.id, b.id])
    assert window.processor.run("ungroup")
    assert not window.processor.busy
    window.selection.clear()

    window.viewport.objectClicked.emit(a.id, Qt.KeyboardModifier.NoModifier)
    assert window.selection.ids == [a.id]
    window.viewport.objectClicked.emit(b.id, Qt.KeyboardModifier.NoModifier)
    assert window.selection.ids == [b.id]
    assert not window.selection.is_selected(unrelated.id)
