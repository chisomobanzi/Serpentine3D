"""GumballAlignment is a command, as it is in Rhino (#41).

The tag on the gumball has offered the alignments since 0.8.4, but only to
someone who had found the tag. A Rhino user types GumballAlignment, or binds
it to a key, and picks CPlane, Object, World or View from its options. The
same command does the same here, and a Rhino alias that runs it with an
option keeps the option.

Its setting lives beside the gumball's on/off switch, and the switch used to
be saved as the whole of the gumball's entry, a bare true or false. Turning
the gumball off and on again forgot the alignment, and choosing one after
that raised, so the two are now kept side by side.
"""

from __future__ import annotations

import json

import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui.gumball import Gumball
from serpentine3d.utils.config import Config, map_rhino_macro
from tests.test_a_held_face_or_edge_gets_a_whole_gumball import _VP


@pytest.fixture
def win(monkeypatch, tmp_path):
    monkeypatch.setenv("SERP3D_CONFIG", str(tmp_path / "s.json"))
    monkeypatch.setenv("SERP3D_NO_RECOVER", "1")
    from serpentine3d.app import MainWindow
    w = MainWindow()
    yield w
    w.mark_saved()
    w.close()


def _said(win):
    lines = []
    win.processor.ctx.add_echo_listener(lines.append)
    return lines


# --- the command --------------------------------------------------------------

def test_the_command_sets_the_alignment(win):
    win.processor.run("gumballalignment world")

    assert win.viewport.gumball.align == "world"
    assert not win.processor.busy


def test_it_offers_rhinos_four_in_rhinos_order(win):
    win.processor.run("gumballalignment")

    assert win.processor.request.options == ["CPlane", "Object", "World",
                                             "View"]
    win.processor.provide_text("v")
    assert win.viewport.gumball.align == "view"


def test_enter_keeps_the_one_already_chosen(win):
    win.processor.run("gumballalignment cplane")
    win.processor.run("gumballalignment")

    assert win.processor.request.default == "CPlane"
    win.processor.provide_text("")
    assert win.viewport.gumball.align == "cplane"


def test_every_pane_follows_the_choice(win):
    win.processor.run("gumballalignment world")

    assert {vp.gumball.align for vp in win.all_viewports()} == {"world"}


def test_it_says_what_the_gumball_now_follows(win):
    said = _said(win)

    win.processor.run("gumballalignment object")

    assert "Gumball aligned to the object." in said


def test_the_choice_is_saved(win, tmp_path):
    win.processor.run("gumballalignment view")

    saved = json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))
    assert saved["gumball"]["align"] == "view"


def test_a_rhino_alias_with_an_option_keeps_the_option():
    assert map_rhino_macro("_GumballAlignment _World") == \
        "gumballalignment world"
    assert map_rhino_macro("! _GumballAlignment _CPlane") == \
        "gumballalignment cplane"
    assert map_rhino_macro("_GumballAlignment _Object") == \
        "gumballalignment object"
    assert map_rhino_macro("_GumballAlignment _View") == \
        "gumballalignment view"
    assert map_rhino_macro("_GumballAlignment") == "gumballalignment"


# --- the switch and the alignment, side by side ------------------------------

def test_turning_the_gumball_off_and_on_keeps_the_alignment(win):
    win.processor.run("gumballalignment world")
    win.processor.run("gumball")
    win.processor.run("gumball")

    assert win.viewport.gumball.enabled
    assert win.viewport.gumball.align == "world"


def test_an_alignment_can_be_chosen_after_the_gumball_was_switched(win):
    win.processor.run("gumball")

    win.processor.run("gumballalignment cplane")

    assert {vp.gumball.align for vp in win.all_viewports()} == {"cplane"}
    assert all(not vp.gumball.enabled for vp in win.all_viewports())


def _viewport(path):
    scene = Scene()
    obj = scene.add(g.make_box((0, 0, 0), 10, 10, 10))
    sel = SelectionManager(scene)
    sel.set([obj.id])
    vp = _VP(scene, sel)
    vp.config = Config(str(path))
    return vp


def test_the_switch_and_the_alignment_both_survive_a_restart(tmp_path):
    path = tmp_path / "config.json"
    vp = _viewport(path)
    gb = Gumball(vp)
    gb.set_align("world")
    gb.set_enabled(False)

    again = Gumball(_viewport(path))

    assert again.enabled is False
    assert again.align == "world"


@pytest.mark.parametrize("enabled", [False, True])
def test_a_switch_saved_by_an_older_version_still_reads(tmp_path, enabled):
    """Older versions saved a bare boolean for the gumball."""
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"gumball": enabled}), encoding="utf-8")

    gb = Gumball(_viewport(path))
    assert gb.enabled is enabled
    assert gb.align == "object"

    gb.set_align("cplane")
    saved = Config(str(path)).get("gumball")
    assert saved == {"enabled": enabled, "align": "cplane"}
