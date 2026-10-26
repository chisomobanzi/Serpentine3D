"""`showselected` brings back the hidden objects you pick, and only those.

`show` brings back everything hidden at once. As in Rhino, `showselected`
puts the hidden objects on show while it waits and steps the visible ones
aside, so what can be clicked is exactly what could be brought back. The
picked ones come back and the rest stay hidden. Escape changes nothing.

Putting them on show is no edit: no object's `visible` changes until the
pick is made, so the drawing is not marked changed, nothing reaches an
autosave, and a pick abandoned leaves no undo step behind.
"""

from __future__ import annotations

from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager


def _box(scene, name, x=0.0):
    return scene.add(g.make_box((x, 0, 0), 10, 10, 10), name=name)


def _drawing(scene):
    """One box in sight and three hidden."""
    shown = _box(scene, "Shown")
    hidden = [_box(scene, f"Hidden {i}", 20.0 * (i + 1)) for i in range(3)]
    scene.update_many([o.id for o in hidden], visible=False)
    return shown, hidden


def _names(objs):
    return sorted(o.name for o in objs)


# -- while it waits --------------------------------------------------------------

def test_while_it_waits_the_hidden_are_on_show_and_the_rest_step_aside(env):
    scene, sel, hist, ctx, proc = env
    shown, hidden = _drawing(scene)
    proc.run("showselected")
    assert proc.busy
    assert _names(scene.visible_objects()) == ["Hidden 0", "Hidden 1",
                                               "Hidden 2"]
    assert scene.is_selectable(hidden[0].id)
    assert not scene.is_selectable(shown.id)
    assert all(not scene.get(o.id).visible for o in hidden), \
        "putting them on show changed what the drawing says is hidden"


def test_a_hidden_object_on_a_layer_that_is_off_is_not_offered(env):
    scene, sel, hist, ctx, proc = env
    _shown, hidden = _drawing(scene)
    off = scene.layers.create("Off")
    scene.update(hidden[0].id, layer_id=off.id)
    scene.layers.set_visible(off.id, False)
    proc.run("showselected")
    assert "Hidden 0" not in _names(scene.visible_objects())


# -- picking ----------------------------------------------------------------------

def test_the_picked_come_back_and_the_rest_stay_hidden(env):
    scene, sel, hist, ctx, proc = env
    shown, hidden = _drawing(scene)
    said = []
    ctx.add_echo_listener(said.append)
    proc.run("showselected")
    proc.click_object(hidden[0].id)
    proc.click_object(hidden[2].id)
    proc.finish_selection()
    assert not proc.busy
    assert scene.showing_only is None
    assert _names(scene.visible_objects()) == ["Hidden 0", "Hidden 2",
                                               "Shown"]
    assert not scene.get(hidden[1].id).visible
    assert any("Showed 2" in line for line in said)


def test_one_undo_hides_them_again(env):
    scene, sel, hist, ctx, proc = env
    _shown, hidden = _drawing(scene)
    proc.run("showselected")
    proc.click_object(hidden[1].id)
    proc.finish_selection()
    assert scene.get(hidden[1].id).visible
    hist.undo()
    assert not scene.get(hidden[1].id).visible
    assert _names(scene.visible_objects()) == ["Shown"]


def test_a_name_typed_at_the_prompt_finds_a_hidden_object(env):
    scene, sel, hist, ctx, proc = env
    _shown, hidden = _drawing(scene)
    proc.run("showselected")
    proc.provide_text("Hidden 1")
    proc.finish_selection()
    assert scene.get(hidden[1].id).visible


def test_what_was_selected_before_is_not_taken_for_the_answer(env):
    """The selection is of visible objects, which are not what it asks for."""
    scene, sel, hist, ctx, proc = env
    shown, hidden = _drawing(scene)
    sel.set([shown.id])
    proc.run("showselected")
    assert proc.busy, "the visible selection answered the prompt"
    assert sel.ids == [] or list(sel.ids) == []


# -- not picking ------------------------------------------------------------------

def test_escape_changes_nothing_and_leaves_no_undo_step(env):
    scene, sel, hist, ctx, proc = env
    _shown, hidden = _drawing(scene)
    revision = scene.revision
    could_undo = hist.can_undo
    proc.run("showselected")
    proc.cancel()
    assert scene.showing_only is None
    assert _names(scene.visible_objects()) == ["Shown"]
    assert scene.revision == revision, "looking marked the drawing changed"
    assert hist.can_undo == could_undo


def test_enter_on_nothing_changes_nothing(env):
    scene, sel, hist, ctx, proc = env
    _drawing(scene)
    proc.run("showselected")
    proc.finish_selection()
    assert not proc.busy
    assert scene.showing_only is None
    assert _names(scene.visible_objects()) == ["Shown"]


def test_with_nothing_hidden_it_says_so(env):
    scene, sel, hist, ctx, proc = env
    _box(scene, "Shown")
    said = []
    ctx.add_echo_listener(said.append)
    proc.run("showselected")
    assert not proc.busy
    assert scene.showing_only is None
    assert any("nothing hidden" in line.lower() for line in said)


# -- the viewport ------------------------------------------------------------------

def test_a_pane_keeps_buffers_for_both_while_they_are_on_show(_qapp):
    """Swapping what is drawn for a pick must not throw the visible
    objects' buffers away, or a big drawing uploads everything again when
    the pick ends; and the hidden ones need buffers to be drawn at all."""
    from serpentine3d.ui.viewport import Viewport
    scene = Scene()
    pane = Viewport(scene, SelectionManager(scene))
    shown, hidden = _drawing(scene)
    before = pane._gpu_sync_key()
    scene.showing_only = frozenset(o.id for o in hidden)
    try:
        assert pane._gpu_sync_key() != before, \
            "nothing tells the pane to upload the hidden objects"
        assert _names(pane._gpu_candidates()) == _names([shown, *hidden])
    finally:
        scene.showing_only = None
