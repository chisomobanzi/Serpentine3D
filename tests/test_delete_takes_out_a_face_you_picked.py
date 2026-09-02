"""Delete removes a Ctrl+Shift-picked face, not just whole objects.

Asked for by a user: Ctrl+Shift-click a face, press Delete, and the face
should go. It was already the way you pick a face for `pushpull` and
`extractsrf`, so having Delete ignore it and then quietly ask you to pick
a whole object instead was the odd behaviour, not the request.

Taking a face off a closed solid opens it, which is the point: it is how
you get at the inside of something, or make a lid you can put back on a
different shape. Delete already worked this way for held control points,
and this is the same rule applied to the other thing you can hold.
"""

from __future__ import annotations

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
    ctx = CommandContext(scene, selection, History(scene))
    proc = CommandProcessor(ctx)
    echoes: list[str] = []
    ctx.add_echo_listener(echoes.append)
    return scene, selection, proc, echoes


def _box(scene):
    return scene.add(g.make_box((0, 0, 0), 10, 10, 10))


# --- the face goes and the object stays ------------------------------------

def test_deleting_a_held_face_opens_the_solid(env):
    scene, selection, proc, _ = env
    obj = _box(scene)
    selection.toggle_subobject(obj.id, "face", 0)

    proc.run("delete")

    assert not proc.busy
    left = scene.get(obj.id)
    assert left is not None, "the rest of the box should still be there"
    assert len(g.faces_of(left.shape)) == 5
    assert g.shape_kind(left.shape) != "solid"


def test_the_object_keeps_its_name_and_layer(env):
    """It is the same object with a face off, not a new one. Anything
    pointing at it, a layer or a name typed into a command, still means
    it."""
    scene, selection, proc, _ = env
    obj = _box(scene)
    name, layer = obj.name, obj.layer_id
    selection.toggle_subobject(obj.id, "face", 2)

    proc.run("delete")

    left = scene.get(obj.id)
    assert (left.name, left.layer_id) == (name, layer)


def test_several_held_faces_all_go(env):
    scene, selection, proc, _ = env
    obj = _box(scene)
    for i in (0, 3):
        selection.toggle_subobject(obj.id, "face", i)

    proc.run("delete")

    assert len(g.faces_of(scene.get(obj.id).shape)) == 4


def test_faces_held_on_two_objects_both_lose_one(env):
    scene, selection, proc, _ = env
    a, b = _box(scene), _box(scene)
    selection.toggle_subobject(a.id, "face", 1)
    selection.toggle_subobject(b.id, "face", 4)

    proc.run("delete")

    assert len(g.faces_of(scene.get(a.id).shape)) == 5
    assert len(g.faces_of(scene.get(b.id).shape)) == 5


def test_holding_every_face_takes_the_object_with_them(env):
    """Nothing is left to be an object, so there is no empty husk to tidy
    up later."""
    scene, selection, proc, _ = env
    obj = _box(scene)
    for i in range(6):
        selection.toggle_subobject(obj.id, "face", i)

    proc.run("delete")

    assert scene.get(obj.id) is None


def test_the_face_is_let_go_of_afterwards(env):
    """Face 2 of the box that is left is not the face that was held, so
    keeping the pick would leave the wrong face lit and the next Delete
    would take something you never chose."""
    scene, selection, proc, _ = env
    obj = _box(scene)
    selection.toggle_subobject(obj.id, "face", 2)

    proc.run("delete")

    assert [e for e in selection.subobjects if e[1] == "face"] == []


# --- it does not get in the way of anything else ---------------------------

def test_a_selected_object_still_wins(env):
    """Selecting the whole thing and pressing Delete means the whole thing,
    the way it always has, whatever is also held underneath."""
    scene, selection, proc, _ = env
    obj = _box(scene)
    selection.toggle_subobject(obj.id, "face", 0)
    selection.set([obj.id])

    proc.run("delete")

    assert scene.get(obj.id) is None


def test_delete_with_nothing_held_still_asks(env):
    scene, _selection, proc, echoes = env
    _box(scene)

    proc.run("delete")

    assert proc.busy, "it should be waiting for a selection"
    proc.finish_selection()
    assert "Nothing selected to delete." in echoes


def test_undo_puts_the_face_back(env):
    scene, selection, proc, _ = env
    obj = _box(scene)
    selection.toggle_subobject(obj.id, "face", 0)
    proc.run("delete")

    proc.run("undo")

    assert len(g.faces_of(scene.get(obj.id).shape)) == 6


# --- and the Delete key reaches it -----------------------------------------

def test_the_delete_key_runs_the_command_for_a_held_face():
    """The window only bothers running `delete` when something is picked,
    and a held face has to count as something or the key does nothing."""
    from PySide6.QtWidgets import QApplication

    from serpentine3d.app import MainWindow
    QApplication.instance() or QApplication([])
    win = MainWindow()
    try:
        obj = win.scene.add(g.make_box((0, 0, 0), 10, 10, 10))
        win.selection.toggle_subobject(obj.id, "face", 0)

        win._delete_selected()

        assert len(g.faces_of(win.scene.get(obj.id).shape)) == 5
    finally:
        win.mark_saved()
        win.close()
