"""Right-clicking a layout tab renames, duplicates or deletes that sheet.

The tabs are where layouts live in the window, but the only way to work on
one was knowing that the `layout` command had those words inside it. The
menu acts on the tab you clicked, so it is never the wrong sheet.
"""

import pytest

from serpentine3d.core.layout import (
    DetailView,
    Layout,
    TextNote,
    unique_layout_name,
)


@pytest.fixture
def win(monkeypatch, tmp_path):
    monkeypatch.setenv("SERP3D_CONFIG", str(tmp_path / "s.json"))
    monkeypatch.setenv("SERP3D_NO_RECOVER", "1")
    from serpentine3d.app import MainWindow
    w = MainWindow()
    yield w
    w.mark_saved()
    w.close()


def _add_layout(w, name="Layout 1") -> Layout:
    lay = Layout(name=name)
    w.scene.layouts.append(lay)
    w.scene.notify()
    return lay


def _tab(w, space_id) -> int:
    for i in range(w.space_tabs.count()):
        if w.space_tabs.tabData(i) == space_id:
            return i
    return -1


# ------------------------------------------------------- what is on a sheet

def test_a_fresh_sheet_is_empty():
    assert Layout().is_empty()


def test_anything_placed_on_the_paper_fills_it():
    lay = Layout()
    lay.revisions.append(["A", "2026-08-11", "issued for tender"])
    assert not lay.is_empty()


def test_emptiness_ignores_the_paper_itself():
    """Renaming a sheet or turning it portrait is not work on the sheet."""
    lay = Layout(name="Site plan", paper_w=297.0, paper_h=420.0, margin=5.0)
    assert lay.is_empty()


# ------------------------------------------------------------- the menu

def test_the_menu_offers_rename_duplicate_and_delete(win):
    lay = _add_layout(win)
    menu = win._layout_tab_menu(_tab(win, lay.id))
    assert [a.text() for a in menu.actions()] == ["Rename…", "Duplicate",
                                                  "Delete"]


def test_the_model_tab_has_no_menu(win):
    _add_layout(win)
    assert win._layout_tab_menu(_tab(win, "model")) is None


def test_a_right_click_on_no_tab_has_no_menu(win):
    _add_layout(win)
    assert win._layout_tab_menu(-1) is None


# ------------------------------------------------------------- renaming

def test_renaming_shows_on_the_tab(win):
    lay = _add_layout(win)
    assert win.rename_layout(lay, "Site plan") is True
    assert lay.name == "Site plan"
    assert win.space_tabs.tabText(_tab(win, lay.id)) == "Site plan"


def test_renaming_is_undoable(win):
    lay = _add_layout(win, "Layout 1")
    win.rename_layout(lay, "Site plan")
    win.history.undo()
    assert [x.name for x in win.scene.layouts] == ["Layout 1"]


def test_a_blank_name_is_ignored(win):
    lay = _add_layout(win, "Layout 1")
    assert win.rename_layout(lay, "   ") is False
    assert lay.name == "Layout 1"


# ------------------------------------------------------------- deleting

def test_deleting_drops_the_tab(win):
    lay = _add_layout(win)
    assert win.delete_layout(lay) is True
    assert win.scene.layouts == []
    assert _tab(win, lay.id) == -1


def test_deleting_the_only_sheet_falls_back_to_the_model(win):
    lay = _add_layout(win)
    win.switch_space(lay.id)
    win.delete_layout(lay)
    assert win.space == "model"


def test_deleting_is_undoable(win):
    lay = _add_layout(win, "Layout 1")
    win.delete_layout(lay)
    win.history.undo()
    assert [x.name for x in win.scene.layouts] == ["Layout 1"]


def test_an_empty_sheet_goes_without_asking(win, monkeypatch):
    monkeypatch.setattr(win, "_confirm_layout_delete",
                        lambda lay: pytest.fail("asked about an empty sheet"))
    win.delete_layout(_add_layout(win))
    assert win.scene.layouts == []


def test_a_sheet_with_work_on_it_asks_first(win, monkeypatch):
    lay = _add_layout(win)
    lay.revisions.append(["A", "2026-08-11", "issued"])
    asked = []
    monkeypatch.setattr(win, "_confirm_layout_delete",
                        lambda x: bool(asked.append(x)))
    assert win.delete_layout(lay) is False
    assert asked == [lay]
    assert win.scene.layouts == [lay]


# ------------------------------------------- where a deleted sheet leaves you

def test_deleting_the_last_sheet_falls_to_the_one_below(win):
    _add_layout(win, "Layout 1")
    b = _add_layout(win, "Layout 2")
    c = _add_layout(win, "Layout 3")
    win.switch_space(c.id)
    win.delete_layout(c)
    assert win.space == b.id
    assert win.viewport.space == b.id


def test_deleting_a_middle_sheet_falls_to_the_one_below(win):
    a = _add_layout(win, "Layout 1")
    b = _add_layout(win, "Layout 2")
    _add_layout(win, "Layout 3")
    win.switch_space(b.id)
    win.delete_layout(b)
    assert win.space == a.id


def test_deleting_the_first_sheet_falls_to_the_model(win):
    """Model is the bottom of the strip, and the one tab that cannot go."""
    a = _add_layout(win, "Layout 1")
    _add_layout(win, "Layout 2")
    win.switch_space(a.id)
    win.delete_layout(a)
    assert win.space == "model"


def test_deleting_a_sheet_you_are_not_on_leaves_you_where_you_are(win):
    a = _add_layout(win, "Layout 1")
    c = _add_layout(win, "Layout 2")
    win.switch_space(a.id)
    win.delete_layout(c)
    assert win.space == a.id


def test_no_pane_is_left_drawing_a_deleted_sheet(win):
    """The window's tab is elsewhere, so nothing else would notice this pane.

    A pane that is never asked to redraw keeps the last frame it drew, so
    the sheet stays on screen after the sheet itself has gone.
    """
    lay = _add_layout(win, "Layout 1")
    win.set_pane_space(win.viewport, lay.id)
    win.delete_layout(lay)
    assert win.space == "model"
    assert win.viewport.space == "model"


def test_the_layout_command_falls_back_the_same_way(win):
    """One rule: the command line has no separate idea of what is below."""
    _add_layout(win, "Layout 1")
    b = _add_layout(win, "Layout 2")
    c = _add_layout(win, "Layout 3")
    win.switch_space(c.id)
    win.processor.run("layout")
    win.processor.provide_text("Delete")
    win.processor.provide_text("Layout 3")
    assert [x.name for x in win.scene.layouts] == ["Layout 1", "Layout 2"]
    assert win.space == b.id


# ------------------------------------------------------------ duplicating

def test_a_duplicate_carries_the_drawing_over():
    lay = Layout(name="Site plan", paper_w=594.0)
    lay.details.append(DetailView(x=25.0))
    lay.notes.append(TextNote(text="NOT TO SCALE"))
    dup = lay.duplicate("Site plan copy")
    assert dup.name == "Site plan copy"
    assert dup.paper_w == 594.0
    assert [d.x for d in dup.details] == [25.0]
    assert [n.text for n in dup.notes] == ["NOT TO SCALE"]


def test_a_duplicate_is_its_own_sheet():
    lay = Layout()
    lay.notes.append(TextNote(text="original"))
    dup = lay.duplicate("copy")
    dup.notes[0].text = "changed"
    assert lay.notes[0].text == "original"


def test_a_duplicate_gets_fresh_ids_throughout():
    """Not only the details — everything on paper carries an id."""
    lay = Layout()
    lay.details.append(DetailView())
    lay.notes.append(TextNote())
    dup = lay.duplicate("copy")
    assert dup.id != lay.id
    assert dup.details[0].id != lay.details[0].id
    assert dup.notes[0].id != lay.notes[0].id


def test_plain_data_on_the_sheet_survives_the_copy():
    """revisions and scale bars are bare lists, with no id to refresh."""
    lay = Layout()
    lay.revisions.append(["A", "2026-08-11", "issued"])
    lay.title_block["client"] = "Jonas"
    dup = lay.duplicate("copy")
    assert dup.revisions == [["A", "2026-08-11", "issued"]]
    assert dup.title_block == {"client": "Jonas"}


def test_a_free_name_is_left_alone():
    assert unique_layout_name([Layout(name="Site plan")],
                              "Site plan copy") == "Site plan copy"


def test_a_taken_name_counts_up():
    taken = [Layout(name="A copy"), Layout(name="A copy 2")]
    assert unique_layout_name(taken, "A copy") == "A copy 3"


def test_duplicating_opens_the_copy(win):
    lay = _add_layout(win, "Site plan")
    dup = win.duplicate_layout(lay)
    assert [x.name for x in win.scene.layouts] == ["Site plan",
                                                   "Site plan copy"]
    assert win.space == dup.id
    assert _tab(win, dup.id) >= 0


def test_duplicating_twice_does_not_repeat_a_name(win):
    lay = _add_layout(win, "Site plan")
    win.duplicate_layout(lay)
    win.duplicate_layout(lay)
    assert [x.name for x in win.scene.layouts] == [
        "Site plan", "Site plan copy", "Site plan copy 2"]


def test_duplicating_is_undoable(win):
    lay = _add_layout(win, "Site plan")
    win.duplicate_layout(lay)
    win.history.undo()
    assert [x.name for x in win.scene.layouts] == ["Site plan"]


def test_the_layout_command_duplicates_the_same_way(win):
    """One implementation: the command line and the tab menu share it."""
    _add_layout(win, "Site plan")
    win.processor.run("layout")
    win.processor.provide_text("Duplicate")
    win.processor.provide_text("Site plan")
    assert [x.name for x in win.scene.layouts] == ["Site plan",
                                                   "Site plan copy"]


def test_a_refused_delete_leaves_the_undo_stack_alone(win, monkeypatch):
    """Saying no must not cost the previous edit its undo step."""
    lay = _add_layout(win, "Layout 1")
    win.rename_layout(lay, "Site plan")
    lay.revisions.append(["A", "2026-08-11", "issued"])
    monkeypatch.setattr(win, "_confirm_layout_delete", lambda x: False)
    win.delete_layout(lay)
    win.history.undo()
    assert [x.name for x in win.scene.layouts] == ["Layout 1"]
