"""What an empty Enter — or a right-click on an idle prompt — repeats.

Repeating the last command is a Rhino habit worth keeping, but not every
command is safe to hand to a reflex. Delete is the one that bites: pick,
delete, right-click to dismiss something, and the geometry you just picked
is gone again. Rhino keeps a list of commands it will never repeat; this is
ours, and delete is on it.

Undo and redo are on it for the same reason and one more of their own. They
already have a key each and a button each, so nobody reaches for a
right-click to undo twice, and a stray one walks the drawing to a state
nobody asked for. Worse, undo becoming the repeat target loses the command
you would actually have wanted repeated: undo a bad circle and the reflex
should give you another circle to get right, not take away the one before
it.
"""

import pytest

from serpentine3d.commands.base import resolve


def test_delete_is_not_repeatable():
    assert resolve("delete").repeatable is False


@pytest.mark.parametrize("name", ["line", "circle", "move", "copy"])
def test_ordinary_commands_are_repeatable(name):
    assert resolve(name).repeatable is True


def test_delete_does_not_become_the_repeat_target(env):
    _scene, _sel, _hist, _ctx, proc = env
    proc.run("line")
    proc.cancel()
    proc.run("delete")
    proc.cancel()
    assert proc.last_command == "line"


@pytest.mark.parametrize("alias", ["del", "erase"])
def test_deletes_aliases_do_not_become_the_repeat_target(env, alias):
    _scene, _sel, _hist, _ctx, proc = env
    proc.run("line")
    proc.cancel()
    proc.run(alias)
    proc.cancel()
    assert proc.last_command == "line"


@pytest.mark.parametrize("name", ["undo", "redo"])
def test_undo_and_redo_are_not_repeatable(name):
    assert resolve(name).repeatable is False


@pytest.mark.parametrize("name", ["undo", "redo"])
def test_undo_and_redo_do_not_become_the_repeat_target(env, name):
    """Undo the circle you got wrong and the reflex hands you another
    circle, not the loss of the one before it."""
    _scene, _sel, _hist, _ctx, proc = env
    proc.run("circle")
    proc.cancel()
    proc.run(name)
    assert proc.last_command == "circle"


def test_delete_first_leaves_nothing_to_repeat(env):
    """No command has been run that may be repeated, so Enter does nothing
    rather than falling through to something older still."""
    _scene, _sel, _hist, _ctx, proc = env
    proc.run("delete")
    proc.cancel()
    assert proc.last_command is None
