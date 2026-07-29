"""Adding a thousand objects should not redraw the panel a thousand times.

`Scene.add` ends by notifying, and two listeners answer by walking the whole
scene: the layers panel rebuilds its tree and counts objects per layer, and
the status bar counts the objects. So importing n objects does n walks of a
scene on its way to holding n of them, and the cost per object grows with
how full the scene already is — 0.08 ms at 500 objects, 0.71 ms at 4000.
On the 522 MB cave file that is about 4.7 seconds of the open spent
redrawing a panel nobody has looked at yet.

Nothing wants those intermediate states. A batch keeps the notifications to
one at the end.
"""

import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene


def _counter(scene, kinds=None):
    calls = []
    scene.add_listener(lambda: calls.append(1), kinds=kinds)
    return calls


def test_a_batch_notifies_once_not_once_an_object():
    scene = Scene()
    calls = _counter(scene)
    box = g.make_box((0, 0, 0), 1, 1, 1)

    with scene.batched():
        for _ in range(50):
            scene.add(box)
    assert len(calls) == 1, f"listeners ran {len(calls)} times for one batch"
    assert len(scene.objects) == 50


def test_listeners_do_not_see_the_scene_half_built():
    """The whole point: what they are shown is the finished state, once."""
    scene = Scene()
    seen = []
    scene.add_listener(lambda: seen.append(len(scene.objects)))
    box = g.make_box((0, 0, 0), 1, 1, 1)

    with scene.batched():
        for _ in range(10):
            scene.add(box)
    assert seen == [10]


def test_a_batch_that_changed_nothing_tells_nobody():
    scene = Scene()
    calls = _counter(scene)
    with scene.batched():
        pass
    assert calls == []


def test_the_notification_still_goes_out_if_the_import_fails():
    """A half-read file still changed the scene. Leaving the panel showing
    what was there before is worse than showing the half."""
    scene = Scene()
    calls = _counter(scene)
    box = g.make_box((0, 0, 0), 1, 1, 1)

    with pytest.raises(ValueError), scene.batched():
        scene.add(box)
        raise ValueError("bad file")
    assert len(calls) == 1


def test_nested_batches_notify_once_when_the_outermost_ends():
    scene = Scene()
    calls = _counter(scene)
    box = g.make_box((0, 0, 0), 1, 1, 1)

    with scene.batched():
        scene.add(box)
        with scene.batched():
            scene.add(box)
        assert calls == [], "the inner batch let a notification out"
    assert len(calls) == 1


def test_a_batch_still_sorts_listeners_by_what_they_asked_for():
    """Collapsing the notifications must not widen them: a listener that
    only wants layer changes should not be woken by objects arriving."""
    scene = Scene()
    objects_only = _counter(scene, kinds=("objects",))
    layouts_only = _counter(scene, kinds=("layouts",))
    box = g.make_box((0, 0, 0), 1, 1, 1)

    with scene.batched():
        scene.add(box)                       # kind="objects"
    assert len(objects_only) == 1
    assert layouts_only == []

    with scene.batched():
        scene.add(box)
        scene.notify("layouts")
    assert len(objects_only) == 2
    assert len(layouts_only) == 1


def test_the_revision_moves_inside_a_batch():
    """Caches are keyed on it — one that is rebuilt mid-batch has to be able
    to tell that the scene moved under it."""
    scene = Scene()
    box = g.make_box((0, 0, 0), 1, 1, 1)
    with scene.batched():
        start = scene.revision
        scene.add(box)
        assert scene.revision > start


def test_arraying_notifies_once_not_once_a_copy():
    """Import is not the only place a scene fills up in one go — an array
    is a count the user types, and 40x40 is not an unusual thing to type."""
    import serpentine3d.commands  # noqa: F401  (registers the commands)
    from serpentine3d.commands.base import CommandContext, CommandProcessor
    from serpentine3d.core.history import History
    from serpentine3d.core.selection import SelectionManager

    scene = Scene()
    sel = SelectionManager(scene)
    ctx = CommandContext(scene, sel, History(scene))
    proc = CommandProcessor(ctx)
    obj = scene.add(g.make_box((0, 0, 0), 1, 1, 1))

    calls = _counter(scene)
    proc.run("array")
    proc.click_object(obj.id)
    proc.finish_selection()
    proc.provide_text("6")               # count X
    proc.provide_text("5")               # count Y
    proc.provide_text("2")               # spacing X
    proc.provide_text("2")               # spacing Y
    assert not proc.busy
    assert len(scene.objects) == 30
    assert len(calls) == 1, (
        f"29 copies made, {len(calls)} notifications")


def test_pasting_notifies_once_not_once_an_object():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from serpentine3d.app import MainWindow

    w = MainWindow()
    box = g.make_box((0, 0, 0), 1, 1, 1)
    for _ in range(20):
        w.scene.add(box)
    w.selection.select_all()
    w._copy_selected()

    calls = _counter(w.scene)
    w._paste()
    assert len(w.scene.objects) == 40
    assert len(calls) == 1, f"20 objects pasted, {len(calls)} notifications"


def test_importing_a_file_notifies_once(tmp_path):
    import os

    from serpentine3d import fileio

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "data", "blocks.3dm")
    scene = Scene()
    calls = _counter(scene)
    n = fileio.import_file(scene, path)
    assert n > 1, "need a file with several objects for this to mean anything"
    assert len(calls) == 1, (
        f"{n} objects imported, {len(calls)} notifications")
