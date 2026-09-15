"""Delete removes a Ctrl+Shift-picked segment of a curve.

Asked for by a user: the gumball already takes hold of one segment of a
polyline, but pressing Delete with a segment held did nothing at all.
Holding a segment and pressing Delete plainly means that segment, so it
goes and the rest of the curve stays. Taking a side out of a closed curve
opens it, and taking a middle segment out of an open one leaves the two
runs either side as separate curves, the way Rhino does it.
"""

from __future__ import annotations

import math

import pytest

from serpentine3d.core import geometry as g


@pytest.fixture
def env():
    import serpentine3d.commands  # registers all commands  # noqa: F401
    from serpentine3d.commands.base import CommandContext, CommandProcessor
    from serpentine3d.core.history import History
    from serpentine3d.core.scene import Scene
    from serpentine3d.core.selection import SelectionManager
    scene = Scene()
    selection = SelectionManager(scene)
    history = History(scene)
    ctx = CommandContext(scene, selection, history)
    proc = CommandProcessor(ctx)
    echoes: list[str] = []
    ctx.add_echo_listener(echoes.append)
    return scene, selection, history, proc, echoes


def _rect(scene):
    return scene.add(g.make_polyline(
        [(0, 0, 0), (10, 0, 0), (10, 6, 0), (0, 6, 0)], closed=True),
        name="Rect")


def _chain(scene):
    return scene.add(g.make_polyline(
        [(0, 0, 0), (10, 0, 0), (20, 0, 0), (30, 0, 0)]), name="Chain")


def _seg_at(shape, mid):
    for i, e in enumerate(g.edges_of(shape)):
        if math.dist(g.centroid(e), mid) < 1e-6:
            return i
    raise AssertionError(f"no segment with midpoint {mid}")


def _total_length(scene):
    return sum(g.curve_length(o.shape) for o in scene.all())


def test_deleting_a_side_opens_the_rectangle(env):
    scene, selection, _hist, proc, _ = env
    obj = _rect(scene)
    selection.toggle_subobject(obj.id, "edge", _seg_at(obj.shape, (5, 0, 0)))

    proc.run("delete")

    assert not proc.busy, "a held segment answers Delete on its own"
    left = scene.get(obj.id)
    assert left is not None
    assert len(g.edges_of(left.shape)) == 3
    assert not g.is_closed_curve(left.shape)
    assert g.curve_length(left.shape) == pytest.approx(22, abs=1e-6)
    assert len(scene.all()) == 1


def test_the_curve_keeps_its_name_and_layer(env):
    scene, selection, _hist, proc, _ = env
    obj = _rect(scene)
    layer = obj.layer_id
    selection.toggle_subobject(obj.id, "edge", _seg_at(obj.shape, (5, 0, 0)))

    proc.run("delete")

    left = scene.get(obj.id)
    assert left.name == "Rect"
    assert left.layer_id == layer


def test_a_middle_segment_leaves_the_two_runs_either_side(env):
    scene, selection, _hist, proc, _ = env
    obj = _chain(scene)
    selection.toggle_subobject(obj.id, "edge", _seg_at(obj.shape, (15, 0, 0)))

    proc.run("delete")

    pieces = scene.all()
    assert len(pieces) == 2
    assert {round(g.curve_length(p.shape), 6) for p in pieces} == {10.0}
    assert obj.id in {p.id for p in pieces}, "the original object stays"


def test_an_end_segment_just_shortens_the_curve(env):
    scene, selection, _hist, proc, _ = env
    obj = _chain(scene)
    selection.toggle_subobject(obj.id, "edge", _seg_at(obj.shape, (25, 0, 0)))

    proc.run("delete")

    assert len(scene.all()) == 1
    assert g.curve_length(scene.get(obj.id).shape) == pytest.approx(20, abs=1e-6)


def test_two_opposite_sides_leave_two_curves(env):
    scene, selection, _hist, proc, _ = env
    obj = _rect(scene)
    for mid in ((5, 0, 0), (5, 6, 0)):
        selection.toggle_subobject(obj.id, "edge", _seg_at(obj.shape, mid))

    proc.run("delete")

    pieces = scene.all()
    assert len(pieces) == 2
    assert {round(g.curve_length(p.shape), 6) for p in pieces} == {6.0}


def test_holding_every_segment_takes_the_curve_with_them(env):
    scene, selection, _hist, proc, _ = env
    obj = _rect(scene)
    for i in range(len(g.edges_of(obj.shape))):
        selection.toggle_subobject(obj.id, "edge", i)

    proc.run("delete")

    assert scene.get(obj.id) is None
    assert scene.all() == []


def test_a_lone_line_goes_when_its_only_segment_does(env):
    scene, selection, _hist, proc, _ = env
    obj = scene.add(g.make_line((0, 0, 0), (10, 0, 0)))
    selection.toggle_subobject(obj.id, "edge", 0)

    proc.run("delete")

    assert scene.get(obj.id) is None


def test_the_segment_is_let_go_of_afterwards(env):
    scene, selection, _hist, proc, _ = env
    obj = _rect(scene)
    selection.toggle_subobject(obj.id, "edge", _seg_at(obj.shape, (5, 0, 0)))

    proc.run("delete")

    assert selection.subobjects == [], (
        "the deleted segment's index now means a different segment")


def test_a_selected_object_still_wins(env):
    scene, selection, _hist, proc, _ = env
    obj = _rect(scene)
    other = scene.add(g.make_line((0, 20, 0), (10, 20, 0)))
    selection.toggle_subobject(obj.id, "edge", _seg_at(obj.shape, (5, 0, 0)))
    selection.set([other.id])

    proc.run("delete")

    assert scene.get(other.id) is None
    assert g.is_closed_curve(scene.get(obj.id).shape), "the rectangle is whole"


def test_a_solid_edge_is_left_alone(env):
    scene, selection, _hist, proc, echoes = env
    box = scene.add(g.make_box((0, 0, 0), 10, 10, 10))
    selection.toggle_subobject(box.id, "edge", 0)

    proc.run("delete")

    assert len(g.faces_of(scene.get(box.id).shape)) == 6
    proc.cancel()


def test_undo_puts_the_segment_back(env):
    scene, selection, history, proc, _ = env
    obj = _rect(scene)
    before = _total_length(scene)
    selection.toggle_subobject(obj.id, "edge", _seg_at(obj.shape, (5, 0, 0)))

    proc.run("delete")
    assert _total_length(scene) < before

    history.undo()
    assert len(scene.all()) == 1
    assert _total_length(scene) == pytest.approx(before, abs=1e-6)
    assert g.is_closed_curve(scene.all()[0].shape)


def test_the_delete_key_runs_the_command_for_a_held_segment():
    """The window only bothers running `delete` when something is picked,
    and a held curve segment has to count or the key does nothing."""
    from PySide6.QtWidgets import QApplication

    from serpentine3d.app import MainWindow
    QApplication.instance() or QApplication([])
    win = MainWindow()
    try:
        obj = win.scene.add(g.make_polyline(
            [(0, 0, 0), (10, 0, 0), (10, 6, 0), (0, 6, 0)], closed=True))
        win.selection.toggle_subobject(obj.id, "edge", 0)

        win._delete_selected()

        assert len(g.edges_of(win.scene.get(obj.id).shape)) == 3
    finally:
        win.mark_saved()
        win.close()
