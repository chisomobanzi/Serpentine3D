"""Typing four letters should be enough to run a command.

From a bug report: "there doesn't seem to be that nifty auto complete - ie, i
have to type the full 'detail' command, i cant just type 'deta' then right
click and it knows what i want". Tab-cycling existed but nothing was ever
filled in, so a right-click submitted the prefix and got
`Unknown command: deta`.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFocusEvent
from PySide6.QtTest import QTest

from serpentine3d.ui.command_line import CommandLine, rank_completions


def _cl():
    return CommandLine()


def _offered(cl):
    return [cl.suggestions.item(i).text()
            for i in range(cl.suggestions.count())]


# ------------------------------------------------- filling in what you meant

def test_typing_a_prefix_fills_in_the_command():
    cl = _cl()
    QTest.keyClicks(cl.input, "deta")
    assert cl.input.text() == "detail"


def test_the_part_you_did_not_type_is_selected():
    """So the next keystroke replaces the guess instead of appending to it."""
    cl = _cl()
    QTest.keyClicks(cl.input, "deta")
    assert cl.input.selectionStart() == 4
    assert cl.input.selectedText() == "il"


def test_right_clicking_a_prefix_runs_the_whole_command():
    """The bug report, exactly: four letters and a right-click."""
    cl = _cl()
    sent = []
    cl.submitted.connect(sent.append)
    QTest.keyClicks(cl.input, "deta")
    cl.submit_input()                 # what a right-click in the viewport does
    assert sent == ["detail"]


def test_typing_on_past_the_guess_narrows_it():
    cl = _cl()
    QTest.keyClicks(cl.input, "detailm")
    assert cl.input.text() == "detailmode"


def test_backspacing_does_not_put_the_guess_back():
    """Otherwise the box fights you: every delete refills itself."""
    cl = _cl()
    QTest.keyClicks(cl.input, "deta")
    QTest.keyClick(cl.input, Qt.Key.Key_Backspace)      # the guess
    QTest.keyClick(cl.input, Qt.Key.Key_Backspace)      # a letter you typed
    assert cl.input.text() == "det"


def test_a_name_that_is_already_a_command_is_left_alone():
    cl = _cl()
    QTest.keyClicks(cl.input, "line")
    assert cl.input.text() == "line", "`line` must not become `linetype`"


def test_an_alias_is_left_alone():
    """`l` is line. Completing it would silently turn it into `layer`,
    because the completions only know registry names, not aliases."""
    cl = _cl()
    QTest.keyClicks(cl.input, "l")
    assert cl.input.text() == "l"


def test_nothing_is_filled_in_while_a_command_is_asking_for_a_value():
    """At an option prompt "to" is the start of a word the command chose;
    it is not an invitation to run Top."""
    cl = _cl()
    cl.awaiting_command = False
    QTest.keyClicks(cl.input, "to")
    assert cl.input.text() == "to"
    assert cl.suggestions.isHidden()


# ------------------------------------------------------ the list of the rest

def test_the_matches_are_offered_as_a_list():
    cl = _cl()
    QTest.keyClicks(cl.input, "deta")
    assert not cl.suggestions.isHidden()
    assert _offered(cl)[0] == "detail"
    assert cl.suggestions.currentRow() == 0, "the guess is the highlighted row"
    assert "detailmode" in _offered(cl)


def test_a_prefix_that_matches_nothing_offers_nothing():
    cl = _cl()
    QTest.keyClicks(cl.input, "zzz")
    assert cl.input.text() == "zzz"
    assert cl.suggestions.isHidden()


def test_the_list_goes_away_once_the_command_runs():
    cl = _cl()
    QTest.keyClicks(cl.input, "deta")
    cl.submit_input()
    assert cl.suggestions.isHidden()


def test_escape_takes_the_list_with_it():
    cl = _cl()
    QTest.keyClicks(cl.input, "deta")
    QTest.keyClick(cl.input, Qt.Key.Key_Escape)
    assert cl.suggestions.isHidden()


def test_the_list_goes_away_when_you_click_off_the_command_line():
    """It floats over the viewport, so it must not outlive the typing."""
    cl = _cl()
    QTest.keyClicks(cl.input, "deta")
    cl.input.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut))
    assert cl.suggestions.isHidden()


def test_the_list_never_runs_off_the_top_of_the_window():
    cl = _cl()
    cl.resize(400, 60)
    QTest.keyClicks(cl.input, "deta")
    assert cl.suggestions.y() >= 0


def test_clicking_a_suggestion_runs_it():
    cl = _cl()
    ran = []
    cl.submitted.connect(ran.append)
    QTest.keyClicks(cl.input, "deta")
    wanted = _offered(cl)[2]
    cl.suggestions.itemClicked.emit(cl.suggestions.item(2))
    assert ran == [wanted]


# --------------------------------------------------- walking through them

def test_down_walks_the_list_while_it_is_open():
    cl = _cl()
    QTest.keyClicks(cl.input, "deta")
    second = _offered(cl)[1]
    QTest.keyClick(cl.input, Qt.Key.Key_Down)
    assert cl.input.text() == second
    assert cl.suggestions.currentRow() == 1


def test_up_and_down_still_walk_the_history_at_an_empty_prompt():
    cl = _cl()
    cl.input.setText("circle")
    cl.submit_input()
    QTest.keyClick(cl.input, Qt.Key.Key_Up)
    assert cl.input.text() == "circle"


def test_tab_still_cycles_the_matches():
    """Tab asked outright, so it commits whole names — and it may extend a
    name that is already a command, which typing must not."""
    cl = _cl()
    cl.input.setText("line")
    cl.input.tabPressed.emit()
    assert cl.input.text() == "line"
    cl.input.tabPressed.emit()
    assert cl.input.text() == "linetype"


# ---------------------------------------------------------------- ranking

def test_the_plain_command_is_guessed_before_its_variants():
    """Alphabetical is no guess at all: it offers `tolerance` to someone
    typing `to`, and slots `detailborder` in ahead of `detailmode`."""
    assert rank_completions("to", [])[0] == "top"
    ranked = rank_completions("deta", [])
    assert ranked[0] == "detail"
    assert ranked.index("detailmode") < ranked.index("detailborder")


def test_what_you_ran_lately_is_guessed_first():
    cl = _cl()
    cl.input.setText("detailscale")
    cl.submit_input()
    QTest.keyClicks(cl.input, "deta")
    assert cl.input.text() == "detailscale"


def test_a_right_click_in_the_viewport_no_longer_says_unknown_command():
    """The whole chain, which is what was actually reported: four letters,
    right-click, and the command runs."""
    from serpentine3d.app import MainWindow
    w = MainWindow()
    said = []
    w.ctx.add_echo_listener(said.append)
    QTest.keyClicks(w.command_line.input, "deta")
    assert w.command_line.input.text() == "detail"
    w._rmb_enter()
    assert not any("Unknown command" in m for m in said), said
    assert said, "the right-click submitted nothing at all"


def test_the_app_says_when_it_is_asking_for_something_rather_than_waiting():
    from serpentine3d.app import MainWindow
    w = MainWindow()
    assert w.command_line.awaiting_command
    w.command_line.run_command("line")
    assert not w.command_line.awaiting_command
    w.processor.cancel()
    w._sync_command_state()
    assert w.command_line.awaiting_command


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
