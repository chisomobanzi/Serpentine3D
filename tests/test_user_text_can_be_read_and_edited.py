"""An object's user text can be read and changed, not only carried.

Rhino shows Attribute User Text in a table in its Properties panel, where a
key and its value are typed in, renamed and taken away; SetUserText and
GetUserText do the same from the command line. Both are here, kept by
Rhino's rules so that what is typed here reads the same in Rhino.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from serpentine3d.core import geometry as g
from serpentine3d.core import user_text as ut
from serpentine3d.core.history import History
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui.properties import PropertiesPanel

DOOR = {"Part": "D-101", "Finish": "Oak"}


# -- the rules ----------------------------------------------------------------

def test_a_key_is_one_key_whatever_its_case():
    """Setting PART on an object holding Part changes Part, as Rhino does."""
    assert ut.with_value({"Part": "A"}, "PART", "B") == {"Part": "B"}


def test_case_is_matched_a_character_at_a_time_like_rhino():
    assert ut.with_value({"Ärger": "1"}, "ärger", "2") == {"Ärger": "2"}
    assert ut.with_value({"Straße": "1"}, "STRASSE", "2") == {
        "Straße": "1", "STRASSE": "2"}


def test_setting_a_value_to_nothing_takes_the_key_away():
    assert ut.with_value({"Part": "A", "Room": "1"}, "part", "") == {
        "Room": "1"}
    assert ut.with_value({"Part": "A"}, "Part", "") is None


def test_a_key_needs_a_name():
    with pytest.raises(ValueError):
        ut.with_value(None, "", "x")


def test_a_rename_keeps_the_value_and_its_place():
    got = ut.renamed({"A": "1", "B": "2", "C": "3"}, "B", "Bee")
    assert list(got.items()) == [("A", "1"), ("Bee", "2"), ("C", "3")]


def test_a_rename_onto_another_key_is_refused():
    """It would throw that key's value away."""
    with pytest.raises(ValueError):
        ut.renamed({"A": "1", "B": "2"}, "A", "b")


def test_a_rename_that_only_changes_the_case_is_taken():
    assert ut.renamed({"Part": "1"}, "Part", "PART") == {"PART": "1"}


def test_nothing_is_changed_in_place():
    """An undo checkpoint shares the object's dict."""
    text = {"A": "1"}
    ut.with_value(text, "B", "2")
    ut.with_value(text, "A", "")
    ut.renamed(text, "A", "Z")
    assert text == {"A": "1"}


def test_a_value_is_read_whatever_the_case_of_the_key():
    assert ut.value_of({"Part": "A"}, "part") == "A"
    assert ut.value_of({"Part": "A"}, "Room") is None
    assert ut.value_of(None, "Part") is None


# -- the Properties page ------------------------------------------------------

@pytest.fixture
def page():
    """A Properties panel with a door picked: (scene, history, panel, door).

    Shown on its own, a panel is a window that takes the keyboard focus,
    so each is deleted afterwards or a later test's window would find a
    field here holding it and swallow its Enter.
    """
    shown = []

    def make(text=DOOR):
        scene = Scene()
        box = scene.add(g.make_box((0, 0, 0), 5, 5, 5), name="door")
        if text:
            box = scene.update(box.id, user_text=dict(text))
        selection = SelectionManager(scene)
        history = History(scene)
        props = PropertiesPanel(scene, selection, history)
        shown.append(props)
        props.show()
        selection.set([box.id])
        QApplication.processEvents()
        return scene, history, props, box

    yield make
    for props in shown:
        props.close()
        props.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _set_cell(props, row, column, text):
    """Type into a cell the way the table's editor hands it over."""
    props.user_text.table.item(row, column).setText(text)
    QApplication.processEvents()


def _text(scene, box):
    return scene.get(box.id).user_text


def test_the_page_lists_an_objects_user_text(page):
    _s, _h, props, _b = page()
    assert props.form.isRowVisible(props.user_text)
    assert props.user_text.pairs() == [("Part", "D-101"), ("Finish", "Oak")]


def test_an_object_without_any_says_so_and_offers_to_add(page):
    _s, _h, props, _b = page(text=None)
    assert props.form.isRowVisible(props.user_text)
    assert props.user_text.pairs() == []
    assert not props.user_text.none_label.isHidden()
    assert not props.user_text.add_link.isHidden()


def test_the_rows_are_for_one_model_object(page):
    """Every row on the page edits a single object."""
    scene, _h, props, box = page()
    other = scene.add(g.make_box((9, 0, 0), 5, 5, 5))
    props.selection.set([box.id, other.id])
    QApplication.processEvents()
    assert not props.form.isRowVisible(props.user_text)
    props.selection.set([])
    QApplication.processEvents()
    assert not props.form.isRowVisible(props.user_text)


def test_changing_a_value_is_one_undo_step(page):
    scene, history, props, box = page()
    _set_cell(props, 1, 1, "Walnut")
    assert _text(scene, box) == {"Part": "D-101", "Finish": "Walnut"}
    assert props.user_text.pairs() == [("Part", "D-101"),
                                       ("Finish", "Walnut")]
    history.undo()
    QApplication.processEvents()
    assert _text(scene, box) == DOOR
    assert props.user_text.pairs() == list(DOOR.items()), \
        "the table did not follow the undo"


def test_clearing_a_value_takes_the_key_away(page):
    """Rhino's own rule: a key with no value is no key at all."""
    scene, _h, props, box = page()
    _set_cell(props, 0, 1, "")
    assert _text(scene, box) == {"Finish": "Oak"}
    assert props.user_text.pairs() == [("Finish", "Oak")]


def test_renaming_a_key_keeps_its_value_and_place(page):
    scene, _h, props, box = page()
    _set_cell(props, 0, 0, "Code")
    assert list(_text(scene, box).items()) == [("Code", "D-101"),
                                               ("Finish", "Oak")]


def test_a_rename_onto_another_key_is_put_back(page):
    scene, _h, props, box = page()
    _set_cell(props, 0, 0, "finish")
    assert _text(scene, box) == DOOR
    assert props.user_text.pairs() == list(DOOR.items())


def test_a_key_typed_empty_is_put_back(page):
    scene, _h, props, box = page()
    _set_cell(props, 0, 0, "   ")
    assert _text(scene, box) == DOOR
    assert props.user_text.pairs() == list(DOOR.items())


def test_adding_a_pair_takes_a_key_and_then_a_value(page):
    scene, history, props, box = page()
    props.user_text.add_link.click()
    QApplication.processEvents()
    row = props.user_text.table.rowCount() - 1
    assert row == 2, "Add made no new row"
    _set_cell(props, row, 0, "Room")
    assert _text(scene, box) == DOOR, \
        "a key with no value yet is not a key Rhino can keep"
    _set_cell(props, row, 1, "204")
    assert list(_text(scene, box).items()) == [
        ("Part", "D-101"), ("Finish", "Oak"), ("Room", "204")]
    history.undo()
    assert _text(scene, box) == DOOR


def test_the_first_pair_on_an_object_with_none(page):
    scene, _h, props, box = page(text=None)
    props.user_text.add_link.click()
    QApplication.processEvents()
    assert not props.user_text.table.isHidden()
    _set_cell(props, 0, 0, "Room")
    _set_cell(props, 0, 1, "204")
    assert _text(scene, box) == {"Room": "204"}
    assert props.user_text.none_label.isHidden()


def test_removing_the_picked_pair(page):
    scene, history, props, box = page()
    props.user_text.table.selectRow(0)
    props.user_text.remove_link.click()
    QApplication.processEvents()
    assert _text(scene, box) == {"Finish": "Oak"}
    history.undo()
    assert _text(scene, box) == DOOR


def test_removing_the_last_pair_leaves_none(page):
    scene, _h, props, box = page(text={"Room": "204"})
    props.user_text.table.selectRow(0)
    props.user_text.remove_link.click()
    QApplication.processEvents()
    assert _text(scene, box) is None
    assert not props.user_text.none_label.isHidden()


def _key(widget, kind, key):
    event = QKeyEvent(kind, key, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, event)
    return event


def test_delete_in_the_table_is_the_tables_to_handle(page):
    """The window's Delete deletes the selected objects. With a pair
    picked in the table, the key belongs to the table: taking a whole
    object away to drop one value would be a nasty surprise."""
    scene, _h, props, box = page()
    table = props.user_text.table
    table.selectRow(0)
    override = _key(table, QEvent.Type.ShortcutOverride, Qt.Key.Key_Delete)
    assert override.isAccepted(), "the window's Delete would have fired"
    _key(table, QEvent.Type.KeyPress, Qt.Key.Key_Delete)
    QApplication.processEvents()
    assert _text(scene, box) == {"Finish": "Oak"}


def test_the_page_follows_a_change_made_elsewhere(page):
    """A command or an assistant can change the text while it is shown."""
    scene, _h, props, box = page()
    scene.update(box.id, user_text={"Room": "9"})
    QApplication.processEvents()
    assert props.user_text.pairs() == [("Room", "9")]


# -- in the window ------------------------------------------------------------

@pytest.fixture
def window():
    """A shown window, so its Delete shortcut is live. Deleted afterwards,
    not just closed: a closed window keeps the keyboard focus it had, and
    the next test's window takes a field in it for one being typed in."""
    from serpentine3d.app import MainWindow
    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    QApplication.processEvents()
    yield w
    w.mark_saved()
    w.close()
    w.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _picked_in(w, text=DOOR):
    box = w.scene.add(g.make_box((0, 0, 0), 5, 5, 5), name="door")
    w.scene.update(box.id, user_text=dict(text))
    w.selection.set([box.id])
    QApplication.processEvents()
    return box


def test_delete_in_the_table_leaves_the_object_where_it_is(window):
    box = _picked_in(window)
    table = window.properties.user_text.table
    table.setFocus()
    table.selectRow(0)
    QTest.keyClick(table, Qt.Key.Key_Delete)
    QApplication.processEvents()
    assert window.scene.get(box.id) is not None, "Delete took the object"
    assert window.scene.get(box.id).user_text == {"Finish": "Oak"}


def test_enter_in_the_table_does_not_repeat_the_last_command(window):
    box = _picked_in(window)
    window.processor.run("circle")
    window.processor.cancel()
    window.selection.set([box.id])
    QApplication.processEvents()
    table = window.properties.user_text.table
    table.setFocus()
    table.setCurrentCell(0, 1)
    QTest.keyClick(table, Qt.Key.Key_Return)
    QApplication.processEvents()
    assert not window.processor.busy, \
        f"Enter in the table started `{window.processor.active.name}`"


# -- the commands -------------------------------------------------------------

def test_setusertext_sets_a_key_on_every_picked_object(env):
    scene, selection, _hist, _ctx, proc = env
    a = scene.add(g.make_box((0, 0, 0), 1, 1, 1))
    b = scene.add(g.make_box((5, 0, 0), 1, 1, 1))
    scene.update(a.id, user_text={"Part": "A"})
    selection.set([a.id, b.id])
    proc.run("setusertext")
    proc.provide_text("Room")
    proc.provide_text("204")
    assert scene.get(a.id).user_text == {"Part": "A", "Room": "204"}
    assert scene.get(b.id).user_text == {"Room": "204"}


def test_setusertext_keeps_the_spelling_a_key_already_has(env):
    scene, selection, _hist, _ctx, proc = env
    a = scene.add(g.make_box((0, 0, 0), 1, 1, 1))
    scene.update(a.id, user_text={"Part": "A"})
    selection.set([a.id])
    proc.run("setusertext")
    proc.provide_text("PART")
    proc.provide_text("B")
    assert scene.get(a.id).user_text == {"Part": "B"}


def test_setusertext_with_no_value_takes_the_key_away(env):
    scene, selection, _hist, _ctx, proc = env
    a = scene.add(g.make_box((0, 0, 0), 1, 1, 1))
    scene.update(a.id, user_text={"Part": "A", "Room": "204"})
    selection.set([a.id])
    proc.run("setusertext")
    proc.provide_text("Room")
    proc.provide_text("")
    assert scene.get(a.id).user_text == {"Part": "A"}


def test_setusertext_is_one_undo_step(env):
    scene, selection, history, _ctx, proc = env
    a = scene.add(g.make_box((0, 0, 0), 1, 1, 1))
    selection.set([a.id])
    proc.run("setusertext")
    proc.provide_text("Room")
    proc.provide_text("204")
    history.undo()
    assert scene.get(a.id).user_text is None


def test_getusertext_reports_one_key_or_all(env):
    scene, selection, _hist, ctx, proc = env
    said = []
    ctx.add_echo_listener(said.append)
    a = scene.add(g.make_box((0, 0, 0), 1, 1, 1), name="door")
    scene.update(a.id, user_text={"Part": "D-101", "Room": "204"})
    selection.set([a.id])
    proc.run("getusertext")
    proc.provide_text("room")
    assert any("Room = 204" in line for line in said), said
    said.clear()
    selection.set([a.id])
    proc.run("getusertext")
    proc.provide_text("")
    text = "\n".join(said)
    assert "Part = D-101" in text and "Room = 204" in text, said


# -- what drives the app from outside ----------------------------------------

def test_scene_info_reports_an_objects_user_text(window):
    from serpentine3d.api import SerpApi
    box = _picked_in(window)
    plain = window.scene.add(g.make_box((9, 0, 0), 1, 1, 1), name="plain")
    rows = {row["name"]: row for row in SerpApi(window).scene_info()["objects"]}
    assert rows["door"]["user_text"] == DOOR
    assert "user_text" not in rows["plain"], \
        "an object with none should not pad every row of a big scene"
    assert box.id and plain.id

def test_delete_in_an_empty_command_line_deletes_the_pick(window):
    box = window.scene.add(g.make_box((0, 0, 0), 5, 5, 5))
    window.selection.set([box.id])
    window.command_line.focus()
    QApplication.processEvents()
    QTest.keyClick(window.command_line.input, Qt.Key.Key_Delete)
    QApplication.processEvents()
    assert window.scene.get(box.id) is None
